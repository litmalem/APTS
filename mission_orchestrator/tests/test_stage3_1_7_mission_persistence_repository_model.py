from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionRepositoryIntegrityError
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import (
    PERSISTENCE_MANIFEST_SCHEMA_VERSION,
    REPOSITORY_MIGRATION_LEVEL,
    REPOSITORY_MODEL,
    REPOSITORY_RECOVERY_MODE,
    REPOSITORY_SCHEMA_VERSION,
    verify_persistence_manifest,
)
from mission_orchestrator.service import CanonicalMissionService


class FakeGovernance:
    base_url = "fake://governance"

    def __init__(self):
        self.scopes = []
        self.requests = []
        self.decisions = []
        self.events = []
        self.create_calls = 0
        self.evaluate_calls = 0

    @staticmethod
    def _hash(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def create_scope_contract(self, payload):
        self.create_calls += 1
        row = {
            "scope_contract_id": f"scope-317-{self.create_calls}",
            "mission_id": payload["mission_id"],
            "name": payload.get("name"),
            "status": "ACTIVE",
            "policy_set_id": payload["policy_set_id"],
            "version": 1,
            "targets": list(payload.get("targets") or []),
            "sources": list(payload.get("sources") or []),
            "action_constraints": list(payload.get("action_constraints") or []),
            "metadata": dict(payload.get("metadata") or {}),
        }
        row["contract_hash"] = self._hash(row)
        self.scopes.append(row)
        return dict(row)

    def get_scope_contract(self, scope_contract_id):
        return dict(next(x for x in self.scopes if x["scope_contract_id"] == scope_contract_id))

    def evaluate_authorization(self, payload):
        self.evaluate_calls += 1
        scope = self.get_scope_contract(payload["scope_contract_id"])
        request_id = f"greq-317-{self.evaluate_calls}"
        decision_id = f"gdec-317-{self.evaluate_calls}"
        self.requests.append({"request_id": request_id, **payload})
        decision = {
            "decision_id": decision_id,
            "request_id": request_id,
            "mission_id": payload["mission_id"],
            "decision": "ALLOW",
            "risk_score": 0.1,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "IP_MATCH"],
            "constraints": {},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": "2026-09-02T00:00:00Z",
            "valid_until": "2030-09-02T00:00:00Z",
            "policy_set_id": scope["policy_set_id"],
            "policy_version": 9,
            "scope_contract_id": scope["scope_contract_id"],
            "scope_version": scope["version"],
        }
        decision["decision_hash"] = self._hash(decision)
        decision["decision_status"] = "ACTIVE"
        event_id = f"gevent-317-{self.evaluate_calls}"
        self.decisions.append(dict(decision))
        self.events.append({"event_id": event_id, "event_type": "POLICY_DECISION_ISSUED", "mission_id": payload["mission_id"], "payload": dict(decision)})
        return {**decision, "governance_event_id": event_id}

    def mission_correlation_snapshot(self, mission_id):
        return {
            "schema_version": "governance-correlation-snapshot-v1",
            "mission_id": mission_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "scope_contracts": [dict(x) for x in self.scopes if x["mission_id"] == mission_id],
            "authorization_requests": [],
            "policy_decisions": [dict(x) for x in self.decisions if x["mission_id"] == mission_id],
            "events": [dict(x) for x in self.events if x["mission_id"] == mission_id],
            "audit_records": [],
        }


class FakeCti:
    base_url = "fake://cti"

    def __init__(self):
        self.start_calls = 0
        self.get_calls = 0
        self.fail_reads = False
        self.mission = {"status": "NOT_FOUND"}

    def start_mission(self, payload):
        self.start_calls += 1
        self.mission = {
            "mission_id": payload["mission_id"],
            "status": "RUNNING",
            "state_version": 1,
            "plan_version": 1,
        }
        return {"status": "accepted", "mission_id": payload["mission_id"], "plan_id": "plan-317"}

    def get_mission(self, mission_id):
        self.get_calls += 1
        if self.fail_reads:
            raise AssertionError("repository reconstruction must not call live CTI")
        return dict(self.mission)


