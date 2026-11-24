from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionPlannerInputSnapshotConflict,
    MissionPlannerInputSnapshotGuardRejected,
    MissionPlannerInputSnapshotNotFound,
    MissionValidationError,
)
from mission_orchestrator.planner_input_snapshot import (
    PLANNER_INPUT_CONTEXT_MODE,
    PLANNER_INPUT_SNAPSHOT_HASH_DOMAIN,
    PLANNER_INPUT_SNAPSHOT_MODE,
    PLANNER_INPUT_SNAPSHOT_SCHEMA_VERSION,
    PLANNER_INPUT_SNAPSHOT_VERSION_INITIAL,
    verify_planner_input_snapshot,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService


class NoExternalClient:
    base_url = "disabled://stage3.3.2"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.3.2 snapshot must remain local-only: unexpected external call {name}")


def make_service(db: Path) -> CanonicalMissionService:
    client = NoExternalClient()
    return CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=client,
        cti_client=client,
    )


def mission_payload(key: str) -> dict:
    return {
        "idempotency_key": f"stage332-mission-{key}",
        "source_system": "STAGE332_PYTEST",
        "created_by": "stage3.3.2-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage332-lab"},
        "success_criteria": [
            {"metric": "planner_context_bound", "expected": True},
            {"metric": "no_authority_expansion", "expected": True},
        ],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-stage332-{key}",
        "pip_version": "16",
        "metadata": {"environment": "LAB", "stage": "3.3.2"},
    }


def create_mission(service: CanonicalMissionService, key: str) -> str:
    return service.create_mission(mission_payload(key))["canonical_identity"]["mission_id"]


def lifecycle_request(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "command_id": f"lc-332-{token}",
        "idempotency_key": f"idem-lc-332-{token}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.3.2-pytest",
        "reason_code": f"STAGE332_{command}",
        "reason": f"Stage 3.3.2 prerequisite command {command}",
        "evidence_refs": [f"evidence:stage332:{token}"],
        "metadata": {"stage": "3.3.2", "token": token},
    }


def execute(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    return service.execute_mission_lifecycle_command(
        mission_id, lifecycle_request(service, mission_id, command, token)
    )


def activate_planning(service: CanonicalMissionService, mission_id: str, token: str) -> None:
    execute(service, mission_id, "BIND_PIP", f"bind-{token}")
    execute(service, mission_id, "START_PLANNING", f"planning-{token}")


def plan_request(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "idempotency_key": f"stage332-plan-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.2-pytest",
        "reason": "Register Stage-3.3.1 canonical Plan prerequisite",
        "metadata": {"stage": "3.3.2", "prerequisite": "3.3.1"},
    }


def register_plan(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    return service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, key))


def snapshot_request(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    plan = service.get_mission_plan_contract(mission_id)
    return {
        "idempotency_key": f"stage332-snapshot-{key}",
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": plan["plan_version"],
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.2-pytest",
        "reason": "Freeze deterministic planner input from canonical local context",
        "metadata": {"stage": "3.3.2", "key": key},
    }


def scope_payload(key: str, expected: int = 0, max_actions: int = 10) -> dict:
    return {
        "expected_contract_version": expected,
        "idempotency_key": f"stage332-scope-{key}",
        "actor": "stage3.3.2-pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [],
            "network_ranges": ["127.0.0.0/8"],
            "domains": ["lab.example.test"],
            "services": [{"name": "https", "protocol": "TCP", "port": 443, "target_ref": "lab.example.test"}],
        },
        "roe": {
            "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": ["VULNERABILITY_VALIDATION"],
        },
        "constraints": {
            "max_actions": max_actions,
            "max_duration": 1200,
            "risk_threshold": "LOW",
            "resource_budget": {"max_network_requests": 100},
            "data_handling_policy": {"classification": "INTERNAL"},
        },
        "reason": "Stage 3.3.2 planner context scope",
        "metadata": {"stage": "3.3.2"},
    }


def provision_plan(service: CanonicalMissionService, key: str, *, with_scope: bool = False) -> tuple[str, dict]:
    mission_id = create_mission(service, key)
    if with_scope:
        service.put_mission_scope_contract(mission_id, scope_payload(key))
    activate_planning(service, mission_id, key)
    return mission_id, register_plan(service, mission_id, key)


