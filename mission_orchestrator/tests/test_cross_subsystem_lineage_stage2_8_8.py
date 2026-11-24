from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.governance_service import GovernanceService
from app.models import ActionClass, AuthorizationRequest


class Repo:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.scope = {
            "scope_contract_id": "scope-288",
            "mission_id": "mission-288",
            "status": "ACTIVE",
            "policy_set_id": "default-policy",
            "version": 1,
            "valid_from": now - timedelta(minutes=5),
            "valid_until": now + timedelta(hours=1),
            "targets": [],
            "sources": [{"source_id": "nvd-cve", "allowed": 1}],
        }
        self.policy = {
            "policy_set_id": "default-policy",
            "version": 1,
            "status": "ACTIVE",
            "effective_from": now - timedelta(days=1),
            "effective_until": now + timedelta(days=1),
        }
        self.auth_rows = []
        self.risk_rows = []
        self.decision_rows = []
        self.auth_status = {}

    def get_scope_contract(self, scope_id):
        return dict(self.scope) if scope_id == self.scope["scope_contract_id"] else None

    def find_active_scope_for_mission(self, mission_id):
        return dict(self.scope) if mission_id == self.scope["mission_id"] else None

    def insert_authorization_request(self, row):
        self.auth_rows.append(dict(row))

    def insert_risk_assessment(self, row):
        self.risk_rows.append(dict(row))

    def get_emergency_state(self):
        return {"active": 0, "version": 1}

    def find_action_constraint(self, scope_id, action_class, action_name):
        return {
            "action_class": "CTI_SOURCE_READ",
            "action_name": "*",
            "effect": "ALLOW",
            "max_risk_level": "LOW",
            "requires_approval": 0,
            "constraints": {"read_only": True},
        }

    def get_policy_set(self, policy_set_id):
        return dict(self.policy)

    def insert_policy_decision(self, row):
        self.decision_rows.append(dict(row))

    def update_authorization_status(self, request_id, status):
        self.auth_status[request_id] = status


class NoObligations:
    def obligations(self, *args, **kwargs):
        return []


class CaptureAudit:
    def __init__(self):
        self.records = []

    def record(self, event_type, **kwargs):
        self.records.append((event_type, dict(kwargs)))
        return f"gaudit-{len(self.records)}"


class CaptureEvents:
    def __init__(self):
        self.events = []
        self.seq = 0

    def publish(self, event_type, **kwargs):
        self.seq += 1
        event_id = f"gevent-288-{self.seq}"
        self.events.append((event_id, event_type, dict(kwargs)))
        return event_id


def _service():
    service = GovernanceService(repo=Repo())
    service.compliance = NoObligations()
    service.audit = CaptureAudit()
    service.events = CaptureEvents()
    return service


def test_policy_decision_response_and_audit_share_authoritative_outbox_event_id():
    service = _service()
    request = AuthorizationRequest(
        mission_id="mission-288",
        scope_contract_id="scope-288",
        subject_component="CTI-A02",
        action_class=ActionClass.CTI_SOURCE_READ,
        action_name="INCREMENTAL_FETCH",
        resource_type="CTI_SOURCE",
        resource_value="nvd-cve",
        context={"environment": "LAB", "read_only": True},
        evidence_refs=[],
        requested_by="CTI-A02",
    )
    decision = service.evaluate_authorization(request)
    assert decision["decision"] == "ALLOW"
    assert decision["governance_event_id"] == "gevent-288-1"
    assert service.events.events[-1][1] == "POLICY_DECISION_ISSUED"
    audit_payload = service.audit.records[-1][1]["payload"]
    assert audit_payload["governance_event_id"] == "gevent-288-1"
    # Event identity is transport provenance and must not be stored inside the
    # authoritative PolicyDecision hash row.
    assert "governance_event_id" not in service.repo.decision_rows[-1]


def test_revalidation_result_and_audit_share_authoritative_outbox_event_id():
    service = _service()
    result = {
        "revalidation_id": "greval-288",
        "status": "VALID",
        "valid": True,
        "execution_authorized": True,
        "decision_id": "gdec-288",
        "request_id": "greq-288",
        "mission_id": "mission-288",
        "decision_hash": "a" * 64,
        "decision_status": "ACTIVE",
    }
    service._record_revalidation(result, task_id="task-288")
    assert result["governance_event_id"] == "gevent-288-1"
    assert service.events.events[-1][1] == "POLICY_DECISION_REVALIDATED"
    audit_payload = service.audit.records[-1][1]["payload"]
    assert audit_payload["governance_event_id"] == "gevent-288-1"
    assert audit_payload["task_id"] == "task-288"
