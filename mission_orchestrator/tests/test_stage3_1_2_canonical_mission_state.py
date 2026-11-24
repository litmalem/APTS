from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionIllegalTransition, MissionStateConflict
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.state_model import CANONICAL_STATES, TERMINAL_STATES


def payload(key="stage312-001"):
    return {
        "idempotency_key": key,
        "source_system": "STAGE312_TEST",
        "created_by": "stage3.1.2-test",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab-target-01"},
        "success_criteria": [{"metric": "authorized_goal_complete", "expected": True}],
        "budgets": {"time_seconds": 1800, "max_actions": 20, "risk_ceiling": "MEDIUM"},
        "required_subsystems": ["CTI", "PENTEST"],
        "scope_contract_id": "scope-stage312-001",
        "scope_version": 1,
        "roe_version": "1",
        "pip_id": "pip-stage312-001",
        "pip_version": "1",
        "policy_version": "1",
        "metadata": {"environment": "LAB"},
    }


def service(tmp_path: Path):
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo)


def create(svc: CanonicalMissionService, key="stage312-001") -> str:
    return svc.create_mission(payload(key))["canonical_identity"]["mission_id"]


def transition(svc: CanonicalMissionService, mission_id: str, version: int, to_state: str, code: str):
    return svc.transition_mission_state(
        mission_id,
        {
            "expected_state_version": version,
            "to_state": to_state,
            "actor": "stage3.1.2-test",
            "reason_code": code,
            "reason": f"transition to {to_state}",
            "evidence_refs": [f"evidence:{code.lower()}"],
            "metadata": {"test": True},
        },
    )


def test_new_mission_has_separate_created_state_version_one(tmp_path):
    svc = service(tmp_path)
    mission_id = create(svc)
    result = svc.get_mission_state(mission_id)
    state = result["mission_state"]

    assert state["state"] == "CREATED"
    assert state["state_version"] == 1
    assert state["terminal"] is False
    assert state["last_transition_id"] is None
    assert "PIP_BOUND" in result["allowed_transitions"]
    assert "FAILED" in result["allowed_transitions"]


def test_canonical_happy_path_increments_state_version_and_appends_history(tmp_path):
    svc = service(tmp_path)
    mission_id = create(svc, "stage312-happy")
    version = 1
    path = [
        ("PIP_BOUND", "PIP_BOUND_CONFIRMED"),
        ("PLANNING", "PLANNING_STARTED"),
        ("RUNNING", "EXECUTION_STARTED"),
        ("WAITING_APPROVAL", "APPROVAL_REQUIRED"),
        ("RUNNING", "APPROVAL_RESOLVED"),
        ("REPLANNING", "REPLAN_REQUIRED"),
        ("RUNNING", "REPLAN_COMMITTED"),
        ("CLEANING_UP", "FINALIZATION_STARTED"),
        ("COMPLETED", "MISSION_GOAL_COMPLETE"),
    ]

    for expected_index, (target, code) in enumerate(path, start=1):
        result = transition(svc, mission_id, version, target, code)
        version += 1
        assert result["mission_state"]["state"] == target
        assert result["mission_state"]["state_version"] == version
        assert result["transition"]["from_state_version"] == version - 1
        assert result["transition"]["to_state_version"] == version
        assert result["transition"]["to_state"] == target
        assert result["transition"]["reason_code"] == code
        assert expected_index == len(svc.get_mission_state_history(mission_id)["transitions"])

    final = svc.get_mission_state(mission_id)["mission_state"]
    assert final["state"] == "COMPLETED"
    assert final["terminal"] is True
    assert svc.get_mission_state_history(mission_id)["transition_count"] == len(path)


def test_illegal_transition_is_rejected_without_state_mutation(tmp_path):
    svc = service(tmp_path)
    mission_id = create(svc, "stage312-illegal")

    with pytest.raises(MissionIllegalTransition, match="CREATED -> RUNNING"):
        transition(svc, mission_id, 1, "RUNNING", "BYPASS_ATTEMPT")

    state = svc.get_mission_state(mission_id)["mission_state"]
    assert state["state"] == "CREATED"
    assert state["state_version"] == 1
    assert svc.get_mission_state_history(mission_id)["transition_count"] == 0


def test_optimistic_version_check_rejects_stale_update(tmp_path):
    svc = service(tmp_path)
    mission_id = create(svc, "stage312-stale")
    transition(svc, mission_id, 1, "PIP_BOUND", "PIP_BOUND_CONFIRMED")

    with pytest.raises(MissionStateConflict, match="expected_state_version=1"):
        transition(svc, mission_id, 1, "PLANNING", "STALE_WRITER")

    state = svc.get_mission_state(mission_id)["mission_state"]
    assert state["state"] == "PIP_BOUND"
    assert state["state_version"] == 2


