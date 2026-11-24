from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
import types

if "pymysql" not in sys.modules:
    pymysql = types.ModuleType("pymysql")
    cursors = types.ModuleType("pymysql.cursors")
    class _DictCursor:
        pass
    cursors.DictCursor = _DictCursor
    pymysql.cursors = cursors
    pymysql.connect = lambda *args, **kwargs: None
    sys.modules["pymysql"] = pymysql
    sys.modules["pymysql.cursors"] = cursors

from app.governance_service import GovernanceService
from app.models import RevokeDecisionInput


class FakeRepo:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.decision = {
            "decision_id": "gdec-27",
            "request_id": "greq-27",
            "mission_id": "mission-27",
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "scope_contract_id": "scope-27",
            "scope_version": 1,
            "decision": "ALLOW",
            "reason_codes": [],
            "constraints": {},
            "requires_human_approval": 0,
            "approval_request_id": None,
            "valid_from": now - timedelta(minutes=1),
            "valid_until": now + timedelta(minutes=5),
            "decision_hash": "a" * 64,
            "decision_status": "ACTIVE",
        }

    def get_policy_decision(self, decision_id):
        return dict(self.decision) if decision_id == self.decision["decision_id"] else None

    def revoke_policy_decision(self, decision_id):
        if decision_id != self.decision["decision_id"] or self.decision["decision_status"] != "ACTIVE":
            return False
        self.decision["decision_status"] = "REVOKED"
        return True


class CaptureAudit:
    def __init__(self):
        self.records = []

    def record(self, *args, **kwargs):
        self.records.append((args, kwargs))
        return "gaudit-27"


class CaptureEvents:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))
        return "gevent-27"


def test_revoke_event_carries_exact_policydecision_binding_material():
    service = GovernanceService(repo=FakeRepo())
    service.audit = CaptureAudit()
    service.events = CaptureEvents()

    result = service.revoke_decision(
        "gdec-27",
        RevokeDecisionInput(actor_id="operator-27", reason="manual safety revoke"),
    )

    assert result["revocation_id"].startswith("grevoke-")
    assert result["decision_id"] == "gdec-27"
    assert result["request_id"] == "greq-27"
    assert result["mission_id"] == "mission-27"
    assert result["decision_hash"] == "a" * 64
    assert result["decision_status"] == "REVOKED"
    assert result["scope_contract_id"] == "scope-27"
    assert result["scope_version"] == 1
    assert result["policy_set_id"] == "default-policy"
    assert result["policy_version"] == 1
    assert result["authority"] == "aptsGSS"
    assert result["authority_component"] == "GOV-PLANE"
    assert result["revocation_scope"] == "POLICY_DECISION"
    assert result["revoked_by"] == "operator-27"
    assert result["revoked_at"]

    event_type, event_kwargs = service.events.events[-1]
    assert event_type == "AUTHORIZATION_REVOKED"
    assert event_kwargs["mission_id"] == "mission-27"
    assert event_kwargs["payload"]["decision_id"] == "gdec-27"


def test_outbox_publisher_embeds_governance_event_id_for_consumer_idempotency():
    from app.event_publisher import GovernanceEventPublisher
    import json

    class Repo:
        def __init__(self):
            self.row = None

        def insert_outbox(self, row):
            self.row = dict(row)

    repo = Repo()
    publisher = GovernanceEventPublisher(repo)
    event_id = publisher.publish(
        "AUTHORIZATION_REVOKED",
        mission_id="mission-27",
        payload={"decision_id": "gdec-27"},
        severity="CRITICAL",
    )
    payload = json.loads(repo.row["payload_json"])
    assert payload["governance_event_id"] == event_id
    assert payload["decision_id"] == "gdec-27"
