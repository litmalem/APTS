from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from pentest_subsystem.api_service import PentestSubsystemStage47Handler, PentestSubsystemStage48Handler
from pentest_subsystem.capability_repository import PentestCapabilityRepository
from pentest_subsystem.governance_contract import (
    PENTEST_GOVERNANCE_CONTROL_VERSION,
    PENTEST_GOVERNANCE_REPOSITORY_MIGRATION_LEVEL,
    canonical_pentest_governance_contract,
    canonical_pentest_governance_definition,
    verify_pentest_governance_contract,
)
from pentest_subsystem.governance_repository import (
    PENTEST_GOVERNANCE_REPOSITORY_SCHEMA_VERSION,
    PentestGovernanceDecisionConflict,
    PentestGovernanceRepository,
)
from pentest_subsystem.governance_service import PentestGovernanceService
from pentest_subsystem.task_contract import build_pentest_task_binding
from tests.test_stage4_4_pentest_lifecycle_state import FIXED_NOW, sample_boundary, sample_pip, sample_task

CONTROL = "stage4.8-governance-scope-roe-enforcement"


def _materialize(repo: PentestGovernanceRepository, boundary=None):
    boundary = boundary or sample_boundary()
    pip = sample_pip(boundary)
    task = sample_task(boundary, pip)
    binding = build_pentest_task_binding(boundary_payload=boundary, pip_payload=pip, task_payload=task, now=FIXED_NOW)
    record, created = repo.create_task(task, binding)
    assert created
    return boundary, task, record


def _request(boundary, task, **overrides):
    payload = {
        "evaluation_id": "eval-stage48-001",
        "idempotency_key": "idem-stage48-001",
        "pentest_task_id": task["pentest_task_id"],
        "boundary": boundary,
        "capability_id": "reconnaissance",
        "action_class": "TARGET_RECON",
        "technique": "TCP_CONNECT_SCAN",
        "target": deepcopy(boundary["scope"]["targets"][0]),
        "requested_at": "2026-09-02T12:00:00Z",
        "estimated_impact": "LOW",
        "rate_cost": 1,
        "active_concurrency": 1,
        "stop_signals": [],
        "metadata": {"test": True},
    }
    payload.update(overrides)
    return payload


def _start_server(tmp_path: Path):
    service = PentestGovernanceService(PentestGovernanceRepository(tmp_path / "pentest.db"))
    handler = type("IsolatedStage48Handler", (PentestSubsystemStage48Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, service, f"http://127.0.0.1:{server.server_address[1]}"


def _post(url, payload):
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode())


def test_01_control_binds_exact_stage47_predecessor_and_next_stage():
    c = canonical_pentest_governance_contract()
    assert c["control_version"] == CONTROL == PENTEST_GOVERNANCE_CONTROL_VERSION
    assert c["predecessor"]["control"] == "stage4.7-capability-registry-tool-contract"
    assert c["repository"]["migration_level"] == 6
    assert c["next_stage"] == "4.9"


def test_02_control_is_hash_bound_and_tamper_fails_closed():
    c = canonical_pentest_governance_contract()
    assert verify_pentest_governance_contract(c)
    bad = deepcopy(c); bad["runtime"]["execution_intake_enabled"] = True
    assert not verify_pentest_governance_contract(bad)


def test_03_definition_contains_all_nine_machine_enforced_roadmap_dimensions():
    dims = canonical_pentest_governance_definition()["machine_enforced_dimensions"]
    assert dims == ["target_allowlist", "target_denylist", "network_range", "credential_boundary", "technique_restrictions", "time_window", "impact_limit", "rate_limit", "stop_conditions"]


def test_04_repository_migrates_to_level_six_and_adds_append_only_decision_store(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db")
    assert repo.migration_level() == PENTEST_GOVERNANCE_REPOSITORY_MIGRATION_LEVEL == 6
    assert repo.metadata()["schema_version"] == PENTEST_GOVERNANCE_REPOSITORY_SCHEMA_VERSION
    with sqlite3.connect(repo.sqlite_path) as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert "pentest_scope_roe_decisions" in tables


def test_05_in_scope_allowed_recon_is_eligible_but_not_authorized_or_executed(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db")
    boundary, task, _ = _materialize(repo)
    result = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task))
    assert result["decision"]["status"] == "ELIGIBLE"
    assert result["scope_roe_eligible"] is True
    assert result["decision_is_authorization"] is False
    assert result["authorization_minted"] is False
    assert result["execution_started"] is False
    assert result["tool_invocation_performed"] is False
    assert result["target_actuation"] is False


def test_06_target_outside_allowlist_fails_closed(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db")
    boundary, task, _ = _materialize(repo)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, target={"target_type":"HOST","target_value":"outside.internal"}))
    assert r["decision"]["status"] == "INELIGIBLE"
    assert "SCOPE-ALLOW" in r["decision"]["failed_rule_ids"]