def test_terminal_state_has_no_outgoing_transition(tmp_path):
    svc = service(tmp_path)
    mission_id = create(svc, "stage312-terminal")
    version = 1
    for target, code in [
        ("PIP_BOUND", "PIP_BOUND_CONFIRMED"),
        ("PLANNING", "PLANNING_STARTED"),
        ("RUNNING", "EXECUTION_STARTED"),
        ("CLEANING_UP", "FINALIZATION_STARTED"),
        ("COMPLETED", "MISSION_GOAL_COMPLETE"),
    ]:
        transition(svc, mission_id, version, target, code)
        version += 1

    with pytest.raises(MissionIllegalTransition, match="terminal mission state COMPLETED"):
        transition(svc, mission_id, version, "RUNNING", "ILLEGAL_RESUME")

    result = svc.get_mission_state(mission_id)
    assert result["mission_state"]["state"] == "COMPLETED"
    assert result["allowed_transitions"] == []


@pytest.mark.parametrize("terminal_state", ["FAILED", "ABORTED", "EXPIRED"])
def test_fail_abort_expire_are_terminal_exits_from_active_state(tmp_path, terminal_state):
    svc = service(tmp_path)
    mission_id = create(svc, f"stage312-{terminal_state.lower()}")
    result = transition(svc, mission_id, 1, terminal_state, f"MISSION_{terminal_state}")
    assert result["mission_state"]["state"] == terminal_state
    assert result["mission_state"]["terminal"] is True
    assert result["allowed_transitions"] == []


def test_reopen_repository_preserves_state_and_history(tmp_path):
    db = tmp_path / "persistent-state.db"
    first = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    mission_id = create(first, "stage312-persist")
    transition(first, mission_id, 1, "PIP_BOUND", "PIP_BOUND_CONFIRMED")
    transition(first, mission_id, 2, "PLANNING", "PLANNING_STARTED")

    second = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    state = second.get_mission_state(mission_id)["mission_state"]
    history = second.get_mission_state_history(mission_id)
    assert state["state"] == "PLANNING"
    assert state["state_version"] == 3
    assert history["transition_count"] == 2
    assert [item["to_state"] for item in history["transitions"]] == ["PIP_BOUND", "PLANNING"]


def test_state_transition_does_not_mutate_immutable_envelope(tmp_path):
    svc = service(tmp_path)
    created = svc.create_mission(payload("stage312-envelope"))
    mission_id = created["canonical_identity"]["mission_id"]
    before = svc.get_envelope(mission_id)["envelope"]

    transition(svc, mission_id, 1, "PIP_BOUND", "PIP_BOUND_CONFIRMED")
    transition(svc, mission_id, 2, "PLANNING", "PLANNING_STARTED")

    after = svc.get_envelope(mission_id)["envelope"]
    assert after == before
    assert after["integrity"]["canonical_sha256"] == before["integrity"]["canonical_sha256"]



def test_stage311_existing_mission_is_backfilled_to_created_without_envelope_mutation(tmp_path):
    import sqlite3

    db = tmp_path / "legacy-stage311.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE global_missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT NOT NULL UNIQUE,
            source_system TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            client_request_id TEXT NULL,
            client_mission_ref TEXT NULL,
            correlation_id TEXT NOT NULL,
            parent_mission_id TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(source_system, idempotency_key)
        );
        CREATE TABLE mission_envelopes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            envelope_id TEXT NOT NULL UNIQUE,
            mission_id TEXT NOT NULL,
            envelope_version INTEGER NOT NULL,
            schema_version TEXT NOT NULL,
            canonical_sha256 TEXT NOT NULL,
            canonical_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(mission_id, envelope_version)
        );
        """
    )
    conn.execute(
        """INSERT INTO global_missions
        (mission_id, source_system, idempotency_key, request_sha256, correlation_id, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "mission-gmo-legacy", "LEGACY", "legacy-1", "a" * 64,
            "corr-legacy", "stage3.1.1", "2026-09-02T01:00:00.000000Z",
        ),
    )
    conn.commit()
    conn.close()

    repo = MissionRepository(driver="sqlite", sqlite_path=str(db))
    state = repo.get_state("mission-gmo-legacy")
    assert state is not None
    assert state["state"] == "CREATED"
    assert state["state_version"] == 1
    assert state["last_reason_code"] == "MISSION_REGISTERED"

def test_health_exposes_state_model_but_keeps_execution_boundary_closed(tmp_path):
    health = service(tmp_path).health()
    assert "stage3.1.2-canonical-mission-state-model" in health["supported_controls"]
    assert health["mission_state_mode"] == "CANONICAL_VERSIONED_OPTIMISTIC_CONCURRENCY"
    assert set(health["canonical_states"]) == set(CANONICAL_STATES)
    assert set(health["terminal_states"]) == set(TERMINAL_STATES)
    assert health["dispatch_enabled"] is False
    assert health["target_actuation"] is False
