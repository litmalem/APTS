from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .common import sha256_object, utcnow_iso


AUTHORIZATION_REQUIRED = "REQUIRED"
AUTHORIZATION_NOT_REQUIRED_INTERNAL = "NOT_REQUIRED_INTERNAL"
AUTHORITATIVE_GOVERNANCE = "aptsGSS"
AUTHORITATIVE_GOVERNANCE_COMPONENT = "GOV-PLANE"


class ContractValidationError(ValueError):
    """Raised when a cross-component contract cannot be committed safely."""


def _parse_utc(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ContractValidationError(f"{field_name} is required")
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ContractValidationError(f"{field_name} is not a valid ISO-8601 timestamp") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def policy_decision_hash_payload(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild the canonical aptsGSS decision body used to calculate decision_hash.

    aptsGSS hashes the decision payload before ``decision_hash`` is appended.  Keep
    this list intentionally explicit so transport metadata injected by VulnDesk
    (authority, request snapshot, verification flags) cannot alter verification.
    """

    return {
        "decision_id": decision.get("decision_id"),
        "request_id": decision.get("request_id"),
        "mission_id": decision.get("mission_id"),
        "decision": decision.get("decision"),
        "risk_score": decision.get("risk_score"),
        "risk_level": decision.get("risk_level"),
        "reason_codes": list(decision.get("reason_codes") or []),
        "constraints": dict(decision.get("constraints") or {}),
        "requires_human_approval": bool(decision.get("requires_human_approval")),
        "approval_request_id": decision.get("approval_request_id"),
        "valid_from": decision.get("valid_from"),
        "valid_until": decision.get("valid_until"),
        "policy_set_id": decision.get("policy_set_id"),
        "policy_version": decision.get("policy_version"),
        "scope_contract_id": decision.get("scope_contract_id"),
        "scope_version": decision.get("scope_version"),
        "supersedes_decision_id": decision.get("supersedes_decision_id"),
    }


def verify_policy_decision_hash(decision: Dict[str, Any]) -> bool:
    supplied = str(decision.get("decision_hash") or "").strip().lower()
    if len(supplied) != 64:
        return False
    return sha256_object(policy_decision_hash_payload(decision)).lower() == supplied


@dataclass(frozen=True)
class PolicyDecisionBinding:
    """Immutable VulnDesk snapshot that binds an aptsGSS decision to one task.

    The binding does not create authority.  It preserves the exact authoritative
    decision identifier/hash plus the authorization request dimensions that were
    evaluated, allowing CTI-A01 to prove why a task was eligible for commit.
    """

    authority: str
    authority_component: str
    decision_id: str
    request_id: str
    mission_id: str
    decision: str
    decision_hash: str
    decision_status: str
    policy_set_id: Optional[str]
    policy_version: Optional[Any]
    scope_contract_id: Optional[str]
    scope_version: Optional[Any]
    valid_from: str
    valid_until: str
    requires_human_approval: bool
    approval_request_id: Optional[str]
    reason_codes: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    action_class: Optional[str] = None
    action_name: Optional[str] = None
    resource_type: Optional[str] = None
    resource_value: Optional[str] = None
    subject_component: Optional[str] = None
    # Stage 2.8.8: authoritative aptsGSS outbox event that issued this
    # PolicyDecision. This is provenance metadata, not part of decision_hash.
    governance_event_id: Optional[str] = None
    hash_verified: bool = False
    bound_at: str = field(default_factory=utcnow_iso)

    @classmethod
    def from_policy_decision(
        cls,
        decision: Dict[str, Any],
        *,
        expected_mission_id: str,
        expected_action_class: Optional[str] = None,
        expected_action_name: Optional[str] = None,
        expected_resource_type: Optional[str] = None,
        expected_resource_value: Optional[str] = None,
        expected_scope_contract_id: Optional[str] = None,
        require_allow: bool = True,
        require_current_validity: bool = True,
    ) -> "PolicyDecisionBinding":
        if not isinstance(decision, dict):
            raise ContractValidationError("PolicyDecision must be an object")

        required = ("decision_id", "request_id", "mission_id", "decision_hash", "valid_from", "valid_until")
        missing = [name for name in required if decision.get(name) in (None, "")]
        if missing:
            raise ContractValidationError(
                "PolicyDecision is missing required fields: " + ", ".join(missing)
            )

        authority = str(decision.get("authority") or "")
        authority_component = str(decision.get("authority_component") or "")
        if authority != AUTHORITATIVE_GOVERNANCE or authority_component != AUTHORITATIVE_GOVERNANCE_COMPONENT:
            raise ContractValidationError(
                "TaskContract authority must originate from aptsGSS/GOV-PLANE"
            )

        governance_event_id = str(decision.get("governance_event_id") or "").strip() or None

        mission_id = str(decision.get("mission_id") or "")
        if mission_id != str(expected_mission_id):
            raise ContractValidationError(
                f"PolicyDecision mission mismatch: expected {expected_mission_id!r}, got {mission_id!r}"
            )

        decision_value = str(decision.get("decision") or "").upper()
        if decision_value not in {"ALLOW", "DENY", "REVIEW"}:
            raise ContractValidationError(f"Unsupported PolicyDecision value: {decision_value!r}")
        if require_allow and decision_value != "ALLOW":
            raise ContractValidationError(
                f"TaskContract requiring authority cannot bind decision={decision_value}"
            )

        decision_status = str(decision.get("decision_status") or "ACTIVE").upper()
        if decision_status != "ACTIVE":
            raise ContractValidationError(
                f"PolicyDecision is not active: decision_status={decision_status}"
            )

        if bool(decision.get("requires_human_approval")):
            raise ContractValidationError(
                "PolicyDecision still requires human approval and cannot authorize task commit"
            )

        # Never trust a transport-supplied verification flag.  Recompute the
        # canonical aptsGSS hash at the TaskContract boundary.
        hash_verified = verify_policy_decision_hash(decision)
        if not hash_verified:
            raise ContractValidationError("PolicyDecision decision_hash verification failed")

        valid_from_dt = _parse_utc(decision.get("valid_from"), "valid_from")
        valid_until_dt = _parse_utc(decision.get("valid_until"), "valid_until")
        if valid_until_dt <= valid_from_dt:
            raise ContractValidationError("PolicyDecision valid_until must be after valid_from")
        if require_current_validity:
            now = datetime.now(timezone.utc)
            if now < valid_from_dt:
                raise ContractValidationError("PolicyDecision is not valid yet")
            if now >= valid_until_dt:
                raise ContractValidationError("PolicyDecision has expired")

        request = decision.get("authorization_request") or {}
        if not isinstance(request, dict):
            request = {}

        action_class = request.get("action_class")
        action_name = request.get("action_name")
        resource_type = request.get("resource_type")
        resource_value = request.get("resource_value")
        subject_component = request.get("subject_component")

        expected_pairs = (
            ("action_class", expected_action_class, action_class),
            ("action_name", expected_action_name, action_name),
            ("resource_type", expected_resource_type, resource_type),
            ("resource_value", expected_resource_value, resource_value),
        )
        for field_name, expected, actual in expected_pairs:
            if expected is not None and str(actual or "") != str(expected):
                raise ContractValidationError(
                    f"PolicyDecision authorization request {field_name} mismatch: "
                    f"expected {expected!r}, got {actual!r}"
                )

        scope_contract_id = decision.get("scope_contract_id")
        if expected_scope_contract_id is not None and str(scope_contract_id or "") != str(expected_scope_contract_id):
            raise ContractValidationError(
                "PolicyDecision scope_contract_id does not match the mission/task scope"
            )

        return cls(
            authority=authority,
            authority_component=authority_component,
            decision_id=str(decision["decision_id"]),
            request_id=str(decision["request_id"]),
            mission_id=mission_id,
            decision=decision_value,
            decision_hash=str(decision["decision_hash"]),
            decision_status=decision_status,
            policy_set_id=decision.get("policy_set_id"),
            policy_version=decision.get("policy_version"),
            scope_contract_id=scope_contract_id,
            scope_version=decision.get("scope_version"),
            valid_from=str(decision.get("valid_from")),
            valid_until=str(decision.get("valid_until")),
            requires_human_approval=bool(decision.get("requires_human_approval")),
            approval_request_id=decision.get("approval_request_id"),
            reason_codes=[str(x) for x in (decision.get("reason_codes") or [])],
            constraints=dict(decision.get("constraints") or {}),
            action_class=str(action_class) if action_class is not None else None,
            action_name=str(action_name) if action_name is not None else None,
            resource_type=str(resource_type) if resource_type is not None else None,
            resource_value=str(resource_value) if resource_value is not None else None,
            subject_component=str(subject_component) if subject_component is not None else None,
            governance_event_id=governance_event_id,
            hash_verified=hash_verified,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "authority_component": self.authority_component,
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "mission_id": self.mission_id,
            "decision": self.decision,
            "decision_hash": self.decision_hash,
            "decision_status": self.decision_status,
            "policy_set_id": self.policy_set_id,
            "policy_version": self.policy_version,
            "scope_contract_id": self.scope_contract_id,
            "scope_version": self.scope_version,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "requires_human_approval": self.requires_human_approval,
            "approval_request_id": self.approval_request_id,
            "reason_codes": list(self.reason_codes),
            "constraints": dict(self.constraints),
            "action_class": self.action_class,
            "action_name": self.action_name,
            "resource_type": self.resource_type,
            "resource_value": self.resource_value,
            "subject_component": self.subject_component,
            "governance_event_id": self.governance_event_id,
            "hash_verified": self.hash_verified,
            "bound_at": self.bound_at,
        }


@dataclass(frozen=True)
class TaskContract:
    """Structured task contract owned by VulnDesk CTI-A01.

    Governance authorization and local workflow admissibility are deliberately
    separate.  ``local_guard`` may only further restrict execution; it never
    substitutes for a required external PolicyDecision.
    """

    task_id: str
    mission_id: str
    plan_id: str
    assigned_component: str
    task_type: str
    priority: int
    input_refs: List[Any]
    local_guard: Dict[str, Any]
    plan_version: int
    policy_version: str
    state_version: int
    trace_id: str
    authorization_mode: str = AUTHORIZATION_NOT_REQUIRED_INTERNAL
    governance: Optional[PolicyDecisionBinding] = None
    retry_policy: Dict[str, Any] = field(default_factory=lambda: {"max_retries": 1, "backoff": "event-driven-replan"})
    success_criteria: Dict[str, Any] = field(default_factory=lambda: {"status": "completed_or_explicitly_skipped"})

    def validate(self) -> None:
        if not str(self.trace_id or "").strip():
            raise ContractValidationError("TaskContract requires a stable non-empty trace_id")
        if str(self.local_guard.get("decision") or "").upper() != "ALLOW":
            raise ContractValidationError("TaskContract cannot be committed unless local guard=ALLOW")
        if self.authorization_mode not in {AUTHORIZATION_REQUIRED, AUTHORIZATION_NOT_REQUIRED_INTERNAL}:
            raise ContractValidationError(f"Unsupported authorization_mode: {self.authorization_mode!r}")
        if self.authorization_mode == AUTHORIZATION_REQUIRED:
            if self.governance is None:
                raise ContractValidationError(
                    "TaskContract authorization_mode=REQUIRED requires an authoritative PolicyDecisionBinding"
                )
            if self.governance.decision != "ALLOW":
                raise ContractValidationError("Required PolicyDecisionBinding must be ALLOW")
            if self.governance.mission_id != self.mission_id:
                raise ContractValidationError("PolicyDecisionBinding mission_id mismatch")
        elif self.governance is not None:
            raise ContractValidationError(
                "Internal TaskContract must not carry external execution authority"
            )

    def as_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "task_id": self.task_id,
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "assigned_component": self.assigned_component,
            "task_type": self.task_type,
            "priority": self.priority,
            "input_refs": list(self.input_refs),
            "local_guard": dict(self.local_guard),
            "plan_version": self.plan_version,
            "policy_version": self.policy_version,
            "state_version": self.state_version,
            "trace_id": self.trace_id,
            "authorization_mode": self.authorization_mode,
            "governance": self.governance.as_dict() if self.governance else None,
            "retry_policy": dict(self.retry_policy),
            "success_criteria": dict(self.success_criteria),
        }
