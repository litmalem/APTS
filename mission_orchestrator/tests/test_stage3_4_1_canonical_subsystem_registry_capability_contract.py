from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionValidationPipelineError,
    SubsystemCapabilityNotFound,
    SubsystemNotFound,
    SubsystemRegistryIntegrityError,
)
from mission_orchestrator.mission_validation import SUPPORTED_REQUIRED_SUBSYSTEMS, validate_canonical_mission_draft
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.subsystem_registry import (
    CANONICAL_SUBSYSTEM_IDS,
    SUBSYSTEM_AVAILABILITY_MODE,
    SUBSYSTEM_CAPABILITY_CONTRACT_SCHEMA_VERSION,
    SUBSYSTEM_CONTRACT_SCHEMA_VERSION,
    SUBSYSTEM_REGISTRY_AUTHORITY,
    SUBSYSTEM_REGISTRY_MODE,
    SUBSYSTEM_REGISTRY_SCHEMA_VERSION,
    SUBSYSTEM_REGISTRY_VERSION,
    build_canonical_registry_snapshot,
    canonical_subsystem_registry_definition,
    capability_contract_for,
    capability_ids_for_subsystem,
    subsystem_for_component,
    verify_capability_contract,
    verify_registry_snapshot,
    verify_subsystem_contract,
)


CONTROL = "stage3.4.1-canonical-subsystem-registry-capability-contract"


class TrapClient:
    base_url = "INJECTED_TRAP"

    def __getattr__(self, name):
        raise AssertionError(f"Stage 3.4.1 registry read must not call external client method {name}")


def make_service(path: Path) -> CanonicalMissionService:
    return CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=str(path)),
        governance_client=TrapClient(),
        cti_client=TrapClient(),
    )


def mission_draft(required_subsystems):
    return {
        "mission": {
            "idempotency_key": "stage341-validation",
            "source_system": "pytest",
            "created_by": "pytest",
            "mission_kind": "AUTONOMOUS_PENTEST",
            "objective": {"type": "PENTEST", "description": "registry admission test"},
            "success_criteria": [{"type": "REPORT_AVAILABLE"}],
            "budgets": {"time_seconds": 600},
            "required_subsystems": list(required_subsystems),
        },
        "scope_contract": {
            "idempotency_key": "stage341-scope",
            "expected_contract_version": 0,
            "actor": "pytest",
            "scope": {
                "targets": [{"target_type": "CIDR", "target_value": "192.0.2.0/24", "environment": "LAB"}],
                "network_ranges": ["192.0.2.0/24"],
                "domains": [],
                "services": [],
                "excluded_targets": [],
            },
            "roe": {
                "allowed_action_classes": ["INTERNAL_REASONING", "TARGET_RECON"],
                "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
                "allowed_time_window": {"start_at": "2026-09-08T00:00:00Z", "end_at": "2030-09-09T00:00:00Z"},
                "maximum_concurrency": 2,
                "destructive_actions_allowed": False,
                "credential_usage_allowed": False,
                "persistence_allowed": False,
                "human_approval_required_for": [],
            },
            "constraints": {
                "max_actions": 20,
                "max_duration": 600,
                "risk_threshold": "MODERATE",
                "resource_budget": {"max_network_requests": 500},
                "data_handling_policy": {"classification": "INTERNAL", "retention_days": 7, "export_allowed": False},
            },
            "reason": "Stage 3.4.1 registry admission validation",
            "metadata": {"environment": "LAB", "stage": "3.4.1"},
        },
    }