def test_health_activates_stage332_without_planner_or_authority_expansion(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
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
    assert health["planner_input_snapshot_schema_version"] == PLANNER_INPUT_SNAPSHOT_SCHEMA_VERSION
    assert health["planner_input_snapshot_mode"] == PLANNER_INPUT_SNAPSHOT_MODE
    assert health["planner_input_snapshot_context_mode"] == PLANNER_INPUT_CONTEXT_MODE
    assert health["planner_input_snapshot_initial_version"] == 1
    assert health["planner_input_snapshot_requires_stage3_3_1_plan_contract"] is True
    assert health["planner_input_snapshot_local_durable_context_only"] is True
    assert health["planner_input_snapshot_external_context_refresh_performed"] is False
    assert health["planner_input_snapshot_planner_input_ready"] is True
    assert health["planner_input_snapshot_planner_invocation_performed"] is False
    assert health["planner_input_snapshot_plan_synthesis_performed"] is False
    assert health["planner_input_snapshot_task_decomposition_performed"] is False
    assert health["planner_input_snapshot_snapshot_is_authorization"] is False
    assert health["planner_input_snapshot_context_is_permission"] is False
    assert health["planner_input_snapshot_planner_is_governance"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False
    assert health["mission_repository_migration_level"] == 53
    assert REPOSITORY_MIGRATION_LEVEL == 53


def test_snapshot_definition_is_discoverable_before_plan_or_snapshot(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "definition")
    result = service.get_planner_input_snapshot_definition(mission_id)
    definition = result["planner_input_snapshot_definition"]
    assert result["plan_registered"] is False
    assert result["snapshot_registered"] is False
    assert definition["schema_version"] == PLANNER_INPUT_SNAPSHOT_SCHEMA_VERSION
    assert definition["creation_state_required"] == "PLANNING"
    assert definition["requires_stage3_3_1_plan_contract"] is True
    assert definition["caller_supplied_planner_content_allowed"] is False
    assert definition["planner_invocation_performed"] is False
    assert definition["plan_synthesis_performed"] is False
    assert definition["snapshot_is_authorization"] is False


def test_snapshot_registration_fails_closed_without_stage331_plan(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "no-plan")
    activate_planning(service, mission_id, "no-plan")
    with pytest.raises(MissionPlannerInputSnapshotGuardRejected, match="Stage-3.3.1"):
        service.create_planner_input_snapshot(
            mission_id,
            {
                "idempotency_key": "stage332-no-plan",
                "expected_plan_id": "mplan-missing",
                "expected_plan_version": 1,
                "expected_plan_sha256": "0" * 64,
                "expected_state_version": service.get_mission_state(mission_id)["mission_state"]["state_version"],
                "created_by": "stage3.3.2-pytest",
                "metadata": {},
            },
        )
    with pytest.raises(MissionPlannerInputSnapshotNotFound):
        service.get_planner_input_snapshot(mission_id)


def test_snapshot_is_immutable_hashed_and_bound_to_exact_plan_state_pip_and_activation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, plan = provision_plan(service, "canonical")
    before = service.get_mission_version_vector(mission_id)
    assert before["version_vector"]["versions"]["planner_input_snapshot_version"] == 0

    result = service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, "canonical"))
    snapshot = result["planner_input_snapshot"]
    assert result["idempotent_replay"] is False
    assert result["snapshot_id"].startswith("mpis-")
    assert result["snapshot_version"] == PLANNER_INPUT_SNAPSHOT_VERSION_INITIAL
    assert result["plan_id"] == plan["plan_id"]
    assert result["source_plan_sha256"] == plan["canonical_sha256"]
    assert snapshot["identity"]["mission_id"] == mission_id
    assert snapshot["identity"]["plan_id"] == plan["plan_id"]
    assert snapshot["plan_binding"]["plan_sha256"] == plan["canonical_sha256"]
    assert snapshot["plan_binding"]["task_graph_status"] == "NOT_MATERIALIZED"
    assert snapshot["lifecycle_context"]["state"] == "PLANNING"
    assert snapshot["lifecycle_context"]["stage3_2_4_activation_evidence"]["activation_ready"] is True
    assert snapshot["knowledge_context"]["pip_id"] == f"pip-stage332-canonical"
    assert snapshot["knowledge_context"]["pip_version"] == "16"
    assert snapshot["context_binding"]["fact_policy"] == "CANONICAL_DURABLE_LOCAL_FACTS_ONLY"
    assert snapshot["semantics"]["planner_input_ready"] is True
    assert snapshot["semantics"]["planner_invocation_performed"] is False
    assert snapshot["semantics"]["plan_synthesis_performed"] is False
    assert snapshot["semantics"]["task_decomposition_performed"] is False
    assert snapshot["semantics"]["snapshot_is_authorization"] is False
    assert snapshot["semantics"]["context_is_permission"] is False
    assert snapshot["semantics"]["target_action_dispatch_enabled"] is False
    assert snapshot["integrity"]["hash_domain"] == PLANNER_INPUT_SNAPSHOT_HASH_DOMAIN
    assert verify_planner_input_snapshot(snapshot)