def mission_payload(key="mission-317"):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST",
        "created_by": "pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab"},
        "success_criteria": [{"metric": "done", "expected": True}],
        "budgets": {"time_seconds": 1800},
        "required_subsystems": ["CTI"],
        "metadata": {"environment": "LAB"},
    }


def scope_payload(key="scope-317", expected=0):
    return {
        "expected_contract_version": expected,
        "idempotency_key": key,
        "actor": "pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [],
            "network_ranges": [],
            "domains": [],
            "services": [],
        },
        "roe": {
            "allowed_action_classes": ["INTERNAL_REASONING", "TARGET_RECON"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "allowed_time_window": {"start_at": "2026-09-01T00:00:00Z", "end_at": "2030-09-03T00:00:00Z"},
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
            "data_handling_policy": {"classification": "INTERNAL", "retention_days": 7, "export_allowed": False},
        },
        "reason": "pytest scope",
        "metadata": {"environment": "LAB"},
    }


def binding_payload(key="bind-317", expected=0):
    return {
        "expected_binding_version": expected,
        "idempotency_key": key,
        "actor": "pytest",
        "policy_set_id": "default-policy",
        "name": "Stage 3.1.7 binding",
        "capabilities": [
            {
                "capability_id": "orchestrator.route.cti",
                "subject_component": "CTI-A01",
                "action_class": "INTERNAL_REASONING",
                "action_name": "START_CTI_MISSION",
                "authorization_mode": "NOT_REQUIRED_INTERNAL",
                "resource_types": [],
                "max_risk_level": "LOW",
                "requires_human_approval": False,
            },
            {
                "capability_id": "pentest.recon",
                "subject_component": "CTI-A02",
                "action_class": "TARGET_RECON",
                "action_name": "recon",
                "authorization_mode": "REQUIRED",
                "resource_types": ["IP"],
                "max_risk_level": "MODERATE",
                "requires_human_approval": False,
            },
        ],
        "reason": "pytest binding",
        "metadata": {"stage": "3.1.7"},
    }


def transition_payload(expected, to_state):
    return {
        "expected_state_version": expected,
        "to_state": to_state,
        "actor": "pytest",
        "reason_code": f"MOVE_TO_{to_state}",
        "metadata": {},
    }


def make_service(db_path: Path):
    gov = FakeGovernance()
    cti = FakeCti()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(db_path))
    return CanonicalMissionService(repo, governance_client=gov, cti_client=cti), gov, cti


