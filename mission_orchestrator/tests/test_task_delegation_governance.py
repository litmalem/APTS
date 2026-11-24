from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from app.governance_service import GovernanceService
from app.models import ActionClass, AuthorizationRequest, PolicyDecisionRevalidationRequest, RiskLevel
from app.policy_engine import DeterministicActionGate
from app.scope_service import ScopeMatcher


ALLOWED = ["PENTEST:pentest.recon"]


class FakeRepo:
    def __init__(self, *, emergency=False):
        now = datetime.now(timezone.utc)
        self.scope = {
            "scope_contract_id": "scope-delegation",
            "mission_id": "mission-delegation",
            "status": "ACTIVE",
            "policy_set_id": "default-policy",
            "version": 1,
            "valid_from": now - timedelta(minutes=1),
            "valid_until": now + timedelta(hours=1),
            # Deliberately resembles a capability string. Delegation checks must
            # never accept this through target URL matching.
            "targets": [{"target_type": "URL", "target_value": "PENTEST:pentest.recon", "allowed": 1}],
            "sources": [],
        }
        self.constraint = {
            "action_class": "TASK_DELEGATION",
            "action_name": "delegate_planned_task",
            "effect": "ALLOW",
            "max_risk_level": "LOW",
            "requires_approval": 0,
            "constraints": {
                "allowed_capabilities": ALLOWED,
                "execution_authorized": False,
                "target_actuation": False,
            },
        }
        self.policy = {"policy_set_id": "default-policy", "version": 1, "status": "ACTIVE"}
        self.emergency = {"active": int(emergency), "version": 1}
        self.authorization_requests = {}
        self.decisions = {}

    def get_scope_contract(self, scope_id):
        return dict(self.scope) if scope_id == self.scope["scope_contract_id"] else None

    def find_active_scope_for_mission(self, mission_id):
        return dict(self.scope) if mission_id == self.scope["mission_id"] else None

    def insert_authorization_request(self, row):
        self.authorization_requests[row["request_id"]] = {
            **row,
            "context": json.loads(row.get("context_json") or "{}"),
            "request_status": "EVALUATING",
        }

    def update_authorization_status(self, request_id, status):
        self.authorization_requests[request_id]["request_status"] = status

    def find_action_constraint(self, scope_id, action_class, action_name):
        if (scope_id, action_class, action_name) == ("scope-delegation", "TASK_DELEGATION", "delegate_planned_task"):
            return dict(self.constraint)
        return None

    def insert_risk_assessment(self, row):
        return None

    def get_emergency_state(self):
        return dict(self.emergency)

    def get_policy_set(self, policy_id):
        return dict(self.policy) if policy_id == "default-policy" else None

    def insert_policy_decision(self, row):
        self.decisions[row["decision_id"]] = {**row, "decision_status": "ACTIVE"}

    def get_policy_decision(self, decision_id):
        return dict(self.decisions[decision_id]) if decision_id in self.decisions else None

    def get_authorization_request(self, request_id):
        row = self.authorization_requests.get(request_id)
        return None if row is None else dict(row)

    def expire_policy_decision(self, decision_id):
        return None


class NoopAudit:
    def record(self, *args, **kwargs):
        return None


class NoopEvents:
    def publish(self, *args, **kwargs):
        return "gevent-test"


class NoopCompliance:
    def obligations(self, *args, **kwargs):
        return {}


def service(repo):
    result = GovernanceService(repo=repo)
    result.audit = NoopAudit()
    result.events = NoopEvents()
    result.compliance = NoopCompliance()
    return result


def request(resource="PENTEST:pentest.recon", resource_type="SUBSYSTEM_CAPABILITY"):
    return AuthorizationRequest(
        mission_id="mission-delegation",
        scope_contract_id="scope-delegation",
        subject_component="APTS-MO01",
        action_class=ActionClass.TASK_DELEGATION,
        action_name="delegate_planned_task",
        resource_type=resource_type,
        resource_value=resource,
        context={
            "authorization_purpose": "PRE_DELEGATION_ONLY",
            "target_action_authority_requested": False,
        },
        requested_by="operator-test",
    )


def test_delegation_authorization_uses_exact_capability_policy_not_target_matching():
    repo = FakeRepo()
    result = service(repo).evaluate_authorization(request())
    assert result["decision"] == "ALLOW"
    assert result["risk_level"] == RiskLevel.LOW
    assert result["constraints"]["allowed_capabilities"] == ALLOWED
    assert result["constraints"]["delegation_scope"]["resource_value"] == ALLOWED[0]
    assert result["constraints"]["delegation_scope"]["execution_authorized"] is False
    assert result["constraints"]["delegation_scope"]["target_actuation"] is False


def test_unknown_capability_and_wrong_resource_type_are_denied_even_if_target_string_matches():
    repo = FakeRepo()
    gov = service(repo)
    other = gov.evaluate_authorization(request("PENTEST:pentest.validate"))
    wrong_type = gov.evaluate_authorization(request(resource_type="URL"))
    assert other["decision"] == "DENY"
    assert "SUBSYSTEM_CAPABILITY_NOT_ALLOWLISTED" in other["reason_codes"]
    assert wrong_type["decision"] == "DENY"
    assert "DELEGATION_REQUEST_CONTRACT_INVALID" in wrong_type["reason_codes"]


def test_emergency_stop_blocks_delegation_and_exploitation_deny_precedence_is_unchanged():
    repo = FakeRepo(emergency=True)
    result = service(repo).evaluate_authorization(request())
    assert result["decision"] == "DENY"
    assert "EMERGENCY_STOP_ACTIVE" in result["reason_codes"]
    gate = DeterministicActionGate().evaluate(
        action_class=ActionClass.DESTRUCTIVE_ACTION,
        risk_level=RiskLevel.LOW,
        emergency_stop_active=False,
        scope_active=True,
        resource_in_scope=True,
        source_allowed=False,
        action_constraint={"effect": "ALLOW", "max_risk_level": "CRITICAL"},
    )
    assert gate.decision.value == "DENY"


def test_revalidation_reports_delegation_permission_without_execution_authority():
    repo = FakeRepo()
    gov = service(repo)
    issued = gov.evaluate_authorization(request())
    result = gov.revalidate_policy_decision(PolicyDecisionRevalidationRequest(
        decision_id=issued["decision_id"],
        request_id=issued["request_id"],
        mission_id="mission-delegation",
        scope_contract_id="scope-delegation",
        scope_version=1,
        policy_set_id="default-policy",
        policy_version=1,
        decision_hash=issued["decision_hash"],
        subject_component="APTS-MO01",
        action_class=ActionClass.TASK_DELEGATION,
        action_name="delegate_planned_task",
        resource_type="SUBSYSTEM_CAPABILITY",
        resource_value="PENTEST:pentest.recon",
        requested_by="operator-test",
    ))
    assert result["valid"] is True
    assert result["delegation_authorized"] is True
    assert result["execution_authorized"] is False


def test_subsystem_capability_matcher_requires_exact_constraint_allowlist():
    matcher = ScopeMatcher()
    constraint = {"constraints": {"allowed_capabilities": ALLOWED}}
    assert matcher.subsystem_capability_allowed(ALLOWED[0], constraint).matched
    assert not matcher.subsystem_capability_allowed("PENTEST:pentest.validate", constraint).matched
    assert not matcher.subsystem_capability_allowed("https://PENTEST:pentest.recon", constraint).matched