def test_exact_retry_is_idempotent_and_does_not_duplicate_snapshot_or_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "replay")
    request = snapshot_request(service, mission_id, "replay")
    first = service.create_planner_input_snapshot(mission_id, request)
    events_after_first = service.get_mission_events(mission_id)["event_count"]
    second = service.create_planner_input_snapshot(mission_id, request)
    events_after_second = service.get_mission_events(mission_id)["event_count"]
    assert second["idempotent_replay"] is True
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]
    assert events_after_second == events_after_first
    assert service.repository.get_repository_record_counts(mission_id)["mission_planner_input_snapshots"] == 1


def test_idempotency_conflict_and_second_snapshot_are_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "conflict")
    request = snapshot_request(service, mission_id, "same-key")
    service.create_planner_input_snapshot(mission_id, request)

    changed = dict(request)
    changed["metadata"] = {"changed": True}
    with pytest.raises(MissionPlannerInputSnapshotConflict, match="idempotency_key"):
        service.create_planner_input_snapshot(mission_id, changed)

    fresh = dict(request)
    fresh["idempotency_key"] = "stage332-second-snapshot"
    with pytest.raises(MissionPlannerInputSnapshotConflict, match="already exists"):
        service.create_planner_input_snapshot(mission_id, fresh)


def test_exact_plan_identity_version_hash_and_state_tokens_fail_closed_when_stale(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "stale")
    request = snapshot_request(service, mission_id, "stale")

    cases = [
        ("expected_plan_id", "mplan-wrong"),
        ("expected_plan_version", 2),
        ("expected_plan_sha256", "0" * 64),
        ("expected_state_version", int(request["expected_state_version"]) + 1),
    ]
    for field, value in cases:
        bad = dict(request)
        bad[field] = value
        bad["idempotency_key"] = f"stage332-stale-{field}"
        with pytest.raises(MissionConcurrencyConflict):
            service.create_planner_input_snapshot(mission_id, bad)


def test_snapshot_cannot_be_created_after_plan_source_planning_state_has_advanced(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "advanced")
    execute(service, mission_id, "START", "start-advanced")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"
    plan = service.get_mission_plan_contract(mission_id)
    with pytest.raises(MissionPlannerInputSnapshotGuardRejected, match="PLANNING"):
        service.create_planner_input_snapshot(
            mission_id,
            {
                "idempotency_key": "stage332-after-running",
                "expected_plan_id": plan["plan_id"],
                "expected_plan_version": plan["plan_version"],
                "expected_plan_sha256": plan["canonical_sha256"],
                "expected_state_version": service.get_mission_state(mission_id)["mission_state"]["state_version"],
                "created_by": "stage3.3.2-pytest",
                "metadata": {},
            },
        )


def test_request_surface_rejects_planner_tasks_authorization_and_dispatch_content(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "surface")
    base = snapshot_request(service, mission_id, "surface")
    for field, value in (
        ("tasks", [{"task_id": "not-allowed"}]),
        ("dependencies", []),
        ("planner_output", {"steps": []}),
        ("authorization", {"decision": "ALLOW"}),
        ("dispatch", {"target": "lab"}),
    ):
        invalid = dict(base)
        invalid[field] = value
        with pytest.raises(MissionValidationError, match="unsupported planner-input-snapshot"):
            service.create_planner_input_snapshot(mission_id, invalid)


