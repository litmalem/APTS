from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskCompletionConflict,
    MissionTaskCompletionGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_completion import (
    TASK_COMPLETION_ACCEPTANCE_STATUS,
    TASK_COMPLETION_ALLOWED_MISSION_STATES,
    TASK_COMPLETION_AUTHORITY,
    TASK_COMPLETION_CONTRACT_SCHEMA_VERSION,
    TASK_COMPLETION_DEPENDENCY_STATUS,
    TASK_COMPLETION_ID_PREFIX,
    TASK_COMPLETION_MODE,
    TASK_COMPLETION_STAGE_SCHEMA_VERSION,
    TASK_COMPLETION_STATUS,
    derive_dependency_aware_completion,
    verify_task_completion_contract,
)
from tests.test_stage3_6_3_evidence_binding_verification import provision_source


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR = "stage3.6.3-evidence-binding-verification"
EVENT_TYPE = "MISSION_TASK_COMPLETION_COMMITTED"


def completion_request(service, mission_id, active, ebind, key: str, **extra):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"task-completion-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_evidence_binding_verification_id": ebind["verification_id"],
        "expected_evidence_binding_verification_sha256": ebind["canonical_sha256"],
        "completed_by": "stage3.6.4-pytest",
        "reason": "accept verified terminal outcome only when active-Plan dependencies are complete",
        "metadata": {"stage": "3.6.4", "key": key},
    }
    body.update(extra)
    return body


def provision_completion_source(tmp_path: Path, key: str):
    ctx = provision_source(tmp_path, key)
    ebind = ctx["service"].verify_task_evidence_binding(ctx["mission_id"], deepcopy(ctx["body"]))
    body = completion_request(ctx["service"], ctx["mission_id"], ctx["active"], ebind, key)
    return {**ctx, "ebind": ebind, "completion_body": body}


@pytest.fixture(scope="module")
def source_context(tmp_path_factory):
    return provision_completion_source(tmp_path_factory.mktemp("stage364-source"), "shared-source364")


@pytest.fixture(scope="module")
def completed_context(tmp_path_factory):
    ctx = provision_completion_source(tmp_path_factory.mktemp("stage364-completed"), "shared-completed364")
    gov_before = ctx["governance"].evaluate_calls
    runtime_before = (ctx["runtime"].health_calls, ctx["runtime"].result_calls, ctx["runtime"].control_calls)
    created = ctx["service"].commit_dependency_aware_task_completion(
        ctx["mission_id"], deepcopy(ctx["completion_body"])
    )
    ctx["created"] = created
    ctx["gov_before"] = gov_before
    ctx["gov_after"] = ctx["governance"].evaluate_calls
    ctx["runtime_before"] = runtime_before
    ctx["runtime_after"] = (
        ctx["runtime"].health_calls,
        ctx["runtime"].result_calls,
        ctx["runtime"].control_calls,
    )
    return ctx