def provision_full_repository(db_path: Path):
    svc, gov, cti = make_service(db_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    svc.put_mission_scope_contract(mission_id, scope_payload())
    svc.put_mission_governance_binding(mission_id, binding_payload())
    svc.authorize_mission_capability(
        mission_id,
        {
            "idempotency_key": "auth-317",
            "capability_id": "pentest.recon",
            "resource_type": "IP",
            "resource_value": "127.0.0.1",
            "context": {"environment": "LAB"},
            "evidence_refs": [],
            "requested_by": "pytest",
        },
    )
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    svc.transition_mission_state(mission_id, transition_payload(2, "PLANNING"))
    task = svc.create_governed_routing_task(
        mission_id,
        {
            "idempotency_key": "task-317",
            "capability_id": "orchestrator.route.cti",
            "task_input": {"auto_acquire_cti": False},
            "requested_by": "pytest",
            "reason": "route CTI",
            "metadata": {"stage": "3.1.7"},
        },
    )
    svc.transition_mission_state(mission_id, transition_payload(3, "RUNNING"))
    svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    return svc, gov, cti, mission_id


def test_stage317_repository_metadata_and_health_contract(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    metadata = svc.repository.get_repository_metadata()
    assert metadata["schema_version"] == REPOSITORY_SCHEMA_VERSION
    assert metadata["migration_level"] == REPOSITORY_MIGRATION_LEVEL
    assert metadata["storage_model"] == REPOSITORY_MODEL

    health = svc.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["mission_repository_schema_version"] == REPOSITORY_SCHEMA_VERSION
    assert health["mission_persistence_manifest_schema_version"] == PERSISTENCE_MANIFEST_SCHEMA_VERSION
    assert health["mission_repository_recovery_mode"] == REPOSITORY_RECOVERY_MODE
    assert health["mission_repository_read_model_enabled"] is True
    assert "stage3.1.6-mission-versioning-concurrency" in health["supported_controls"]
    assert "stage3.1.7-mission-persistence-repository-model" in health["supported_controls"]
    assert health["dispatch_enabled"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_initial_repository_manifest_is_stable_across_reconstruction_reads(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    first = svc.get_mission_repository(mission_id)
    second = svc.get_mission_repository(mission_id)

    assert first["integrity_status"] == "PASS"
    assert first["repository_sha256"] == second["repository_sha256"]
    assert first["persistence_manifest"]["reconstructed_at"] != ""
    assert first["persistence_manifest"]["schema_version"] == PERSISTENCE_MANIFEST_SCHEMA_VERSION
    assert verify_persistence_manifest(first["persistence_manifest"]) is True
    assert first["record_counts"]["global_missions"] == 1
    assert first["record_counts"]["mission_envelopes"] == 1
    assert first["record_counts"]["mission_states"] == 1


def test_repository_hash_changes_only_after_durable_local_mutation(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    h1 = svc.get_mission_repository(mission_id)["repository_sha256"]
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    h2 = svc.get_mission_repository(mission_id)["repository_sha256"]
    svc.put_mission_scope_contract(mission_id, scope_payload())
    h3 = svc.get_mission_repository(mission_id)["repository_sha256"]

    assert h1 != h2
    assert h2 != h3
    assert svc.get_mission_repository(mission_id)["repository_sha256"] == h3


def test_full_repository_projection_covers_all_stage311_to316_stores(tmp_path):
    svc, _, _, mission_id = provision_full_repository(tmp_path / "missions.db")
    view = svc.get_mission_repository(mission_id)

    assert view["integrity_status"] == "PASS"
    assert all(x["status"] == "PASS" for x in view["integrity_checks"])
    counts = view["record_counts"]
    assert counts["mission_state_transitions"] == 3
    assert counts["mission_scope_contract_versions"] == 1
    assert counts["mission_governance_binding_versions"] == 1
    assert counts["mission_governance_binding_operations"] == 1
    assert counts["mission_authorization_operations"] == 1
    assert counts["mission_authorization_bindings"] == 1
    assert counts["mission_routed_tasks"] == 1
    assert counts["mission_task_dispatch_attempts"] == 1
    assert counts["mission_events"] == 9
    manifest = view["persistence_manifest"]
    assert manifest["current_state"]["state"] == "RUNNING"
    assert manifest["current_state"]["state_version"] == 4
    assert len(manifest["scope_contract_store"]["versions"]) == 1
    assert len(manifest["governance_binding_store"]["versions"]) == 1
    assert len(manifest["authorization_store"]["bindings"]) == 1
    assert len(manifest["routing_store"]["tasks"]) == 1
    assert [e["event_type"] for e in manifest["mission_event_store"]] == [
        "MISSION_REGISTERED",
        "MISSION_SCOPE_CONTRACT_COMMITTED",
        "MISSION_GOVERNANCE_BOUND",
        "MISSION_AUTHORIZATION_BOUND",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_ROUTING_TASK_CREATED",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_ROUTING_TASK_DISPATCHED",
    ]


def test_new_service_instance_recovers_same_durable_repository_without_memory_clone(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _, mission_id = provision_full_repository(db_path)
    before = svc.get_mission_repository(mission_id)

    # Construct an independent repository/service over the same durable DB. No service
    # object, in-memory state, fake Governance state, or CTI state is copied into it.
    recovered_repo = MissionRepository(driver="sqlite", sqlite_path=str(db_path))
    recovered = CanonicalMissionService(
        recovered_repo,
        governance_client=FakeGovernance(),
        cti_client=FakeCti(),
    )
    after = recovered.get_mission_repository(mission_id)

    assert after["repository_sha256"] == before["repository_sha256"]
    assert after["persistence_manifest"]["current_state"] == before["persistence_manifest"]["current_state"]
    assert after["record_counts"] == before["record_counts"]
    assert recovered.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"


def test_repository_reconstruction_is_local_only_and_does_not_query_live_cti(tmp_path):
    svc, _, cti, mission_id = provision_full_repository(tmp_path / "missions.db")
    calls_before = cti.get_calls
    cti.fail_reads = True
    view = svc.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert cti.get_calls == calls_before


def test_state_projection_corruption_fails_repository_read_closed(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE mission_states SET state_version=99 WHERE mission_id=?", (mission_id,))
        conn.commit()

    with pytest.raises(MissionRepositoryIntegrityError, match="state_projection_from_append_only_ledger"):
        svc.get_mission_repository(mission_id)


def test_scope_head_corruption_fails_repository_read_closed(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    svc.put_mission_scope_contract(mission_id, scope_payload())

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE mission_scope_contract_heads SET current_sha256=? WHERE mission_id=?",
            ("0" * 64, mission_id),
        )
        conn.commit()

    with pytest.raises(MissionRepositoryIntegrityError, match="scope_version_store_and_head"):
        svc.get_mission_repository(mission_id)


def test_envelope_payload_corruption_fails_repository_read_closed(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT canonical_json FROM mission_envelopes WHERE mission_id=?", (mission_id,)).fetchone()
        envelope = json.loads(row[0])
        envelope["metadata"]["tampered"] = True
        conn.execute(
            "UPDATE mission_envelopes SET canonical_json=? WHERE mission_id=?",
            (json.dumps(envelope, sort_keys=True, separators=(",", ":")), mission_id),
        )
        conn.commit()

    with pytest.raises(MissionRepositoryIntegrityError, match="immutable_envelope_hash"):
        svc.get_mission_repository(mission_id)


def test_migration_007_declares_repository_metadata_without_external_authority_tables():
    sql = Path("migrations/007_stage3_1_7_mission_persistence_repository_model.sql").read_text()
    assert "mission_repository_metadata" in sql
    assert "apts-mission-repository-v1" in sql
    assert "NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS" in sql
    assert "CREATE TABLE" in sql
    assert "policy_decisions" not in sql.lower()
    assert "cti_state_version" not in sql.lower()


def test_command_journal_persisted_version_vectors_are_reverified(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    token = svc.get_mission_version_vector(mission_id)["version_sha256"]
    svc.execute_mission_command(
        mission_id,
        {
            "command_id": "cmd-317-persisted-vector",
            "idempotency_key": "idem-cmd-317-persisted-vector",
            "operation": "STATE_TRANSITION",
            "expected_version_sha256": token,
            "payload": transition_payload(1, "PIP_BOUND"),
            "submitted_by": "pytest",
            "metadata": {"stage": "3.1.7"},
        },
    )

    view = svc.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert view["record_counts"]["mission_command_journal"] == 1
    assert len(view["persistence_manifest"]["command_journal"]) == 1
    assert view["persistence_manifest"]["command_journal"][0]["after_version_sha256"] is not None


def test_corrupted_command_journal_version_vector_fails_repository_read_closed(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    token = svc.get_mission_version_vector(mission_id)["version_sha256"]
    svc.execute_mission_command(
        mission_id,
        {
            "command_id": "cmd-317-corrupt-vector",
            "idempotency_key": "idem-cmd-317-corrupt-vector",
            "operation": "STATE_TRANSITION",
            "expected_version_sha256": token,
            "payload": transition_payload(1, "PIP_BOUND"),
            "submitted_by": "pytest",
            "metadata": {"stage": "3.1.7"},
        },
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT after_version_json FROM mission_command_journal WHERE command_id='cmd-317-corrupt-vector'"
        ).fetchone()
        vector = json.loads(row[0])
        vector["integrity"]["canonical_sha256"] = "0" * 64
        conn.execute(
            "UPDATE mission_command_journal SET after_version_json=? WHERE command_id='cmd-317-corrupt-vector'",
            (json.dumps(vector, sort_keys=True, separators=(",", ":")),),
        )
        conn.commit()

    with pytest.raises(MissionRepositoryIntegrityError, match="command_journal_persisted_vectors"):
        svc.get_mission_repository(mission_id)
