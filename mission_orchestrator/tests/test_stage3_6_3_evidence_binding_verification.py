from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskEvidenceBindingConflict,
    MissionTaskEvidenceBindingGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_evidence_binding import (
    TASK_EVIDENCE_BINDING_ALLOWED_MISSION_STATES,
    TASK_EVIDENCE_BINDING_AUTHORITY,
    TASK_EVIDENCE_BINDING_CONTRACT_SCHEMA_VERSION,
    TASK_EVIDENCE_BINDING_ID_PREFIX,
    TASK_EVIDENCE_BINDING_MODE,
    TASK_EVIDENCE_BINDING_STAGE_SCHEMA_VERSION,
    TASK_EVIDENCE_BINDING_STATUS,
    derive_evidence_binding_verification,
    verify_task_evidence_binding_verification_contract,
)
from tests.test_stage3_6_2_task_terminality_completion_eligibility import evaluate


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR = "stage3.6.2-task-terminality-completion-eligibility"
EVENT_TYPE = "MISSION_TASK_EVIDENCE_BINDING_VERIFIED"


def binding_request(service, mission_id, active, task_outcome, gate, result_capture, key: str, **extra):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"evidence-binding-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_outcome_id": task_outcome["task_outcome_id"],
        "expected_task_outcome_sha256": task_outcome["canonical_sha256"],
        "expected_eligibility_gate_id": gate["eligibility_gate_id"],
        "expected_eligibility_gate_sha256": gate["canonical_sha256"],
        "expected_result_capture_id": result_capture["result_capture_id"],
        "expected_result_capture_sha256": result_capture["canonical_sha256"],
        "verified_by": "stage3.6.3-pytest",
        "reason": "verify local immutable evidence/artifact reference and hash bindings",
        "metadata": {"stage": "3.6.3", "key": key},
    }
    body.update(extra)
    return body


def provision_source(tmp_path: Path, key: str):
    data = evaluate(tmp_path, key)
    service, governance, runtime, mission_id, active = data[:5]
    result_capture = data[8]
    task_outcome = data[12]
    gate = data[14]
    body = binding_request(service, mission_id, active, task_outcome, gate, result_capture, key)
    return {
        "data": data,
        "service": service,
        "governance": governance,
        "runtime": runtime,
        "mission_id": mission_id,
        "active": active,
        "result_capture": result_capture,
        "task_outcome": task_outcome,
        "gate": gate,
        "body": body,
    }


@pytest.fixture(scope="module")
def source_context(tmp_path_factory):
    return provision_source(tmp_path_factory.mktemp("stage363-source"), "shared-source363")


@pytest.fixture(scope="module")
def verified_context(tmp_path_factory):
    ctx = provision_source(tmp_path_factory.mktemp("stage363-verified"), "shared-verified363")
    gov_before = ctx["governance"].evaluate_calls
    runtime_before = (ctx["runtime"].health_calls, ctx["runtime"].result_calls, ctx["runtime"].control_calls)
    created = ctx["service"].verify_task_evidence_binding(ctx["mission_id"], deepcopy(ctx["body"]))
    ctx["created"] = created
    ctx["gov_before"] = gov_before
    ctx["gov_after"] = ctx["governance"].evaluate_calls
    ctx["runtime_before"] = runtime_before
    ctx["runtime_after"] = (ctx["runtime"].health_calls, ctx["runtime"].result_calls, ctx["runtime"].control_calls)
    return ctx


