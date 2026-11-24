from __future__ import annotations

from cti_source_config import adapter_type, parse_config, source_binding

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .audit_store import AuditStore
from .common import clamp, new_id, safe_json_loads, utcnow, utcnow_iso
from .db_adapter import DbAdapter, to_json
from .service_registry import ServiceRegistry


class AcquisitionFreshnessAgent:
    """CTI-A02 RAO agent baseline.

    This implementation deliberately separates proposal from execution.  The
    agent can select a source/action and produce a structured ProposedAction,
    but a connector is executed only when the caller supplies an explicitly
    authorized connector callable.  This preserves the design's authority
    boundary and makes the agent suitable for deterministic dissertation tests.
    """

    SERVICE_KEY = "cti_acquisition_freshness_agent"
    COMPONENT_ID = "CTI-A02"

    DEFAULT_WEIGHTS = {
        "mission_relevance": 0.25,
        "freshness_due": 0.30,
        "criticality": 0.15,
        "change_signal": 0.10,
        "recovery_need": 0.10,
        "health": 0.10,
        "rate_pressure": -0.15,
        "cost": -0.10,
    }

    def __init__(
        self,
        db: Optional[DbAdapter] = None,
        registry: Optional[ServiceRegistry] = None,
        audit: Optional[AuditStore] = None,
    ):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

    def list_sources(self, source_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not self.db.table_exists("cti_source_registry"):
            return []
        params: Dict[str, Any] = {}
        where = "WHERE enabled=1"
        if source_ids:
            placeholders = []
            for idx, sid in enumerate(source_ids):
                key = f"sid{idx}"
                placeholders.append(f"%({key})s")
                params[key] = sid
            where += " AND source_id IN (" + ",".join(placeholders) + ")"
        rows = self.db.fetch_all(
            f"""
            SELECT source_id, protocol, endpoint_ref, credential_ref, incremental_strategy,
                   freshness_sla_seconds, criticality, rate_limit_per_window,
                   rate_window_seconds, max_payload_bytes, trust_tier, config_json, enabled
            FROM cti_source_registry
            {where}
            ORDER BY criticality DESC, source_id
            """,
            params,
        )
        # Registry-only sources are visible in the UI but cannot propose an unsupported acquisition.
        return [row for row in rows if adapter_type(row["source_id"], parse_config(row.get("config_json"))) != "registry-only"]

    def source_state(self, source_id: str) -> Dict[str, Any]:
        if not self.db.table_exists("cti_source_state"):
            return {"source_id": source_id, "status": "UNKNOWN", "health_score": 1.0, "failure_count": 0}
        row = self.db.fetch_one(
            "SELECT * FROM cti_source_state WHERE source_id=%(source_id)s LIMIT 1",
            {"source_id": source_id},
        )
        return row or {"source_id": source_id, "status": "NEW", "health_score": 1.0, "failure_count": 0}

    @staticmethod
    def _age_seconds(last_success_at: Any, now: Optional[datetime] = None) -> Optional[float]:
        if not last_success_at:
            return None
        if isinstance(last_success_at, str):
            try:
                last_success_at = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
            except Exception:
                return None
        if not isinstance(last_success_at, datetime):
            return None
        if last_success_at.tzinfo is None:
            last_success_at = last_success_at.replace(tzinfo=timezone.utc)
        now = now or utcnow()
        return max(0.0, (now - last_success_at.astimezone(timezone.utc)).total_seconds())

    def freshness_metrics(self, descriptor: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, float]:
        sla = max(1.0, float(descriptor.get("freshness_sla_seconds") or 86400))
        age = self._age_seconds(state.get("last_success_at"))
        if age is None:
            return {"age_seconds": sla * 2.0, "due_pressure": 1.0, "lateness_debt": 1.0, "freshness_score": 0.0}
        due = clamp(age / sla)
        late = max(0.0, (age - sla) / sla)
        freshness_score = clamp(1.0 - due)
        return {
            "age_seconds": age,
            "due_pressure": due,
            "lateness_debt": min(3.0, late),
            "freshness_score": freshness_score,
        }

    def _eligible(self, descriptor: Dict[str, Any], state: Dict[str, Any], objective: Dict[str, Any]) -> bool:
        source_id = descriptor.get("source_id")
        allowed = set(objective.get("source_set") or [])
        if allowed and source_id not in allowed:
            return False
        if not int(descriptor.get("enabled") or 0):
            return False
        circuit = str(state.get("circuit_state") or "CLOSED").upper()
        if circuit == "OPEN":
            next_retry = state.get("next_retry_at")
            if next_retry:
                if isinstance(next_retry, str):
                    try:
                        next_retry = datetime.fromisoformat(next_retry.replace("Z", "+00:00"))
                    except Exception:
                        next_retry = None
                if isinstance(next_retry, datetime):
                    if next_retry.tzinfo is None:
                        next_retry = next_retry.replace(tzinfo=timezone.utc)
                    if next_retry > utcnow():
                        return False
        return True

    def score_source(self, descriptor: Dict[str, Any], state: Dict[str, Any], objective: Dict[str, Any]) -> Dict[str, Any]:
        source_id = descriptor.get("source_id")
        freshness = self.freshness_metrics(descriptor, state)
        overrides = objective.get("priority_overrides") or {}
        mission_rel = clamp(overrides.get(source_id, objective.get("mission_relevance", 0.5)), default=0.5)
        criticality = clamp(descriptor.get("criticality"), default=0.5)
        change_signal = clamp(state.get("change_signal"), default=0.0)
        recovery_need = clamp(float(state.get("failure_count") or 0) / 5.0)
        health = clamp(state.get("health_score"), default=1.0)
        remaining_quota = state.get("remaining_quota")
        limit = descriptor.get("rate_limit_per_window")
        if remaining_quota is None or not limit:
            rate_pressure = 0.0
        else:
            try:
                rate_pressure = clamp(1.0 - float(remaining_quota) / max(1.0, float(limit)))
            except Exception:
                rate_pressure = 0.0
        cost = clamp(state.get("estimated_cost"), default=0.1)
        components = {
            "mission_relevance": mission_rel,
            "freshness_due": freshness["due_pressure"],
            "criticality": criticality,
            "change_signal": change_signal,
            "recovery_need": recovery_need,
            "health": health,
            "rate_pressure": rate_pressure,
            "cost": cost,
        }
        score = sum(self.DEFAULT_WEIGHTS[k] * components[k] for k in self.DEFAULT_WEIGHTS)
        # deterministic tie-breaking is handled by source_id sort after score.
        return {"source_id": source_id, "score": round(score, 6), "components": components, "freshness": freshness}

    def propose_next_action(self, objective: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return None
        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            sources = self.list_sources(objective.get("source_set"))
            ranked: List[Dict[str, Any]] = []
            for descriptor in sources:
                state = self.source_state(descriptor["source_id"])
                if not self._eligible(descriptor, state, objective):
                    continue
                scored = self.score_source(descriptor, state, objective)
                scored["descriptor"] = descriptor
                scored["state"] = state
                ranked.append(scored)
            ranked.sort(key=lambda x: (-x["score"], str(x["source_id"])))
            if not ranked:
                self.registry.update_status(self.SERVICE_KEY, "idle")
                return None

            best = ranked[0]
            state = best["state"]
            descriptor = best["descriptor"]
            freshness = best["freshness"]
            reason_code = "CRITICAL_STALE" if freshness["lateness_debt"] > 0 and clamp(descriptor.get("criticality"), default=0.5) >= 0.7 else "FRESHNESS_DUE"
            if int(state.get("failure_count") or 0) > 0:
                reason_code = "RETRY_DUE"
            decision_id = new_id("acqdec")
            source_config = safe_json_loads(descriptor.get("config_json"), default={}) or {}
            proposal = {
                "decision_id": decision_id,
                "mission_id": objective.get("mission_id"),
                "acquisition_objective_id": objective.get("acquisition_objective_id"),
                "source_id": descriptor.get("source_id"),
                "action_type": "INCREMENTAL_FETCH",
                "connector_id": f"connector:{descriptor.get('protocol') or 'UNKNOWN'}",
                "source_protocol": descriptor.get("protocol"),
                "source_binding": source_binding(descriptor),
                "source_sync_config": source_config if isinstance(source_config, dict) else {},
                "query_window_or_cursor": state.get("watermark_value"),
                "page_token": None,
                "expected_request_cost": 1,
                "expected_freshness_gain": round(1.0 - freshness["freshness_score"], 4),
                "reason_code": reason_code,
                "score_components": best["components"],
                "preconditions": ["SOURCE_ENABLED", "POLICY_GATE_ALLOW", "BUDGET_AVAILABLE"],
                "idempotency_key": f"{objective.get('mission_id')}:{descriptor.get('source_id')}:{state.get('watermark_value') or 'initial'}",
                "policy_context_id": objective.get("policy_context_id"),
                "created_at": utcnow_iso(),
                "authority_state": "PROPOSED_NOT_AUTHORIZED",
            }
            self._persist_proposal(proposal)
            self.audit.append(
                mission_id=objective.get("mission_id"), component_id=self.COMPONENT_ID,
                event_type="acquisition.proposed", reason_code=reason_code,
                input_snapshot={"objective": objective, "source_state": state},
                candidate_alternatives=[{"source_id": x["source_id"], "score": x["score"]} for x in ranked],
                selected_output=proposal,
                evidence_refs=[],
                versions={"algorithm": "rao-baseline-1.0", "policy_context_id": objective.get("policy_context_id")},
                trace_id=decision_id,
            )
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return proposal
        except Exception as exc:
            self.registry.update_status(self.SERVICE_KEY, "error", str(exc))
            raise

    def execute_authorized(
        self,
        proposal: Dict[str, Any],
        policy_decision: Dict[str, Any],
        connector: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute only an externally authorized proposal using a supplied connector."""
        if str(policy_decision.get("decision") or "").upper() != "ALLOW":
            result = {
                "status": "DENIED",
                "proposal": proposal,
                "policy_decision": policy_decision,
                "reason_code": "POLICY_DENIED",
            }
            self.audit.append(
                mission_id=proposal.get("mission_id"),
                component_id=self.COMPONENT_ID,
                event_type="acquisition.denied",
                reason_code="POLICY_DENIED",
                input_snapshot={"proposal": proposal},
                candidate_alternatives=None,
                selected_output=result,
                evidence_refs=[],
                versions={"policy_version": policy_decision.get("policy_version")},
                trace_id=proposal.get("decision_id"),
            )
            return result
        outcome = connector(proposal)
        classification = self.classify_outcome(outcome)
        self.update_source_state(proposal["source_id"], classification, outcome)
        result = {
            "status": classification,
            "proposal": proposal,
            "policy_decision": policy_decision,
            "outcome": outcome,
        }
        self.audit.append(
            mission_id=proposal.get("mission_id"),
            component_id=self.COMPONENT_ID,
            event_type="acquisition.executed",
            reason_code=classification,
            input_snapshot={"proposal": proposal, "policy_decision": policy_decision},
            candidate_alternatives=None,
            selected_output={
                "status": classification,
                "source_id": proposal.get("source_id"),
                "sync_status": outcome.get("sync_status"),
                "watermark_after_candidate": outcome.get("watermark_after_candidate"),
            },
            evidence_refs=[],
            versions={"policy_version": policy_decision.get("policy_version")},
            trace_id=proposal.get("decision_id"),
        )
        return result

    @staticmethod
    def classify_outcome(outcome: Dict[str, Any]) -> str:
        """Classify connector outcomes without conflating partial work with failure.

        ``PARTIAL`` is an expected outcome for bounded agent refreshes (for
        example, Governance may explicitly constrain ``max_pages`` to one).
        It is therefore represented as ``DEGRADED``: incomplete but usable,
        and distinct from transport/validation failures.
        """
        status = int(outcome.get("http_status") or outcome.get("status_code") or 200)
        validation = str(outcome.get("validation_status") or "valid").lower()
        sync_status = str(outcome.get("sync_status") or "").upper()

        if sync_status == "PARTIAL" or validation == "partial":
            return "DEGRADED"
        if status == 429:
            return "RATE_LIMITED"
        if status >= 500 or outcome.get("transient_error"):
            return "TRANSIENT"
        if 200 <= status < 300 and validation not in {"invalid", "failed"}:
            return "SUCCESS"
        return "FAILED"

    def update_source_state(self, source_id: str, classification: str, outcome: Dict[str, Any]) -> None:
        """Persist source health using three-way success/degraded/failure semantics.

        Important invariants:
        * A bounded ``PARTIAL``/``DEGRADED`` response is not a source failure and
          must not increment the consecutive-failure counter or open the
          circuit breaker.
        * ``RATE_LIMITED`` uses retry/backoff semantics but is also not counted
          as source unavailability.
        * Only actual ``FAILED``/``TRANSIENT`` outcomes contribute to circuit
          opening.
        * All Python-generated DATETIME values are persisted as UTC-naive
          values so ``last_attempt_at`` and ``next_retry_at`` share one time
          basis instead of mixing MariaDB local time with Python UTC.
        """
        if not self.db.table_exists("cti_source_state"):
            return

        current = self.source_state(source_id)
        classification = str(classification or "FAILED").upper()
        failures = int(current.get("failure_count") or 0)
        now_db = utcnow().replace(tzinfo=None)
        last_success = current.get("last_success_at")
        watermark = current.get("watermark_value")
        next_retry = None
        circuit = str(current.get("circuit_state") or "CLOSED").upper()

        if classification == "SUCCESS":
            # A successful connector request closes the circuit and resets
            # consecutive source failures. A full success may advance the
            # durable watermark/checkpoint.
            failures = 0
            circuit = "CLOSED"
            last_success = now_db
            watermark = outcome.get("watermark_after_candidate") or watermark
            status = "HEALTHY"
            health = 1.0

        elif classification == "DEGRADED":
            # PARTIAL is intentionally non-fatal. It proves the source is
            # reachable (typically HTTP 2xx) while indicating that the bounded
            # acquisition did not consume the full available window. Reset
            # consecutive source failures and close the circuit, but do not
            # advance last_success_at/watermark as if a complete sync occurred.
            failures = 0
            circuit = "CLOSED"
            status = "DEGRADED"
            health = 0.90

        elif classification == "RATE_LIMITED":
            # Rate limiting is a scheduling/backoff condition, not evidence
            # that the CTI source is unavailable. Preserve the failure counter
            # and keep the circuit closed while setting a retry time.
            circuit = "CLOSED"
            backoff_seconds = min(3600, 2 ** min(max(failures, 1), 10) + random.randint(0, 3))
            next_retry = (utcnow() + timedelta(seconds=backoff_seconds)).replace(tzinfo=None)
            status = "RATE_LIMITED"
            health = clamp(0.80 - failures * 0.05, low=0.50, high=0.80)

        else:
            # Actual transport/server/validation failures contribute to the
            # consecutive-failure counter and may open the circuit breaker.
            failures += 1
            circuit = "OPEN" if failures >= 3 else "CLOSED"
            backoff_seconds = min(3600, 2 ** min(failures, 10) + random.randint(0, 3))
            next_retry = (utcnow() + timedelta(seconds=backoff_seconds)).replace(tzinfo=None)
            status = classification
            health = clamp(1.0 - failures * 0.15, low=0.0, high=1.0)

        self.db.execute(
            """
            INSERT INTO cti_source_state
                (source_id, status, watermark_value, last_success_at, last_attempt_at, failure_count,
                 circuit_state, next_retry_at, health_score, last_observation_json, state_version, updated_at)
            VALUES
                (%(source_id)s, %(status)s, %(watermark_value)s, %(last_success_at)s, %(last_attempt_at)s, %(failure_count)s,
                 %(circuit_state)s, %(next_retry_at)s, %(health_score)s, %(obs)s, 1, %(updated_at)s)
            ON DUPLICATE KEY UPDATE
                status=VALUES(status), watermark_value=VALUES(watermark_value),
                last_success_at=COALESCE(VALUES(last_success_at), last_success_at),
                last_attempt_at=VALUES(last_attempt_at),
                failure_count=VALUES(failure_count), circuit_state=VALUES(circuit_state),
                next_retry_at=VALUES(next_retry_at), health_score=VALUES(health_score),
                last_observation_json=VALUES(last_observation_json), state_version=state_version+1,
                updated_at=VALUES(updated_at)
            """,
            {
                "source_id": source_id,
                "status": status,
                "watermark_value": watermark,
                "last_success_at": last_success,
                "last_attempt_at": now_db,
                "failure_count": failures,
                "circuit_state": circuit,
                "next_retry_at": next_retry,
                "health_score": health,
                "obs": to_json(outcome),
                "updated_at": now_db,
            },
        )

    def _persist_proposal(self, proposal: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_action_proposals"):
            return
        self.db.execute(
            """
            INSERT INTO cti_action_proposals
                (proposal_id, mission_id, proposal_kind, action_type, target_component,
                 target_source_id, reason_code, priority_utility, state_version, plan_version,
                 policy_version, valid_until, evidence_refs_json, proposal_json, status, created_at)
            VALUES
                (%(proposal_id)s, %(mission_id)s, 'RAO', %(action_type)s, %(target_component)s,
                 %(target_source_id)s, %(reason_code)s, %(priority)s, NULL, NULL,
                 %(policy_version)s, NULL, '[]', %(proposal_json)s, 'PROPOSED', CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE proposal_json=VALUES(proposal_json), status='PROPOSED'
            """,
            {
                "proposal_id": proposal["decision_id"],
                "mission_id": proposal.get("mission_id"),
                "action_type": proposal.get("action_type"),
                "target_component": self.SERVICE_KEY,
                "target_source_id": proposal.get("source_id"),
                "reason_code": proposal.get("reason_code"),
                "priority": sum(float(v) for v in (proposal.get("score_components") or {}).values()),
                "policy_version": proposal.get("policy_context_id"),
                "proposal_json": to_json(proposal),
            },
        )
