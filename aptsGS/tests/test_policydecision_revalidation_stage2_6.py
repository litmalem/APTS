from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.governance_service import GovernanceService
from app.models import PolicyDecisionRevalidationRequest


class FakeRepo:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.expired = []
        self.decision = {
            "decision_id": "gdec-26",
            "request_id": "greq-26",
            "mission_id": "mission-26",
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "scope_contract_id": "scope-26",
            "scope_version": 1,
            "decision": "ALLOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "SOURCE_ALLOWLIST_MATCH"],
            "constraints": {"read_only": True, "max_pages": 1},
            "requires_human_approval": 0,
            "approval_request_id": None,
            "valid_from": now - timedelta(minutes=1),
            "valid_until": now + timedelta(minutes=5),
            "decision_hash": "a" * 64,
            "decision_status": "ACTIVE",
        }
        self.auth_request = {
            "request_id": "greq-26",
            "mission_id": "mission-26",
            "scope_contract_id": "scope-26",
            "subject_component": "CTI-A02",
            "action_class": "CTI_SOURCE_READ",
            "action_name": "INCREMENTAL_FETCH",
            "resource_type": "CTI_SOURCE",
            "resource_value": "nvd-cve",
            "requested_by": "CTI-A02",
            "request_status": "ALLOW",
            "context": {},
            "evidence_refs": [],
        }
        self.scope = {
            "scope_contract_id": "scope-26",
            "mission_id": "mission-26",
            "status": "ACTIVE",
            "policy_set_id": "default-policy",
            "version": 1,
            "valid_from": now - timedelta(minutes=10),
            "valid_until": now + timedelta(hours=1),
            "sources": [
                {"scope_source_id": "ssrc-1", "source_id": "nvd-cve", "allowed": 1}
            ],
            "targets": [],
        }
        self.constraint = {
            "action_class": "CTI_SOURCE_READ",
            "action_name": "*",
            "effect": "ALLOW",
            "max_risk_level": "LOW",
            "requires_approval": 0,
            "constraints": {"read_only": True, "max_pages": 1},
        }
        self.policy = {
            "policy_set_id": "default-policy",
            "version": 1,
            "status": "ACTIVE",
            "effective_from": now - timedelta(days=1),
            "effective_until": now + timedelta(days=1),
        }
        self.emergency = {"active": 0, "version": 1}

    def get_policy_decision(self, decision_id):
        return dict(self.decision) if decision_id == self.decision["decision_id"] else None

    def expire_policy_decision(self, decision_id):
        self.expired.append(decision_id)
        self.decision["decision_status"] = "EXPIRED"
        return True

    def get_authorization_request(self, request_id):
        return dict(self.auth_request) if request_id == self.auth_request["request_id"] else None

    def get_scope_contract(self, scope_contract_id):
        return dict(self.scope) if scope_contract_id == self.scope["scope_contract_id"] else None

    def find_action_constraint(self, scope_contract_id, action_class, action_name):
        if scope_contract_id != self.scope["scope_contract_id"]:
            return None
        return dict(self.constraint)

    def get_policy_set(self, policy_set_id):
        return dict(self.policy) if policy_set_id == self.policy["policy_set_id"] else None

    def get_emergency_state(self):
        return dict(self.emergency)


class CaptureAudit:
    def __init__(self):
        self.records = []

    def record(self, *args, **kwargs):
        self.records.append((args, kwargs))
        return "audit-1"


class CaptureEvents:
    def __init__(self):
        self.events = []

    def publish(self, *args, **kwargs):
        self.events.append((args, kwargs))
        return {"event_type": args[0] if args else None}


def request(**overrides):
    data = {
        "task_id": "task-26",
        "decision_id": "gdec-26",
        "request_id": "greq-26",
        "mission_id": "mission-26",
        "scope_contract_id": "scope-26",
        "scope_version": 1,
        "policy_set_id": "default-policy",
        "policy_version": 1,
        "decision_hash": "a" * 64,
        "subject_component": "CTI-A02",
        "action_class": "CTI_SOURCE_READ",
        "action_name": "INCREMENTAL_FETCH",
        "resource_type": "CTI_SOURCE",
        "resource_value": "nvd-cve",
        "requested_by": "CTI-A01",
    }
    data.update(overrides)
    return PolicyDecisionRevalidationRequest(**data)


def service_with(repo: FakeRepo):
    service = GovernanceService(repo=repo)
    service.audit = CaptureAudit()
    service.events = CaptureEvents()
    return service


def test_revalidation_validates_exact_bound_decision_against_current_state():
    repo = FakeRepo()
    service = service_with(repo)
    result = service.revalidate_policy_decision(request())
    assert result["status"] == "VALID"
    assert result["valid"] is True
    assert result["execution_authorized"] is True
    assert result["decision_status"] == "ACTIVE"
    assert result["current_scope_version"] == 1
    assert result["current_policy_version"] == 1
    assert result["reason_codes"] == ["POLICY_DECISION_STILL_VALID"]
    assert service.audit.records
    assert service.events.events


def test_revalidation_rejects_revoked_decision():
    repo = FakeRepo()
    repo.decision["decision_status"] = "REVOKED"
    result = service_with(repo).revalidate_policy_decision(request())
    assert result["status"] == "INVALID"
    assert result["valid"] is False
    assert "DECISION_STATUS_REVOKED" in result["reason_codes"]


def test_revalidation_rejects_scope_version_drift():
    repo = FakeRepo()
    repo.scope["version"] = 2
    result = service_with(repo).revalidate_policy_decision(request())
    assert result["valid"] is False
    assert "CURRENT_SCOPE_VERSION_CHANGED" in result["reason_codes"]


def test_revalidation_rejects_emergency_stop():
    repo = FakeRepo()
    repo.emergency["active"] = 1
    result = service_with(repo).revalidate_policy_decision(request())
    assert result["valid"] is False
    assert "EMERGENCY_STOP_ACTIVE" in result["reason_codes"]


def test_revalidation_marks_expired_decision():
    repo = FakeRepo()
    repo.decision["valid_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    result = service_with(repo).revalidate_policy_decision(request())
    assert result["valid"] is False
    assert "DECISION_EXPIRED" in result["reason_codes"]
    assert result["decision_status"] == "EXPIRED"
    assert repo.expired == ["gdec-26"]