def test_snapshot_embeds_exact_plan_bound_scope_contract_and_constraints(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "scope", with_scope=True)
    result = service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, "scope"))
    scope = result["planner_input_snapshot"]["scope_context"]
    assert scope["binding_status"] == "BOUND"
    assert scope["scope_version"] == 1
    assert scope["scope_contract"]["constraints"]["max_actions"] == 10
    assert scope["scope_contract"]["roe"]["destructive_actions_allowed"] is False
    assert scope["scope_sha256"] == scope["scope_contract"]["integrity"]["canonical_sha256"]


def test_scope_drift_after_plan_registration_blocks_snapshot(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "scope-drift", with_scope=True)
    revised = scope_payload("scope-drift-v2", expected=1, max_actions=5)
    service.put_mission_scope_contract(mission_id, revised)
    with pytest.raises(MissionPlannerInputSnapshotGuardRejected, match="Scope changed"):
        service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, "scope-drift"))


def test_snapshot_integrity_rejects_tampering(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "tamper")
    snapshot = service.create_planner_input_snapshot(
        mission_id, snapshot_request(service, mission_id, "tamper")
    )["planner_input_snapshot"]
    assert verify_planner_input_snapshot(snapshot)
    tampered = {**snapshot, "mission_context": dict(snapshot["mission_context"])}
    tampered["mission_context"]["budgets"] = {"time_seconds": 999999}
    assert verify_planner_input_snapshot(tampered) is False


def test_version_vector_advances_planner_input_snapshot_domain_only_after_registration(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_plan(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    assert before["version_vector"]["versions"]["mission_plan_version"] == 1
    assert before["version_vector"]["versions"]["planner_input_snapshot_version"] == 0
    service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, "vector"))
    after = service.get_mission_version_vector(mission_id)
    assert after["version_vector"]["versions"]["mission_plan_version"] == 1
    assert after["version_vector"]["versions"]["planner_input_snapshot_version"] == 1
    assert after["version_sha256"] != before["version_sha256"]


def test_snapshot_event_repository_manifest_and_integrity_projection_are_canonical(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, plan = provision_plan(service, "repo")
    result = service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, "repo"))

    events = service.get_mission_events(mission_id)
    snapshot_events = [x for x in events["events"] if x["event_type"] == "MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED"]
    assert len(snapshot_events) == 1
    assert snapshot_events[0]["causation_id"] == result["snapshot_id"]
    assert snapshot_events[0]["plan_version"] == "1"

    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert "mission_planner_input_snapshots" in repo["repository"]["stores"]
    assert repo["record_counts"]["mission_plans"] == 1
    assert repo["record_counts"]["mission_planner_input_snapshots"] == 1
    manifest = repo["persistence_manifest"]
    assert manifest["mission_plan_store"]["plan_id"] == plan["plan_id"]
    assert manifest["planner_input_snapshot_store"]["snapshot_id"] == result["snapshot_id"]
    assert manifest["planner_input_snapshot_store"]["source_plan_sha256"] == plan["canonical_sha256"]
    assert any(x["check"] == "planner_input_snapshot_store" and x["status"] == "PASS" for x in repo["integrity_checks"])


def test_restart_reconstructs_snapshot_without_external_reads(tmp_path):
    db = tmp_path / "missions.db"
    first = make_service(db)
    mission_id, _ = provision_plan(first, "restart", with_scope=True)
    created = first.create_planner_input_snapshot(mission_id, snapshot_request(first, mission_id, "restart"))

    restarted = make_service(db)
    restored = restarted.get_planner_input_snapshot(mission_id)
    repo = restarted.get_mission_repository(mission_id)
    assert restored["snapshot_id"] == created["snapshot_id"]
    assert restored["canonical_sha256"] == created["canonical_sha256"]
    assert verify_planner_input_snapshot(restored["planner_input_snapshot"])
    assert repo["integrity_status"] == "PASS"


def test_migration_010_declares_snapshot_store_context_boundary_and_level_10():
    sql = Path("migrations/010_stage3_3_2_planner_input_snapshot_context_binding.sql").read_text().lower()
    assert "create table if not exists mission_planner_input_snapshots" in sql
    assert "unique key uq_mission_planner_input_snapshot_plan" in sql
    assert "snapshot_id" in sql and "snapshot_version" in sql and "source_plan_sha256" in sql
    assert "foreign key (plan_id) references mission_plans(plan_id)" in sql
    assert "no external context refresh" in sql
    assert "planner invocation" in sql and "task" in sql
    assert "snapshot != authorization" in sql
    assert "planner != governance" in sql
    assert "    10," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
