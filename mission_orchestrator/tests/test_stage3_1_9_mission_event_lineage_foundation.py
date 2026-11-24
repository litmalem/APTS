from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionEventIntegrityError,
    MissionEventNotFound,
    MissionRepositoryIntegrityError,
)
from mission_orchestrator.mission_events import (
    CANONICAL_EVENT_TYPES,
    MISSION_EVENT_MODE,
    MISSION_EVENT_SCHEMA_VERSION,
    MISSION_EVENT_SOURCE_COMPONENT,
    MISSION_LINEAGE_MODE,
    MISSION_LINEAGE_SCHEMA_VERSION,
    verify_event,
    verify_event_chain,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, verify_persistence_manifest
from mission_orchestrator.service import CanonicalMissionService


class NoCallGovernance:
    base_url = "fake://governance-no-call"

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def fail(*args, **kwargs):
            self.calls += 1
            raise AssertionError(f"Stage 3.1.9 local event/lineage reads must not call Governance: {name}")

        return fail


class NoCallCti:
    base_url = "fake://cti-no-call"

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def fail(*args, **kwargs):
            self.calls += 1
            raise AssertionError(f"Stage 3.1.9 local event/lineage reads must not call CTI: {name}")

        return fail


def mission_payload(key: str = "mission-319"):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST",
        "created_by": "stage3.1.9-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab-target"},
        "success_criteria": [{"metric": "lineage_valid", "expected": True}],
        "budgets": {"time_seconds": 1800},
        "required_subsystems": ["CTI", "PENTEST"],
        "metadata": {"environment": "LAB", "stage": "3.1.9"},
    }


def transition_payload(expected: int, to_state: str):
    return {
        "expected_state_version": expected,
        "to_state": to_state,
        "actor": "stage3.1.9-pytest",
        "reason_code": f"MOVE_TO_{to_state}",
        "reason": "Stage 3.1.9 lineage test",
        "evidence_refs": [],
        "metadata": {"stage": "3.1.9"},
    }


def scope_payload(key: str = "scope-319"):
    return {
        "expected_contract_version": 0,
        "idempotency_key": key,
        "actor": "stage3.1.9-pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [],
            "network_ranges": ["127.0.0.0/8"],
            "domains": [],
            "services": [],
        },
        "roe": {
            "allowed_action_classes": ["INTERNAL_REASONING", "TARGET_RECON"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "allowed_time_window": {
                "start_at": "2026-09-01T00:00:00Z",
                "end_at": "2030-09-03T00:00:00Z",
            },
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": [],
        },
        "constraints": {
            "max_actions": 20,
            "max_duration": 1800,
            "risk_threshold": "MODERATE",
            "resource_budget": {"max_network_requests": 500},
            "data_handling_policy": {
                "classification": "INTERNAL",
                "retention_days": 7,
                "export_allowed": False,
            },
        },
        "reason": "Stage 3.1.9 event hook test",
        "metadata": {"environment": "LAB", "stage": "3.1.9"},
    }


def make_service(db_path: Path):
    gov = NoCallGovernance()
    cti = NoCallCti()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(db_path))
    return CanonicalMissionService(repo, governance_client=gov, cti_client=cti), gov, cti


def create_mission(svc: CanonicalMissionService, key: str = "mission-319"):
    created = svc.create_mission(mission_payload(key))
    return created["canonical_identity"]["mission_id"], created