def test_01_health_activates_stage363_migration38_and_durable_store(source_context):
    health = source_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == ["stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_task_evidence_binding_verifications" in REPOSITORY_STORES
    assert health["task_evidence_binding_stage_schema_version"] == TASK_EVIDENCE_BINDING_STAGE_SCHEMA_VERSION
    assert health["task_evidence_binding_contract_schema_version"] == TASK_EVIDENCE_BINDING_CONTRACT_SCHEMA_VERSION
    assert health["task_evidence_binding_identity_prefix"] == TASK_EVIDENCE_BINDING_ID_PREFIX
    assert health["task_evidence_binding_mode"] == TASK_EVIDENCE_BINDING_MODE
    assert health["task_evidence_binding_authority"] == TASK_EVIDENCE_BINDING_AUTHORITY
    assert health["task_evidence_binding_verification_status"] == TASK_EVIDENCE_BINDING_STATUS
    assert health["task_evidence_binding_database_migration_level"] == 38
    assert health["task_evidence_binding_persistence_store"] == "mission_task_evidence_binding_verifications"


def test_02_definition_declares_binding_scope_and_reserves_acceptance_for_364(source_context):
    definition = source_context["service"].get_task_evidence_binding_verification_definition(source_context["mission_id"])[
        "task_evidence_binding_verification_definition"
    ]
    assert definition["schema_version"] == TASK_EVIDENCE_BINDING_CONTRACT_SCHEMA_VERSION
    assert definition["requires_stage357_result_capture"] is True
    assert definition["requires_stage361_task_outcome_identity"] is True
    assert definition["requires_stage362_completion_eligible_gate"] is True
    assert definition["verifies_evidence_manifest_reference_hash_binding"] is True
    assert definition["verifies_artifact_manifest_reference_hash_binding"] is True
    assert definition["content_dereference_performed"] is False
    assert definition["external_content_hash_recomputed"] is False
    assert definition["content_authenticity_attestation_performed"] is False
    assert definition["task_outcome_acceptance_performed"] is False
    assert definition["task_completion_commit_performed"] is False
    assert definition["dependency_release_performed"] is False
    assert definition["next_stage"] == "3.6.4"


def test_03_verified_completion_creates_immutable_evidence_binding_verification(verified_context):
    created = verified_context["created"]
    assert created["verification_id"].startswith(TASK_EVIDENCE_BINDING_ID_PREFIX)
    assert created["verification_status"] == TASK_EVIDENCE_BINDING_STATUS
    assert created["evidence_binding_verified"] is True
    assert created["artifact_binding_verified"] is True
    assert created["evidence_reference_count"] >= 1
    assert created["artifact_reference_count"] >= 0
    assert verify_task_evidence_binding_verification_contract(created["task_evidence_binding_verification_contract"])


def test_04_contract_binds_stage357_stage361_stage362_and_active_plan(verified_context):
    created = verified_context["created"]
    c = created["task_evidence_binding_verification_contract"]
    i, src = c["identity"], c["source_bindings"]
    assert i["mission_id"] == verified_context["mission_id"]
    assert i["plan_version_record_id"] == verified_context["active"]["plan_version_record_id"]
    assert i["task_outcome_id"] == verified_context["task_outcome"]["task_outcome_id"]
    assert i["eligibility_gate_id"] == verified_context["gate"]["eligibility_gate_id"]
    assert i["result_capture_id"] == verified_context["result_capture"]["result_capture_id"]
    assert src["active_plan_sha256"] == verified_context["active"]["canonical_sha256"]
    assert src["task_outcome_sha256"] == verified_context["task_outcome"]["canonical_sha256"]
    assert src["eligibility_gate_sha256"] == verified_context["gate"]["canonical_sha256"]
    assert src["result_capture_sha256"] == verified_context["result_capture"]["canonical_sha256"]


def test_05_verification_is_reference_binding_not_content_attestation_or_completion(verified_context):
    created = verified_context["created"]
    assert created["evidence_content_dereferenced"] is False
    assert created["artifact_content_dereferenced"] is False
    assert created["external_content_hash_recomputed"] is False
    for key in (
        "task_outcome_acceptance_performed",
        "acceptance_criteria_evaluation_performed",
        "task_completion_commit_performed",
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
    body = deepcopy(source_context["body"])
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        source_context["service"].verify_task_evidence_binding(source_context["mission_id"], body)


def test_07_stale_active_plan_hash_is_rejected(source_context):
    body = deepcopy(source_context["body"])
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        source_context["service"].verify_task_evidence_binding(source_context["mission_id"], body)


def test_08_stale_source_hashes_are_rejected_fail_closed(source_context):
    cases = [
        ("expected_task_outcome_sha256", "Stage-3.6.1 task outcome SHA-256"),
        ("expected_eligibility_gate_sha256", "Stage-3.6.2 eligibility gate SHA-256"),
        ("expected_result_capture_sha256", "Stage-3.5.7 result capture SHA-256"),
    ]
    for idx, (field, message) in enumerate(cases):
        body = deepcopy(source_context["body"])
        body["idempotency_key"] = f"binding-stale-hash-{idx}"
        body[field] = "0" * 64
        with pytest.raises(MissionConcurrencyConflict, match=message):
            source_context["service"].verify_task_evidence_binding(source_context["mission_id"], body)


def test_09_missing_stage357_361_or_362_source_artifact_fails_closed(source_context):
    cases = [
        ("expected_task_outcome_id", "toutcome-00000000-0000-0000-0000-000000000000", "task outcome is missing"),
        ("expected_eligibility_gate_id", "telig-00000000-0000-0000-0000-000000000000", "eligibility gate is missing"),
        ("expected_result_capture_id", "xresult-00000000-0000-0000-0000-000000000000", "result capture is missing"),
    ]
    for idx, (field, value, message) in enumerate(cases):
        body = deepcopy(source_context["body"])
        body["idempotency_key"] = f"binding-missing-{idx}"
        body[field] = value
        with pytest.raises(MissionTaskEvidenceBindingGuardRejected, match=message):
            source_context["service"].verify_task_evidence_binding(source_context["mission_id"], body)


def test_10_caller_supplied_evidence_acceptance_completion_or_side_effect_fields_are_forbidden(source_context):
    forbidden = [
        ("evidence", [{"id": "caller"}]),
        ("artifact_manifest", {}),
        ("completion_eligible", True),
        ("task_outcome_accepted", True),
        ("task_completed", True),
        ("dependency_release", True),
        ("mission_completed", True),
        ("runtime_action", "resume"),
        ("governance_decision", "ALLOW"),
    ]
    for idx, (field, value) in enumerate(forbidden):
        body = deepcopy(source_context["body"])
        body["idempotency_key"] = f"binding-forbidden-{idx}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported task evidence-binding verification field"):
            source_context["service"].verify_task_evidence_binding(source_context["mission_id"], body)


def test_11_same_request_is_idempotent_without_duplicate_verification_or_event(verified_context):
    service, mission_id = verified_context["service"], verified_context["mission_id"]
    first = verified_context["created"]
    replay = service.verify_task_evidence_binding(mission_id, deepcopy(verified_context["body"]))
    assert replay["idempotent_replay"] is True
    assert replay["verification_id"] == first["verification_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_task_evidence_binding_verification_history(mission_id)["verification_count"] == 1
    events = service.get_mission_events(mission_id)["events"]
    assert len([e for e in events if e["event_type"] == EVENT_TYPE]) == 1


def test_12_same_idempotency_key_with_different_request_conflicts(verified_context):
    body = deepcopy(verified_context["body"])
    body["reason"] = "different canonical Stage-3.6.3 request"
    with pytest.raises(MissionTaskEvidenceBindingConflict, match="idempotency_key"):
        verified_context["service"].verify_task_evidence_binding(verified_context["mission_id"], body)


def test_13_only_one_immutable_verification_is_allowed_per_stage362_gate(verified_context):
    body = deepcopy(verified_context["body"])
    body["idempotency_key"] = "evidence-binding-second363"
    body["reason"] = "second verification attempt for same immutable gate"
    with pytest.raises(MissionTaskEvidenceBindingConflict, match="already has an immutable"):
        verified_context["service"].verify_task_evidence_binding(verified_context["mission_id"], body)


def test_14_verification_and_replay_do_not_contact_runtime_or_governance(verified_context):
    assert verified_context["gov_after"] == verified_context["gov_before"]
    assert verified_context["runtime_after"] == verified_context["runtime_before"]
    service, governance, runtime = verified_context["service"], verified_context["governance"], verified_context["runtime"]
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    replay = service.verify_task_evidence_binding(verified_context["mission_id"], deepcopy(verified_context["body"]))
    assert governance.evaluate_calls == gov_before
    assert (runtime.health_calls, runtime.result_calls, runtime.control_calls) == runtime_before
    assert replay["external_network_io_performed"] is False
    assert replay["target_actuation"] is False


def test_15_restart_reads_same_immutable_verification_from_durable_repository(verified_context):
    service, mission_id, created = verified_context["service"], verified_context["mission_id"], verified_context["created"]
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=service.repository.sqlite_path))
    fetched = restarted.get_task_evidence_binding_verification(mission_id, created["verification_id"])
    assert fetched["verification_id"] == created["verification_id"]
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert verify_task_evidence_binding_verification_contract(fetched["task_evidence_binding_verification_contract"])
    assert fetched["evidence_binding_verified"] is True
    assert fetched["task_completion_commit_performed"] is False


