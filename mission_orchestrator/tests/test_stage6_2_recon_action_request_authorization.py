from __future__ import annotations

import sqlite3

import pytest

from execution_subsystem.authorization_contract import AUTHORIZATION_INTAKE_SCHEMA
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.authorization_service import ExecutionAuthorizationService
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.execution_contract import ExecutionRequestIntegrityError, ExecutionSourceRejected
from execution_subsystem.request_repository import ExecutionRequestRepository
from execution_subsystem.request_service import ExecutionRequestService
from execution_subsystem.proposal_source import PentestProposalSource
from tests.test_stage6_2_authoritative_execution_authorization import FakeAuthority, NOW, seed_mission
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline


@pytest.fixture
def recon_authorization(tmp_path):
    pentest_repo, boundary, _, _, runs = _pipeline(tmp_path, "stage62-recon", through_stage="5.2")
    pentest_db = pentest_repo.sqlite_path
    mission_db = tmp_path / "mission.db"
    seed_mission(mission_db, boundary)

    action = runs["5.2"]["output"]["action_requests"][0]
    intake = {
        "schema_version": "apts-execution-request-intake-v2",
        "source_type": "STAGE5_2_RECON_ACTION_REQUEST",
        "request_id": "ereq-stage62-recon",
        "idempotency_key": "idem-stage62-recon",
        "recon_action_id": action["action_id"],
        "recon_request_sha256": action["integrity"]["canonical_sha256"],
    }
    request_service = ExecutionRequestService(
        ExecutionRequestRepository(tmp_path / "execution.db"), PentestProposalSource(pentest_db))
    request = request_service.create_request(intake)
    auth_intake = {
        "schema_version": AUTHORIZATION_INTAKE_SCHEMA,
        "revalidation_id": "eauthreq-stage62-recon",
        "idempotency_key": "idem-auth-stage62-recon",
        "execution_id": request["execution_id"],
        "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"],
        "requested_by": "stage62-recon-test",
    }
    authority = FakeAuthority()
    service = ExecutionAuthorizationService(
        ExecutionAuthorizationRepository(tmp_path / "execution.db"),
        ExecutionAuthorizationProposalSource(pentest_db), MissionAuthorizationSource(mission_db),
        authority, clock=lambda: NOW)
    return service, auth_intake, authority, request, pentest_db


def test_recon_action_request_gets_fresh_action_bound_gss_decision(recon_authorization):
    service, intake, authority, request, _ = recon_authorization
    result = service.authorize_execution(intake)
    record = result["record"]
    evaluated = authority.calls[0]
    assert result["created"] is True
    assert result["governance_query_performed"] is True
    assert evaluated["context"]["execution_authorization_evaluation"]["execution_request"] == request["envelope"]["execution_request"]
    assert evaluated["action_class"] == "TARGET_RECON"
    assert evaluated["context"]["execution_authorization_evaluation"]["execution_request"]["action"] == {
        "action_class": "TARGET_RECON", "capability_id": "reconnaissance",
        "technique": "TCP_CONNECT_SCAN",
    }
    assert evaluated["resource_value"] == request["envelope"]["execution_request"]["target"]["target_value"]
    assert record["decision"] == "ALLOW"
    assert record["checks"] == {key: "PASS" for key in record["checks"]}
    assert record["semantics"]["dispatch_performed"] is False
    assert record["semantics"]["target_network_io_performed"] is False


@pytest.mark.parametrize("decision", ["DENY", "REVIEW"])
def test_gss_deny_or_review_is_preserved_for_recon_action(recon_authorization, decision):
    service, intake, authority, _, _ = recon_authorization
    authority.decision = decision
    result = service.authorize_execution(intake)
    assert result["record"]["decision"] == decision
    assert result["execution_authorized"] is False
    assert len(authority.calls) == 1


@pytest.mark.parametrize("mutation", ["orchestration", "task_scope"])
def test_changed_recon_lifecycle_or_scope_blocks_gss_query(recon_authorization, mutation):
    service, intake, authority, _, pentest_db = recon_authorization
    with sqlite3.connect(pentest_db) as conn:
        if mutation == "orchestration":
            conn.execute("UPDATE pentest_agentic_orchestrations SET orchestration_status='TERMINATED'")
        else:
            row = conn.execute("SELECT pentest_task_id, task_json FROM pentest_tasks").fetchone()
            import json
            task = json.loads(row[1])
            task["scope"]["targets"] = []
            conn.execute("UPDATE pentest_tasks SET task_json=? WHERE pentest_task_id=?",
                         (json.dumps(task, sort_keys=True, separators=(",", ":")), row[0]))
    with pytest.raises((ExecutionSourceRejected, ExecutionRequestIntegrityError)):
        service.authorize_execution(intake)
    assert authority.calls == []


def test_gss_unavailable_does_not_create_authorization_or_fall_back_to_old_allow(recon_authorization, monkeypatch):
    service, intake, authority, _, _ = recon_authorization
    service.authorize_execution(intake)
    def unavailable(_):
        from execution_subsystem.authorization_contract import ExecutionGovernanceUnavailable
        raise ExecutionGovernanceUnavailable("offline")
    monkeypatch.setattr(authority, "evaluate_authorization", unavailable)
    fresh = {**intake, "revalidation_id": "eauthreq-recon-fresh", "idempotency_key": "idem-auth-recon-fresh"}
    from execution_subsystem.authorization_contract import ExecutionGovernanceUnavailable
    with pytest.raises(ExecutionGovernanceUnavailable):
        service.authorize_execution(fresh)
    assert len(service.repository.list_authorizations(intake["execution_id"])) == 1