def test_stage341_health_declares_registry_contract_without_routing_or_execution_expansion(tmp_path):
    service = make_service(tmp_path / "missions.db")
    health = service.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][30:40] == [
        CONTROL,
        "stage3.4.2-task-routing-intent-candidate-resolution",
        "stage3.4.3-routing-eligibility-compatibility-gate",
        "stage3.4.4-deterministic-route-selection-decision-record",
        "stage3.4.5-governance-bound-delegation-authorization",
        "stage3.4.6-canonical-delegation-contract-handoff-envelope",
        "stage3.4.7-delegation-delivery-acknowledgement-ownership",
        "stage3.4.8-retry-fallback-reassignment-conflict-control",
        "stage3.4.9-routing-delegation-event-lineage-replay-recovery",
        "stage3.4.10-routing-delegation-acceptance-regression-gate",
    ]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["subsystem_registry_schema_version"] == SUBSYSTEM_REGISTRY_SCHEMA_VERSION
    assert health["subsystem_contract_schema_version"] == SUBSYSTEM_CONTRACT_SCHEMA_VERSION
    assert health["subsystem_capability_contract_schema_version"] == SUBSYSTEM_CAPABILITY_CONTRACT_SCHEMA_VERSION
    assert health["subsystem_registry_version"] == SUBSYSTEM_REGISTRY_VERSION == 1
    assert health["subsystem_registry_mode"] == SUBSYSTEM_REGISTRY_MODE
    assert health["subsystem_registry_authority"] == SUBSYSTEM_REGISTRY_AUTHORITY
    assert health["canonical_registered_subsystems"] == ["CTI", "PENTEST"]
    assert health["subsystem_registry_database_migration_level"] == 18
    assert health["subsystem_registry_runtime_endpoint_binding_performed"] is False
    assert health["subsystem_registry_runtime_health_probe_performed"] is False
    assert health["subsystem_registry_candidate_resolution_performed"] is False
    assert health["subsystem_registry_route_selection_performed"] is False
    assert health["subsystem_registry_delegation_performed"] is False
    assert health["subsystem_registry_governance_query_performed"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_static_registry_definition_is_canonical_and_declared_only():
    definition = canonical_subsystem_registry_definition()
    snapshot = build_canonical_registry_snapshot()
    assert definition["schema_version"] == SUBSYSTEM_REGISTRY_SCHEMA_VERSION
    assert definition["registry_version"] == 1
    assert definition["canonical_subsystem_ids"] == ["CTI", "PENTEST"]
    assert definition["subsystem_count"] == 2
    assert definition["capability_count"] == 4
    assert definition["canonical_sha256"] == snapshot["integrity"]["canonical_sha256"]
    assert definition["runtime_binding_mode"] == "DEFERRED_TO_LATER_ROUTING_AND_DELEGATION_STAGES"
    assert definition["availability_mode"] == SUBSYSTEM_AVAILABILITY_MODE
    assert definition["registry_is_authorization"] is False
    assert definition["route_selection_performed"] is False
    assert definition["delegation_performed"] is False


def test_registry_snapshot_has_nested_hash_verified_subsystems_and_capabilities():
    snapshot = build_canonical_registry_snapshot()
    assert verify_registry_snapshot(snapshot)
    assert snapshot["counts"] == {"subsystems": 2, "capabilities": 4}
    assert [item["identity"]["subsystem_id"] for item in snapshot["subsystems"]] == ["CTI", "PENTEST"]
    assert all(verify_subsystem_contract(item) for item in snapshot["subsystems"])
    assert all(verify_capability_contract(item) for item in snapshot["capabilities"])
    assert {item["identity"]["capability_id"] for item in snapshot["capabilities"]} == {
        "cti.read.context",
        "cti.analyze.context",
        "pentest.recon",
        "pentest.validate",
    }


def test_subsystem_identity_is_independent_of_runtime_endpoint_and_instance():
    snapshot = build_canonical_registry_snapshot()
    for subsystem in snapshot["subsystems"]:
        text = json.dumps(subsystem, sort_keys=True)
        assert "http://" not in text and "https://" not in text
        assert "127.0.0.1" not in text
        assert subsystem["registration"]["runtime_endpoint_bound"] is False
        assert subsystem["registration"]["runtime_health_probed"] is False
        assert subsystem["contract"]["network_endpoint_is_identity"] is False
        assert subsystem["contract"]["component_instance_is_identity"] is False
        assert subsystem["authority"]["registration_is_runtime_availability"] is False
        assert subsystem["authority"]["registration_is_route_selection"] is False
        assert subsystem["authority"]["registration_is_dispatch"] is False


def test_capability_contracts_preserve_authorization_and_execution_boundaries():
    snapshot = build_canonical_registry_snapshot()
    for capability in snapshot["capabilities"]:
        assert capability["compatibility"]["accepted_task_schema_versions"] == ["apts-canonical-planned-task-v1"]
        semantics = capability["semantics"]
        assert semantics["capability_is_route_selection"] is False
        assert semantics["capability_is_authorization"] is False
        assert semantics["capability_is_dispatch"] is False
        assert semantics["runtime_endpoint_resolution_performed"] is False
        assert semantics["resource_assignment_performed"] is False
        assert semantics["governance_query_performed"] is False
        assert semantics["target_action_dispatch_enabled"] is False
        assert semantics["target_actuation"] is False
        assert semantics["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"


def test_repository_seeds_registry_once_and_reconstructs_same_snapshot_after_restart(tmp_path):
    db = tmp_path / "missions.db"
    first = MissionRepository(driver="sqlite", sqlite_path=str(db))
    snap1 = first.get_subsystem_registry_snapshot()
    assert snap1 is not None and verify_registry_snapshot(snap1)
    second = MissionRepository(driver="sqlite", sqlite_path=str(db))
    snap2 = second.get_subsystem_registry_snapshot()
    assert snap2 == snap1
    assert len(second.list_canonical_subsystems()) == 2
    assert len(second.list_subsystem_capability_contracts()) == 4
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from subsystem_registry_snapshots").fetchone()[0] == 1
        assert conn.execute("select count(*) from canonical_subsystems").fetchone()[0] == 2
        assert conn.execute("select count(*) from subsystem_capability_contracts").fetchone()[0] == 4


def test_service_registry_read_is_local_only_and_returns_exact_persisted_hash(tmp_path):
    service = make_service(tmp_path / "missions.db")
    expected = build_canonical_registry_snapshot()
    result = service.get_subsystem_registry()
    assert result["registry"] == expected
    assert result["source_of_truth"] == "MISSION_ORCHESTRATOR_DATABASE"
    assert result["runtime_endpoint_binding_performed"] is False
    assert result["runtime_health_probe_performed"] is False
    assert result["governance_query_performed"] is False


def test_service_registry_definition_binds_to_persisted_registry_without_external_queries(tmp_path):
    service = make_service(tmp_path / "missions.db")
    result = service.get_subsystem_registry_definition()
    assert result["definition"]["canonical_sha256"] == result["persisted_registry_sha256"]
    assert result["external_query_performed"] is False
    assert result["route_selection_performed"] is False
    assert result["delegation_performed"] is False


def test_cti_and_pentest_read_models_expose_only_their_declared_capabilities(tmp_path):
    service = make_service(tmp_path / "missions.db")
    cti = service.get_subsystem("cti")
    pentest = service.get_subsystem("PENTEST")
    assert cti["subsystem"]["identity"]["subsystem_id"] == "CTI"
    assert [c["identity"]["capability_id"] for c in cti["capabilities"]] == [
        "cti.analyze.context",
        "cti.read.context",
    ]
    assert pentest["subsystem"]["identity"]["subsystem_id"] == "PENTEST"
    assert [c["identity"]["capability_id"] for c in pentest["capabilities"]] == [
        "pentest.recon",
        "pentest.validate",
    ]


def test_capability_lookup_is_exact_and_subsystem_scoped(tmp_path):
    service = make_service(tmp_path / "missions.db")
    result = service.get_subsystem_capability("CTI", "cti.read.context")
    assert result["capability"]["identity"]["capability_id"] == "cti.read.context"
    assert result["capability"]["identity"]["subsystem_id"] == "CTI"
    assert result["capability_is_authorization"] is False
    with pytest.raises(SubsystemCapabilityNotFound):
        service.get_subsystem_capability("PENTEST", "cti.read.context")


def test_unknown_subsystem_and_capability_fail_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    with pytest.raises(SubsystemNotFound):
        service.get_subsystem("UNKNOWN")
    with pytest.raises(SubsystemCapabilityNotFound):
        service.get_subsystem_capability("CTI", "cti.unknown")


def test_registry_integrity_detects_tampered_snapshot(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    with sqlite3.connect(db) as conn:
        conn.execute("update subsystem_registry_snapshots set canonical_sha256=?", ("0" * 64,))
        conn.commit()
    with pytest.raises(SubsystemRegistryIntegrityError):
        service.get_subsystem_registry()


def test_registry_integrity_detects_tampered_subsystem_row(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    with sqlite3.connect(db) as conn:
        row = conn.execute("select canonical_json from canonical_subsystems where subsystem_id='CTI'").fetchone()[0]
        body = json.loads(row)
        body["classification"]["description"] = "tampered"
        conn.execute("update canonical_subsystems set canonical_json=? where subsystem_id='CTI'", (json.dumps(body),))
        conn.commit()
    with pytest.raises(SubsystemRegistryIntegrityError):
        service.list_subsystems()


def test_component_selector_and_capability_helpers_are_deterministic():
    assert subsystem_for_component("CTI-INF01") == "CTI"
    assert subsystem_for_component("cti-worker-2") == "CTI"
    assert subsystem_for_component("PENTEST-A01") == "PENTEST"
    assert subsystem_for_component("UNKNOWN-A01") is None
    assert capability_ids_for_subsystem("CTI") == ("cti.read.context", "cti.analyze.context")
    contract = capability_contract_for("pentest.recon", subsystem_id="PENTEST")
    assert contract is not None
    assert contract["identity"]["subsystem_id"] == "PENTEST"


def test_canonical_mission_validation_uses_same_registry_subsystem_vocabulary():
    assert SUPPORTED_REQUIRED_SUBSYSTEMS == frozenset(CANONICAL_SUBSYSTEM_IDS) == frozenset({"CTI", "PENTEST"})
    valid = validate_canonical_mission_draft(mission_draft(["CTI", "PENTEST"]))
    assert valid["valid"] is True
    bad = mission_draft(["CTI", "UNKNOWN"])
    with pytest.raises(MissionValidationPipelineError, match="unsupported required_subsystems"):
        validate_canonical_mission_draft(bad)


def test_legacy_stage315_dispatch_scope_is_not_widened_by_registry(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["canonical_registered_subsystems"] == ["CTI", "PENTEST"]
    assert health["supported_routing_subsystems"] == ["CTI"]
    assert health["subsystem_routing_dispatch_enabled"] is True  # historical high-level CTI route only
    assert health["dispatch_enabled"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_migration_018_declares_registry_stores_seed_and_authority_boundary():
    sql = Path("migrations/018_stage3_4_1_canonical_subsystem_registry_capability_contract.sql").read_text().lower()
    assert "create table if not exists subsystem_registry_snapshots" in sql
    assert "create table if not exists canonical_subsystems" in sql
    assert "create table if not exists subsystem_capability_contracts" in sql
    assert "insert ignore into subsystem_registry_snapshots" in sql
    assert "insert ignore into canonical_subsystems" in sql
    assert "insert ignore into subsystem_capability_contracts" in sql
    assert "registration != availability" in sql
    assert "capability != permission" in sql
    assert "registry != authorization" in sql
    assert "route selection != execution" in sql
    assert "does not probe subsystem health" in sql
    assert "    18," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53


def test_sqlite_schema_contains_stage341_global_registry_stores(tmp_path):
    db = tmp_path / "missions.db"
    MissionRepository(driver="sqlite", sqlite_path=str(db))
    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert {"subsystem_registry_snapshots", "canonical_subsystems", "subsystem_capability_contracts"} <= tables


def test_stage341_http_read_model_routes_match_documented_registry_api(tmp_path, monkeypatch):
    """Regression guard for the public Stage-3.4.1 registry read-model routes.

    Stage 3.4.2 acceptance consumes /api/subsystem-registry over HTTP.  Service-level
    coverage alone is insufficient because an omitted handler route otherwise degrades
    to ROUTE_NOT_FOUND while the canonical registry itself remains healthy.
    """
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen

    service = make_service(tmp_path / "missions.db")
    previous_service = MissionOrchestratorHandler.service
    MissionOrchestratorHandler.service = service
    monkeypatch.setenv("MISSION_HTTP_QUIET", "1")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), MissionOrchestratorHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get_json(path):
        with urlopen(base + path, timeout=5) as response:
            assert response.status == 200
            return json.loads(response.read().decode("utf-8"))

    try:
        registry = get_json("/api/subsystem-registry")
        assert registry["status"] == "completed"
        assert registry["registry"]["counts"] == {"subsystems": 2, "capabilities": 4}
        assert registry["runtime_endpoint_binding_performed"] is False
        assert registry["runtime_health_probe_performed"] is False
        assert registry["governance_query_performed"] is False

        definition = get_json("/api/subsystem-registry-definition")
        assert definition["status"] == "completed"
        assert definition["external_query_performed"] is False

        subsystems = get_json("/api/subsystems")
        assert subsystems["count"] == 2

        cti = get_json("/api/subsystems/CTI")
        assert cti["subsystem"]["identity"]["subsystem_id"] == "CTI"
        assert cti["capability_count"] == 2

        capabilities = get_json("/api/subsystems/CTI/capabilities")
        assert capabilities["count"] == 2
        assert [item["identity"]["capability_id"] for item in capabilities["capabilities"]] == [
            "cti.analyze.context",
            "cti.read.context",
        ]

        capability = get_json("/api/subsystems/CTI/capabilities/cti.read.context")
        assert capability["capability"]["identity"]["capability_id"] == "cti.read.context"
        assert capability["capability_is_authorization"] is False
        assert capability["route_selection_performed"] is False
        assert capability["delegation_performed"] is False
        assert capability["governance_query_performed"] is False
        assert capability["target_action_dispatch_enabled"] is False
        assert capability["target_actuation"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        MissionOrchestratorHandler.service = previous_service
