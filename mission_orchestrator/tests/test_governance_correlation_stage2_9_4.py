from __future__ import annotations

from app.governance_service import GovernanceService


class CorrelationRepo:
    def mission_scope_contracts(self, mission_id):
        return [{"scope_contract_id": "scope-294", "mission_id": mission_id, "version": 3}]

    def mission_authorization_requests(self, mission_id):
        return [{"request_id": "greq-294", "mission_id": mission_id}]

    def mission_policy_decisions(self, mission_id):
        return [{"decision_id": "gdec-294", "request_id": "greq-294", "mission_id": mission_id}]

    def mission_outbox_events(self, mission_id):
        return [{"event_id": "gevent-294", "mission_id": mission_id, "event_type": "POLICY_DECISION_ISSUED", "payload": {}}]

    def mission_audit_records(self, mission_id):
        return [{"audit_id": "gaudit-294", "mission_id": mission_id, "payload": {}}]


def test_governance_service_exposes_authoritative_mission_correlation_snapshot_without_new_authorization():
    service = GovernanceService(repo=CorrelationRepo())
    snapshot = service.mission_correlation_snapshot("mission-294")

    assert snapshot["schema_version"] == "governance-correlation-snapshot-v1"
    assert snapshot["mission_id"] == "mission-294"
    assert snapshot["authority"] == "aptsGSS"
    assert snapshot["authority_component"] == "GOV-PLANE"
    assert snapshot["counts"] == {
        "scope_contracts": 1,
        "authorization_requests": 1,
        "policy_decisions": 1,
        "events": 1,
        "audit_records": 1,
    }
    assert snapshot["events"][0]["event_id"] == "gevent-294"


def test_repository_correlation_read_model_decodes_authoritative_json_payloads():
    from app.repositories import GovernanceRepository

    class Db:
        def fetch_all(self, sql, params=None):
            if "gov_scope_contracts" in sql:
                return [{"id": 1, "scope_contract_id": "scope-294", "mission_id": "mission-294", "metadata_json": '{"lab":true}'}]
            if "gov_authorization_requests" in sql:
                return [{"id": 2, "request_id": "greq-294", "mission_id": "mission-294", "context_json": '{"environment":"LAB"}', "evidence_refs_json": '["e1"]'}]
            if "gov_policy_decisions" in sql:
                return [{"id": 3, "decision_id": "gdec-294", "mission_id": "mission-294", "reason_codes_json": '["OK"]', "constraints_json": '{"read_only":true}'}]
            if "gov_event_outbox" in sql:
                return [{"id": 4, "event_id": "gevent-294", "mission_id": "mission-294", "payload_json": '{"decision_id":"gdec-294"}'}]
            if "gov_audit_log" in sql:
                return [{"id": 5, "audit_id": "gaudit-294", "mission_id": "mission-294", "payload_json": '{"governance_event_id":"gevent-294"}'}]
            raise AssertionError(sql)

    repo = GovernanceRepository(db=Db())
    assert repo.mission_scope_contracts("mission-294")[0]["metadata"] == {"lab": True}
    assert repo.mission_authorization_requests("mission-294")[0]["evidence_refs"] == ["e1"]
    assert repo.mission_policy_decisions("mission-294")[0]["constraints"] == {"read_only": True}
    assert repo.mission_outbox_events("mission-294")[0]["payload"]["decision_id"] == "gdec-294"
    assert repo.mission_audit_records("mission-294")[0]["payload"]["governance_event_id"] == "gevent-294"