def test_01_health_activates_stage364_migration39_and_durable_completion_store(source_context):
    health = source_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == ["stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_task_completion_commits" in REPOSITORY_STORES
    assert health["task_completion_stage_schema_version"] == TASK_COMPLETION_STAGE_SCHEMA_VERSION
    assert health["task_completion_contract_schema_version"] == TASK_COMPLETION_CONTRACT_SCHEMA_VERSION
    assert health["task_completion_identity_prefix"] == TASK_COMPLETION_ID_PREFIX
    assert health["task_completion_mode"] == TASK_COMPLETION_MODE
    assert health["task_completion_authority"] == TASK_COMPLETION_AUTHORITY
    assert health["task_completion_status"] == TASK_COMPLETION_STATUS
    assert health["task_completion_database_migration_level"] == 39
    assert health["task_completion_persistence_store"] == "mission_task_completion_commits"


def test_02_definition_declares_dependency_aware_acceptance_and_reserves_release_for_365(source_context):
    definition = source_context["service"].get_task_completion_definition(source_context["mission_id"])[
        "task_completion_definition"
    ]
    assert definition["schema_version"] == TASK_COMPLETION_CONTRACT_SCHEMA_VERSION
    assert definition["requires_stage363_verified_evidence_binding"] is True
    assert definition["requires_active_stage337_plan_version"] is True
    assert definition["requires_all_active_plan_dependencies_completed"] is True
    assert definition["rejects_superseded_plan_dependencies"] is True
    assert definition["task_outcome_acceptance_performed"] is True
    assert definition["task_completion_commit_performed"] is True
    assert definition["dependency_release_performed"] is False
    assert definition["readiness_recalculation_performed"] is False
    assert definition["plan_progression_performed"] is False
    assert definition["next_stage"] == "3.6.5"


def test_03_root_task_completion_creates_immutable_dependency_consistent_commit(completed_context):
    created = completed_context["created"]
    assert created["task_completion_id"].startswith(TASK_COMPLETION_ID_PREFIX)
    assert created["completion_status"] == TASK_COMPLETION_STATUS
    assert created["task_outcome_accepted"] is True
    assert created["task_completion_committed"] is True
    assert created["dependency_status"] == TASK_COMPLETION_DEPENDENCY_STATUS
    assert created["dependency_count"] == created["completed_dependency_count"] == 0
    assert verify_task_completion_contract(created["task_completion_contract"])


def test_04_completion_contract_binds_stage363_outcome_gate_and_active_plan(completed_context):
    created = completed_context["created"]
    c = created["task_completion_contract"]
    identity, source = c["identity"], c["source_bindings"]
    assert identity["mission_id"] == completed_context["mission_id"]
    assert identity["plan_version_record_id"] == completed_context["active"]["plan_version_record_id"]
    assert identity["evidence_binding_verification_id"] == completed_context["ebind"]["verification_id"]
    assert identity["task_outcome_id"] == completed_context["task_outcome"]["task_outcome_id"]
    assert identity["eligibility_gate_id"] == completed_context["gate"]["eligibility_gate_id"]
    assert source["active_plan_sha256"] == completed_context["active"]["canonical_sha256"]
    assert source["evidence_binding_verification_sha256"] == completed_context["ebind"]["canonical_sha256"]
    assert c["completion_decision"]["task_outcome_acceptance_status"] == TASK_COMPLETION_ACCEPTANCE_STATUS


def test_05_completion_commits_acceptance_but_does_not_release_or_progress(completed_context):
    created = completed_context["created"]
    assert created["task_outcome_acceptance_performed"] is True
    assert created["dependency_precondition_evaluation_performed"] is True
    assert created["canonical_completion_record_created"] is True
    for key in (
        "task_state_transition_performed",
        "dependency_release_performed",
        "readiness_recalculation_performed",
        "plan_progression_performed",
        "mission_success_completion_authority_exercised",
        "governance_query_performed",
        "runtime_query_performed",
        "runtime_control_io_performed",
        "dispatch_redelivery_performed",
        "new_execution_attempt_created",
        "new_target_action_dispatch_performed",
        "external_network_io_performed",
        "target_actuation",
        "mission_state_transition_performed",
    ):
        assert created[key] is False


def test_06_stale_mission_version_vector_is_rejected(source_context):
    body = deepcopy(source_context["completion_body"])
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        source_context["service"].commit_dependency_aware_task_completion(source_context["mission_id"], body)


def test_07_stale_active_plan_hash_is_rejected(source_context):
    body = deepcopy(source_context["completion_body"])
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        source_context["service"].commit_dependency_aware_task_completion(source_context["mission_id"], body)


def test_08_stale_evidence_binding_hash_is_rejected(source_context):
    body = deepcopy(source_context["completion_body"])
    body["expected_evidence_binding_verification_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="evidence-binding verification SHA-256"):
        source_context["service"].commit_dependency_aware_task_completion(source_context["mission_id"], body)


def test_09_missing_stage363_evidence_binding_fails_closed(source_context):
    body = deepcopy(source_context["completion_body"])
    body["expected_evidence_binding_verification_id"] = "ebind-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionTaskCompletionGuardRejected, match="evidence-binding verification is missing"):
        source_context["service"].commit_dependency_aware_task_completion(source_context["mission_id"], body)


def test_10_caller_supplied_dependencies_release_or_progression_fields_are_forbidden(source_context):
    forbidden = [
        ("dependency_task_keys", []),
        ("dependency_completions", []),
        ("task_outcome_accepted", True),
        ("task_completed", True),
        ("completion_status", TASK_COMPLETION_STATUS),
        ("dependency_release", True),
        ("readiness_recalculation", True),
        ("plan_progression", True),
        ("mission_completed", True),
        ("governance_decision", "ALLOW"),
        ("runtime_action", "resume"),
    ]
    for idx, (field, value) in enumerate(forbidden):
        body = deepcopy(source_context["completion_body"])
        body["idempotency_key"] = f"completion-forbidden-{idx}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported dependency-aware task completion field"):
            source_context["service"].commit_dependency_aware_task_completion(source_context["mission_id"], body)


def test_11_same_request_is_idempotent_without_duplicate_completion_or_event(completed_context):
    service, mission_id = completed_context["service"], completed_context["mission_id"]
    first = completed_context["created"]
    replay = service.commit_dependency_aware_task_completion(mission_id, deepcopy(completed_context["completion_body"]))
    assert replay["idempotent_replay"] is True
    assert replay["task_completion_id"] == first["task_completion_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_task_completion_history(mission_id)["task_completion_count"] == 1
    events = service.get_mission_events(mission_id)["events"]
    assert len([e for e in events if e["event_type"] == EVENT_TYPE]) == 1


def test_12_same_idempotency_key_with_different_request_conflicts(completed_context):
    body = deepcopy(completed_context["completion_body"])
    body["reason"] = "different canonical Stage-3.6.4 request"
    with pytest.raises(MissionTaskCompletionConflict, match="idempotency_key"):
        completed_context["service"].commit_dependency_aware_task_completion(completed_context["mission_id"], body)


def test_13_only_one_immutable_completion_is_allowed_per_active_plan_task(completed_context):
    body = deepcopy(completed_context["completion_body"])
    body["idempotency_key"] = "task-completion-second364"
    body["reason"] = "second completion attempt for the same active Plan task"
    with pytest.raises(MissionTaskCompletionConflict, match="already has an immutable"):
        completed_context["service"].commit_dependency_aware_task_completion(completed_context["mission_id"], body)


def test_14_completion_and_replay_do_not_contact_runtime_or_governance(completed_context):
    assert completed_context["gov_after"] == completed_context["gov_before"]
    assert completed_context["runtime_after"] == completed_context["runtime_before"]
    service, governance, runtime = completed_context["service"], completed_context["governance"], completed_context["runtime"]
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    replay = service.commit_dependency_aware_task_completion(
        completed_context["mission_id"], deepcopy(completed_context["completion_body"])
    )
    assert governance.evaluate_calls == gov_before
    assert (runtime.health_calls, runtime.result_calls, runtime.control_calls) == runtime_before
    assert replay["external_network_io_performed"] is False
    assert replay["target_actuation"] is False


def test_15_restart_reads_same_immutable_completion_from_durable_repository(completed_context):
    service, mission_id, created = completed_context["service"], completed_context["mission_id"], completed_context["created"]
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=service.repository.sqlite_path))
    fetched = restarted.get_task_completion(mission_id, created["task_completion_id"])
    assert fetched["task_completion_id"] == created["task_completion_id"]
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert verify_task_completion_contract(fetched["task_completion_contract"])
    assert fetched["task_outcome_accepted"] is True
    assert fetched["dependency_release_performed"] is False


