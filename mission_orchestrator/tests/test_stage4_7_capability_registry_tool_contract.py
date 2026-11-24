from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from http.client import RemoteDisconnected
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import time
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.repository import REPOSITORY_MIGRATION_LEVEL
from pentest_subsystem.api_service import (
    PentestSubsystemHandler,
    PentestSubsystemStage42Handler,
    PentestSubsystemStage43Handler,
    PentestSubsystemStage44Handler,
    PentestSubsystemStage45Handler,
    PentestSubsystemStage46Handler,
    PentestSubsystemStage47Handler,
)
from pentest_subsystem.capability_contract import (
    PENTEST_CAPABILITY_CONTROL_VERSION,
    PENTEST_CAPABILITY_IDS,
    PENTEST_CAPABILITY_NEXT_STAGE,
    PENTEST_CAPABILITY_REPOSITORY_MIGRATION_LEVEL,
    PENTEST_TOOL_IDS,
    build_pentest_capability_registry_snapshot,
    canonical_pentest_capability_control_contract,
    canonical_pentest_capability_definition,
    canonical_pentest_capability_tool_mappings,
    canonical_pentest_capability_contracts,
    canonical_pentest_tool_contracts,
    verify_pentest_capability_control_contract,
    verify_pentest_capability_registry_snapshot,
)
from pentest_subsystem.capability_repository import (
    PENTEST_CAPABILITY_REPOSITORY_SCHEMA_VERSION,
    PentestCapabilityNotFoundError,
    PentestCapabilityRegistryIntegrityError,
    PentestCapabilityRepository,
    PentestToolNotFoundError,
)
from pentest_subsystem.capability_service import PentestCapabilityService
from pentest_subsystem.task_contract import build_pentest_task_binding
from pentest_subsystem.workflow_contract import canonical_pentest_workflow_contract
from pentest_subsystem.workflow_repository import PentestWorkflowRepository
from tests.test_stage4_4_pentest_lifecycle_state import FIXED_NOW, sample_boundary, sample_pip, sample_task
from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import start_payload

CONTROL = "stage4.7-capability-registry-tool-contract"
SERVER_VERSION = "APTSPentestSubsystem/4.7"


