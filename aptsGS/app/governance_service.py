from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .audit_service import AuditService
from .approval_auth import AUTH_MODE, ApprovalAccessError, ApprovalPrincipal
from .config import settings
from .compliance_service import ComplianceService
from .db import to_json
from .event_publisher import GovernanceEventPublisher
from .models import (
    ActionClass,
    ApprovalDecisionInput,
    AuthorizationRequest,
    PolicyDecisionRevalidationRequest,
    Decision,
    EmergencyStopInput,
    RevokeDecisionInput,
    RiskLevel,
    ScopeContractCreate,
)
from .policy_engine import DeterministicActionGate, GateResult
from .repositories import GovernanceRepository
from .risk_engine import DeterministicRiskEngine
from .scope_service import ScopeMatcher
from .utils import new_id, sha256_json
from .execution_revalidation import prepare_execution_evaluation, execution_risk_context, apply_execution_checks
from .delegation_profile import scope_action_constraints_with_profiles
from .workflow_profile import apply_workflow_profile


class GovernanceError(RuntimeError):
    pass


def _aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dt_str(dt: datetime | str | None) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class GovernanceService:
    def __init__(self, repo: Optional[GovernanceRepository] = None):
        self.repo = repo or GovernanceRepository()
        self.risk = DeterministicRiskEngine()
        self.scope_matcher = ScopeMatcher()
        self.gate = DeterministicActionGate()
        self.audit = AuditService(self.repo)
        self.compliance = ComplianceService(self.repo)
        self.events = GovernanceEventPublisher(self.repo)

    # ---------- Scope ----------
    def create_scope_contract(self, *args, **kwargs):
        database = getattr(self.repo, "db", None)
        if database is None:
            return self._create_scope_contract_tx(*args, **kwargs)
        with database.connect():
            return self._create_scope_contract_tx(*args, **kwargs)

    def _create_scope_contract_tx(
            self, 
            request: ScopeContractCreate, 
            *, 
            revision_version: int = 1,
            auto_recon_task_delegation_profile: bool | None = None,
            workflow_profile: str | None = None,
            ) -> dict:
        policy = self.repo.get_policy_set(request.policy_set_id)
        if not policy or policy.get("status") != "ACTIVE":
            raise GovernanceError(f"Policy set is not active: {request.policy_set_id}")

        scope_contract_id = new_id("scope")
        valid_from = _aware_utc(request.valid_from) or datetime.now(timezone.utc)
        valid_until = _aware_utc(request.valid_until)
        action_constraints, profile_metadata = apply_workflow_profile(
            [item.model_dump(mode="json") for item in request.action_constraints],
            workflow_profile,
        )
        action_constraints, auto_profile_applied = scope_action_constraints_with_profiles(
            action_constraints,
            auto_recon_task_delegation=(
                settings.auto_recon_task_delegation
                if auto_recon_task_delegation_profile is None
                else auto_recon_task_delegation_profile
            ),
        )

        metadata = dict(request.metadata)
        if profile_metadata:
            metadata["gss_workflow_profile"] = profile_metadata
        else:
            metadata.pop("gss_workflow_profile", None)

        contract_payload = {
            "scope_contract_id": scope_contract_id,
            "mission_id": request.mission_id,
            "name": request.name,
            "policy_set_id": request.policy_set_id,
            "version": revision_version,
            "valid_from": _dt_str(valid_from),
            "valid_until": _dt_str(valid_until),
            "created_by": request.created_by,
            "approved_by": request.approved_by,
            "targets": [item.model_dump(mode="json") for item in request.targets],
            "sources": [item.model_dump(mode="json") for item in request.sources],
            "action_constraints": action_constraints,
            "metadata": metadata,
        }
        contract_hash = sha256_json(contract_payload)

        self.repo.insert_scope_contract({
            "scope_contract_id": scope_contract_id,
            "mission_id": request.mission_id,
            "name": request.name,
            "status": "ACTIVE",
            "policy_set_id": request.policy_set_id,
            "version": revision_version,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "created_by": request.created_by,
            "approved_by": request.approved_by,
            "approved_at": datetime.now(timezone.utc) if request.approved_by else None,
            "metadata_json": to_json(metadata),
            "contract_hash": contract_hash,
        })

        self.repo.insert_scope_targets([
            {
                "scope_target_id": new_id("stgt"),
                "scope_contract_id": scope_contract_id,
                "target_type": item.target_type.upper(),
                "target_value": item.target_value,
                "normalized_value": item.target_value.strip().lower(),
                "environment": item.environment.upper(),
                "allowed": 1 if item.allowed else 0,
                "notes": item.notes,
            }
            for item in request.targets
        ])
        self.repo.insert_scope_sources([
            {
                "scope_source_id": new_id("ssrc"),
                "scope_contract_id": scope_contract_id,
                "source_id": item.source_id,
                "source_type": item.source_type,
                "allowed": 1 if item.allowed else 0,
                "constraints_json": to_json(item.constraints),
            }
            for item in request.sources
        ])
        self.repo.insert_action_constraints([
            {
                "constraint_id": new_id("sact"),
                "scope_contract_id": scope_contract_id,
                "action_class": item["action_class"],
                "action_name": item["action_name"],
                "effect": item["effect"],
                "max_risk_level": item["max_risk_level"],
                "requires_approval": 1 if item["requires_approval"] else 0,
                "constraints_json": to_json(item["constraints"]),
            }
            for item in action_constraints
        ])

        self.audit.record(
            "SCOPE_CONTRACT_CREATED",
            actor_id=request.created_by,
            mission_id=request.mission_id,
            subject_type="SCOPE_CONTRACT",
            subject_id=scope_contract_id,
            payload={"contract_hash": contract_hash, "policy_set_id": request.policy_set_id,
                     "auto_recon_task_delegation_profile_applied": auto_profile_applied,
                     "workflow_profile": profile_metadata},
        )
        self.events.publish(
            "SCOPE_CHANGED",
            mission_id=request.mission_id,
            payload={
                "scope_contract_id": scope_contract_id,
                "scope_version": revision_version,
                "contract_hash": contract_hash,
            },
        )
        return self.repo.get_scope_contract(scope_contract_id) or contract_payload

    # ---------- Authorization ----------
    def evaluate_authorization(
        self,
        request: AuthorizationRequest,
        *,
        human_approval_granted: bool = False,
        supersedes_decision_id: Optional[str] = None,
        existing_request_id: Optional[str] = None,
    ) -> dict:
        if human_approval_granted:
            raise ApprovalAccessError("HUMAN_APPROVAL_MUST_USE_AUTHENTICATED_DECISION_PATH")
        return self._evaluate_authorization(
            request, supersedes_decision_id=supersedes_decision_id,
            existing_request_id=existing_request_id,
        )

    def _evaluate_authorization(self, request, **kwargs):
        database = getattr(self.repo, "db", None)
        if database is None:
            return self._evaluate_authorization_tx(request, **kwargs)
        with database.connect():
            return self._evaluate_authorization_tx(request, **kwargs)

    def _evaluate_authorization_tx(
        self,
        request: AuthorizationRequest,
        *,
        approval_evidence: Optional[dict] = None,
        supersedes_decision_id: Optional[str] = None,
        existing_request_id: Optional[str] = None,
    ) -> dict:
        human_approval_granted = approval_evidence is not None
        try:
            execution_evaluation = prepare_execution_evaluation(request)
        except ValueError as exc:
            raise GovernanceError(str(exc)) from exc
        request_id = existing_request_id or new_id("greq")
        scope = None
        if request.scope_contract_id:
            scope = self.repo.get_scope_contract(request.scope_contract_id)
        if scope is None and not request.scope_contract_id:
            scope = self.repo.find_active_scope_for_mission(request.mission_id)

        if existing_request_id is None:
            self.repo.insert_authorization_request({
                "request_id": request_id,
                "mission_id": request.mission_id,
                "scope_contract_id": scope.get("scope_contract_id") if scope else request.scope_contract_id,
                "subject_component": request.subject_component,
                "action_class": request.action_class.value,
                "action_name": request.action_name,
                "resource_type": request.resource_type,
                "resource_value": request.resource_value,
                "context_json": to_json(request.context),
                "evidence_refs_json": to_json(request.evidence_refs),
                "requested_by": request.requested_by,
            })

        execution_constraint = self.repo.find_action_constraint(scope["scope_contract_id"], request.action_class.value, request.action_name) if execution_evaluation and scope else None
        risk_context = execution_risk_context(execution_evaluation, scope, execution_constraint) if execution_evaluation else request.context
        if request.action_class == ActionClass.TASK_DELEGATION:
            # TASK_DELEGATION is a logical handoff permission. Caller-supplied
            # target/risk flags do not define its risk or grant target authority.
            risk_context = {}
        risk = self.risk.assess(request.action_class, risk_context)
        assessment_id = new_id("grisk")
        self.repo.insert_risk_assessment({
            "assessment_id": assessment_id,
            "request_id": request_id,
            "mission_id": request.mission_id,
            "risk_score": risk.score,
            "risk_level": risk.level.value,
            "factors_json": to_json(risk.factors),
        })

        emergency = self.repo.get_emergency_state()
        scope_active = self._scope_active(scope)
        targets = (scope or {}).get("targets") or []
        sources = (scope or {}).get("sources") or []

        target_match = self.scope_matcher.target_in_scope(request.resource_value, targets)
        source_match = self.scope_matcher.source_allowed(request.resource_value, sources)
        constraint = None
        if scope:
            constraint = self.repo.find_action_constraint(
                scope["scope_contract_id"],
                request.action_class.value,
                request.action_name,
            )

        if request.action_class == ActionClass.TASK_DELEGATION:
            valid_delegation_request = (
                request.subject_component == "APTS-MO01"
                and request.action_name == "delegate_planned_task"
                and request.resource_type == "SUBSYSTEM_CAPABILITY"
                and request.context.get("authorization_purpose") == "PRE_DELEGATION_ONLY"
                and request.context.get("target_action_authority_requested") is False
            )
            target_match = (
                self.scope_matcher.subsystem_capability_allowed(request.resource_value, constraint)
                if valid_delegation_request
                else type(target_match)(False, "DELEGATION_REQUEST_CONTRACT_INVALID")
            )

        gate = self.gate.evaluate(
            action_class=request.action_class,
            risk_level=risk.level,
            emergency_stop_active=bool(emergency.get("active")),
            scope_active=scope_active,
            resource_in_scope=target_match.matched,
            source_allowed=source_match.matched,
            action_constraint=constraint,
            human_approval_granted=human_approval_granted,
        )

        if request.action_class == ActionClass.TASK_DELEGATION and gate.decision == Decision.ALLOW:
            # Defense in depth: reject legacy or manually corrupted DB rules,
            # even if their capability string happens to be allowlisted.
            from .delegation_preflight import allow_rule_problems
            problems = allow_rule_problems(constraint, request.resource_value)
            if problems:
                gate = GateResult(Decision.DENY, problems)

        policy_set_id = (scope or {}).get("policy_set_id") or "default-policy"
        current_policy = self.repo.get_policy_set(policy_set_id)
        policy = current_policy or {
            "policy_set_id": policy_set_id,
            "version": None,
        }
        if scope and scope.get("mission_id") != request.mission_id:
            gate = GateResult(Decision.DENY, ["SCOPE_MISSION_MISMATCH"])
        if not self._policy_active(current_policy):
            gate = GateResult(Decision.DENY, ["NO_ACTIVE_POLICY_SET"])

        execution_proof = None
        if execution_evaluation:
            try:
                gate, execution_proof = apply_execution_checks(self, request, execution_evaluation, scope, policy,
                    constraint, emergency, gate, now=datetime.now(timezone.utc), human_approval_granted=human_approval_granted)
            except (KeyError, TypeError, ValueError) as exc:
                raise GovernanceError("Invalid Stage 6 execution restrictions") from exc

        # AL-025: autonomy-level authorization gate (deny-closed; opt-in). Applies only
        # when a grant store is provisioned and the request declares the autonomy level
        # it operates under. Never grants authority; only denies when the level is not
        # covered by an ACTIVE, unexpired grant.
        level_denials = self._level_gate_denials(request, scope, emergency)
        if level_denials:
            gate = GateResult(Decision.DENY, [*gate.reason_codes, *level_denials], gate.constraints)

        approval_request_id = (approval_evidence or {}).get("approval_request_id")
        if gate.decision == Decision.REVIEW and gate.requires_human_approval:
            approval_request_id = new_id("gapproval")
            self.repo.insert_approval_request({
                "approval_request_id": approval_request_id,
                "authorization_request_id": request_id,
                "mission_id": request.mission_id,
                "risk_level": risk.level.value,
                "reason": ",".join(gate.reason_codes),
                "required_approver_role": (constraint or {}).get("constraints", {}).get(
                    "required_approver_role", "SECURITY_APPROVER"
                ),
                "expires_at": datetime.now(timezone.utc)
                + timedelta(seconds=settings.approval_ttl_seconds),
            })

        valid_from = datetime.now(timezone.utc)
        valid_until = valid_from + timedelta(seconds=settings.decision_ttl_seconds)
        decision_id = new_id("gdec")
        reason_codes = list(gate.reason_codes)
        if request.action_class == ActionClass.CTI_SOURCE_READ:
            reason_codes.append(source_match.reason)
        elif request.action_class not in {ActionClass.INTERNAL_REASONING, ActionClass.REPORTING}:
            reason_codes.append(target_match.reason)

        obligations = self.compliance.obligations(
            str(policy.get("policy_set_id") or "default-policy"),
            request.action_class.value,
        )
        decision_constraints = dict(gate.constraints)
        if request.action_class == ActionClass.TASK_DELEGATION:
            decision_constraints["delegation_scope"] = {
                "action_class": ActionClass.TASK_DELEGATION.value,
                "action_name": request.action_name,
                "subject_component": request.subject_component,
                "resource_type": request.resource_type,
                "resource_value": request.resource_value,
                "authorization_purpose": request.context.get("authorization_purpose"),
                "delegation_authorized": gate.decision == Decision.ALLOW,
                "execution_authorized": False,
                "target_actuation": False,
            }
        if obligations:
            decision_constraints["compliance_obligations"] = obligations

        decision_body = {
            "decision_id": decision_id,
            "request_id": request_id,
            "mission_id": request.mission_id,
            "decision": gate.decision.value,
            "risk_score": risk.score,
            "risk_level": risk.level.value,
            "reason_codes": reason_codes,
            "constraints": decision_constraints,
            "requires_human_approval": gate.requires_human_approval,
            "approval_request_id": approval_request_id,
            "valid_from": _dt_str(valid_from),
            "valid_until": _dt_str(valid_until),
            "policy_set_id": policy.get("policy_set_id"),
            "policy_version": policy.get("version"),
            "scope_contract_id": (scope or {}).get("scope_contract_id"),
            "scope_version": (scope or {}).get("version"),
            "supersedes_decision_id": supersedes_decision_id,
        }
        if approval_evidence is not None:
            decision_body["human_approval"] = dict(approval_evidence)
        if execution_proof is not None:
            # The attestation is included before the immutable decision hash and
            # preserved in authoritative audit/outbox payloads.
            execution_proof["checked_at"] = _dt_str(valid_from)
            decision_body["execution_revalidation"] = execution_proof
        decision_hash = sha256_json(decision_body)
        decision_body["decision_hash"] = decision_hash

        self.repo.insert_policy_decision({
            "decision_id": decision_id,
            "request_id": request_id,
            "mission_id": request.mission_id,
            "policy_set_id": policy.get("policy_set_id"),
            "policy_version": policy.get("version"),
            "scope_contract_id": (scope or {}).get("scope_contract_id"),
            "scope_version": (scope or {}).get("version"),
            "decision": gate.decision.value,
            "reason_codes_json": to_json(reason_codes),
            "constraints_json": to_json(decision_constraints),
            "requires_human_approval": 1 if gate.requires_human_approval else 0,
            "approval_request_id": approval_request_id,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "decision_hash": decision_hash,
            "supersedes_decision_id": supersedes_decision_id,
        })
        self.repo.update_authorization_status(request_id, gate.decision.value)

        # Stage 2.8.8: the authoritative outbox event identity is returned to
        # the synchronous caller and preserved in the Governance audit record.
        # It is transport/provenance metadata and is intentionally excluded
        # from the immutable PolicyDecision hash payload.
        governance_event_id = self.events.publish(
            "POLICY_DECISION_ISSUED",
            mission_id=request.mission_id,
            payload=decision_body,
            severity="WARNING" if gate.decision != Decision.ALLOW else "INFO",
        )
        if isinstance(governance_event_id, str) and governance_event_id:
            decision_body["governance_event_id"] = governance_event_id
        self.audit.record(
            "POLICY_DECISION_ISSUED",
            actor_id="GOV-S04",
            mission_id=request.mission_id,
            subject_type="POLICY_DECISION",
            subject_id=decision_id,
            payload=decision_body,
        )
        return decision_body

    def _scope_active(self, scope: Optional[dict]) -> bool:
        if not scope or scope.get("status") != "ACTIVE":
            return False
        now = datetime.now(timezone.utc)
        for key, comparator in (("valid_from", "from"), ("valid_until", "until")):
            value = scope.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            if comparator == "from" and now < value:
                return False
            if comparator == "until" and now > value:
                return False
        return True

    def _policy_active(self, policy: Optional[dict]) -> bool:
        if not policy or policy.get("status") != "ACTIVE":
            return False
        now = datetime.now(timezone.utc)
        for field, lower in (("effective_from", True), ("effective_until", False)):
            value = policy.get(field)
            if value is not None:
                if isinstance(value, str):
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                value = _aware_utc(value)
                if (lower and now < value) or (not lower and now >= value):
                    return False
        return True

    # ---------- Approval ----------
    def decide_approval(self, approval_request_id: str, decision: ApprovalDecisionInput,
                        *, principal: Optional[ApprovalPrincipal] = None) -> dict:
        if not isinstance(principal, ApprovalPrincipal):
            raise ApprovalAccessError("HUMAN_APPROVAL_AUTHENTICATION_REQUIRED", 401)
        if principal.principal_type != "HUMAN":
            raise ApprovalAccessError("HUMAN_APPROVER_REQUIRED")
        with self.repo.approval_transaction():
            return self._decide_authenticated_approval(approval_request_id, decision, principal)

    def _decide_authenticated_approval(self, approval_request_id: str,
                                      decision: ApprovalDecisionInput, principal: ApprovalPrincipal) -> dict:
        approval = self.repo.get_approval_request(approval_request_id)
        if not approval:
            raise ApprovalAccessError("Approval request not found", 404)
        if approval.get("status") != "PENDING":
            raise ApprovalAccessError("Approval request is not pending", 409)
        expires_at = approval.get("expires_at")
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ApprovalAccessError("Invalid approval expiry", 409) from exc
        if not isinstance(expires_at, datetime) or _aware_utc(expires_at) <= datetime.now(timezone.utc):
            raise ApprovalAccessError("Approval request has expired or has no expiry", 409)
        role = approval.get("required_approver_role")
        if not isinstance(role, str) or not role or role not in principal.roles:
            raise ApprovalAccessError("REQUIRED_APPROVER_ROLE_NOT_GRANTED")
        if decision.approver_id is not None and decision.approver_id != principal.principal_id:
            raise ApprovalAccessError("APPROVER_IDENTITY_MISMATCH")
        if decision.approver_role is not None and decision.approver_role != role:
            raise ApprovalAccessError("APPROVER_ROLE_MISMATCH")

        auth_row = self.repo.get_authorization_request(approval["authorization_request_id"])
        if not auth_row:
            raise GovernanceError("Original authorization request not found")
        if (auth_row.get("request_id") != approval["authorization_request_id"]
                or auth_row.get("mission_id") != approval.get("mission_id")
                or auth_row.get("request_status") != "REVIEW"):
            raise ApprovalAccessError("APPROVAL_AUTHORIZATION_BINDING_MISMATCH", 409)

        request = AuthorizationRequest(
            mission_id=auth_row["mission_id"],
            scope_contract_id=auth_row.get("scope_contract_id"),
            subject_component=auth_row["subject_component"],
            action_class=ActionClass(auth_row["action_class"]),
            action_name=auth_row["action_name"],
            resource_type=auth_row["resource_type"],
            resource_value=auth_row["resource_value"],
            context=auth_row.get("context") or {},
            evidence_refs=auth_row.get("evidence_refs") or [],
            requested_by=auth_row.get("requested_by"),
        )
        try:
            prepare_execution_evaluation(request)
        except ValueError as exc:
            raise GovernanceError(str(exc)) from exc
        current_constraint = self.repo.find_action_constraint(
            request.scope_contract_id, request.action_class.value, request.action_name,
        ) if request.scope_contract_id else None
        if current_constraint:
            current_role = (current_constraint.get("constraints") or {}).get("required_approver_role", "SECURITY_APPROVER")
            if current_role != role:
                raise ApprovalAccessError("APPROVER_ROLE_REQUIREMENT_CHANGED", 409)

        approval_decision_id = new_id("gapprovaldec")
        approval_payload = {
            "approval_decision_id": approval_decision_id,
            "approval_request_id": approval_request_id,
            "authorization_request_id": auth_row["request_id"],
            "mission_id": auth_row["mission_id"],
            "approver_id": principal.principal_id,
            "approver_role": role,
            "authentication_mode": AUTH_MODE,
            "decision": decision.decision,
            "reason": decision.reason,
        }
        approval_hash = sha256_json(approval_payload)
        self.repo.insert_approval_decision({**approval_payload, "decision_hash": approval_hash})

        if decision.decision == "APPROVE":
            final_decision = self._evaluate_authorization(
                request,
                approval_evidence={**approval_payload, "decision_hash": approval_hash},
                existing_request_id=auth_row["request_id"],
            )
        else:
            final_decision = self._issue_human_denial(auth_row, approval_request_id, decision,
                approval_evidence={**approval_payload, "decision_hash": approval_hash})

        self.audit.record(
            "APPROVAL_DECIDED",
            actor_id=principal.principal_id,
            mission_id=auth_row["mission_id"],
            subject_type="APPROVAL_REQUEST",
            subject_id=approval_request_id,
            payload={**approval_payload, "decision_hash": approval_hash},
        )
        return {
            "approval": {**approval_payload, "decision_hash": approval_hash},
            "policy_decision": final_decision,
        }

    def _issue_human_denial(self, auth_row: dict, approval_request_id: str, decision: ApprovalDecisionInput,
                            *, approval_evidence: dict) -> dict:
        now = datetime.now(timezone.utc)
        decision_id = new_id("gdec")
        body = {
            "decision_id": decision_id,
            "request_id": auth_row["request_id"],
            "mission_id": auth_row["mission_id"],
            "decision": "DENY",
            "risk_score": 0.0,
            "risk_level": "LOW",
            "reason_codes": ["HUMAN_APPROVAL_DENIED"],
            "constraints": {},
            "requires_human_approval": False,
            "approval_request_id": approval_request_id,
            "human_approval": dict(approval_evidence),
            "valid_from": _dt_str(now),
            "valid_until": _dt_str(now + timedelta(seconds=settings.decision_ttl_seconds)),
            "policy_set_id": None,
            "policy_version": None,
            "scope_contract_id": auth_row.get("scope_contract_id"),
            "scope_version": None,
        }
        body["decision_hash"] = sha256_json(body)
        self.repo.insert_policy_decision({
            "decision_id": decision_id,
            "request_id": auth_row["request_id"],
            "mission_id": auth_row["mission_id"],
            "policy_set_id": None,
            "policy_version": None,
            "scope_contract_id": auth_row.get("scope_contract_id"),
            "scope_version": None,
            "decision": "DENY",
            "reason_codes_json": to_json(body["reason_codes"]),
            "constraints_json": "{}",
            "requires_human_approval": 0,
            "approval_request_id": approval_request_id,
            "valid_from": now,
            "valid_until": now + timedelta(seconds=settings.decision_ttl_seconds),
            "decision_hash": body["decision_hash"],
            "supersedes_decision_id": None,
        })
        self.repo.update_authorization_status(auth_row["request_id"], "DENY")
        governance_event_id = self.events.publish(
            "POLICY_DECISION_ISSUED",
            mission_id=auth_row["mission_id"],
            payload=body,
            severity="WARNING",
        )
        if isinstance(governance_event_id, str) and governance_event_id:
            body["governance_event_id"] = governance_event_id
        return body

    # ---------- Emergency ----------
    def activate_emergency_stop(self, request: EmergencyStopInput) -> dict:
        action_id = new_id("gstop")
        state = self.repo.set_emergency_state(
            active=True,
            actor_id=request.actor_id,
            reason=request.reason,
            metadata=request.metadata,
            action_id=action_id,
        )
        self.audit.record(
            "EMERGENCY_STOP_ACTIVATED",
            actor_id=request.actor_id,
            subject_type="EMERGENCY_STATE",
            subject_id="global",
            payload={"action_id": action_id, "reason": request.reason, "state": state},
        )
        for mission_id in self.repo.active_mission_ids():
            # Current VulnDesk CTI-A01 already consumes AUTHORIZATION_REVOKED.
            # The emergency flag preserves the semantic source of revocation.
            self.events.publish(
                "AUTHORIZATION_REVOKED",
                mission_id=mission_id,
                payload={
                    "reason": "GLOBAL_EMERGENCY_STOP",
                    "emergency_stop": True,
                    "revocation_scope": "GLOBAL_EMERGENCY_STOP",
                    "governance_state_version": state.get("version"),
                    "authority": "aptsGSS",
                    "authority_component": "GOV-PLANE",
                },
                severity="CRITICAL",
            )
        return state

    def release_emergency_stop(self, request: EmergencyStopInput) -> dict:
        action_id = new_id("gstop")
        state = self.repo.set_emergency_state(
            active=False,
            actor_id=request.actor_id,
            reason=request.reason,
            metadata=request.metadata,
            action_id=action_id,
        )
        self.audit.record(
            "EMERGENCY_STOP_RELEASED",
            actor_id=request.actor_id,
            subject_type="EMERGENCY_STATE",
            subject_id="global",
            payload={"action_id": action_id, "reason": request.reason, "state": state},
        )
        for mission_id in self.repo.active_mission_ids():
            self.events.publish(
                "POLICY_CHANGED",
                mission_id=mission_id,
                payload={
                    "reason": "GLOBAL_EMERGENCY_STOP_RELEASED",
                    "emergency_stop": False,
                    "governance_state_version": state.get("version"),
                },
                severity="WARNING",
            )
        return state

    # ---------- Autonomy-level authorization (AL-025) ----------
    def _level_gate_denials(self, request, scope, emergency) -> list:
        """DENY reason codes when the request's declared autonomy level is not covered
        by an ACTIVE, unexpired grant. Opt-in: no-op unless the repo provides a grant
        store and the request declares `autonomy_level_required` in its context."""
        getter = getattr(self.repo, "get_active_level_grant", None)
        if getter is None:
            return []
        context = request.context if isinstance(request.context, dict) else {}
        required = context.get("autonomy_level_required")
        if required is None:
            return []
        scope_contract_id = (scope or {}).get("scope_contract_id") or request.scope_contract_id
        from .authorization_level import AuthorizationLevelError, level_gate_reason_codes
        try:
            grant = getter(mission_id=request.mission_id, scope_contract_id=scope_contract_id)
            return level_gate_reason_codes(
                grant, requested_level=required,
                now=datetime.now(timezone.utc), emergency_active=bool(emergency.get("active")),
            )
        except AuthorizationLevelError:
            return ["LEVEL_AUTHORIZATION_FAILED:GRANT-INTEGRITY"]

    def issue_authorization_level_grant(self, *, mission_id: str, scope_contract_id: str,
                                        authorized_level: int, approver: str,
                                        authorization_reference: str,
                                        valid_from=None, valid_until=None) -> dict:
        """Issue a fresh ACTIVE level grant (human-approved), persisted + lineage recorded."""
        from .authorization_level import build_authorization_level_grant
        now = datetime.now(timezone.utc)
        start = valid_from or now
        end = valid_until or (now + timedelta(seconds=settings.level_grant_ttl_seconds))
        grant = build_authorization_level_grant(
            grant_id=new_id("glevel"), mission_id=mission_id, scope_contract_id=scope_contract_id,
            authorized_level=authorized_level, approver=approver,
            authorization_reference=authorization_reference, valid_from=start, valid_until=end,
        )
        self.repo.save_level_grant(grant)
        self.audit.record("AUTONOMY_LEVEL_GRANT_ISSUED", actor_id=approver,
                          subject_type="AUTONOMY_LEVEL_GRANT", subject_id=grant["grant_id"],
                          payload={"authorized_level": authorized_level, "grant_sha256": grant["integrity"]["canonical_sha256"]})
        return grant

    def downgrade_authorization_level(self, *, mission_id: str, scope_contract_id: str,
                                      signal: str, to_level: int) -> dict:
        """Lower the autonomy ceiling in response to an incident; persist + record lineage."""
        from .authorization_level import downgrade_on_incident
        grant = self.repo.get_active_level_grant(mission_id=mission_id, scope_contract_id=scope_contract_id)
        if grant is None:
            raise GovernanceError("no active autonomy-level grant to downgrade")
        transition_id = new_id("gleveltr")
        downgraded, transition = downgrade_on_incident(
            grant, signal=signal, to_level=to_level, now=datetime.now(timezone.utc),
            transition_id=transition_id, downgraded_grant_id=new_id("glevel"),
        )
        self.repo.save_level_grant(downgraded)
        self.repo.save_level_transition(transition, transition_id=transition_id,
                                        mission_id=mission_id, scope_contract_id=scope_contract_id)
        self.audit.record("AUTONOMY_LEVEL_DOWNGRADED", actor_id="SYSTEM",
                          subject_type="AUTONOMY_LEVEL_GRANT", subject_id=downgraded["grant_id"],
                          payload={"signal": signal, "to_level": to_level,
                                   "transition_sha256": transition["integrity"]["canonical_sha256"]})
        return downgraded

    def reauthorize_authorization_level(self, *, mission_id: str, scope_contract_id: str,
                                        approver: str, authorized_level: int,
                                        authorization_reference: str,
                                        valid_from=None, valid_until=None) -> dict:
        """Human re-authorization that supersedes an expired/downgraded grant."""
        from .authorization_level import reauthorize_level
        previous = self.repo.get_active_level_grant(mission_id=mission_id, scope_contract_id=scope_contract_id)
        if previous is None:
            raise GovernanceError("no prior autonomy-level grant to re-authorize")
        now = datetime.now(timezone.utc)
        transition_id = new_id("gleveltr")
        new_grant, transition = reauthorize_level(
            previous, approver=approver, authorized_level=authorized_level,
            authorization_reference=authorization_reference,
            valid_from=valid_from or now, valid_until=valid_until or (now + timedelta(seconds=settings.level_grant_ttl_seconds)),
            now=now, grant_id=new_id("glevel"), transition_id=transition_id,
        )
        self.repo.save_level_grant(new_grant)
        self.repo.save_level_transition(transition, transition_id=transition_id,
                                        mission_id=mission_id, scope_contract_id=scope_contract_id)
        self.audit.record("AUTONOMY_LEVEL_REAUTHORIZED", actor_id=approver,
                          subject_type="AUTONOMY_LEVEL_GRANT", subject_id=new_grant["grant_id"],
                          payload={"authorized_level": authorized_level,
                                   "transition_sha256": transition["integrity"]["canonical_sha256"]})
        return new_grant

    # ---------- Oversight monitoring (HO L4 / A3) ----------
    def monitoring_snapshot(self, *, window_seconds: int = 3600) -> dict:
        """Produce one 24/7 monitoring sample: aggregate recent governance activity,
        compute liveness (heartbeat gap), raise alerts, seal, and record the heartbeat.

        Returns a tamper-evident snapshot (`healthy` False when any alert fires). A
        scheduled loop calling this each interval IS the 24/7 monitoring signal; a
        gap between samples surfaces as a `MONITORING_STALE` critical alert."""
        from .oversight_attestation import build_monitoring_snapshot
        now = datetime.now(timezone.utc)
        since = (now - timedelta(seconds=int(window_seconds))).strftime("%Y-%m-%d %H:%M:%S")
        window = self.repo.monitoring_window(since=since)

        heartbeat = self.repo.read_monitoring_heartbeat()
        last = (heartbeat or {}).get("last_sample_at")
        gap = None
        if last:
            try:
                prior = datetime.strptime(str(last), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                gap = max(0.0, (now - prior).total_seconds())
            except ValueError:
                gap = None
        window["heartbeat_gap_seconds"] = gap

        snapshot = build_monitoring_snapshot(window, sampled_at=now)
        self.repo.touch_monitoring_heartbeat(sampled_at=now.strftime("%Y-%m-%d %H:%M:%S"))
        self.audit.record("MONITORING_SNAPSHOT", actor_id="SYSTEM",
                          subject_type="MONITORING", subject_id="global",
                          payload={"healthy": snapshot["healthy"],
                                   "critical_alert_codes": snapshot["critical_alert_codes"],
                                   "window": window})
        return snapshot

    # ---------- Pre-dispatch PolicyDecision revalidation ----------
    def revalidate_policy_decision(self, request: PolicyDecisionRevalidationRequest) -> dict:
        """Revalidate an already-issued PolicyDecision immediately before dispatch.

        This operation never issues a new authorization.  It validates the exact
        decision/request/hash bound into a subsystem TaskContract against the
        current authoritative Governance state.  Any uncertainty is represented
        as INVALID so consumers can fail closed.
        """

        checked_at = datetime.now(timezone.utc)
        revalidation_id = new_id("greval")
        reasons: list[str] = []

        decision = self.repo.get_policy_decision(request.decision_id)
        if not decision:
            reasons.append("POLICY_DECISION_NOT_FOUND")
            result = {
                "revalidation_id": revalidation_id,
                "status": "INVALID",
                "valid": False,
                "execution_authorized": False,
                "delegation_authorized": False,
                "reason_codes": reasons,
                "decision_id": request.decision_id,
                "request_id": request.request_id,
                "mission_id": request.mission_id,
                "decision": None,
                "decision_status": "NOT_FOUND",
                "decision_hash": str(request.decision_hash or "").lower(),
                "scope_contract_id": request.scope_contract_id,
                "scope_version": request.scope_version,
                "current_scope_version": None,
                "policy_set_id": request.policy_set_id,
                "policy_version": request.policy_version,
                "current_policy_version": None,
                "emergency_stop_active": bool(self.repo.get_emergency_state().get("active")),
                "checked_at": _dt_str(checked_at),
                "authority": "aptsGSS",
                "authority_component": "GOV-PLANE",
            }
            self._record_revalidation(result, task_id=request.task_id)
            return result

        decision_status = str(decision.get("decision_status") or "").upper()
        decision_value = str(decision.get("decision") or "").upper()

        if str(decision.get("decision_id") or "") != request.decision_id:
            reasons.append("DECISION_ID_MISMATCH")
        if str(decision.get("request_id") or "") != request.request_id:
            reasons.append("REQUEST_ID_MISMATCH")
        if str(decision.get("mission_id") or "") != request.mission_id:
            reasons.append("MISSION_ID_MISMATCH")
        if str(decision.get("decision_hash") or "").lower() != str(request.decision_hash or "").lower():
            reasons.append("DECISION_HASH_MISMATCH")
        if decision_value != Decision.ALLOW.value:
            reasons.append("DECISION_NOT_ALLOW")
        if decision_status != "ACTIVE":
            reasons.append(f"DECISION_STATUS_{decision_status or 'UNKNOWN'}")
        if bool(decision.get("requires_human_approval")):
            reasons.append("HUMAN_APPROVAL_STILL_REQUIRED")

        valid_from = _aware_utc(decision.get("valid_from"))
        valid_until = _aware_utc(decision.get("valid_until"))
        if valid_from is None or checked_at < valid_from:
            reasons.append("DECISION_NOT_YET_VALID")
        if valid_until is None or checked_at >= valid_until:
            reasons.append("DECISION_EXPIRED")
            if decision_status == "ACTIVE":
                self.repo.expire_policy_decision(request.decision_id)
                decision_status = "EXPIRED"

        decision_scope_id = decision.get("scope_contract_id")
        decision_scope_version = decision.get("scope_version")
        if str(decision_scope_id or "") != str(request.scope_contract_id or ""):
            reasons.append("SCOPE_CONTRACT_ID_MISMATCH")
        if request.scope_version is not None and int(decision_scope_version or -1) != int(request.scope_version):
            reasons.append("BOUND_SCOPE_VERSION_MISMATCH")

        decision_policy_set_id = decision.get("policy_set_id")
        decision_policy_version = decision.get("policy_version")
        if str(decision_policy_set_id or "") != str(request.policy_set_id or ""):
            reasons.append("POLICY_SET_ID_MISMATCH")
        if request.policy_version is not None and int(decision_policy_version or -1) != int(request.policy_version):
            reasons.append("BOUND_POLICY_VERSION_MISMATCH")

        auth_request = self.repo.get_authorization_request(request.request_id)
        if not auth_request:
            reasons.append("AUTHORIZATION_REQUEST_NOT_FOUND")
        else:
            expected_request_fields = {
                "mission_id": request.mission_id,
                "scope_contract_id": request.scope_contract_id,
                "subject_component": request.subject_component,
                "action_class": request.action_class.value,
                "action_name": request.action_name,
                "resource_type": request.resource_type,
                "resource_value": request.resource_value,
            }
            for field_name, expected_value in expected_request_fields.items():
                if expected_value is None:
                    continue
                if str(auth_request.get(field_name) or "") != str(expected_value):
                    reasons.append(f"AUTH_REQUEST_{field_name.upper()}_MISMATCH")
            if str(auth_request.get("request_status") or "").upper() != Decision.ALLOW.value:
                reasons.append("AUTHORIZATION_REQUEST_NOT_ALLOWED")
            if request.action_class == ActionClass.TASK_DELEGATION:
                delegation_context = auth_request.get("context") or {}
                if (request.subject_component != "APTS-MO01"
                        or request.action_name != "delegate_planned_task"
                        or request.resource_type != "SUBSYSTEM_CAPABILITY"
                        or delegation_context.get("authorization_purpose") != "PRE_DELEGATION_ONLY"
                        or delegation_context.get("target_action_authority_requested") is not False):
                    reasons.append("DELEGATION_REQUEST_CONTRACT_INVALID")

        scope = self.repo.get_scope_contract(str(decision_scope_id)) if decision_scope_id else None
        current_scope_version = scope.get("version") if scope else None
        if not scope:
            reasons.append("CURRENT_SCOPE_NOT_FOUND")
        else:
            if str(scope.get("mission_id") or "") != request.mission_id:
                reasons.append("CURRENT_SCOPE_MISSION_MISMATCH")
            if not self._scope_active(scope):
                reasons.append("CURRENT_SCOPE_NOT_ACTIVE")
            if int(scope.get("version") or -1) != int(decision_scope_version or -1):
                reasons.append("CURRENT_SCOPE_VERSION_CHANGED")

            constraint = self.repo.find_action_constraint(
                str(scope.get("scope_contract_id")),
                request.action_class.value,
                request.action_name,
            )
            if constraint is None:
                reasons.append("CURRENT_ACTION_CONSTRAINT_MISSING")
            else:
                effect = str(constraint.get("effect") or "DENY").upper()
                if effect != Decision.ALLOW.value:
                    reasons.append("CURRENT_ACTION_CONSTRAINT_NOT_ALLOW")
                if bool(constraint.get("requires_approval")):
                    reasons.append("CURRENT_ACTION_REQUIRES_APPROVAL")

            if request.action_class == ActionClass.CTI_SOURCE_READ:
                source_match = self.scope_matcher.source_allowed(
                    request.resource_value,
                    scope.get("sources") or [],
                )
                if not source_match.matched:
                    reasons.append("CURRENT_SOURCE_NOT_ALLOWLISTED")
            elif request.action_class == ActionClass.TASK_DELEGATION:
                capability_match = self.scope_matcher.subsystem_capability_allowed(
                    request.resource_value, constraint
                )
                if not capability_match.matched:
                    reasons.append("CURRENT_SUBSYSTEM_CAPABILITY_NOT_ALLOWLISTED")
                # Revalidation must not resurrect a previously allowed decision
                # when the stored delegation rule is malformed or corrupted.
                from .delegation_preflight import allow_rule_problems
                reasons.extend("CURRENT_" + code for code in allow_rule_problems(constraint, request.resource_value))
            elif request.action_class not in {ActionClass.INTERNAL_REASONING, ActionClass.REPORTING}:
                target_match = self.scope_matcher.target_in_scope(
                    request.resource_value,
                    scope.get("targets") or [],
                )
                if not target_match.matched:
                    reasons.append("CURRENT_RESOURCE_OUT_OF_SCOPE")

        policy = self.repo.get_policy_set(str(decision_policy_set_id)) if decision_policy_set_id else None
        current_policy_version = policy.get("version") if policy else None
        if not policy:
            reasons.append("CURRENT_POLICY_NOT_FOUND")
        else:
            if str(policy.get("status") or "").upper() != "ACTIVE":
                reasons.append("CURRENT_POLICY_NOT_ACTIVE")
            if int(policy.get("version") or -1) != int(decision_policy_version or -1):
                reasons.append("CURRENT_POLICY_VERSION_CHANGED")
            effective_from = _aware_utc(policy.get("effective_from"))
            effective_until = _aware_utc(policy.get("effective_until"))
            if effective_from is not None and checked_at < effective_from:
                reasons.append("CURRENT_POLICY_NOT_YET_EFFECTIVE")
            if effective_until is not None and checked_at > effective_until:
                reasons.append("CURRENT_POLICY_EXPIRED")

        emergency = self.repo.get_emergency_state()
        emergency_active = bool(emergency.get("active"))
        if emergency_active and request.action_class not in {ActionClass.INTERNAL_REASONING, ActionClass.REPORTING}:
            reasons.append("EMERGENCY_STOP_ACTIVE")

        # Preserve deterministic order but remove duplicates.
        unique_reasons = list(dict.fromkeys(reasons))
        valid = not unique_reasons
        is_delegation = request.action_class == ActionClass.TASK_DELEGATION
        result = {
            "revalidation_id": revalidation_id,
            "status": "VALID" if valid else "INVALID",
            "valid": valid,
            "execution_authorized": bool(valid and not is_delegation),
            "delegation_authorized": bool(valid and is_delegation and decision_value == Decision.ALLOW.value),
            "reason_codes": unique_reasons or ["POLICY_DECISION_STILL_VALID"],
            "decision_id": request.decision_id,
            "request_id": request.request_id,
            "mission_id": request.mission_id,
            "decision": decision_value,
            "decision_status": decision_status,
            "decision_hash": str(decision.get("decision_hash") or "").lower(),
            "scope_contract_id": decision_scope_id,
            "scope_version": decision_scope_version,
            "current_scope_version": current_scope_version,
            "policy_set_id": decision_policy_set_id,
            "policy_version": decision_policy_version,
            "current_policy_version": current_policy_version,
            "emergency_stop_active": emergency_active,
            "checked_at": _dt_str(checked_at),
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
        }
        self._record_revalidation(result, task_id=request.task_id)
        return result

    def _record_revalidation(self, result: dict, *, task_id: Optional[str]) -> None:
        valid = bool(result.get("valid"))
        event_type = "POLICY_DECISION_REVALIDATED" if valid else "POLICY_DECISION_REVALIDATION_FAILED"
        payload = dict(result)
        if task_id:
            payload["task_id"] = task_id
        governance_event_id = self.events.publish(
            event_type,
            mission_id=result.get("mission_id"),
            payload=payload,
            severity="INFO" if valid else "CRITICAL",
        )
        if isinstance(governance_event_id, str) and governance_event_id:
            payload["governance_event_id"] = governance_event_id
            # The result object is the synchronous response body consumed by
            # VulnDesk. Mutating it here keeps the exact outbox identity aligned
            # with the durable asynchronous event.
            result["governance_event_id"] = governance_event_id
        self.audit.record(
            event_type,
            actor_id="GOV-S04",
            mission_id=result.get("mission_id"),
            subject_type="POLICY_DECISION",
            subject_id=result.get("decision_id"),
            payload=payload,
        )

    # ---------- Stage 2.9.4 cross-subsystem Governance correlation ----------
    def mission_correlation_snapshot(self, mission_id: str) -> dict:
        """Return authoritative mission-scoped Governance provenance for read-side correlation.

        This is deliberately not an authorization operation.  It exposes the durable
        Governance records already created by authorization, revalidation, and
        revocation so VulnDesk can correlate its canonical lineage without direct
        cross-database access or cross-database foreign keys.
        """
        mission_id = str(mission_id or "").strip()
        if not mission_id:
            raise GovernanceError("mission_id is required")

        scopes = self.repo.mission_scope_contracts(mission_id)
        requests = self.repo.mission_authorization_requests(mission_id)
        decisions = self.repo.mission_policy_decisions(mission_id)
        events = self.repo.mission_outbox_events(mission_id)
        audits = self.repo.mission_audit_records(mission_id)

        return {
            "schema_version": "governance-correlation-snapshot-v1",
            "mission_id": mission_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "scope_contracts": scopes,
            "authorization_requests": requests,
            "policy_decisions": decisions,
            "events": events,
            "audit_records": audits,
            "counts": {
                "scope_contracts": len(scopes),
                "authorization_requests": len(requests),
                "policy_decisions": len(decisions),
                "events": len(events),
                "audit_records": len(audits),
            },
        }

    # ---------- Revocation ----------
    def revoke_decision(self, decision_id: str, request: RevokeDecisionInput) -> dict:
        current = self.repo.get_policy_decision(decision_id)
        if not current:
            raise GovernanceError("Policy decision not found")
        if not self.repo.revoke_policy_decision(decision_id):
            raise GovernanceError("Policy decision is not active")

        # Stage 2.7: revocation is an exact PolicyDecision lifecycle event, not a
        # mission-wide boolean. Publish enough immutable binding material for the
        # consumer to correlate the event to only the TaskContracts that were
        # authorized by this decision. VulnDesk still verifies current state by
        # calling the authoritative decision endpoint before trusting the event.
        revoked_at = datetime.now(timezone.utc)
        payload = {
            "revocation_id": new_id("grevoke"),
            "decision_id": decision_id,
            "request_id": current.get("request_id"),
            "mission_id": current.get("mission_id"),
            "decision_hash": current.get("decision_hash"),
            "decision_status": "REVOKED",
            "scope_contract_id": current.get("scope_contract_id"),
            "scope_version": current.get("scope_version"),
            "policy_set_id": current.get("policy_set_id"),
            "policy_version": current.get("policy_version"),
            "reason": request.reason,
            "revoked_by": request.actor_id,
            "revoked_at": _dt_str(revoked_at),
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "revocation_scope": "POLICY_DECISION",
        }
        governance_event_id = self.events.publish(
            "AUTHORIZATION_REVOKED",
            mission_id=current.get("mission_id"),
            payload=payload,
            severity="CRITICAL",
        )
        if isinstance(governance_event_id, str) and governance_event_id:
            payload["governance_event_id"] = governance_event_id
        self.audit.record(
            "AUTHORIZATION_REVOKED",
            actor_id=request.actor_id,
            mission_id=current.get("mission_id"),
            subject_type="POLICY_DECISION",
            subject_id=decision_id,
            payload=payload,
        )
        return payload
