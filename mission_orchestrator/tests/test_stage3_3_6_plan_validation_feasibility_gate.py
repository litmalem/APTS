from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import json

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionPlanValidationConflict,
    MissionPlanValidationGuardRejected,
    MissionPlanValidationNotFound,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.plan_validation import (
    PLAN_FEASIBILITY_MODE,
    PLAN_VALIDATION_ID_PREFIX,
    PLAN_VALIDATION_MODE,
    PLAN_VALIDATION_REQUIRED_STATE,
    PLAN_VALIDATION_SCHEMA_VERSION,
    PLAN_VALIDATION_STATUS,
    canonical_plan_validation_definition,
    evaluate_plan_feasibility,
    verify_plan_validation_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from tests.test_stage3_3_5_planner_invocation_plan_generation import (
    make_service,
    provision_graph,
    planner_request,
    scope_payload,
)
from tests.test_stage3_3_4_task_dependency_graph_structural_validation import execute


def provision_generated(service, key: str, *, with_scope: bool = False):
    mission_id, plan, snapshot, decomp, graph = provision_graph(service, key, with_scope=with_scope)
    generated = service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, key))
    return mission_id, plan, snapshot, decomp, graph, generated


def validation_request(service, mission_id: str, key: str, **overrides) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    generated = service.get_generated_plan(mission_id)
    request = {
        "idempotency_key": f"stage336-validation-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_generated_plan_id": generated["generated_plan_id"],
        "expected_generated_plan_sha256": generated["canonical_sha256"],
        "created_by": "stage3.3.6-pytest",
        "reason": "Validate Stage-3.3.5 candidate Plan feasibility",
        "metadata": {"stage": "3.3.6", "key": key},
    }
    request.update(overrides)
    return request


def test_health_activates_stage336_validation_without_authority_or_execution_expansion(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][20:30] == [
        "stage3.3.1-canonical-plan-contract-identity",
        "stage3.3.2-planner-input-snapshot-context-binding",
        "stage3.3.3-canonical-task-decomposition-contract",
        "stage3.3.4-task-dependency-graph-structural-validation",
        "stage3.3.5-planner-invocation-plan-generation",
        "stage3.3.6-plan-validation-feasibility-gate",
        "stage3.3.7-plan-versioning-replanning-supersession",
        "stage3.3.8-task-readiness-scheduling-projection",
        "stage3.3.9-planning-event-lineage-replay-recovery",
        "stage3.3.10-planning-acceptance-regression-gate",
    ]
    assert health["plan_validation_schema_version"] == PLAN_VALIDATION_SCHEMA_VERSION
    assert health["plan_validation_mode"] == PLAN_VALIDATION_MODE
    assert health["plan_validation_feasibility_mode"] == PLAN_FEASIBILITY_MODE
    assert health["plan_validation_creation_state_required"] == PLAN_VALIDATION_REQUIRED_STATE
    assert health["plan_validation_feasibility_validation_performed"] is True
    assert health["plan_validation_plan_activation_performed"] is False
    assert health["plan_validation_readiness_projection_performed"] is False
    assert health["plan_validation_scheduling_performed"] is False
    assert health["plan_validation_governance_query_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["plan_validation_target_action_dispatch_enabled"] is False
    assert health["plan_validation_target_actuation"] is False
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "plan_validation_version" in health["observed_version_domains"]


def test_plan_validation_definition_is_discoverable_before_validation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "definition")
    result = service.get_plan_validation_definition(mission_id)
    assert result["generated_plan_registered"] is True
    assert result["generated_plan_status"] == "GENERATED_UNVALIDATED"
    assert result["plan_validation_registered"] is False
    assert result["plan_validation_definition"] == canonical_plan_validation_definition()


