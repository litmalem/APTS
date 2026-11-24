from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from tests._localhost_http import urlopen_local_with_retry

from pentest_subsystem.api_service import PentestSubsystemStage52Handler, PentestSubsystemStage53Handler
from pentest_subsystem.enumeration import (
    ENUMERATED_ASSET_MODEL_SCHEMA_VERSION,
    ENUMERATION_AGENT_CONTROL_VERSION,
    ENUMERATION_AGENT_ID,
    ENUMERATION_AGENT_NEXT_STAGE,
    ENUMERATION_AGENT_REPOSITORY_MIGRATION_LEVEL,
    ENUMERATION_AGENT_SCHEMA_VERSION,
    ENUMERATION_CAPABILITY_ID,
    ENUMERATION_EVIDENCE_CONTRACT_SCHEMA_VERSION,
    ENUMERATION_OUTPUT_SCHEMA_VERSION,
    ENUMERATION_RUN_REQUEST_SCHEMA_VERSION,
    EnumerationAgentConflict,
    EnumerationAgentIntegrityError,
    EnumerationAgentRepository,
    EnumerationAgentService,
    EnumerationAgentValidationError,
    canonical_enumeration_agent_contract,
    deterministic_enumeration_run_id,
    normalize_enumeration_run_request,
    verify_enumerated_asset_model,
    verify_enumeration_agent_contract,
    verify_enumeration_evidence_bundle,
    verify_enumeration_output,
)
from pentest_subsystem.reconnaissance import canonical_reconnaissance_agent_contract
from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import materialize
from tests.test_stage5_1_full_agentic_pentest_workflow_orchestrator import start_payload
from tests.test_stage5_2_reconnaissance_agent import recon_request

CONTROL = "stage5.3-enumeration-agent"
SERVER_VERSION = "APTSPentestSubsystem/5.3"


def enumeration_request(boundary: dict, task: dict, recon_run: dict, suffix: str = "stage53", *, proposals: bool = True) -> dict:
    target = deepcopy(task["target"])
    observations = [
        {
            "observation_id": f"enum-service-{suffix}",
            "kind": "SERVICE",
            "target": target,
            "summary": "Authorized upstream enumeration observed an HTTP service.",
            "attributes": {"host": target["target_value"], "service": "http", "port": 8080, "protocol": "tcp"},
            "confidence": 0.95,
            "observed_at": "2026-09-01T02:00:01Z",
            "source": {
                "source_kind": "IMPORTED_ENUMERATION_RESULT",
                "source_id": f"enum-source-service-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_ENUMERATION",
            },
        },
        {
            "observation_id": f"enum-tech-{suffix}",
            "kind": "TECHNOLOGY",
            "target": target,
            "summary": "Authorized upstream enumeration identified a web technology.",
            "attributes": {"technology": "Apache HTTP Server", "category": "web-server", "endpoint": "/"},
            "confidence": 0.91,
            "observed_at": "2026-09-01T02:00:02Z",
            "source": {
                "source_kind": "IMPORTED_ENUMERATION_RESULT",
                "source_id": f"enum-source-tech-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_ENUMERATION",
            },
        },
        {
            "observation_id": f"enum-version-{suffix}",
            "kind": "VERSION",
            "target": target,
            "summary": "Authorized upstream enumeration identified a product version.",
            "attributes": {"product": "Apache HTTP Server", "version": "2.4.x", "component_type": "server", "service": "http"},
            "confidence": 0.88,
            "observed_at": "2026-09-01T02:00:03Z",
            "source": {
                "source_kind": "IMPORTED_ENUMERATION_RESULT",
                "source_id": f"enum-source-version-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_ENUMERATION",
            },
        },
        {
            "observation_id": f"enum-endpoint-{suffix}",
            "kind": "ENDPOINT",
            "target": target,
            "summary": "Authorized upstream enumeration observed an application endpoint.",
            "attributes": {"endpoint": "/status", "scheme": "http", "method": "GET", "status": 200},
            "confidence": 0.86,
            "observed_at": "2026-09-01T02:00:04Z",
            "source": {
                "source_kind": "IMPORTED_ENUMERATION_RESULT",
                "source_id": f"enum-source-endpoint-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_ENUMERATION",
            },
        },
        {
            "observation_id": f"enum-config-{suffix}",
            "kind": "CONFIGURATION",
            "target": target,
            "summary": "Authorized upstream enumeration observed a non-secret response configuration.",
            "attributes": {"configuration_key": "server_header_present", "configuration_value": True, "classification": "OBSERVED_HEADER"},
            "confidence": 0.84,
            "observed_at": "2026-09-01T02:00:05Z",
            "source": {
                "source_kind": "IMPORTED_ENUMERATION_RESULT",
                "source_id": f"enum-source-config-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_ENUMERATION",
            },
        },
    ]
    enumeration_proposals = []
    if proposals:
        enumeration_proposals.append({
            "proposal_key": f"enum-proposal-{suffix}",
            "target": target,
            "technique": "SERVICE_ENUMERATION",
            "estimated_impact": "LOW",
            "rate_cost": 1,
            "active_concurrency": 1,
            "stop_signals": [],
        })
    return {
        "schema_version": ENUMERATION_RUN_REQUEST_SCHEMA_VERSION,
        "request_id": f"enumreq-{suffix}",
        "idempotency_key": f"idem-enumreq-{suffix}",
        "actor": "stage5.3-pytest",
        "boundary": deepcopy(boundary),
        "reconnaissance_context": {
            "recon_run_id": recon_run["recon_run_id"],
            "output_sha256": recon_run["output"]["integrity"]["canonical_sha256"],
            "evidence_bundle_sha256": recon_run["evidence_bundle"]["integrity"]["canonical_sha256"],
        },
        "observations": observations,
        "enumeration_proposals": enumeration_proposals,
        "metadata": {"test": suffix},
    }