def test_16_lineage_event_is_exactly_once_and_causally_bound_to_verification(verified_context):
    service, mission_id, created = verified_context["service"], verified_context["mission_id"], verified_context["created"]
    selected = [e for e in service.get_mission_events(mission_id)["events"] if e["event_type"] == EVENT_TYPE]
    assert len(selected) == 1
    event = selected[0]
    assert event["causation_id"] == created["verification_id"]
    assert event["payload"]["verification_id"] == created["verification_id"]
    assert event["payload"]["task_outcome_id"] == created["task_outcome_id"]
    assert event["payload"]["eligibility_gate_id"] == created["eligibility_gate_id"]
    assert event["payload"]["result_capture_id"] == created["result_capture_id"]
    assert event["payload"]["canonical_sha256"] == created["canonical_sha256"]
    assert event["payload"]["evidence_content_dereferenced"] is False
    assert event["payload"]["task_completion_commit_performed"] is False


def test_17_repository_projection_persists_verification_and_passes_integrity(verified_context):
    service, mission_id, created = verified_context["service"], verified_context["mission_id"], verified_context["created"]
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_task_evidence_binding_verifications"] == 1
    refs = repo["persistence_manifest"]["task_evidence_binding_verification_store"]["verifications"]
    assert refs[0]["verification_id"] == created["verification_id"]
    assert refs[0]["eligibility_gate_id"] == created["eligibility_gate_id"]
    checks = {item["check"]: item for item in repo["integrity_checks"]}
    assert checks["task_evidence_binding_verification_store"]["status"] == "PASS"