def test_07_target_on_denylist_fails_closed(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db")
    boundary, task, _ = _materialize(repo)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, target=deepcopy(boundary["scope"]["excluded_targets"][0])))
    assert r["decision"]["status"] == "INELIGIBLE"
    assert "SCOPE-DENY" in r["decision"]["failed_rule_ids"]


def test_08_network_range_restricts_ip_even_if_generic_ip_target_is_declared(tmp_path):
    boundary = sample_boundary()
    boundary["scope"]["targets"] = [{"target_type":"CIDR","target_value":"10.10.0.0/16"}]
    boundary["scope"]["excluded_targets"] = []
    boundary["constraints"]["network_ranges"] = ["10.10.0.0/16"]
    repo = PentestGovernanceRepository(tmp_path / "pentest.db")
    boundary, task, _ = _materialize(repo, boundary)
    ok = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, target={"target_type":"IP","target_value":"10.10.1.8"}))
    assert ok["decision"]["status"] == "ELIGIBLE"


def test_09_prohibited_action_class_is_ineligible(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db")
    boundary, task, _ = _materialize(repo)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, action_class="DESTRUCTIVE_ACTION", estimated_impact="DESTRUCTIVE"))
    assert r["decision"]["status"] == "INELIGIBLE"
    assert "ROE-ACTION" in r["decision"]["failed_rule_ids"]
    assert "ROE-IMPACT" in r["decision"]["failed_rule_ids"]


def test_10_credential_use_requires_explicit_permission_and_boundary(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db")
    boundary, task, _ = _materialize(repo)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, credential_ref="cred-1"))
    assert r["decision"]["status"] == "INELIGIBLE"
    assert "ROE-CREDENTIAL" in r["decision"]["failed_rule_ids"]


def test_11_declared_technique_denylist_is_enforced(tmp_path):
    boundary = sample_boundary(); boundary["roe"]["prohibited_techniques"] = ["T-BLOCKED"]
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo, boundary)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, technique="T-BLOCKED"))
    assert "ROE-TECHNIQUE" in r["decision"]["failed_rule_ids"]


def test_12_time_window_is_machine_enforced(tmp_path):
    boundary = sample_boundary(); boundary["roe"]["allowed_time_window"] = {"start_at":"2026-09-02T10:00:00Z","end_at":"2026-09-02T11:00:00Z"}
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo, boundary)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, requested_at="2026-09-02T12:00:00Z"))
    assert "ROE-TIME" in r["decision"]["failed_rule_ids"]


def test_13_rate_and_concurrency_limits_are_enforced(tmp_path):
    boundary = sample_boundary(); boundary["roe"]["maximum_concurrency"] = 1; boundary["constraints"]["resource_budget"] = {"max_network_requests": 5}
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo, boundary)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, rate_cost=6, active_concurrency=2))
    assert "ROE-RATE" in r["decision"]["failed_rule_ids"]


def test_14_stop_signal_blocks_further_eligibility(tmp_path):
    boundary = sample_boundary(); boundary["roe"]["stop_conditions"] = ["OPERATOR_KILL", "TARGET_INSTABILITY"]
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo, boundary)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task, stop_signals=["OPERATOR_KILL"]))
    assert "ROE-STOP" in r["decision"]["failed_rule_ids"]


def test_15_human_approval_requirement_produces_review_required_not_local_allow(tmp_path):
    boundary = sample_boundary(); boundary["roe"]["human_approval_required_for"] = ["TARGET_RECON"]
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo, boundary)
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task))
    assert r["decision"]["status"] == "REVIEW_REQUIRED"
    assert r["scope_roe_eligible"] is False
    assert r["decision"]["semantics"]["decision_is_authorization"] is False


def test_16_boundary_task_binding_mismatch_fails_closed(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo)
    other = deepcopy(boundary); other["objective"] = {"type":"OTHER","description":"changed"}
    r = PentestGovernanceService(repo).evaluate_scope_roe(_request(other, task))
    assert "CTX-001" in r["decision"]["failed_rule_ids"]