def _start_repo(tmp_path: Path, suffix: str = "stage53"):
    repo = EnumerationAgentRepository(tmp_path / "pentest.db")
    boundary, _, task, _, _ = materialize(repo)
    orch, lifecycle, transitions, created = repo.start_orchestration(task["pentest_task_id"], start_payload(suffix))
    assert created is True
    recon, recon_created = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, suffix))
    assert recon_created is True
    return repo, boundary, task, repo.get_orchestration(orch["orchestration_id"]), recon, lifecycle, transitions


def _start_server(tmp_path: Path):
    service = EnumerationAgentService(EnumerationAgentRepository(tmp_path / "pentest.db"))
    handler = type("IsolatedStage53Handler", (PentestSubsystemStage53Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, service, f"http://127.0.0.1:{server.server_address[1]}"


def _get(url: str):
    with urlopen_local_with_retry(url, timeout=5) as response:
        return response.status, dict(response.headers), json.loads(response.read().decode())


def _post(url: str, payload: dict):
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen_local_with_retry(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_01_contract_binds_stage52_migration10_and_roadmap_functions():
    contract = canonical_enumeration_agent_contract()
    predecessor = canonical_reconnaissance_agent_contract()
    assert contract["control_version"] == CONTROL == ENUMERATION_AGENT_CONTROL_VERSION
    assert contract["schema_version"] == ENUMERATION_AGENT_SCHEMA_VERSION
    assert contract["predecessor"]["control"] == "stage5.2-reconnaissance-agent"
    assert contract["predecessor"]["contract_sha256"] == predecessor["integrity"]["canonical_sha256"]
    assert contract["repository"]["migration_level"] == ENUMERATION_AGENT_REPOSITORY_MIGRATION_LEVEL == 10
    assert contract["functions"] == [
        "service_enumeration", "technology_identification", "version_discovery", "endpoint_discovery", "configuration_observation"
    ]
    assert contract["next_stage"] == ENUMERATION_AGENT_NEXT_STAGE == "5.4"


def test_02_contract_is_sha_bound_and_tamper_fails_closed():
    contract = canonical_enumeration_agent_contract()
    assert verify_enumeration_agent_contract(contract)
    forged = deepcopy(contract)
    forged["runtime"]["target_actuation_enabled"] = True
    assert not verify_enumeration_agent_contract(forged)


def test_03_specialist_is_active_but_has_no_direct_execution_authority():
    contract = canonical_enumeration_agent_contract()
    assert contract["specialist"]["agent_id"] == ENUMERATION_AGENT_ID
    assert contract["specialist"]["capability_id"] == ENUMERATION_CAPABILITY_ID
    assert contract["specialist"]["implementation_available"] is True
    assert contract["specialist"]["execution_authority"] is False
    assert contract["specialist"]["direct_tool_access"] is False
    assert contract["runtime"]["tool_invocation_enabled"] is False
    assert contract["runtime"]["external_network_io_enabled"] is False
    assert contract["runtime"]["controlled_execution_stage"] == "6"


def test_04_run_request_is_strict_and_rejects_raw_command_surface(tmp_path: Path):
    _, boundary, task, _, recon, _, _ = _start_repo(tmp_path, "normalize53")
    payload = enumeration_request(boundary, task, recon, "normalize53")
    normalized = normalize_enumeration_run_request(payload)
    assert normalized["request_id"] == "enumreq-normalize53"
    bad = deepcopy(payload)
    bad["command"] = "service-enumerator --target lab-a.internal"
    with pytest.raises(EnumerationAgentValidationError):
        normalize_enumeration_run_request(bad)


def test_05_enumeration_run_identity_is_deterministic():
    one = deterministic_enumeration_run_id("paorch-stage53")
    two = deterministic_enumeration_run_id("paorch-stage53")
    assert one == two and one.startswith("enumrun-")
    assert one != deterministic_enumeration_run_id("paorch-stage53-other")


def test_06_repository_migrates_to_level10_and_creates_enumeration_store(tmp_path: Path):
    repo = EnumerationAgentRepository(tmp_path / "pentest.db")
    assert repo.migration_level() == 10
    with sqlite3.connect(repo.sqlite_path) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert "pentest_recon_runs" in tables
    assert "pentest_enumeration_runs" in tables
    assert "pentest_lineage_objects" in tables
    assert "pentest_scope_roe_decisions" in tables


def test_07_enumeration_requires_completed_stage52_recon_run(tmp_path: Path):
    repo = EnumerationAgentRepository(tmp_path / "pentest.db")
    boundary, _, task, _, _ = materialize(repo)
    orch, _, _, _ = repo.start_orchestration(task["pentest_task_id"], start_payload("missing-recon53"))
    recon_node = orch["task_graph"]["nodes"][0]
    repo.record_progress(orch["orchestration_id"], {
        "progress_id": "paoprogress-fake-recon53",
        "idempotency_key": "idem-paoprogress-fake-recon53",
        "subtask_id": recon_node["subtask_id"],
        "source_agent_id": recon_node["specialist"]["agent_id"],
        "status": "SUCCEEDED",
        "summary": "compatibility-only recon completion without Stage 5.2 run",
        "evidence_refs": [],
        "metadata": {},
    })
    fake_recon = {
        "recon_run_id": "reconrun-" + "a" * 48,
        "output": {"integrity": {"canonical_sha256": "b" * 64}},
        "evidence_bundle": {"integrity": {"canonical_sha256": "c" * 64}},
    }
    with pytest.raises(EnumerationAgentConflict):
        repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, fake_recon, "missing-recon53"))


def test_08_predecessor_recon_context_must_match_exact_authoritative_hashes(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "recon-bind53")
    payload = enumeration_request(boundary, task, recon, "recon-bind53")
    payload["reconnaissance_context"]["output_sha256"] = "f" * 64
    with pytest.raises(EnumerationAgentConflict):
        repo.run_enumeration(orch["orchestration_id"], payload)


def test_09_run_materializes_all_roadmap_enumeration_functions(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "output53")
    run, created = repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "output53"))
    assert created is True and run["run_status"] == "COMPLETED"
    output = run["output"]
    assert output["schema_version"] == ENUMERATION_OUTPUT_SCHEMA_VERSION
    assert verify_enumeration_output(output)
    assert len(output["service_observations"]) == 1
    assert len(output["technology_identifications"]) == 1
    assert len(output["version_discoveries"]) == 1
    assert len(output["endpoint_discoveries"]) == 1
    assert len(output["configuration_observations"]) == 1
    assert output["confidence"]["basis_observations"] == 5