def test_18_persisted_verification_tampering_breaks_repository_integrity(tmp_path):
    ctx = provision_source(tmp_path, "tamper363")
    created = ctx["service"].verify_task_evidence_binding(ctx["mission_id"], deepcopy(ctx["body"]))
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as conn:
        conn.execute(
            "UPDATE mission_task_evidence_binding_verifications SET evidence_binding_verified=? WHERE verification_id=?",
            (0, created["verification_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        ctx["service"].get_mission_repository(ctx["mission_id"])


def test_19_api_routes_migration_definition_and_history_are_registered(verified_context):
    service, mission_id, created = verified_context["service"], verified_context["mission_id"], verified_context["created"]
    fetched = service.get_task_evidence_binding_verification(mission_id, created["verification_id"])
    history = service.get_task_evidence_binding_verification_history(mission_id)
    definition = service.get_task_evidence_binding_verification_definition(mission_id)
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert history["verification_count"] == 1
    assert definition["registered_verification_count"] == 1
    api_source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "task-evidence-binding-verifications" in api_source
    assert "task-evidence-binding-verification-definition" in api_source
    migration = Path("migrations/038_stage3_6_3_evidence_binding_verification.sql")
    assert migration.is_file()
    migration_text = migration.read_text(encoding="utf-8")
    assert "mission_task_evidence_binding_verifications" in migration_text
    assert "UNIQUE" in migration_text.upper()


def test_20_manifest_binding_derivation_is_deterministic_reference_only_and_fail_closed(source_context):
    outcome = source_context["task_outcome"]
    gate = source_context["gate"]
    result = source_context["result_capture"]
    first = derive_evidence_binding_verification(task_outcome=outcome, eligibility_gate=gate, result_capture=result)
    second = derive_evidence_binding_verification(task_outcome=outcome, eligibility_gate=gate, result_capture=result)
    assert first == second
    assert first["evidence_binding_verified"] is True
    assert first["artifact_binding_verified"] is True
    assert first["reference_only_manifest_verified"] is True
    assert first["evidence_content_dereferenced"] is False
    assert first["artifact_content_dereferenced"] is False
    assert first["external_content_hash_recomputed"] is False
    assert set(TASK_EVIDENCE_BINDING_ALLOWED_MISSION_STATES) == {"RUNNING", "FAILED", "ABORTED"}

    noneligible_gate = deepcopy(gate)
    noneligible_gate["completion_eligible"] = False
    with pytest.raises(MissionValidationError, match="completion-eligible"):
        derive_evidence_binding_verification(task_outcome=outcome, eligibility_gate=noneligible_gate, result_capture=result)

    tampered_result = deepcopy(result)
    tampered_result["execution_result_capture_contract"]["evidence_manifest"]["items"][0]["sha256"] = "0" * 64
    with pytest.raises(MissionValidationError, match="result capture contract failed integrity"):
        derive_evidence_binding_verification(task_outcome=outcome, eligibility_gate=gate, result_capture=tampered_result)