def _start_server(tmp_path: Path):
    repository = PentestCapabilityRepository(tmp_path / "pentest.db")
    service = PentestCapabilityService(repository)
    handler = type("IsolatedStage47Handler", (PentestSubsystemStage47Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, service, f"http://127.0.0.1:{server.server_address[1]}"


def _urlopen_local_with_retry(target, *, timeout: float = 5, attempts: int = 3):
    last_exc = None
    for attempt in range(attempts):
        try:
            return urlopen(target, timeout=timeout)
        except HTTPError:
            raise
        except (ConnectionAbortedError, ConnectionResetError, RemoteDisconnected) as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError(f"localhost HTTP retry exhausted: {last_exc!r}")


def _post_json(url: str, payload: dict):
    raw = json.dumps(payload).encode("utf-8")
    req = Request(url, data=raw, headers={"Content-Type": "application/json"}, method="POST")
    with _urlopen_local_with_retry(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _materialize(repo: PentestCapabilityRepository):
    boundary = sample_boundary()
    pip = sample_pip(boundary)
    task = sample_task(boundary, pip)
    binding = build_pentest_task_binding(
        boundary_payload=boundary,
        pip_payload=pip,
        task_payload=task,
        now=FIXED_NOW,
    )
    record, created = repo.create_task(task, binding)
    assert created is True
    return boundary, pip, task, binding, record


def test_01_stage47_control_binds_exact_stage46_predecessor():
    contract = canonical_pentest_capability_control_contract()
    predecessor = canonical_pentest_workflow_contract()
    assert contract["control_version"] == CONTROL == PENTEST_CAPABILITY_CONTROL_VERSION
    assert contract["predecessor"]["control"] == predecessor["control_version"]
    assert contract["predecessor"]["contract_sha256"] == predecessor["integrity"]["canonical_sha256"]
    assert contract["repository"]["migration_level"] == 5
    assert contract["next_stage"] == "4.8"


def test_02_stage47_control_is_hash_bound_and_tamper_fails_closed():
    contract = canonical_pentest_capability_control_contract()
    assert verify_pentest_capability_control_contract(contract) is True
    tampered = deepcopy(contract)
    tampered["runtime"]["capability_selection_enabled"] = True
    assert verify_pentest_capability_control_contract(tampered) is False


def test_03_registry_contains_exact_seven_roadmap_capabilities_and_eight_tools():
    registry = build_pentest_capability_registry_snapshot()
    assert verify_pentest_capability_registry_snapshot(registry) is True
    assert registry["counts"] == {"capabilities": 7, "tools": 8, "mappings": 8}
    assert tuple(item["identity"]["capability_id"] for item in registry["capabilities"]) == PENTEST_CAPABILITY_IDS
    assert tuple(item["identity"]["tool_id"] for item in registry["tools"]) == PENTEST_TOOL_IDS


def test_04_every_capability_declares_input_output_permission_tool_and_safety_contracts():
    for capability in canonical_pentest_capability_contracts():
        assert capability["schemas"]["input_schema"]["required"]
        assert capability["schemas"]["output_schema"]["required"]
        assert capability["permission"]["requirement"]
        assert capability["classification"]["safety_class"]
        assert capability["tools"]["requirements"]
        assert capability["permission"]["registry_grants_permission"] is False
        assert capability["tools"]["tool_invocation_enabled"] is False
        assert capability["semantics"]["capability_is_execution"] is False


def test_05_logical_tool_contracts_expose_no_binary_command_shell_or_direct_target_access():
    for tool in canonical_pentest_tool_contracts():
        runtime = tool["runtime"]
        semantics = tool["semantics"]
        assert runtime["logical_contract_only"] is True
        assert runtime["adapter_bound"] is False
        assert runtime["runtime_endpoint_bound"] is False
        assert runtime["binary_or_command_bound"] is False
        assert runtime["credential_binding_present"] is False
        assert runtime["invocation_enabled"] is False
        assert semantics["direct_raw_target_access"] is False
        assert semantics["shell_access_exposed"] is False
        assert semantics["target_actuation"] is False


def test_06_exploitation_contract_is_high_risk_and_requires_later_controlled_execution_gateway():
    exploitation = next(item for item in canonical_pentest_capability_contracts() if item["identity"]["capability_id"] == "exploitation")
    tool = next(item for item in canonical_pentest_tool_contracts() if item["identity"]["tool_id"] == "pentest.tool.exploitation_adapter")
    assert exploitation["classification"]["safety_class"] == "HIGH_RISK_CONTROLLED"
    assert exploitation["permission"]["requirement"] == "EXPLICIT_GOVERNANCE_ALLOW_AND_STAGE6_EXECUTION_GATEWAY_REQUIRED"
    assert tool["runtime"]["stage6_authorized_adapter_required"] is True
    assert tool["runtime"]["binary_or_command_bound"] is False


def test_07_stage3_routing_aliases_are_preserved_without_widening_local_capability_ids():
    capabilities = {item["identity"]["capability_id"]: item for item in canonical_pentest_capability_contracts()}
    assert capabilities["reconnaissance"]["compatibility"]["routing_aliases"] == ["pentest.recon"]
    assert capabilities["validation"]["compatibility"]["routing_aliases"] == ["pentest.validate"]
    assert all(alias.startswith("pentest.") for cap in capabilities.values() for alias in cap["compatibility"]["routing_aliases"])


def test_08_capability_tool_mapping_is_exact_cross_referenced_and_non_invoking():
    capability_ids = set(PENTEST_CAPABILITY_IDS)
    tool_ids = set(PENTEST_TOOL_IDS)
    mappings = canonical_pentest_capability_tool_mappings()
    assert len(mappings) == 8
    for mapping in mappings:
        assert mapping["identity"]["capability_id"] in capability_ids
        assert mapping["identity"]["tool_id"] in tool_ids
        assert mapping["requirement"] == "REQUIRED"
        assert mapping["semantics"]["mapping_is_selection"] is False
        assert mapping["semantics"]["mapping_is_authorization"] is False
        assert mapping["semantics"]["mapping_is_invocation"] is False


def test_09_repository_migrates_to_level_five_and_seeds_registry_stores(tmp_path: Path):
    repo = PentestCapabilityRepository(tmp_path / "pentest.db")
    assert repo.migration_level() == PENTEST_CAPABILITY_REPOSITORY_MIGRATION_LEVEL == 5
    assert repo.metadata()["schema_version"] == PENTEST_CAPABILITY_REPOSITORY_SCHEMA_VERSION
    with sqlite3.connect(repo.sqlite_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {
            "registry": conn.execute("SELECT count(*) FROM pentest_capability_registry_snapshots").fetchone()[0],
            "capabilities": conn.execute("SELECT count(*) FROM pentest_capability_contracts").fetchone()[0],
            "tools": conn.execute("SELECT count(*) FROM pentest_tool_contracts").fetchone()[0],
            "mappings": conn.execute("SELECT count(*) FROM pentest_capability_tool_mappings").fetchone()[0],
        }
    assert {
        "pentest_capability_registry_snapshots",
        "pentest_capability_contracts",
        "pentest_tool_contracts",
        "pentest_capability_tool_mappings",
    }.issubset(tables)
    assert counts == {"registry": 1, "capabilities": 7, "tools": 8, "mappings": 8}


def test_10_registry_reconstructs_identically_after_repository_restart(tmp_path: Path):
    db = tmp_path / "pentest.db"
    first = PentestCapabilityRepository(db)
    snapshot1 = first.get_capability_registry()
    second = PentestCapabilityRepository(db)
    snapshot2 = second.get_capability_registry()
    assert snapshot2 == snapshot1 == build_pentest_capability_registry_snapshot()


def test_11_registry_snapshot_tampering_is_detected(tmp_path: Path):
    db = tmp_path / "pentest.db"
    repo = PentestCapabilityRepository(db)
    repo.get_capability_registry()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE pentest_capability_registry_snapshots SET canonical_sha256=?", ("0" * 64,))
        conn.commit()
    restarted = PentestCapabilityRepository(db)
    with pytest.raises(PentestCapabilityRegistryIntegrityError):
        restarted.get_capability_registry()


def test_12_individual_capability_tampering_is_detected(tmp_path: Path):
    db = tmp_path / "pentest.db"
    repo = PentestCapabilityRepository(db)
    repo.list_capabilities()
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT canonical_json FROM pentest_capability_contracts WHERE capability_id='validation'").fetchone()[0]
        body = json.loads(row)
        body["classification"]["safety_class"] = "TAMPERED"
        conn.execute("UPDATE pentest_capability_contracts SET canonical_json=? WHERE capability_id='validation'", (json.dumps(body),))
        conn.commit()
    restarted = PentestCapabilityRepository(db)
    with pytest.raises(PentestCapabilityRegistryIntegrityError):
        restarted.list_capabilities()


def test_13_unknown_capability_and_tool_fail_closed(tmp_path: Path):
    repo = PentestCapabilityRepository(tmp_path / "pentest.db")
    with pytest.raises(PentestCapabilityNotFoundError):
        repo.get_capability("unknown")
    with pytest.raises(PentestToolNotFoundError):
        repo.get_tool("pentest.tool.unknown")


def test_14_service_health_activates_registry_but_keeps_execution_disabled(tmp_path: Path):
    service = PentestCapabilityService(PentestCapabilityRepository(tmp_path / "pentest.db"))
    health = service.health()
    assert health["control_version"] == CONTROL
    assert health["pentest_repository_migration_level"] == 5
    assert health["stage4_7_capability_count"] == 7
    assert health["stage4_7_tool_count"] == 8
    assert health["stage4_7_mapping_count"] == 8
    assert health["stage4_7_capability_registry_enabled"] is True
    assert health["stage4_7_tool_contract_enabled"] is True
    assert health["stage4_7_tool_capability_mapping_enabled"] is True
    assert health["stage4_7_capability_selection_enabled"] is False
    assert health["stage4_7_tool_invocation_enabled"] is False
    assert health["stage4_7_target_actuation"] is False


def test_15_service_registry_is_local_read_only_metadata(tmp_path: Path):
    service = PentestCapabilityService(PentestCapabilityRepository(tmp_path / "pentest.db"))
    result = service.get_capability_registry()
    assert result["source_of_truth"] == "PENTEST_SUBSYSTEM_DATABASE"
    assert result["read_only"] is True
    assert result["capability_selection_performed"] is False
    assert result["tool_invocation_performed"] is False
    assert result["external_network_io_performed"] is False
    assert result["target_actuation"] is False


def test_16_service_resolves_declared_enumeration_tools_without_invocation(tmp_path: Path):
    service = PentestCapabilityService(PentestCapabilityRepository(tmp_path / "pentest.db"))
    result = service.get_capability_tools("enumeration")
    assert result["capability_id"] == "enumeration"
    assert [item["identity"]["tool_id"] for item in result["tools"]] == [
        "pentest.tool.network_discovery",
        "pentest.tool.service_enumerator",
    ]
    assert result["tool_invocation_performed"] is False
    assert result["target_actuation"] is False


def test_17_active_projection_enables_registry_without_mutating_stage46_canonical_contract(tmp_path: Path):
    service = PentestCapabilityService(PentestCapabilityRepository(tmp_path / "pentest.db"))
    projected = service.get_workflow_contract()
    historical = canonical_pentest_workflow_contract()
    assert projected["control_version"] == historical["control_version"]
    assert projected["active_control_version"] == CONTROL
    assert projected["capability_registry_enabled"] is True
    assert projected["capability_selection_enabled"] is False
    assert historical["runtime"]["capability_registry_enabled"] is False


def test_18_task_materialization_exposes_registry_availability_but_selects_nothing(tmp_path: Path):
    service = PentestCapabilityService(PentestCapabilityRepository(tmp_path / "pentest.db"))
    now = datetime.now(timezone.utc)
    boundary = sample_boundary(); pip = sample_pip(boundary, now=now); task = sample_task(boundary, pip, now=now)
    result = service.create_task({"boundary": boundary, "pip": pip, "task": task})
    assert result["capability_registry_available"] is True
    assert result["capability_selected"] is False
    assert result["tool_invocation_performed"] is False
    assert result["target_actuation"] is False


def test_19_workflow_remains_placeholder_and_does_not_select_or_invoke_capabilities(tmp_path: Path):
    repo = PentestCapabilityRepository(tmp_path / "pentest.db")
    _, _, task, _, _ = _materialize(repo)
    service = PentestCapabilityService(repo)
    result = service.start_workflow(task["pentest_task_id"], start_payload("stage47"))
    assert result["workflow"]["worker_assignment"]["capability_id"] is None
    assert result["capability_registry_available"] is True
    assert result["capability_selected"] is False
    assert result["tool_invocation_performed"] is False
    assert result["execution_started"] is False
    assert result["target_actuation"] is False


def test_20_http_stage47_contract_registry_capability_tool_and_mapping_routes(tmp_path: Path):
    server, thread, _, base = _start_server(tmp_path)
    try:
        with urlopen(base + "/health", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
        with urlopen(base + "/api/pentest/capability-contract", timeout=5) as response:
            contract = json.loads(response.read().decode("utf-8"))
        with urlopen(base + "/api/pentest/capability-registry", timeout=5) as response:
            registry = json.loads(response.read().decode("utf-8"))
        with urlopen(base + "/api/pentest/capabilities", timeout=5) as response:
            capabilities = json.loads(response.read().decode("utf-8"))
        with urlopen(base + "/api/pentest/capabilities/enumeration/tools", timeout=5) as response:
            mapping = json.loads(response.read().decode("utf-8"))
        tool_id = quote("pentest.tool.exploitation_adapter", safe="")
        with urlopen(base + f"/api/pentest/tools/{tool_id}", timeout=5) as response:
            tool = json.loads(response.read().decode("utf-8"))
        assert health["control_version"] == CONTROL
        assert contract["definition"]["capability_count"] == 7
        assert registry["registry"]["counts"]["tools"] == 8
        assert capabilities["count"] == 7
        assert len(mapping["tools"]) == 2
        assert tool["tool"]["identity"]["tool_id"] == "pentest.tool.exploitation_adapter"
        assert tool["runtime_available"] is False
        assert tool["tool_invocation_performed"] is False
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_21_http_unknown_registry_objects_return_404(tmp_path: Path):
    server, thread, _, base = _start_server(tmp_path)
    try:
        with pytest.raises(HTTPError) as cap_error:
            _urlopen_local_with_retry(base + "/api/pentest/capabilities/unknown", timeout=5)
        assert cap_error.value.code == 404
        with pytest.raises(HTTPError) as tool_error:
            _urlopen_local_with_retry(base + "/api/pentest/tools/pentest.tool.unknown", timeout=5)
        assert tool_error.value.code == 404
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_22_http_execution_dispatch_remains_fail_closed_even_with_registered_exploitation_contract(tmp_path: Path):
    server, thread, _, base = _start_server(tmp_path)
    try:
        req = Request(
            base + "/api/execution/dispatches",
            data=b'{"capability_id":"exploitation"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc:
            _urlopen_local_with_retry(req, timeout=5)
        assert exc.value.code == 409
        body = json.loads(exc.value.read().decode("utf-8"))
        assert body["error_code"] == "STAGE4_7_EXECUTION_INTAKE_NOT_ENABLED"
        assert body["capability_registry_enabled"] is True
        assert body["capability_selection_enabled"] is False
        assert body["execution_started"] is False
        assert body["tool_invocation_performed"] is False
        assert body["target_actuation"] is False
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_23_historical_stage_handlers_and_global_orchestrator_control_remain_compatible():
    assert PentestSubsystemHandler.server_version == "APTSPentestSubsystem/4.1"
    assert PentestSubsystemStage42Handler.server_version == "APTSPentestSubsystem/4.2"
    assert PentestSubsystemStage43Handler.server_version == "APTSPentestSubsystem/4.3"
    assert PentestSubsystemStage44Handler.server_version == "APTSPentestSubsystem/4.4"
    assert PentestSubsystemStage45Handler.server_version == "APTSPentestSubsystem/4.5"
    assert PentestSubsystemStage46Handler.server_version == "APTSPentestSubsystem/4.6"
    assert PentestSubsystemStage47Handler.server_version == SERVER_VERSION
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"


def test_24_upgrade_from_stage46_database_preserves_workflow_and_events(tmp_path: Path):
    db = tmp_path / "upgrade47.db"
    stage46 = PentestWorkflowRepository(db)
    boundary = sample_boundary(); pip = sample_pip(boundary); task = sample_task(boundary, pip)
    binding = build_pentest_task_binding(boundary_payload=boundary, pip_payload=pip, task_payload=task, now=FIXED_NOW)
    stage46.create_task(task, binding)
    workflow, lifecycle, _, created = stage46.start_workflow(task["pentest_task_id"], start_payload("upgrade47"))
    assert created is True and lifecycle["state"] == "RUNNING"
    assert stage46.migration_level() == 4
    stage47 = PentestCapabilityRepository(db)
    assert stage47.migration_level() == 5
    assert stage47.get_workflow(workflow["workflow_id"])["workflow_status"] == "RUNNING"
    assert stage47.verify_event_stream(boundary["pentest_id"])["status"] == "VERIFIED"
    assert stage47.get_capability_registry()["counts"]["capabilities"] == 7


def test_25_registry_definition_exposes_stage48_boundary_and_no_selection_or_execution():
    definition = canonical_pentest_capability_definition()
    assert definition["capability_registry_enabled"] is True
    assert definition["tool_contract_enabled"] is True
    assert definition["tool_capability_mapping_enabled"] is True
    assert definition["capability_selection_enabled"] is False
    assert definition["execution_intake_enabled"] is False
    assert definition["tool_invocation_enabled"] is False
    assert definition["external_network_io_performed"] is False
    assert definition["target_actuation"] is False
    assert definition["authorization_minting_enabled"] is False
    assert PENTEST_CAPABILITY_NEXT_STAGE == "4.8"


def test_26_tool_contracts_do_not_encode_concrete_exploit_commands_or_runtime_endpoints():
    text = json.dumps(canonical_pentest_tool_contracts(), sort_keys=True).lower()
    assert "127.0.0.1" not in text
    assert "http://" not in text and "https://" not in text
    assert " nmap " not in text
    assert " metasploit " not in text
    assert "msfconsole" not in text
    assert "shell_command" not in text


def test_27_stage47_migration_declares_registry_capability_tool_and_mapping_stores():
    sql = Path("pentest_migrations/005_stage4_7_capability_registry_tool_contract.sql").read_text(encoding="utf-8").lower()
    assert "create table if not exists pentest_capability_registry_snapshots" in sql
    assert "create table if not exists pentest_capability_contracts" in sql
    assert "create table if not exists pentest_tool_contracts" in sql
    assert "create table if not exists pentest_capability_tool_mappings" in sql