def test_10_enumerated_asset_model_is_integrity_bound_and_evidence_linked(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "asset53")
    run, _ = repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "asset53"))
    assets = run["output"]["enumerated_assets"]
    assert len(assets) == 1
    asset = assets[0]
    assert asset["schema_version"] == ENUMERATED_ASSET_MODEL_SCHEMA_VERSION
    assert verify_enumerated_asset_model(asset)
    assert asset["target"] == task["target"]
    assert asset["services"][0]["port"] == 8080
    assert asset["technologies"][0]["technology"] == "Apache HTTP Server"
    assert asset["versions"][0]["version"] == "2.4.x"
    assert asset["endpoints"][0]["endpoint"] == "/status"
    assert asset["configuration_observations"][0]["configuration_key"] == "server_header_present"
    assert len(asset["evidence_refs"]) == 5


def test_11_enumeration_evidence_bundle_binds_recon_request_output_assets_and_lineage(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "bundle53")
    run, _ = repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "bundle53"))
    bundle = run["evidence_bundle"]
    assert bundle["schema_version"] == ENUMERATION_EVIDENCE_CONTRACT_SCHEMA_VERSION
    assert verify_enumeration_evidence_bundle(bundle)
    assert bundle["request_sha256"] == run["request_sha256"]
    assert bundle["output_sha256"] == run["output"]["integrity"]["canonical_sha256"]
    assert bundle["predecessor_reconnaissance"]["recon_run_id"] == recon["recon_run_id"]
    assert len(bundle["asset_model_sha256"]) == 1
    assert len(bundle["lineage_items"]) == 5