def test_stage319_health_advertises_event_lineage_foundation_without_new_execution_authority(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    health = svc.health()

    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert "stage3.1.8-canonical-mission-api-validation-layer" in health["supported_controls"]
    assert health["mission_repository_migration_level"] == 53
    assert health["mission_event_schema_version"] == MISSION_EVENT_SCHEMA_VERSION
    assert health["mission_lineage_schema_version"] == MISSION_LINEAGE_SCHEMA_VERSION
    assert health["mission_event_mode"] == MISSION_EVENT_MODE
    assert health["mission_lineage_mode"] == MISSION_LINEAGE_MODE
    assert health["mission_event_types"] == list(CANONICAL_EVENT_TYPES)
    assert health["mission_event_audit_hooks_enabled"] is True
    assert health["mission_event_external_delivery_enabled"] is False
    assert health["mission_event_external_authority_queries"] is False
    assert health["mission_event_historical_backfill_mode"] == "NO_SYNTHETIC_HISTORICAL_EVENTS"
    assert health["dispatch_enabled"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_registration_creates_root_event_with_all_required_identity_and_version_fields(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id, created = create_mission(svc)
    view = svc.get_mission_events(mission_id)

    assert view["event_count"] == 1
    assert view["history_complete_from_registration"] is True
    event = view["events"][0]
    required = {
        "event_id", "mission_id", "trace_id", "correlation_id", "causation_id",
        "parent_event_id", "source_component", "event_type", "state_version",
        "plan_version", "policy_version", "occurred_at",
    }
    assert required.issubset(event)
    assert event["event_type"] == "MISSION_REGISTERED"
    assert event["event_id"] == event["trace_id"]
    assert event["mission_id"] == mission_id
    assert event["correlation_id"] == created["canonical_identity"]["correlation_id"]
    assert event["causation_id"] == created["canonical_identity"]["envelope_id"]
    assert event["parent_event_id"] is None
    assert event["source_component"] == MISSION_EVENT_SOURCE_COMPONENT
    assert event["state_version"] == 1
    assert event["plan_version"] is None
    assert event["policy_version"] is None
    assert event["previous_event_sha256"] is None
    assert len(event["canonical_sha256"]) == 64
    assert verify_event(event) is True


def test_local_mutations_form_single_trace_parent_and_hash_chain(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id, created = create_mission(svc, "chain-319")
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    svc.put_mission_scope_contract(mission_id, scope_payload("chain-scope-319"))

    events = svc.get_mission_events(mission_id)["events"]
    assert [e["event_type"] for e in events] == [
        "MISSION_REGISTERED",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_SCOPE_CONTRACT_COMMITTED",
    ]
    ok, errors = verify_event_chain(events)
    assert ok is True, errors
    root = events[0]
    assert all(e["trace_id"] == root["event_id"] for e in events)
    assert all(e["correlation_id"] == created["canonical_identity"]["correlation_id"] for e in events)
    assert events[1]["parent_event_id"] == events[0]["event_id"]
    assert events[2]["parent_event_id"] == events[1]["event_id"]
    assert events[1]["previous_event_sha256"] == events[0]["canonical_sha256"]
    assert events[2]["previous_event_sha256"] == events[1]["canonical_sha256"]
    assert events[1]["state_version"] == 2
    assert events[2]["state_version"] == 2


def test_idempotent_create_and_scope_replay_do_not_duplicate_audit_events(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id, _ = create_mission(svc, "idem-319")
    replay = svc.create_mission(mission_payload("idem-319"))
    assert replay["idempotent_replay"] is True

    first_scope = svc.put_mission_scope_contract(mission_id, scope_payload("idem-scope-319"))
    second_scope = svc.put_mission_scope_contract(mission_id, scope_payload("idem-scope-319"))
    assert first_scope["idempotent_replay"] is False
    assert second_scope["idempotent_replay"] is True

    events = svc.get_mission_events(mission_id)["events"]
    assert [e["event_type"] for e in events].count("MISSION_REGISTERED") == 1
    assert [e["event_type"] for e in events].count("MISSION_SCOPE_CONTRACT_COMMITTED") == 1


def test_lineage_projection_is_local_read_only_and_exposes_causal_edges(tmp_path):
    svc, gov, cti = make_service(tmp_path / "missions.db")
    mission_id, _ = create_mission(svc, "lineage-319")
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    before = (gov.calls, cti.calls)

    lineage = svc.get_mission_lineage(mission_id)

    assert lineage["projection_schema_version"] == MISSION_LINEAGE_SCHEMA_VERSION
    assert lineage["event_count"] == 2
    assert lineage["causal_edge_count"] == 1
    assert lineage["upstream_edge_count"] == 0
    assert lineage["causal_edges"][0] == {
        "edge_type": "LOCAL_PARENT",
        "parent_event_id": lineage["events"][0]["event_id"],
        "child_event_id": lineage["events"][1]["event_id"],
    }
    assert lineage["integrity_status"] == "PASS"
    assert lineage["external_authority_query_performed"] is False
    assert lineage["target_action_dispatch_enabled"] is False
    assert lineage["target_actuation"] is False
    assert (gov.calls, cti.calls) == before


def test_no_synthetic_historical_backfill_and_first_post_upgrade_event_becomes_root(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id, _ = create_mission(svc, "legacy-319")

    # Simulate a mission that existed before Stage 3.1.9 by removing its newly-created
    # event row.  Schema initialization/reconstruction must not synthesize history.
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM mission_events WHERE mission_id=?", (mission_id,))
        conn.commit()

    reconstructed = CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db_path)),
        governance_client=NoCallGovernance(),
        cti_client=NoCallCti(),
    )
    assert reconstructed.get_mission_events(mission_id)["event_count"] == 0

    reconstructed.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    view = reconstructed.get_mission_events(mission_id)
    assert view["event_count"] == 1
    assert view["history_complete_from_registration"] is False
    event = view["events"][0]
    assert event["event_type"] == "MISSION_STATE_TRANSITIONED"
    assert event["event_id"] == event["trace_id"]
    assert event["parent_event_id"] is None


def test_repository_manifest_includes_event_store_and_event_count(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id, _ = create_mission(svc, "manifest-319")
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))

    repository = svc.get_mission_repository(mission_id)
    manifest = repository["persistence_manifest"]
    assert repository["record_counts"]["mission_events"] == 2
    assert len(manifest["mission_event_store"]) == 2
    assert [e["event_type"] for e in manifest["mission_event_store"]] == [
        "MISSION_REGISTERED", "MISSION_STATE_TRANSITIONED"
    ]
    assert verify_persistence_manifest(manifest) is True
    assert any(c["check"] == "mission_event_append_only_hash_chain" and c["status"] == "PASS"
               for c in repository["integrity_checks"])


def test_event_tampering_fails_closed_for_event_lineage_single_event_and_repository_reads(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id, _ = create_mission(svc, "tamper-319")
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    event_id = svc.get_mission_events(mission_id)["events"][1]["event_id"]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM mission_events WHERE event_id=?", (event_id,)).fetchone()
        payload = json.loads(row[0])
        payload["to_state"] = "TAMPERED"
        conn.execute(
            "UPDATE mission_events SET payload_json=? WHERE event_id=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), event_id),
        )
        conn.commit()

    with pytest.raises(MissionEventIntegrityError):
        svc.get_mission_events(mission_id)
    with pytest.raises(MissionEventIntegrityError):
        svc.get_mission_event(mission_id, event_id)
    with pytest.raises(MissionEventIntegrityError):
        svc.get_mission_lineage(mission_id)
    with pytest.raises(MissionRepositoryIntegrityError):
        svc.get_mission_repository(mission_id)


def test_single_event_read_returns_404_domain_error_for_unknown_event(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id, _ = create_mission(svc, "not-found-319")
    with pytest.raises(MissionEventNotFound):
        svc.get_mission_event(mission_id, "mevent-does-not-exist")


def test_migration_008_declares_required_event_fields_append_only_indexes_and_level_8():
    migration = Path("migrations/008_stage3_1_9_mission_event_lineage_foundation.sql").read_text().lower()
    assert "create table if not exists mission_events" in migration
    for field in (
        "event_id", "mission_id", "trace_id", "correlation_id", "causation_id",
        "parent_event_id", "source_component", "event_type", "state_version",
        "plan_version", "policy_version", "occurred_at",
    ):
        assert field in migration
    assert "unique key uq_mission_event_causation" in migration
    assert "previous_event_sha256" in migration
    assert "canonical_sha256" in migration
    assert "no event delivery bus" in migration
    assert "not synthesized into fake events" in migration
    assert "migration_level=values(migration_level)" in migration
    assert "    8," in migration
    assert REPOSITORY_MIGRATION_LEVEL == 53
