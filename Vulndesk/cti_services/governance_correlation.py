from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .db_adapter import make_json_safe
from .governance_client import (
    GovernanceClient,
    GovernanceClientError,
    GovernanceProtocolError,
    GovernanceUnavailableError,
)


GOVERNANCE_CORRELATION_SCHEMA_V1 = "cti-governance-correlation-v1"


class CrossSubsystemGovernanceCorrelator:
    """Stage 2.9.4 read-side correlation against authoritative aptsGSS records.

    The correlator never changes local lineage or Governance authority. It compares
    durable identifiers already present in the canonical CTI projection with one
    authoritative mission snapshot returned by aptsGSS and reports correlation facts.
    Integrity/violation classification is intentionally deferred to Stage 2.9.5.
    """

    _GOV_EVENT_TYPES = {
        "authorization": {"POLICY_DECISION_ISSUED"},
        "revalidation": {"POLICY_DECISION_REVALIDATED", "POLICY_DECISION_REVALIDATION_FAILED"},
        "revocation": {"AUTHORIZATION_REVOKED"},
    }

    def __init__(self, governance_client: Optional[GovernanceClient] = None):
        self.governance = governance_client or GovernanceClient()

    def correlate_mission(self, projection: Dict[str, Any]) -> Dict[str, Any]:
        mission_id = self._text((projection.get("identity") or {}).get("mission_id"))
        if not mission_id:
            raise ValueError("mission projection has no mission_id")
        snapshot, error = self._authoritative_snapshot(mission_id)
        if error:
            result = self._unavailable_result(mission_id, error)
            return self._attach_mission_result(projection, result)

        indexes = self._indexes(snapshot)
        task_results = [
            self._correlate_task(task, indexes, mission_id=mission_id)
            for task in projection.get("task_lineages") or []
        ]
        external_event_results = self._correlate_mission_external_events(projection, indexes)
        facts = self._mission_facts(task_results, external_event_results)
        status = self._overall_status(task_results, external_event_results)
        result = make_json_safe({
            "schema_version": GOVERNANCE_CORRELATION_SCHEMA_V1,
            "scope": "MISSION",
            "mission_id": mission_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "status": status,
            "authoritative_snapshot": self._snapshot_summary(snapshot),
            "task_correlations": task_results,
            "external_event_correlations": external_event_results,
            "correlation_facts": facts,
            "classification": "CORRELATION_FACTS_ONLY_STAGE_2_9_4",
            "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
        })
        return self._attach_mission_result(projection, result)

    def correlate_task(self, projection: Dict[str, Any]) -> Dict[str, Any]:
        identity = projection.get("identity") or {}
        mission_id = self._text(identity.get("mission_id"))
        if not mission_id:
            raise ValueError("task projection has no mission_id")
        snapshot, error = self._authoritative_snapshot(mission_id)
        if error:
            result = self._unavailable_result(mission_id, error, scope="TASK")
            return self._attach_task_result(projection, result)

        indexes = self._indexes(snapshot)
        task_result = self._correlate_task(projection, indexes, mission_id=mission_id)
        result = make_json_safe({
            "schema_version": GOVERNANCE_CORRELATION_SCHEMA_V1,
            "scope": "TASK",
            "mission_id": mission_id,
            "task_id": self._text(identity.get("task_id")),
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "status": task_result["status"],
            "authoritative_snapshot": self._snapshot_summary(snapshot),
            "task_correlation": task_result,
            "classification": "CORRELATION_FACTS_ONLY_STAGE_2_9_4",
            "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
        })
        return self._attach_task_result(projection, result)

    def _authoritative_snapshot(self, mission_id: str):
        try:
            return self.governance.get_mission_correlation_snapshot(mission_id), None
        except GovernanceUnavailableError as exc:
            return None, {"status": "UNAVAILABLE", "error_type": type(exc).__name__, "message": str(exc)}
        except GovernanceProtocolError as exc:
            return None, {"status": "PROTOCOL_ERROR", "error_type": type(exc).__name__, "message": str(exc)}
        except GovernanceClientError as exc:
            return None, {"status": "ERROR", "error_type": type(exc).__name__, "message": str(exc)}

    def _correlate_task(self, lineage: Mapping[str, Any], indexes: Dict[str, Dict[str, Dict[str, Any]]], *, mission_id: str) -> Dict[str, Any]:
        identity = lineage.get("identity") or {}
        task_id = self._text(identity.get("task_id"))
        binding = lineage.get("governance_binding") or {}
        contract = lineage.get("task_contract") or {}
        required = bool(binding.get("required_authority")) or self._text(binding.get("authorization_mode")).upper() == "REQUIRED"

        if not required:
            return {
                "task_id": task_id,
                "status": "NOT_REQUIRED_INTERNAL",
                "required_authority": False,
                "references": [],
                "field_comparisons": [],
                "coverage_complete": True,
            }

        refs: List[Dict[str, Any]] = []
        comparisons: List[Dict[str, Any]] = []

        request_id = self._nullable(binding.get("authorization_request_id"))
        decision_id = self._nullable(binding.get("policy_decision_id"))
        scope_id = self._nullable(binding.get("scope_contract_id"))
        issuance_event_id = self._nullable(binding.get("authorization_governance_event_id"))
        revalidation_event_id = self._nullable(binding.get("pre_dispatch_governance_event_id"))
        revocation_event_id = self._nullable(binding.get("revocation_event_id"))

        request = self._reference(refs, "AUTHORIZATION_REQUEST", request_id, indexes["requests"])
        decision = self._reference(refs, "POLICY_DECISION", decision_id, indexes["decisions"])
        scope = self._reference(refs, "SCOPE_CONTRACT", scope_id, indexes["scopes"])
        issuance = self._reference(refs, "AUTHORIZATION_GOVERNANCE_EVENT", issuance_event_id, indexes["events"])
        revalidation = self._reference(refs, "REVALIDATION_GOVERNANCE_EVENT", revalidation_event_id, indexes["events"], optional=True)
        revocation = self._reference(refs, "REVOCATION_GOVERNANCE_EVENT", revocation_event_id, indexes["events"], optional=True)

        if request:
            self._compare(comparisons, "request.mission_id", mission_id, request.get("mission_id"))
            self._compare(comparisons, "request.scope_contract_id", scope_id, request.get("scope_contract_id"), optional=scope_id is None)
            self._compare(comparisons, "request.subject_component", contract.get("governance_subject_component"), request.get("subject_component"), optional=contract.get("governance_subject_component") in (None, ""))
            self._compare(comparisons, "request.action_class", contract.get("governance_action_class"), request.get("action_class"), optional=contract.get("governance_action_class") in (None, ""))
            self._compare(comparisons, "request.action_name", contract.get("governance_action_name"), request.get("action_name"), optional=contract.get("governance_action_name") in (None, ""))
            self._compare(comparisons, "request.resource_type", contract.get("governance_resource_type"), request.get("resource_type"), optional=contract.get("governance_resource_type") in (None, ""))
            self._compare(comparisons, "request.resource_value", contract.get("governance_resource_value"), request.get("resource_value"), optional=contract.get("governance_resource_value") in (None, ""))

        if decision:
            self._compare(comparisons, "decision.mission_id", mission_id, decision.get("mission_id"))
            self._compare(comparisons, "decision.request_id", request_id, decision.get("request_id"))
            self._compare(comparisons, "decision.decision_hash", binding.get("policy_decision_hash"), decision.get("decision_hash"), optional=binding.get("policy_decision_hash") in (None, ""))
            self._compare(comparisons, "decision.scope_contract_id", scope_id, decision.get("scope_contract_id"), optional=scope_id is None)
            self._compare(comparisons, "decision.scope_version", binding.get("scope_version"), decision.get("scope_version"), optional=binding.get("scope_version") is None)
            self._compare(comparisons, "decision.policy_set_id", binding.get("policy_set_id"), decision.get("policy_set_id"), optional=binding.get("policy_set_id") in (None, ""))
            self._compare(comparisons, "decision.policy_version", binding.get("policy_version"), decision.get("policy_version"), optional=binding.get("policy_version") in (None, ""))
            self._compare(comparisons, "decision.decision", binding.get("authorization_decision"), decision.get("decision"), optional=binding.get("authorization_decision") in (None, ""))

        if scope:
            self._compare(comparisons, "scope.mission_id", mission_id, scope.get("mission_id"))
            self._compare(comparisons, "scope.version", binding.get("scope_version"), scope.get("version"), optional=binding.get("scope_version") is None)

        if issuance:
            self._compare_event(comparisons, "authorization_event", issuance, self._GOV_EVENT_TYPES["authorization"], mission_id, decision_id=decision_id, request_id=request_id, task_id=None)
        if revalidation:
            self._compare_event(comparisons, "revalidation_event", revalidation, self._GOV_EVENT_TYPES["revalidation"], mission_id, decision_id=decision_id, request_id=request_id, task_id=task_id)
            payload = revalidation.get("payload") or {}
            self._compare(comparisons, "revalidation_event.revalidation_id", binding.get("pre_dispatch_revalidation_id"), payload.get("revalidation_id"), optional=binding.get("pre_dispatch_revalidation_id") in (None, ""))
        if revocation:
            self._compare_event(comparisons, "revocation_event", revocation, self._GOV_EVENT_TYPES["revocation"], mission_id, decision_id=decision_id, request_id=request_id, task_id=None)
            payload = revocation.get("payload") or {}
            self._compare(comparisons, "revocation_event.revocation_id", binding.get("revocation_id"), payload.get("revocation_id"), optional=binding.get("revocation_id") in (None, ""))

        missing_required = [
            ref
            for ref in refs
            if ref["status"] in {"MISSING_GOVERNANCE_RECORD", "MISSING_LOCAL_REFERENCE"}
            and not ref.get("optional")
        ]
        mismatches = [item for item in comparisons if item["status"] == "MISMATCH"]
        status = "CORRELATED" if not missing_required and not mismatches else "PARTIAL"
        return make_json_safe({
            "task_id": task_id,
            "status": status,
            "required_authority": True,
            "references": refs,
            "field_comparisons": comparisons,
            "coverage_complete": not missing_required and not mismatches,
            "missing_required_reference_count": len(missing_required),
            "mismatch_count": len(mismatches),
        })

    def _correlate_mission_external_events(self, projection: Mapping[str, Any], indexes: Dict[str, Dict[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        seen = set()
        result: List[Dict[str, Any]] = []
        for event in projection.get("events") or []:
            upstream = self._nullable((event or {}).get("upstream_event_id"))
            if not upstream or not upstream.startswith("gevent-") or upstream in seen:
                continue
            seen.add(upstream)
            authoritative = indexes["events"].get(upstream)
            result.append(make_json_safe({
                "governance_event_id": upstream,
                "local_event_id": (event or {}).get("event_id"),
                "local_event_type": (event or {}).get("event_type"),
                "status": "MATCH" if authoritative else "MISSING_GOVERNANCE_RECORD",
                "authoritative_event_type": authoritative.get("event_type") if authoritative else None,
                "delivery_status": authoritative.get("delivery_status") if authoritative else None,
            }))
        return result

    @classmethod
    def _reference(cls, refs: List[Dict[str, Any]], kind: str, reference_id: Optional[str], index: Mapping[str, Dict[str, Any]], optional: bool = False):
        if not reference_id:
            refs.append({
                "kind": kind,
                "reference_id": None,
                "status": "NOT_PRESENT_OPTIONAL" if optional else "MISSING_LOCAL_REFERENCE",
                "optional": optional,
            })
            return None
        row = index.get(reference_id)
        refs.append({
            "kind": kind,
            "reference_id": reference_id,
            "status": "MATCH" if row else "MISSING_GOVERNANCE_RECORD",
            "optional": optional,
        })
        return row

    @classmethod
    def _compare(cls, result: List[Dict[str, Any]], field: str, local: Any, authoritative: Any, *, optional: bool = False) -> None:
        if optional and local in (None, ""):
            result.append({"field": field, "local": local, "authoritative": authoritative, "status": "NOT_ASSERTED_OPTIONAL"})
            return
        result.append({
            "field": field,
            "local": local,
            "authoritative": authoritative,
            "status": "MATCH" if cls._normalized(local) == cls._normalized(authoritative) else "MISMATCH",
        })

    @classmethod
    def _compare_event(cls, result: List[Dict[str, Any]], prefix: str, event: Mapping[str, Any], allowed_types: set[str], mission_id: str, *, decision_id: Optional[str], request_id: Optional[str], task_id: Optional[str]) -> None:
        payload = event.get("payload") or {}
        event_type = cls._text(event.get("event_type")).upper()
        result.append({
            "field": f"{prefix}.event_type",
            "local": sorted(allowed_types),
            "authoritative": event_type,
            "status": "MATCH" if event_type in allowed_types else "MISMATCH",
        })
        cls._compare(result, f"{prefix}.mission_id", mission_id, event.get("mission_id"))
        if decision_id:
            cls._compare(result, f"{prefix}.decision_id", decision_id, payload.get("decision_id"))
        if request_id:
            cls._compare(result, f"{prefix}.request_id", request_id, payload.get("request_id"))
        if task_id:
            cls._compare(result, f"{prefix}.task_id", task_id, payload.get("task_id"))

    @classmethod
    def _mission_facts(cls, task_results: Sequence[Mapping[str, Any]], event_results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        governed = [row for row in task_results if row.get("required_authority")]
        correlated = [row for row in governed if row.get("status") == "CORRELATED"]
        missing = sum(int(row.get("missing_required_reference_count") or 0) for row in governed)
        mismatches = sum(int(row.get("mismatch_count") or 0) for row in governed)
        missing_events = sum(1 for row in event_results if row.get("status") == "MISSING_GOVERNANCE_RECORD")
        return {
            "task_count": len(task_results),
            "governed_task_count": len(governed),
            "correlated_governed_task_count": len(correlated),
            "missing_required_reference_count": missing,
            "field_mismatch_count": mismatches,
            "external_event_reference_count": len(event_results),
            "missing_external_event_count": missing_events,
            "coverage_complete": len(governed) == len(correlated) and missing_events == 0,
        }

    @staticmethod
    def _overall_status(task_results: Sequence[Mapping[str, Any]], event_results: Sequence[Mapping[str, Any]]) -> str:
        governed = [row for row in task_results if row.get("required_authority")]
        if not governed and not event_results:
            return "NOT_REQUIRED"
        if all(row.get("status") == "CORRELATED" for row in governed) and all(row.get("status") == "MATCH" for row in event_results):
            return "CORRELATED"
        return "PARTIAL"

    @classmethod
    def _indexes(cls, snapshot: Mapping[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
        return {
            "requests": cls._index(snapshot.get("authorization_requests") or [], "request_id"),
            "decisions": cls._index(snapshot.get("policy_decisions") or [], "decision_id"),
            "scopes": cls._index(snapshot.get("scope_contracts") or [], "scope_contract_id"),
            "events": cls._index(snapshot.get("events") or [], "event_id"),
            "audits": cls._index(snapshot.get("audit_records") or [], "audit_id"),
        }

    @classmethod
    def _index(cls, rows: Iterable[Mapping[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            identity = cls._nullable(row.get(key))
            if identity and identity not in result:
                result[identity] = dict(row)
        return result

    @staticmethod
    def _snapshot_summary(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "mission_id": snapshot.get("mission_id"),
            "scope_contract_count": len(snapshot.get("scope_contracts") or []),
            "authorization_request_count": len(snapshot.get("authorization_requests") or []),
            "policy_decision_count": len(snapshot.get("policy_decisions") or []),
            "event_count": len(snapshot.get("events") or []),
            "audit_record_count": len(snapshot.get("audit_records") or []),
        }

    @staticmethod
    def _unavailable_result(mission_id: str, error: Mapping[str, Any], *, scope: str = "MISSION") -> Dict[str, Any]:
        return {
            "schema_version": GOVERNANCE_CORRELATION_SCHEMA_V1,
            "scope": scope,
            "mission_id": mission_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "status": error.get("status") or "UNAVAILABLE",
            "error": dict(error),
            "classification": "CORRELATION_FACTS_ONLY_STAGE_2_9_4",
            "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
        }

    @staticmethod
    def _attach_mission_result(projection: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(projection)
        enriched["governance_correlation"] = result
        metadata = dict(enriched.get("projection_metadata") or {})
        metadata["governance_correlation_status"] = result.get("status")
        metadata["integrity_classification_status"] = "NOT_EVALUATED_STAGE_2_9_5"
        enriched["projection_metadata"] = metadata
        return make_json_safe(enriched)

    @staticmethod
    def _attach_task_result(projection: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(projection)
        enriched["governance_correlation"] = result
        binding = dict(enriched.get("governance_binding") or {})
        binding["correlation_status"] = result.get("status")
        enriched["governance_binding"] = binding
        return make_json_safe(enriched)

    @staticmethod
    def _normalized(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value).strip().lower()

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _nullable(cls, value: Any) -> Optional[str]:
        text = cls._text(value)
        return text or None