def test_12_every_imported_enumeration_observation_creates_stage49_lineage(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "lineage53")
    repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "lineage53", proposals=False))
    records = repo.list_lineage_objects(task["pentest_task_id"])
    stage53_obs = [x for x in records if x["record_type"] == "OBSERVATION" and x["record"]["provenance"]["source_system"] == "APTS_PENTEST_STAGE5_3"]
    stage53_evi = [x for x in records if x["record_type"] == "EVIDENCE" and x["record"]["provenance"]["source_system"] == "APTS_PENTEST_STAGE5_3"]
    assert len(stage53_obs) == 5 and len(stage53_evi) == 5
    for item in [*stage53_obs, *stage53_evi]:
        assert item["record"]["identity"]["mission_id"] == task["mission_id"]


def test_13_in_scope_enumeration_proposal_is_governed_and_not_executed(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "proposal53")
    payload = enumeration_request(boundary, task, recon, "proposal53")
    # The test boundary explicitly permits the fixed Stage-6 enumeration adapter.
    payload["enumeration_proposals"][0]["technique"] = "TCP_BANNER_READ"
    run, _ = repo.run_enumeration(orch["orchestration_id"], payload)
    gov = run["output"]["governance"][0]
    proposal = run["output"]["action_proposals"][0]
    assert gov["status"] == "ELIGIBLE" and gov["scope_roe_eligible"] is True
    assert gov["decision_is_authorization"] is False
    assert proposal["execution_status"] == "DEFERRED_TO_STAGE6"
    assert run["output"]["semantics"]["target_actuation"] is False


def test_14_boundary_allowed_but_local_task_out_of_scope_proposal_fails_closed(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "local-scope53")
    payload = enumeration_request(boundary, task, recon, "local-scope53", proposals=False)
    payload["enumeration_proposals"] = [{
        "proposal_key": "outside-local53",
        "target": deepcopy(boundary["scope"]["targets"][1]),
        "technique": "SERVICE_ENUMERATION",
        "estimated_impact": "LOW",
    }]
    run, _ = repo.run_enumeration(orch["orchestration_id"], payload)
    gov = run["output"]["governance"][0]
    assert gov["status"] == "INELIGIBLE"
    assert gov["local_task_scope_precheck"] is False
    assert run["output"]["action_proposals"] == []
    decisions = repo.list_scope_roe_decisions(task["pentest_task_id"])
    assert any("STAGE5_3_LOCAL_TASK_SCOPE" in d["decision"]["failed_rule_ids"] for d in decisions)


def test_15_outside_local_task_observation_is_evidence_only_and_excluded_from_asset_model(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "observed-only53")
    payload = enumeration_request(boundary, task, recon, "observed-only53", proposals=False)
    payload["observations"][0]["target"] = deepcopy(boundary["scope"]["targets"][1])
    payload["observations"][0]["attributes"]["host"] = boundary["scope"]["targets"][1]["target_value"]
    run, _ = repo.run_enumeration(orch["orchestration_id"], payload)
    raw = next(x for x in run["output"]["raw_evidence"] if x["observation_id"] == "enum-service-observed-only53")
    assert raw["scope_status"] == "OUTSIDE_LOCAL_TASK_SCOPE_OBSERVED_ONLY"
    assert all(asset["target"] != boundary["scope"]["targets"][1] for asset in run["output"]["enumerated_assets"])
    assert len(run["output"]["service_observations"]) == 0