def test_stage336_requires_stage335_generated_candidate_plan(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_graph(service, "missing-generation")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    payload = {
        "idempotency_key": "stage336-missing-generation",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_generated_plan_id": "pgen-missing",
        "expected_generated_plan_sha256": "0" * 64,
        "created_by": "stage3.3.6-pytest",
    }
    with pytest.raises(MissionPlanValidationGuardRejected, match="Stage-3.3.5"):
        service.validate_generated_plan_feasibility(mission_id, payload)


def test_valid_candidate_materializes_immutable_validated_feasible_artifact(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "valid")
    result = service.validate_generated_plan_feasibility(mission_id, validation_request(service, mission_id, "valid"))
    assert result["idempotent_replay"] is False
    assert result["plan_validation_id"].startswith(PLAN_VALIDATION_ID_PREFIX)
    assert result["validation_version"] == 1
    assert result["validation_status"] == PLAN_VALIDATION_STATUS
    assert result["feasible"] is True
    assert verify_plan_validation_contract(result["plan_validation"])
    checks = result["plan_validation"]["validation"]["checks"]
    assert all(x["status"] == "PASS" for x in checks)
    assert result["feasibility_is_authorization"] is False
    assert result["plan_activation_performed"] is False
    assert result["readiness_projection_performed"] is False
    assert result["target_action_dispatch_enabled"] is False


def test_exact_replay_is_idempotent_and_second_distinct_validation_is_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "replay")
    request = validation_request(service, mission_id, "replay")
    first = service.validate_generated_plan_feasibility(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.validate_generated_plan_feasibility(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["plan_validation_id"] == first["plan_validation_id"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count
    different = dict(request)
    different["idempotency_key"] = "stage336-validation-replay-2"
    different["expected_version_sha256"] = service.get_mission_version_vector(mission_id)["version_sha256"]
    with pytest.raises(MissionPlanValidationConflict, match="exactly one immutable validation"):
        service.validate_generated_plan_feasibility(mission_id, different)


def test_stale_version_and_non_planning_state_fail_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "stale")
    request = validation_request(service, mission_id, "stale")
    request["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="expected_version_sha256"):
        service.validate_generated_plan_feasibility(mission_id, request)

    request = validation_request(service, mission_id, "state")
    execute(service, mission_id, "START", "stage336-running")
    request["expected_version_sha256"] = service.get_mission_version_vector(mission_id)["version_sha256"]
    request["expected_state_version"] = service.get_mission_state(mission_id)["mission_state"]["state_version"]
    with pytest.raises(MissionPlanValidationGuardRejected, match="PLANNING"):
        service.validate_generated_plan_feasibility(mission_id, request)


def test_scope_context_drift_after_generation_blocks_validation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "scope-drift", with_scope=True)
    service.put_mission_scope_contract(mission_id, scope_payload("stage336-scope-v2", expected=1))
    request = validation_request(service, mission_id, "scope-drift")
    with pytest.raises(MissionPlanValidationGuardRejected, match="Scope changed"):
        service.validate_generated_plan_feasibility(mission_id, request)


@pytest.mark.parametrize("field", ["authorization", "readiness", "schedule", "dispatch", "execution_command", "feasibility"])
def test_request_rejects_caller_supplied_authority_readiness_or_feasibility_surfaces(tmp_path, field):
    service = make_service(tmp_path / f"surface-{field}.db")
    mission_id, *_ = provision_generated(service, f"surface-{field}")
    request = validation_request(service, mission_id, f"surface-{field}")
    request[field] = True
    with pytest.raises(MissionValidationError, match="does not accept caller-supplied feasibility"):
        service.validate_generated_plan_feasibility(mission_id, request)


def test_feasibility_evaluator_rejects_candidate_without_evidence_contract(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "bad-evidence")
    generated = deepcopy(service.repository.get_generated_plan(mission_id))
    generated["generated_plan"]["generated_plan"]["plan_steps"][0]["evidence_requirements"] = []
    # Recompute is intentionally not performed: integrity must fail before feasibility can be claimed.
    with pytest.raises(MissionPlanValidationGuardRejected, match="integrity"):
        evaluate_plan_feasibility(
            generated_plan_record=generated,
            decomposition_record=service.repository.get_task_decomposition(mission_id),
            task_records=service.repository.list_planned_tasks(mission_id),
            graph_record=service.repository.get_task_dependency_graph(mission_id),
            mission_required_subsystems=["CTI"],
        )


def test_version_vector_advances_only_plan_validation_domain(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    bv = before["version_vector"]["versions"]
    assert bv["planner_generation_version"] == 1
    assert bv["plan_validation_version"] == 0
    result = service.validate_generated_plan_feasibility(mission_id, validation_request(service, mission_id, "vector"))
    after = service.get_mission_version_vector(mission_id)
    av = after["version_vector"]["versions"]
    for key in ("mission_plan_version", "planner_input_snapshot_version", "task_decomposition_version", "task_dependency_graph_version", "planner_generation_version"):
        assert av[key] == bv[key]
    assert av["plan_validation_version"] == 1
    assert result["source_version_sha256"] == before["version_sha256"]
    assert after["version_sha256"] != before["version_sha256"]


def test_validation_emits_exactly_one_canonical_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "events")
    result = service.validate_generated_plan_feasibility(mission_id, validation_request(service, mission_id, "events"))
    events = service.get_mission_events(mission_id)["events"]
    matches = [e for e in events if e["event_type"] == "MISSION_PLAN_VALIDATED_FEASIBLE"]
    assert len(matches) == 1
    assert matches[0]["causation_id"] == result["plan_validation_id"]
    assert matches[0]["payload"]["canonical_sha256"] == result["canonical_sha256"]


def test_repository_integrity_restart_and_read_model_include_validation(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_ = provision_generated(service, "repo")
    result = service.validate_generated_plan_feasibility(mission_id, validation_request(service, mission_id, "repo"))
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_plan_validations"] == 1
    assert repo["persistence_manifest"]["plan_validation_store"]["plan_validation_id"] == result["plan_validation_id"]
    restarted = make_service(db)
    restored = restarted.get_plan_validation(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)
    assert restored["canonical_sha256"] == result["canonical_sha256"]
    assert repo_after["repository_sha256"] == repo["repository_sha256"]


def test_repository_integrity_detects_plan_validation_tampering(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_ = provision_generated(service, "tamper")
    service.validate_generated_plan_feasibility(mission_id, validation_request(service, mission_id, "tamper"))
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT canonical_json FROM mission_plan_validations WHERE mission_id=?", (mission_id,)).fetchone()
    contract = json.loads(row[0]); contract["validation"]["feasible"] = False
    conn.execute("UPDATE mission_plan_validations SET canonical_json=? WHERE mission_id=?", (json.dumps(contract, sort_keys=True, separators=(",", ":")), mission_id))
    conn.commit(); conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="plan_validation_feasibility_store"):
        service.get_mission_repository(mission_id)


def test_missing_validation_read_model_is_typed_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "not-found")
    with pytest.raises(MissionPlanValidationNotFound):
        service.get_plan_validation(mission_id)


def test_migration_014_declares_validation_store_boundaries_and_level_14():
    sql = Path("migrations/014_stage3_3_6_plan_validation_feasibility_gate.sql").read_text().lower()
    assert "create table if not exists mission_plan_validations" in sql
    assert "foreign key (generated_plan_id) references mission_generated_plans(generated_plan_id)" in sql
    assert "no governance authorization" in sql
    assert "readiness" in sql and "scheduling" in sql
    assert "target-action dispatch" in sql and "target actuation" in sql
    assert "    14," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[13].name == "014_stage3_3_6_plan_validation_feasibility_gate.sql"