def test_16_lineage_event_is_exactly_once_and_causally_bound_to_completion(completed_context):
    service, mission_id, created = completed_context["service"], completed_context["mission_id"], completed_context["created"]
    selected = [e for e in service.get_mission_events(mission_id)["events"] if e["event_type"] == EVENT_TYPE]
    assert len(selected) == 1
    event = selected[0]
    assert event["causation_id"] == created["task_completion_id"]
    assert event["payload"]["task_completion_id"] == created["task_completion_id"]
    assert event["payload"]["evidence_binding_verification_id"] == created["evidence_binding_verification_id"]
    assert event["payload"]["canonical_sha256"] == created["canonical_sha256"]
    assert event["payload"]["task_completion_committed"] is True
    assert event["payload"]["dependency_release_performed"] is False
    assert event["payload"]["readiness_recalculation_performed"] is False


def test_17_repository_projection_persists_completion_and_passes_integrity(completed_context):
    service, mission_id, created = completed_context["service"], completed_context["mission_id"], completed_context["created"]
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_task_completion_commits"] == 1
    refs = repo["persistence_manifest"]["dependency_aware_task_completion_store"]["completions"]
    assert refs[0]["task_completion_id"] == created["task_completion_id"]
    assert refs[0]["evidence_binding_verification_id"] == created["evidence_binding_verification_id"]
    assert refs[0]["dependency_count"] == 0
    checks = {item["check"]: item for item in repo["integrity_checks"]}
    assert checks["dependency_aware_task_completion_store"]["status"] == "PASS"