def test_16_exact_replay_is_idempotent_and_does_not_duplicate_lineage_or_progress(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "replay53")
    payload = enumeration_request(boundary, task, recon, "replay53")
    # Keep the proposal eligible under the fixture's explicit technique allowlist.
    payload["enumeration_proposals"][0]["technique"] = "TCP_BANNER_READ"
    first, c1 = repo.run_enumeration(orch["orchestration_id"], payload)
    second, c2 = repo.run_enumeration(orch["orchestration_id"], payload)
    assert c1 is True and c2 is False
    assert first["enumeration_run_id"] == second["enumeration_run_id"]
    with sqlite3.connect(repo.sqlite_path) as conn:
        assert conn.execute("select count(*) from pentest_enumeration_runs").fetchone()[0] == 1
        assert conn.execute("select count(*) from pentest_agentic_progress_records").fetchone()[0] == 2
        assert conn.execute("select count(*) from pentest_lineage_objects").fetchone()[0] == 20


def test_17_changed_request_after_completed_run_conflicts(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "conflict53")
    payload = enumeration_request(boundary, task, recon, "conflict53")
    repo.run_enumeration(orch["orchestration_id"], payload)
    changed = deepcopy(payload)
    changed["observations"][0]["confidence"] = 0.31
    with pytest.raises(EnumerationAgentConflict):
        repo.run_enumeration(orch["orchestration_id"], changed)


def test_18_successful_enumeration_handoff_releases_vulnerability_hypothesis(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "handoff53")
    repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "handoff53"))
    updated = repo.get_orchestration(orch["orchestration_id"])
    assert updated is not None
    assert updated["task_graph"]["nodes"][1]["capability_id"] == "enumeration"
    assert updated["task_graph"]["nodes"][1]["status"] == "SUCCEEDED"
    assert updated["task_graph"]["nodes"][2]["capability_id"] == "vulnerability_analysis"
    assert updated["task_graph"]["nodes"][2]["status"] == "READY"


def test_19_restart_preserves_enumeration_run_and_integrity(tmp_path: Path):
    path = tmp_path / "pentest.db"
    repo = EnumerationAgentRepository(path)
    boundary, _, task, _, _ = materialize(repo)
    orch, _, _, _ = repo.start_orchestration(task["pentest_task_id"], start_payload("restart53"))
    recon, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "restart53"))
    first, _ = repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "restart53"))
    repo2 = EnumerationAgentRepository(path)
    second = repo2.get_enumeration_run(first["enumeration_run_id"])
    assert second is not None
    assert second["output"]["integrity"] == first["output"]["integrity"]
    assert repo2.migration_level() == 10


def test_20_persisted_enumeration_output_tamper_fails_integrity_check(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "tamper53")
    run, _ = repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "tamper53"))
    with sqlite3.connect(repo.sqlite_path) as conn:
        row = conn.execute("select output_json from pentest_enumeration_runs where enumeration_run_id=?", (run["enumeration_run_id"],)).fetchone()
        output = json.loads(row[0])
        output["semantics"]["target_actuation"] = True
        conn.execute("update pentest_enumeration_runs set output_json=? where enumeration_run_id=?", (json.dumps(output, sort_keys=True), run["enumeration_run_id"]))
    with pytest.raises(EnumerationAgentIntegrityError):
        repo.get_enumeration_run(run["enumeration_run_id"])


def test_21_health_activates_stage53_and_preserves_non_execution_boundary(tmp_path: Path):
    service = EnumerationAgentService(EnumerationAgentRepository(tmp_path / "pentest.db"))
    health = service.health()
    assert health["control_version"] == CONTROL
    assert health["pentest_repository_migration_level"] == 10
    assert health["stage5_3_enumeration_agent_enabled"] is True
    assert health["stage5_3_enumerated_asset_model_enabled"] is True
    assert health["stage5_3_predecessor_recon_binding_enabled"] is True
    assert health["stage5_3_execution_intake_enabled"] is False
    assert health["stage5_3_tool_invocation_enabled"] is False
    assert health["stage5_3_external_network_io_performed"] is False
    assert health["stage5_3_target_actuation"] is False
    assert health["stage5_3_next_stage"] == "5.4"