def test_17_exact_replay_is_idempotent_and_does_not_duplicate_audit_record(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo)
    svc = PentestGovernanceService(repo); payload = _request(boundary, task)
    a = svc.evaluate_scope_roe(payload); b = svc.evaluate_scope_roe(payload)
    assert a["created"] is True and b["replayed"] is True
    assert a["decision"]["decision_id"] == b["decision"]["decision_id"]
    assert len(repo.list_scope_roe_decisions(task["pentest_task_id"])) == 1


def test_18_idempotency_key_aliasing_different_request_conflicts(tmp_path):
    repo = PentestGovernanceRepository(tmp_path / "pentest.db"); boundary, task, _ = _materialize(repo)
    svc = PentestGovernanceService(repo); svc.evaluate_scope_roe(_request(boundary, task))
    changed = _request(boundary, task, target={"target_type":"HOST","target_value":"outside.internal"}, evaluation_id="eval-stage48-002")
    with pytest.raises(PentestGovernanceDecisionConflict): svc.evaluate_scope_roe(changed)


def test_19_restart_preserves_and_verifies_decision(tmp_path):
    db = tmp_path / "pentest.db"; repo = PentestGovernanceRepository(db); boundary, task, _ = _materialize(repo)
    decision = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task))["decision"]
    restarted = PentestGovernanceRepository(db)
    assert restarted.get_scope_roe_decision(decision["decision_id"])["decision"] == decision
    assert restarted.migration_level() == 6


def test_20_health_activates_stage48_and_keeps_execution_disabled(tmp_path):
    h = PentestGovernanceService(PentestGovernanceRepository(tmp_path / "pentest.db")).health()
    assert h["control_version"] == CONTROL
    assert h["stage4_8_scope_validator_enabled"] is True
    assert h["stage4_8_roe_enforcement_enabled"] is True
    assert h["stage4_8_authorization_minting_enabled"] is False
    assert h["stage4_8_execution_intake_enabled"] is False
    assert h["stage4_8_target_actuation"] is False


def test_21_http_contract_evaluation_query_and_execution_boundary(tmp_path):
    server, thread, svc, base = _start_server(tmp_path)
    try:
        boundary, task, _ = _materialize(svc.repository)
        with urlopen(base + "/api/pentest/governance-contract", timeout=5) as resp:
            assert json.loads(resp.read())["control_version"] == CONTROL
        status, body = _post(base + "/api/pentest/governance/evaluate", _request(boundary, task))
        assert status == 200 and body["decision"]["status"] == "ELIGIBLE"
        did = body["decision"]["decision_id"]
        with urlopen(base + "/api/pentest/governance/decisions/" + did, timeout=5) as resp:
            assert json.loads(resp.read())["decision"]["decision_id"] == did
        with urlopen(base + f"/api/pentest/tasks/{task['pentest_task_id']}/governance-decisions", timeout=5) as resp:
            assert json.loads(resp.read())["count"] == 1
        req = Request(base + "/api/execution/dispatches", data=b"{}", headers={"Content-Type":"application/json"}, method="POST")
        with pytest.raises(HTTPError) as exc: urlopen(req, timeout=5)
        assert exc.value.code == 409
        assert json.loads(exc.value.read())["error_code"] == "STAGE4_8_EXECUTION_INTAKE_NOT_ENABLED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_22_stage47_handler_is_preserved_for_historical_regression():
    assert PentestSubsystemStage47Handler.server_version == "APTSPentestSubsystem/4.7"
    assert PentestSubsystemStage48Handler.server_version == "APTSPentestSubsystem/4.8"


def test_23_upgrade_from_stage47_database_preserves_registry(tmp_path):
    db = tmp_path / "upgrade.db"
    old = PentestCapabilityRepository(db)
    assert old.migration_level() == 5
    reg = old.get_capability_registry()
    new = PentestGovernanceRepository(db)
    assert new.migration_level() == 6
    assert new.get_capability_registry() == reg


def test_24_decision_store_tamper_is_detected_on_read(tmp_path):
    db = tmp_path / "pentest.db"; repo = PentestGovernanceRepository(db); boundary, task, _ = _materialize(repo)
    d = PentestGovernanceService(repo).evaluate_scope_roe(_request(boundary, task))["decision"]
    with sqlite3.connect(db) as conn:
        conn.execute("update pentest_scope_roe_decisions set decision_sha256=? where decision_id=?", ("0"*64, d["decision_id"])); conn.commit()
    from pentest_subsystem.governance_repository import PentestGovernanceDecisionIntegrityError
    with pytest.raises(PentestGovernanceDecisionIntegrityError): PentestGovernanceRepository(db).get_scope_roe_decision(d["decision_id"])