def test_18_persisted_completion_tampering_breaks_repository_integrity(tmp_path):
    ctx = provision_completion_source(tmp_path, "tamper364")
    created = ctx["service"].commit_dependency_aware_task_completion(ctx["mission_id"], deepcopy(ctx["completion_body"]))
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as conn:
        conn.execute(
            "UPDATE mission_task_completion_commits SET task_completion_committed=? WHERE task_completion_id=?",
            (0, created["task_completion_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        ctx["service"].get_mission_repository(ctx["mission_id"])


def test_19_api_routes_migration_definition_and_history_are_registered(completed_context):
    service, mission_id, created = completed_context["service"], completed_context["mission_id"], completed_context["created"]
    fetched = service.get_task_completion(mission_id, created["task_completion_id"])
    history = service.get_task_completion_history(mission_id)
    definition = service.get_task_completion_definition(mission_id)
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert history["task_completion_count"] == 1
    assert definition["registered_task_completion_count"] == 1
    api_source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "task-completions" in api_source
    assert "task-completion-definition" in api_source
    migration = Path("migrations/039_stage3_6_4_dependency_aware_task_completion.sql")
    assert migration.is_file()
    migration_text = migration.read_text(encoding="utf-8")
    assert "mission_task_completion_commits" in migration_text
    assert "UNIQUE" in migration_text.upper()


def test_20_dependency_derivation_is_active_plan_aware_fail_closed_and_rejects_superseded_dependency(source_context):
    active = source_context["active"]
    ebind = deepcopy(source_context["ebind"])
    steps = active["plan_version_contract"]["candidate_plan"]["plan_steps"]
    root = next(step for step in steps if step["task_key"] == "collect-cti")
    dependent = next(step for step in steps if step["task_key"] == "analyze-cti")
    ebind_contract = ebind["task_evidence_binding_verification_contract"]
    ebind_contract["identity"]["planned_task_id"] = dependent["planned_task_id"]
    ebind_contract["identity"]["task_key"] = dependent["task_key"]

    with patch("mission_orchestrator.task_completion.verify_plan_version_contract", return_value=True), patch(
        "mission_orchestrator.task_completion.verify_task_evidence_binding_verification_contract", return_value=True
    ):
        with pytest.raises(MissionValidationError, match="incomplete prerequisite task"):
            derive_dependency_aware_completion(
                active_plan=active,
                evidence_binding_verification=ebind,
                dependency_completions=[],
            )

        prerequisite = {
            "task_completion_id": "tcomp-00000000-0000-0000-0000-000000000001",
            "planned_task_id": root["planned_task_id"],
            "task_key": root["task_key"],
            "plan_version_record_id": active["plan_version_record_id"],
            "plan_version": int(active["plan_version"]),
            "completion_status": TASK_COMPLETION_STATUS,
            "canonical_sha256": "a" * 64,
        }
        derived = derive_dependency_aware_completion(
            active_plan=active,
            evidence_binding_verification=ebind,
            dependency_completions=[prerequisite],
        )
        assert derived["dependency_task_keys"] == ["collect-cti"]
        assert derived["dependency_count"] == derived["completed_dependency_count"] == 1
        assert derived["all_dependencies_completed"] is True
        assert derived["active_plan_dependency_consistent"] is True
        assert derived["superseded_plan_dependency_used"] is False

        stale = deepcopy(prerequisite)
        stale["plan_version_record_id"] = "pver-00000000-0000-0000-0000-000000000000"
        with pytest.raises(MissionValidationError, match="stale/superseded Plan"):
            derive_dependency_aware_completion(
                active_plan=active,
                evidence_binding_verification=ebind,
                dependency_completions=[stale],
            )

    assert set(TASK_COMPLETION_ALLOWED_MISSION_STATES) == {"RUNNING", "FAILED", "ABORTED"}