def test_22_http_contract_run_get_list_and_handoff(tmp_path: Path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        boundary, _, task, _, _ = materialize(service.repository)
        orch, _, _, _ = service.repository.start_orchestration(task["pentest_task_id"], start_payload("http53"))
        recon, _ = service.repository.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "http53"))
        status, headers, health = _get(base + "/health")
        assert status == 200 and SERVER_VERSION in headers["Server"] and health["control_version"] == CONTROL
        status, _, contract = _get(base + "/api/pentest/enumeration-agent-contract")
        assert status == 200 and contract["control_version"] == CONTROL
        status, result = _post(base + f"/api/pentest/agentic-orchestrations/{orch['orchestration_id']}/enumeration/run", enumeration_request(boundary, task, recon, "http53"))
        assert status == 201 and result["created"] is True and result["execution_started"] is False
        run_id = result["run"]["enumeration_run_id"]
        status, _, fetched = _get(base + f"/api/pentest/enumeration-runs/{run_id}")
        assert status == 200 and fetched["run"]["enumeration_run_id"] == run_id
        status, _, listed = _get(base + "/api/pentest/enumeration-runs?limit=10")
        assert status == 200 and listed["count"] == 1
        assert result["orchestration"]["task_graph"]["nodes"][2]["status"] == "READY"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_23_http_execution_dispatch_remains_rejected_for_stage53(tmp_path: Path):
    server, thread, _, base = _start_server(tmp_path)
    try:
        status, rejected = _post(base + "/api/execution/dispatches", {})
        assert status == 409
        assert rejected["error_code"] == "STAGE5_3_CONTROLLED_EXECUTION_NOT_ENABLED"
        assert rejected["enumeration_agent_enabled"] is True
        assert rejected["execution_started"] is False
        assert rejected["tool_invocation_performed"] is False
        assert rejected["target_actuation"] is False
        assert rejected["next_stage"] == "5.4"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_24_http_run_rejects_raw_command_field(tmp_path: Path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        boundary, _, task, _, _ = materialize(service.repository)
        orch, _, _, _ = service.repository.start_orchestration(task["pentest_task_id"], start_payload("http-invalid53"))
        recon, _ = service.repository.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "http-invalid53"))
        payload = enumeration_request(boundary, task, recon, "http-invalid53")
        payload["command"] = "nmap -sV target"
        status, result = _post(base + f"/api/pentest/agentic-orchestrations/{orch['orchestration_id']}/enumeration/run", payload)
        assert status == 400 and result["status"] == "invalid"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_25_stage52_handler_is_preserved_and_stage53_is_active_successor():
    assert PentestSubsystemStage52Handler.server_version == "APTSPentestSubsystem/5.2"
    assert PentestSubsystemStage53Handler.server_version == SERVER_VERSION
    assert issubclass(PentestSubsystemStage53Handler, PentestSubsystemStage52Handler)


def test_26_contract_and_output_preserve_governance_lineage_predecessor_and_stage6_boundaries(tmp_path: Path):
    repo, boundary, task, orch, recon, _, _ = _start_repo(tmp_path, "semantics53")
    run, _ = repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "semantics53"))
    contract = canonical_enumeration_agent_contract()
    assert contract["asset_model"]["schema_version"] == ENUMERATED_ASSET_MODEL_SCHEMA_VERSION
    assert contract["evidence_contract"]["stage4_9_lineage_required"] is True
    assert contract["evidence_contract"]["predecessor_recon_binding_required"] is True
    assert contract["governance"]["stage4_8_scope_roe_evaluation_required_for_action_proposals"] is True
    assert contract["governance"]["decision_is_authorization"] is False
    assert run["output"]["predecessor_reconnaissance"]["recon_run_id"] == recon["recon_run_id"]
    assert run["output"]["semantics"]["act_semantics"] == "PUBLISH_GOVERNED_ENUMERATION_ACTION_PROPOSAL_ONLY"
    assert run["output"]["semantics"]["controlled_execution_deferred_to_stage6"] is True
    assert run["output"]["semantics"]["authorization_minted"] is False
