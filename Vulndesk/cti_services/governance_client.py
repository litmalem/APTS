from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from config import Config
from .contracts import verify_policy_decision_hash


class GovernanceClientError(RuntimeError):
    """Base error raised when the Governance & Safety Plane cannot be used safely."""


class GovernanceUnavailableError(GovernanceClientError):
    """Raised when the Governance & Safety Plane is disabled or unreachable."""


class GovernanceProtocolError(GovernanceClientError):
    """Raised when the Governance API returns an invalid or unexpected response."""


@dataclass(frozen=True)
class GovernanceClientStatus:
    enabled: bool
    base_url: str
    timeout_seconds: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "authority_mode": "EXTERNAL_AUTHORITATIVE_FAIL_CLOSED",
            "task_binding_mode": "POLICY_DECISION_BOUND_TASK_CONTRACT",
            "pre_dispatch_revalidation_mode": "AUTHORITATIVE_FAIL_CLOSED",
            "granular_revocation_mode": "AUTHORITATIVE_EVENT_TRIGGERED_EXACT_BINDING",
            "correlation_probe_mode": "MISSION_SCOPED_AUTHORITATIVE_READ_ONLY",
        }


class GovernanceClient:
    """HTTP adapter from VulnDesk CTI to the independent aptsGSS authority.

    The client performs transport/protocol duties only. It does not contain policy
    logic and it never turns an unavailable Governance service into an ALLOW.

    Stage 2 adds strict PolicyDecision contract validation.  A newly issued
    decision is hash-verified against the canonical aptsGSS decision body and the
    authorization-request dimensions are attached as non-authoritative transport
    metadata so CTI-A01 can bind the exact authorization to its TaskContract.
    """

    COMPONENT_ID = "CTI-INF05"
    AUTHORIZATION_PATH = "/api/governance/authorization/evaluate"
    REVALIDATION_PATH = "/api/governance/authorization/revalidate"
    DECISION_PATH = "/api/governance/decisions/{decision_id}"
    MISSION_CORRELATION_PATH = "/api/governance/correlation/missions/{mission_id}"
    HEALTH_PATH = "/health"

    _REQUIRED_DECISION_FIELDS = (
        "request_id",
        "decision_id",
        "mission_id",
        "decision",
        "reason_codes",
        "constraints",
        "requires_human_approval",
        "valid_from",
        "valid_until",
        "decision_hash",
    )

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        session: Optional[requests.Session] = None,
    ):
        self.enabled = Config.GOVERNANCE_ENABLED if enabled is None else bool(enabled)
        self.base_url = str(base_url or Config.GOVERNANCE_BASE_URL).rstrip("/")
        self.timeout_seconds = float(
            Config.GOVERNANCE_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        )
        self.session = session or requests.Session()

    @property
    def status(self) -> GovernanceClientStatus:
        return GovernanceClientStatus(
            enabled=self.enabled,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
        )

    def health_check(self) -> Dict[str, Any]:
        if not self.enabled:
            raise GovernanceUnavailableError("Governance integration is disabled")
        try:
            response = self.session.get(
                f"{self.base_url}{self.HEALTH_PATH}",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            raise GovernanceUnavailableError(f"Governance health check failed: {exc}") from exc
        except ValueError as exc:
            raise GovernanceProtocolError("Governance health response is not valid JSON") from exc
        if not isinstance(body, dict):
            raise GovernanceProtocolError("Governance health response must be a JSON object")
        return body

    def evaluate_cti_source_read(
        self,
        *,
        mission_id: str,
        source_id: str,
        action_name: str = "INCREMENTAL_FETCH",
        scope_contract_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        evidence_refs: Optional[List[str]] = None,
        requested_by: str = "CTI-A02",
    ) -> Dict[str, Any]:
        payload = {
            "mission_id": str(mission_id),
            "scope_contract_id": scope_contract_id or None,
            "subject_component": "CTI-A02",
            "action_class": "CTI_SOURCE_READ",
            "action_name": str(action_name or "INCREMENTAL_FETCH"),
            "resource_type": "CTI_SOURCE",
            "resource_value": str(source_id),
            "context": dict(context or {}),
            "evidence_refs": list(evidence_refs or []),
            "requested_by": requested_by,
        }
        return self.evaluate_authorization(payload)

    def evaluate_authorization(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            raise GovernanceUnavailableError("Governance integration is disabled")

        request_payload = dict(payload)
        try:
            response = self.session.post(
                f"{self.base_url}{self.AUTHORIZATION_PATH}",
                json=request_payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GovernanceUnavailableError(f"Governance authorization request failed: {exc}") from exc

        body = self._completed_json_response(response, operation="authorization")
        decision = body.get("policy_decision")
        normalized = self._normalize_policy_decision(
            decision,
            expected_mission_id=request_payload.get("mission_id"),
            expected_scope_contract_id=request_payload.get("scope_contract_id"),
            verify_hash=True,
        )
        governance_event_id = str(normalized.get("governance_event_id") or "").strip()
        if not governance_event_id.startswith("gevent-"):
            raise GovernanceProtocolError(
                "Governance policy_decision is missing authoritative governance_event_id (gevent-*)"
            )
        normalized["governance_event_id"] = governance_event_id
        normalized["authorization_request"] = {
            "mission_id": request_payload.get("mission_id"),
            "scope_contract_id": request_payload.get("scope_contract_id"),
            "subject_component": request_payload.get("subject_component"),
            "action_class": request_payload.get("action_class"),
            "action_name": request_payload.get("action_name"),
            "resource_type": request_payload.get("resource_type"),
            "resource_value": request_payload.get("resource_value"),
            "requested_by": request_payload.get("requested_by"),
        }
        return normalized

    def revalidate_policy_decision(
        self,
        *,
        task_id: str,
        decision_id: str,
        request_id: str,
        mission_id: str,
        decision_hash: str,
        scope_contract_id: Optional[str],
        scope_version: Optional[Any],
        policy_set_id: Optional[str],
        policy_version: Optional[Any],
        subject_component: Optional[str],
        action_class: str,
        action_name: str,
        resource_type: str,
        resource_value: str,
        requested_by: str = "CTI-A01",
    ) -> Dict[str, Any]:
        """Ask aptsGSS to validate the exact bound decision immediately before dispatch.

        This does not request a fresh authorization and never upgrades an invalid
        result to ALLOW.  The returned authority/status/hash are checked again at
        the transport boundary so CTI-A01 can fail closed on malformed responses.
        """
        if not self.enabled:
            raise GovernanceUnavailableError("Governance integration is disabled")

        payload = {
            "task_id": str(task_id),
            "decision_id": str(decision_id),
            "request_id": str(request_id),
            "mission_id": str(mission_id),
            "scope_contract_id": scope_contract_id or None,
            "scope_version": scope_version,
            "policy_set_id": policy_set_id or None,
            "policy_version": policy_version,
            "decision_hash": str(decision_hash or "").lower(),
            "subject_component": subject_component or None,
            "action_class": str(action_class),
            "action_name": str(action_name),
            "resource_type": str(resource_type),
            "resource_value": str(resource_value),
            "requested_by": requested_by,
        }
        try:
            response = self.session.post(
                f"{self.base_url}{self.REVALIDATION_PATH}",
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GovernanceUnavailableError(
                f"Governance PolicyDecision revalidation failed: {exc}"
            ) from exc

        body = self._completed_json_response(response, operation="PolicyDecision revalidation")
        result = body.get("revalidation")
        if not isinstance(result, dict):
            raise GovernanceProtocolError("Governance revalidation response does not contain revalidation")

        required = (
            "revalidation_id",
            "status",
            "valid",
            "execution_authorized",
            "reason_codes",
            "decision_id",
            "request_id",
            "mission_id",
            "decision_hash",
            "decision_status",
            "checked_at",
            "authority",
            "authority_component",
            "governance_event_id",
        )
        missing = [name for name in required if name not in result or result.get(name) is None]
        if missing:
            raise GovernanceProtocolError(
                "Governance revalidation is missing required fields: " + ", ".join(missing)
            )
        if not isinstance(result.get("reason_codes"), list):
            raise GovernanceProtocolError("Governance revalidation reason_codes must be a list")
        if str(result.get("decision_id")) != str(decision_id):
            raise GovernanceProtocolError("Governance revalidation decision_id mismatch")
        if str(result.get("request_id")) != str(request_id):
            raise GovernanceProtocolError("Governance revalidation request_id mismatch")
        if str(result.get("mission_id")) != str(mission_id):
            raise GovernanceProtocolError("Governance revalidation mission_id mismatch")
        if str(result.get("decision_hash") or "").lower() != str(decision_hash or "").lower():
            raise GovernanceProtocolError("Governance revalidation decision_hash mismatch")
        if str(result.get("authority")) != "aptsGSS" or str(result.get("authority_component")) != "GOV-PLANE":
            raise GovernanceProtocolError("Governance revalidation authority mismatch")
        governance_event_id = str(result.get("governance_event_id") or "").strip()
        if not governance_event_id.startswith("gevent-"):
            raise GovernanceProtocolError(
                "Governance revalidation is missing authoritative governance_event_id (gevent-*)"
            )

        status = str(result.get("status") or "").upper()
        valid = bool(result.get("valid"))
        execution_authorized = bool(result.get("execution_authorized"))
        if status not in {"VALID", "INVALID"}:
            raise GovernanceProtocolError(f"Unsupported Governance revalidation status: {status!r}")
        if status == "VALID" and (not valid or not execution_authorized):
            raise GovernanceProtocolError("Governance VALID revalidation is not execution-authorized")
        if status == "INVALID" and (valid or execution_authorized):
            raise GovernanceProtocolError("Governance INVALID revalidation is inconsistent")

        normalized = dict(result)
        normalized["status"] = status
        normalized["decision_hash"] = str(result.get("decision_hash") or "").lower()
        normalized["decision_status"] = str(result.get("decision_status") or "").upper()
        normalized["governance_event_id"] = governance_event_id
        return normalized

    def get_policy_decision(
        self,
        decision_id: str,
        *,
        expected_mission_id: Optional[str] = None,
        expected_scope_contract_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve the current authoritative state of an existing decision.

        The persisted aptsGSS row exposes the original ``decision_hash`` plus
        lifecycle state (ACTIVE/REVOKED/EXPIRED/SUPERSEDED).  Its SQL DATETIME
        representation is not byte-identical to the original hashed JSON, so this
        GET path validates the hash format and identity but does not recompute it.
        The original POST response is hash-verified before task commit; later
        revalidation can compare the stored TaskContract hash with this value.
        """

        if not self.enabled:
            raise GovernanceUnavailableError("Governance integration is disabled")
        decision_id = str(decision_id or "").strip()
        if not decision_id:
            raise GovernanceProtocolError("decision_id is required")
        path = self.DECISION_PATH.format(decision_id=quote(decision_id, safe=""))
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GovernanceUnavailableError(f"Governance decision lookup failed: {exc}") from exc

        body = self._completed_json_response(response, operation="decision lookup")
        normalized = self._normalize_policy_decision(
            body.get("policy_decision"),
            expected_mission_id=expected_mission_id,
            expected_scope_contract_id=expected_scope_contract_id,
            verify_hash=False,
        )
        if normalized["decision_id"] != decision_id:
            raise GovernanceProtocolError(
                f"Governance decision lookup identity mismatch: expected {decision_id!r}"
            )
        return normalized

    def get_mission_correlation_snapshot(self, mission_id: str) -> Dict[str, Any]:
        """Fetch one authoritative Governance snapshot for Stage 2.9.4 correlation.

        The endpoint is read-only and mission-scoped.  VulnDesk consumes the
        snapshot as provenance evidence only; it never treats it as a new
        authorization or mutates the returned Governance records.
        """
        if not self.enabled:
            raise GovernanceUnavailableError("Governance integration is disabled")
        mission_id = str(mission_id or "").strip()
        if not mission_id:
            raise GovernanceProtocolError("mission_id is required")
        path = self.MISSION_CORRELATION_PATH.format(mission_id=quote(mission_id, safe=""))
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GovernanceUnavailableError(
                f"Governance mission correlation lookup failed: {exc}"
            ) from exc

        body = self._completed_json_response(response, operation="mission correlation lookup")
        snapshot = body.get("correlation_snapshot")
        if not isinstance(snapshot, dict):
            raise GovernanceProtocolError(
                "Governance mission correlation response does not contain correlation_snapshot"
            )
        if str(snapshot.get("mission_id") or "") != mission_id:
            raise GovernanceProtocolError(
                "Governance mission correlation snapshot mission_id mismatch"
            )
        required_collections = (
            "scope_contracts",
            "authorization_requests",
            "policy_decisions",
            "events",
            "audit_records",
        )
        for name in required_collections:
            if not isinstance(snapshot.get(name), list):
                raise GovernanceProtocolError(
                    f"Governance mission correlation snapshot {name} must be a list"
                )
        return snapshot

    def _completed_json_response(self, response: requests.Response, *, operation: str) -> Dict[str, Any]:
        if response.status_code < 200 or response.status_code >= 300:
            detail = self._response_detail(response)
            raise GovernanceProtocolError(
                f"Governance {operation} returned HTTP {response.status_code}: {detail}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise GovernanceProtocolError(f"Governance {operation} response is not valid JSON") from exc
        if not isinstance(body, dict):
            raise GovernanceProtocolError(f"Governance {operation} response must be a JSON object")
        if str(body.get("status") or "").lower() != "completed":
            raise GovernanceProtocolError(
                f"Governance {operation} response status is not completed: {body.get('status')!r}"
            )
        return body

    def _normalize_policy_decision(
        self,
        decision: Any,
        *,
        expected_mission_id: Optional[str],
        expected_scope_contract_id: Optional[str],
        verify_hash: bool,
    ) -> Dict[str, Any]:
        if not isinstance(decision, dict):
            raise GovernanceProtocolError("Governance response does not contain policy_decision")

        missing = [
            name for name in self._REQUIRED_DECISION_FIELDS
            if name not in decision or decision.get(name) is None
        ]
        if missing:
            raise GovernanceProtocolError(
                "Governance policy_decision is missing required fields: " + ", ".join(missing)
            )

        decision_value = str(decision.get("decision") or "").upper()
        if decision_value not in {"ALLOW", "DENY", "REVIEW"}:
            raise GovernanceProtocolError(
                f"Governance returned unsupported decision value: {decision_value!r}"
            )

        decision_hash = str(decision.get("decision_hash") or "").strip().lower()
        if len(decision_hash) != 64 or any(ch not in "0123456789abcdef" for ch in decision_hash):
            raise GovernanceProtocolError("Governance policy_decision has an invalid decision_hash")
        if verify_hash and not verify_policy_decision_hash(decision):
            raise GovernanceProtocolError("Governance policy_decision decision_hash verification failed")

        mission_id = str(decision.get("mission_id") or "")
        if expected_mission_id is not None and mission_id != str(expected_mission_id):
            raise GovernanceProtocolError(
                f"Governance policy_decision mission mismatch: expected {expected_mission_id!r}, got {mission_id!r}"
            )

        if expected_scope_contract_id is not None:
            returned_scope = decision.get("scope_contract_id")
            if str(returned_scope or "") != str(expected_scope_contract_id):
                raise GovernanceProtocolError(
                    "Governance policy_decision scope_contract_id does not match the requested scope"
                )

        reason_codes = decision.get("reason_codes")
        constraints = decision.get("constraints")
        if not isinstance(reason_codes, list):
            raise GovernanceProtocolError("Governance policy_decision reason_codes must be a list")
        if not isinstance(constraints, dict):
            raise GovernanceProtocolError("Governance policy_decision constraints must be an object")

        normalized = dict(decision)
        normalized["decision"] = decision_value
        normalized["decision_hash"] = decision_hash
        normalized["decision_status"] = str(decision.get("decision_status") or "ACTIVE").upper()
        normalized["authority"] = "aptsGSS"
        normalized["authority_component"] = "GOV-PLANE"
        normalized["execution_authorized"] = (
            decision_value == "ALLOW" and normalized["decision_status"] == "ACTIVE"
        )
        normalized["target_actuation"] = False
        normalized["decision_hash_verified"] = bool(verify_hash)
        return normalized

    @staticmethod
    def _response_detail(response: requests.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("message") or body
                return str(detail)[:500]
        except ValueError:
            pass
        text = str(getattr(response, "text", "") or "").strip()
        return text[:500] or "no response detail"
