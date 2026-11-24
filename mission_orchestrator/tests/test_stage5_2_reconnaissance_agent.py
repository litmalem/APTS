from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from tests._localhost_http import urlopen_local_with_retry

from pentest_subsystem.api_service import PentestSubsystemStage51Handler, PentestSubsystemStage52Handler
from pentest_subsystem.orchestration.orchestrator import canonical_agentic_pentest_orchestrator_contract
from pentest_subsystem.reconnaissance import (
    RECONNAISSANCE_AGENT_CONTROL_VERSION,
    RECONNAISSANCE_AGENT_ID,
    RECONNAISSANCE_AGENT_NEXT_STAGE,
    RECONNAISSANCE_AGENT_REPOSITORY_MIGRATION_LEVEL,
    RECONNAISSANCE_AGENT_SCHEMA_VERSION,
    RECONNAISSANCE_CAPABILITY_ID,
    RECONNAISSANCE_EVIDENCE_CONTRACT_SCHEMA_VERSION,
    RECONNAISSANCE_OUTPUT_SCHEMA_VERSION,
    RECONNAISSANCE_RUN_REQUEST_SCHEMA_VERSION,
    RECONNAISSANCE_RUN_REQUEST_LEGACY_SCHEMA_VERSION,
    RECON_ACTION_REQUEST_SCHEMA_VERSION,
    ReconnaissanceAgentConflict,
    ReconnaissanceAgentIntegrityError,
    ReconnaissanceAgentRepository,
    ReconnaissanceAgentService,
    ReconnaissanceAgentValidationError,
    canonical_reconnaissance_agent_contract,
    deterministic_reconnaissance_run_id,
    normalize_reconnaissance_run_request,
    normalize_recon_action_request,
    derive_recon_action_proposals,
    derive_recon_observation_needs,
    verify_recon_evidence_bundle,
    verify_reconnaissance_agent_contract,
    verify_reconnaissance_output,
)
from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import materialize
from tests.test_stage4_4_pentest_lifecycle_state import sample_boundary
from tests.test_stage5_1_full_agentic_pentest_workflow_orchestrator import start_payload

CONTROL = "stage5.2-reconnaissance-agent"
SERVER_VERSION = "APTSPentestSubsystem/5.2"
FIXED_OBSERVED_AT = "2026-09-01T01:02:03Z"


def recon_request(boundary: dict, task: dict, suffix: str = "stage52", *, proposals: bool = False) -> dict:
    target = deepcopy(task["target"])
    observations = [
        {
            "observation_id": f"host-{suffix}",
            "kind": "HOST",
            "target": target,
            "summary": "Authorized upstream source observed the target host.",
            "attributes": {"host": target["target_value"]},
            "confidence": 0.94,
            "observed_at": FIXED_OBSERVED_AT,
            "source": {
                "source_kind": "IMPORTED_SENSOR",
                "source_id": f"source-host-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_DISCOVERY",
            },
        },
        {
            "observation_id": f"domain-{suffix}",
            "kind": "DOMAIN",
            "target": target,
            "summary": "Authorized upstream source mapped a domain to the target.",
            "attributes": {"domain": target["target_value"]},
            "confidence": 0.90,
            "observed_at": "2026-09-01T01:02:04Z",
            "source": {
                "source_kind": "IMPORTED_SENSOR",
                "source_id": f"source-domain-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_DISCOVERY",
            },
        },
        {
            "observation_id": f"service-{suffix}",
            "kind": "SERVICE",
            "target": target,
            "summary": "Authorized upstream source observed an HTTP service.",
            "attributes": {"host": target["target_value"], "service": "http", "port": 8080, "protocol": "tcp"},
            "confidence": 0.88,
            "observed_at": "2026-09-01T01:02:05Z",
            "source": {
                "source_kind": "IMPORTED_SENSOR",
                "source_id": f"source-service-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_DISCOVERY",
            },
        },
        {
            "observation_id": f"surface-{suffix}",
            "kind": "ATTACK_SURFACE",
            "target": target,
            "summary": "Web-facing service is part of the observed attack surface.",
            "attributes": {"surface": "web", "service": "http", "port": 8080},
            "confidence": 0.86,
            "observed_at": "2026-09-01T01:02:06Z",
            "source": {
                "source_kind": "IMPORTED_SENSOR",
                "source_id": f"source-surface-{suffix}",
                "collection_method": "AUTHORIZED_UPSTREAM_DISCOVERY",
            },
        },
    ]
    discovery_proposals = []
    if proposals:
        discovery_proposals.append(
            {
                "proposal_key": f"passive-{suffix}",
                "target": target,
                "technique": "PASSIVE_DISCOVERY",
                "estimated_impact": "NONE",
                "rate_cost": 0,
                "active_concurrency": 0,
                "stop_signals": [],
            }
        )
    result = {
        "schema_version": RECONNAISSANCE_RUN_REQUEST_SCHEMA_VERSION,
        "request_id": f"reconreq-{suffix}",
        "idempotency_key": f"idem-reconreq-{suffix}",
        "actor": "stage5.2-pytest",
        "boundary": deepcopy(boundary),
        "observations": observations,
        "metadata": {"test": suffix},
    }
    if proposals:
        result["schema_version"] = RECONNAISSANCE_RUN_REQUEST_LEGACY_SCHEMA_VERSION
        result["discovery_proposals"] = discovery_proposals
    return result


def _start_repo(tmp_path: Path, suffix: str = "stage52", boundary: dict | None = None):
    repo = ReconnaissanceAgentRepository(tmp_path / "pentest.db")
    if boundary is None:
        boundary, _, task, _, _ = materialize(repo)
    else:
        from tests import test_stage4_6_pentest_workflow_orchestrator_skeleton as materialize_module
        original_boundary = materialize_module.sample_boundary
        materialize_module.sample_boundary = lambda: deepcopy(boundary)
        try:
            boundary, _, task, _, _ = materialize(repo)
        finally:
            materialize_module.sample_boundary = original_boundary
    orch, lifecycle, transitions, created = repo.start_orchestration(task["pentest_task_id"], start_payload(suffix))
    assert created is True
    return repo, boundary, task, orch, lifecycle, transitions


def _start_server(tmp_path: Path):
    service = ReconnaissanceAgentService(ReconnaissanceAgentRepository(tmp_path / "pentest.db"))
    handler = type("IsolatedStage52Handler", (PentestSubsystemStage52Handler,), {"service": service})
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


def test_01_contract_binds_stage51_and_migration9_and_roadmap_outputs():
    contract = canonical_reconnaissance_agent_contract()
    predecessor = canonical_agentic_pentest_orchestrator_contract()
    assert contract["control_version"] == CONTROL == RECONNAISSANCE_AGENT_CONTROL_VERSION
    assert contract["schema_version"] == RECONNAISSANCE_AGENT_SCHEMA_VERSION
    assert contract["predecessor"]["control"] == "stage5.1-full-agentic-pentest-workflow-orchestrator"
    assert contract["predecessor"]["contract_sha256"] == predecessor["integrity"]["canonical_sha256"]
    assert contract["repository"]["migration_level"] == RECONNAISSANCE_AGENT_REPOSITORY_MIGRATION_LEVEL == 10
    assert contract["loop"] == ["OBSERVE", "REASON", "PROPOSE", "GOVERN", "ACT", "OBSERVE"]
    assert contract["outputs"] == ["hosts", "domains", "services", "attack_surface", "raw_evidence", "confidence"]
    assert contract["next_stage"] == RECONNAISSANCE_AGENT_NEXT_STAGE == "5.3"


def test_02_contract_is_sha_bound_and_tamper_fails_closed():
    contract = canonical_reconnaissance_agent_contract()
    assert verify_reconnaissance_agent_contract(contract)
    forged = deepcopy(contract)
    forged["runtime"]["target_actuation_enabled"] = True
    assert not verify_reconnaissance_agent_contract(forged)


def test_03_specialist_is_active_but_has_no_direct_execution_authority():
    contract = canonical_reconnaissance_agent_contract()
    assert contract["specialist"]["agent_id"] == RECONNAISSANCE_AGENT_ID
    assert contract["specialist"]["implementation_available"] is True
    assert contract["specialist"]["execution_authority"] is False
    assert contract["specialist"]["direct_tool_access"] is False
    assert contract["specialist"]["external_network_access"] is False
    assert contract["runtime"]["tool_invocation_enabled"] is False
    assert contract["runtime"]["external_network_io_enabled"] is False
    assert contract["runtime"]["target_actuation_enabled"] is False
    assert contract["runtime"]["controlled_execution_stage"] == "6"


def test_04_run_request_is_strict_and_rejects_raw_command_surface(tmp_path: Path):
    _, boundary, task, _, _, _ = _start_repo(tmp_path, "normalize")
    payload = recon_request(boundary, task, "normalize")
    normalized = normalize_reconnaissance_run_request(payload)
    assert normalized["request_id"] == "reconreq-normalize"
    bad = deepcopy(payload)
    bad["command"] = "nmap target"
    with pytest.raises(ReconnaissanceAgentValidationError):
        normalize_reconnaissance_run_request(bad)


def test_05_recon_run_identity_is_deterministic():
    one = deterministic_reconnaissance_run_id("paorch-stage52")
    two = deterministic_reconnaissance_run_id("paorch-stage52")
    assert one == two and one.startswith("reconrun-")
    assert one != deterministic_reconnaissance_run_id("paorch-stage52-other")


def test_06_repository_migrates_to_level9_and_creates_recon_store(tmp_path: Path):
    repo = ReconnaissanceAgentRepository(tmp_path / "pentest.db")
    assert repo.migration_level() == 10
    with sqlite3.connect(repo.sqlite_path) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert "pentest_recon_runs" in tables
    assert "pentest_agentic_orchestrations" in tables
    assert "pentest_lineage_objects" in tables
    assert "pentest_scope_roe_decisions" in tables


def test_07_recon_requires_stage51_recon_subtask_ready_or_running(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "not-ready")
    first = orch["task_graph"]["nodes"][0]
    # Complete recon through the Stage-5.1 compatibility surface first; a second new Stage-5.2 run is then invalid.
    repo.record_progress(orch["orchestration_id"], {
        "progress_id": "paoprogress-precompleted",
        "idempotency_key": "idem-paoprogress-precompleted",
        "subtask_id": first["subtask_id"],
        "source_agent_id": first["specialist"]["agent_id"],
        "status": "SUCCEEDED",
        "summary": "pre-complete",
        "evidence_refs": [],
        "metadata": {},
    })
    with pytest.raises(ReconnaissanceAgentConflict):
        repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "not-ready"))


def test_08_run_materializes_required_recon_outputs_and_integrity(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "output")
    run, created = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "output"))
    assert created is True and run["run_status"] == "COMPLETED"
    output = run["output"]
    assert output["schema_version"] == RECONNAISSANCE_OUTPUT_SCHEMA_VERSION
    assert verify_reconnaissance_output(output)
    assert output["hosts"][0]["host"] == task["target"]["target_value"]
    assert output["domains"][0]["domain"] == task["target"]["target_value"]
    assert output["services"][0]["port"] == 8080
    assert output["attack_surface"]["service_count"] == 1
    assert len(output["raw_evidence"]) == 4
    assert output["confidence"]["basis_observations"] == 4


def test_09_recon_evidence_bundle_is_hash_bound_to_request_output_and_lineage(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "bundle")
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "bundle"))
    bundle = run["evidence_bundle"]
    assert bundle["schema_version"] == RECONNAISSANCE_EVIDENCE_CONTRACT_SCHEMA_VERSION
    assert verify_recon_evidence_bundle(bundle)
    assert bundle["request_sha256"] == run["request_sha256"]
    assert bundle["output_sha256"] == run["output"]["integrity"]["canonical_sha256"]
    assert len(bundle["lineage_items"]) == 4


def test_10_every_imported_observation_creates_observation_and_evidence_lineage(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "lineage")
    repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "lineage", proposals=False))
    records = repo.list_lineage_objects(task["pentest_task_id"])
    kinds = [item["record_type"] for item in records]
    assert kinds.count("OBSERVATION") == 4
    assert kinds.count("EVIDENCE") == 4
    assert "ACTION_RESULT" not in kinds
    for item in records:
        assert item["record"]["identity"]["mission_id"] == task["mission_id"]


def test_11_in_scope_discovery_proposal_is_governed_and_published_not_executed(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "proposal")
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "proposal"))
    gov = run["output"]["governance"][0]
    proposal = run["output"]["action_proposals"][0]
    action_request = run["output"]["action_requests"][0]
    assert gov["status"] == "ELIGIBLE" and gov["scope_roe_eligible"] is True
    assert gov["decision_is_authorization"] is False
    assert proposal["execution_status"] == "DEFERRED_TO_STAGE6"
    assert proposal["need_codes"]
    assert "older than the seven-day freshness window" in proposal["rationale"]
    assert action_request["schema_version"] == RECON_ACTION_REQUEST_SCHEMA_VERSION
    assert action_request["proposal_ref"] == proposal["action_proposal_ref"]
    assert action_request["mission_id"] == task["mission_id"]
    assert action_request["task_id"] == task["pentest_task_id"]
    assert action_request["orchestration_id"] == orch["orchestration_id"]
    assert action_request["capability_id"] == "reconnaissance"
    assert action_request["request_status"] == "PROPOSED_AWAITING_STAGE6_INTAKE"
    assert action_request["semantics"]["request_is_authorization"] is False
    assert action_request["semantics"]["external_network_io_performed"] is False
    assert normalize_recon_action_request(action_request) == action_request
    lifecycle = proposal["proposal_lifecycle"]
    assert lifecycle["current_status"] == "AWAITING_STAGE6_INTAKE"
    assert [x["to_status"] for x in lifecycle["transitions"]] == [
        "PROPOSED", "VALIDATED", "AWAITING_STAGE6_INTAKE"
    ]
    assert lifecycle["binding"]["orchestration_id"] == orch["orchestration_id"]
    assert lifecycle["binding"]["task_id"] == task["pentest_task_id"]
    assert lifecycle["binding"]["assigned_agent_id"] == RECONNAISSANCE_AGENT_ID
    assert lifecycle["semantics"]["gss_authorized"] is False
    stage6_validation = repo.validate_recon_action_request_for_stage6(action_request["action_id"])
    assert stage6_validation["status"] == "VALIDATED_AWAITING_GSS"
    assert stage6_validation["source_proposal_integrity_verified"] is True
    records = repo.list_lineage_objects(task["pentest_task_id"])
    assert [item["record_type"] for item in records].count("ACTION_PROPOSAL") == 1
    assert [item["record_type"] for item in records].count("ACTION_RESULT") == 0
    assert run["output"]["semantics"]["target_actuation"] is False


def test_11d_lifecycle_or_orchestration_closure_blocks_stage6_intake(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "lifecycle-block")
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "lifecycle-block"))
    action_id = run["output"]["action_requests"][0]["action_id"]
    with sqlite3.connect(repo.sqlite_path) as conn:
        conn.execute(
            "UPDATE pentest_task_lifecycle SET state='WAITING', state_version=state_version+1 WHERE pentest_task_id=?",
            (task["pentest_task_id"],),
        )
    with pytest.raises(ReconnaissanceAgentConflict, match="lifecycle to remain RUNNING"):
        repo.validate_recon_action_request_for_stage6(action_id)

    repo2, boundary2, task2, orch2, _, _ = _start_repo(tmp_path, "orchestration-block")
    run2, _ = repo2.run_reconnaissance(orch2["orchestration_id"], recon_request(boundary2, task2, "orchestration-block"))
    with sqlite3.connect(repo2.sqlite_path) as conn:
        conn.execute(
            "UPDATE pentest_agentic_orchestrations SET orchestration_status='TERMINATED' WHERE orchestration_id=?",
            (orch2["orchestration_id"],),
        )
    with pytest.raises(ReconnaissanceAgentConflict, match="orchestration is closed"):
        repo2.validate_recon_action_request_for_stage6(run2["output"]["action_requests"][0]["action_id"])


def test_11e_non_running_lifecycle_cannot_publish_action_proposal(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "lifecycle-before-publish")
    with sqlite3.connect(repo.sqlite_path) as conn:
        conn.execute(
            "UPDATE pentest_task_lifecycle SET state='WAITING', state_version=state_version+1 WHERE pentest_task_id=?",
            (task["pentest_task_id"],),
        )
    with pytest.raises(ReconnaissanceAgentConflict, match="requires Pentest lifecycle RUNNING"):
        repo.run_reconnaissance(
            orch["orchestration_id"],
            recon_request(boundary, task, "lifecycle-before-publish"),
        )
    assert repo.list_lineage_objects(task["pentest_task_id"], record_type="ACTION_PROPOSAL") == []


def test_11a_action_request_rejects_tampering_unknown_fields_and_invalid_binding(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "request-contract")
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "request-contract"))
    request = run["output"]["action_requests"][0]
    forged = deepcopy(request)
    forged["target_ref"]["target_value"] = "outside.example"
    with pytest.raises(ReconnaissanceAgentIntegrityError):
        normalize_recon_action_request(forged)
    unknown = deepcopy(request)
    unknown["command"] = "nmap target"
    with pytest.raises(ReconnaissanceAgentValidationError):
        normalize_recon_action_request(unknown)
    no_auth = deepcopy(request)
    no_auth["semantics"]["request_is_authorization"] = True
    no_auth["integrity"] = {
        **no_auth["integrity"],
        "canonical_sha256": request["integrity"]["canonical_sha256"],
    }
    with pytest.raises(ReconnaissanceAgentValidationError):
        normalize_recon_action_request(no_auth)


def test_11b_recon_derives_proposals_from_missing_stale_and_low_confidence_coverage(tmp_path: Path):
    _, boundary, task, _, _, _ = _start_repo(tmp_path, "derive-needs")
    payload = recon_request(boundary, task, "derive-needs")
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    observations = deepcopy(payload["observations"])
    observations = [item for item in observations if item["kind"] != "SERVICE"]
    for item in observations:
        item["observed_at"] = (datetime.now(timezone.utc) - timedelta(days=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        item["confidence"] = 0.72
    plan = derive_recon_observation_needs(observations=observations, task=task, as_of=as_of)
    codes = {item["need_code"] for item in plan["needs"]}
    assert "MISSING_SERVICE_COVERAGE" in codes
    assert "STALE_HOST_OBSERVATION" in codes
    assert "LOW_CONFIDENCE_HOST_OBSERVATION" in codes
    proposals = derive_recon_action_proposals(plan)
    assert len(proposals) == 1
    assert proposals[0]["target"] == task["target"]
    assert set(proposals[0]["need_codes"]) == codes
    assert proposals[0]["technique"] == "TCP_CONNECT_SCAN"


@pytest.mark.parametrize("missing_grant", ["technique", "concurrency", "budget"])
def test_active_recon_requires_explicit_technique_and_single_request_budget(tmp_path: Path, missing_grant: str):
    boundary = sample_boundary()
    if missing_grant == "technique":
        boundary["roe"].pop("allowed_techniques", None)
    elif missing_grant == "concurrency":
        boundary["roe"].pop("maximum_concurrency", None)
    else:
        boundary["constraints"].pop("resource_budget", None)
    repo, boundary, task, orch, _, _ = _start_repo(
        tmp_path, "explicit-active-roe-" + missing_grant, boundary)
    payload = recon_request(boundary, task, "explicit-active-roe-" + missing_grant)
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], payload)
    assert run["output"]["governance"][0]["status"] == "INELIGIBLE"
    assert run["output"]["governance"][0]["explicit_active_roe_precheck"] is False
    assert run["output"]["action_proposals"] == []
    assert run["output"]["action_requests"] == []


def test_11c_recon_detects_conflicting_observations_and_suppresses_fully_met_needs(tmp_path: Path):
    _, boundary, task, _, _, _ = _start_repo(tmp_path, "contradiction")
    payload = recon_request(boundary, task, "contradiction")
    as_of_dt = datetime.now(timezone.utc).replace(microsecond=0)
    fresh_ts = (as_of_dt - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    observations = deepcopy(payload["observations"])
    for item in observations:
        item["observed_at"] = fresh_ts
        item["confidence"] = 0.95
    plan = derive_recon_observation_needs(observations=observations, task=task, as_of=as_of_dt.isoformat().replace("+00:00", "Z"))
    assert plan["needs"] == []
    assert derive_recon_action_proposals(plan) == []

    left = next(item for item in observations if item["kind"] == "SERVICE")
    left["attributes"]["version"] = "1.2"
    right = deepcopy(left)
    right["observation_id"] = "service-conflicting-version"
    right["attributes"]["version"] = "2.0"
    right["observed_at"] = fresh_ts
    observations.append(right)
    plan = derive_recon_observation_needs(observations=observations, task=task, as_of=as_of_dt.isoformat().replace("+00:00", "Z"))
    assert "CONTRADICTORY_SERVICE_OBSERVATIONS" in {item["need_code"] for item in plan["needs"]}


def test_12_boundary_allowed_but_local_task_out_of_scope_proposal_fails_closed(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "localscope")
    payload = recon_request(boundary, task, "localscope", proposals=True)
    payload["discovery_proposals"] = [{
        "proposal_key": "outside-local",
        "target": deepcopy(boundary["scope"]["targets"][1]),
        "technique": "PASSIVE_DISCOVERY",
        "estimated_impact": "NONE",
    }]
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], payload)
    assert run["output"]["observation_plan"]["needs"]
    assert run["output"]["action_proposals"]
    assert all(item["target"] == task["target"] for item in run["output"]["action_proposals"])
    assert all(item["target"] != boundary["scope"]["targets"][1] for item in run["output"]["action_proposals"])
    assert "discovery_proposals" in run["request"]  # legacy input retained for audit only


def test_13_outside_local_task_observation_is_preserved_as_observed_only(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "observed-only")
    payload = recon_request(boundary, task, "observed-only", proposals=False)
    payload["observations"][0]["target"] = deepcopy(boundary["scope"]["targets"][1])
    payload["observations"][0]["attributes"] = {"host": boundary["scope"]["targets"][1]["target_value"]}
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], payload)
    first = next(x for x in run["output"]["raw_evidence"] if x["observation_id"] == "host-observed-only")
    assert first["scope_status"] == "OUTSIDE_LOCAL_TASK_SCOPE_OBSERVED_ONLY"
    assert run["output"]["semantics"]["external_network_io_performed"] is False


def test_14_exact_replay_is_idempotent_and_does_not_duplicate_lineage_or_progress(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "replay")
    payload = recon_request(boundary, task, "replay")
    first, c1 = repo.run_reconnaissance(orch["orchestration_id"], payload)
    second, c2 = repo.run_reconnaissance(orch["orchestration_id"], payload)
    assert c1 is True and c2 is False
    assert first["recon_run_id"] == second["recon_run_id"]
    with sqlite3.connect(repo.sqlite_path) as conn:
        assert conn.execute("select count(*) from pentest_recon_runs").fetchone()[0] == 1
        assert conn.execute("select count(*) from pentest_agentic_progress_records").fetchone()[0] == 1
        assert conn.execute("select count(*) from pentest_lineage_objects").fetchone()[0] == 9


def test_15_changed_request_after_completed_run_conflicts(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "conflict")
    payload = recon_request(boundary, task, "conflict")
    repo.run_reconnaissance(orch["orchestration_id"], payload)
    changed = deepcopy(payload)
    changed["observations"][0]["confidence"] = 0.31
    with pytest.raises(ReconnaissanceAgentConflict):
        repo.run_reconnaissance(orch["orchestration_id"], changed)


def test_16_successful_recon_handoff_releases_enumeration(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "handoff")
    repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "handoff"))
    updated = repo.get_orchestration(orch["orchestration_id"])
    assert updated is not None
    assert updated["task_graph"]["nodes"][0]["capability_id"] == "reconnaissance"
    assert updated["task_graph"]["nodes"][0]["status"] == "SUCCEEDED"
    assert updated["task_graph"]["nodes"][1]["capability_id"] == "enumeration"
    assert updated["task_graph"]["nodes"][1]["status"] == "READY"


def test_17_restart_preserves_recon_run_and_integrity(tmp_path: Path):
    path = tmp_path / "pentest.db"
    repo = ReconnaissanceAgentRepository(path)
    boundary, _, task, _, _ = materialize(repo)
    orch, _, _, _ = repo.start_orchestration(task["pentest_task_id"], start_payload("restart52"))
    first, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "restart52"))
    repo2 = ReconnaissanceAgentRepository(path)
    second = repo2.get_recon_run(first["recon_run_id"])
    assert second is not None
    assert second["output"]["integrity"] == first["output"]["integrity"]
    assert repo2.migration_level() == 10


def test_18_persisted_recon_output_tamper_fails_integrity_check(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "tamper")
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "tamper"))
    with sqlite3.connect(repo.sqlite_path) as conn:
        row = conn.execute("select output_json from pentest_recon_runs where recon_run_id=?", (run["recon_run_id"],)).fetchone()
        output = json.loads(row[0])
        output["semantics"]["target_actuation"] = True
        conn.execute("update pentest_recon_runs set output_json=? where recon_run_id=?", (json.dumps(output, sort_keys=True), run["recon_run_id"]))
    with pytest.raises(ReconnaissanceAgentIntegrityError):
        repo.get_recon_run(run["recon_run_id"])


def test_19_health_activates_stage52_and_preserves_non_execution_boundary(tmp_path: Path):
    service = ReconnaissanceAgentService(ReconnaissanceAgentRepository(tmp_path / "pentest.db"))
    health = service.health()
    assert health["control_version"] == CONTROL
    assert health["pentest_repository_migration_level"] == 10
    assert health["stage5_2_recon_agent_enabled"] is True
    assert health["stage5_2_recon_evidence_contract_enabled"] is True
    assert health["stage5_2_execution_intake_enabled"] is False
    assert health["stage5_2_tool_invocation_enabled"] is False
    assert health["stage5_2_external_network_io_performed"] is False
    assert health["stage5_2_target_actuation"] is False
    assert health["stage5_2_next_stage"] == "5.3"


def test_20_http_contract_run_get_list_and_handoff(tmp_path: Path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        boundary, _, task, _, _ = materialize(service.repository)
        orch, _, _, _ = service.repository.start_orchestration(task["pentest_task_id"], start_payload("http52"))
        status, headers, health = _get(base + "/health")
        assert status == 200 and SERVER_VERSION in headers["Server"] and health["control_version"] == CONTROL
        status, _, contract = _get(base + "/api/pentest/reconnaissance-agent-contract")
        assert status == 200 and contract["control_version"] == CONTROL
        status, _, action_contract = _get(base + "/api/contracts/recon-action-request")
        assert status == 200
        assert action_contract["request_schema_version"] == RECON_ACTION_REQUEST_SCHEMA_VERSION
        assert action_contract["execution_intake_enabled"] is False
        status, result = _post(base + f"/api/pentest/agentic-orchestrations/{orch['orchestration_id']}/reconnaissance/run", recon_request(boundary, task, "http52"))
        assert status == 201 and result["created"] is True and result["execution_started"] is False
        run_id = result["run"]["recon_run_id"]
        status, _, fetched = _get(base + f"/api/pentest/reconnaissance-runs/{run_id}")
        assert status == 200 and fetched["run"]["recon_run_id"] == run_id
        action_id = fetched["run"]["output"]["action_requests"][0]["action_id"]
        status, _, intake = _get(base + f"/api/pentest/recon-action-requests/{action_id}/validate-stage6-intake")
        assert status == 200 and intake["validation"]["status"] == "VALIDATED_AWAITING_GSS"
        assert intake["validation"]["gss_authorized"] is False
        status, _, listed = _get(base + "/api/pentest/reconnaissance-runs?limit=10")
        assert status == 200 and listed["count"] == 1
        assert result["orchestration"]["task_graph"]["nodes"][1]["status"] == "READY"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_21_http_execution_dispatch_remains_rejected_for_stage52(tmp_path: Path):
    server, thread, _, base = _start_server(tmp_path)
    try:
        status, rejected = _post(base + "/api/execution/dispatches", {})
        assert status == 409
        assert rejected["error_code"] == "STAGE5_2_CONTROLLED_EXECUTION_NOT_ENABLED"
        assert rejected["recon_agent_enabled"] is True
        assert rejected["execution_started"] is False
        assert rejected["tool_invocation_performed"] is False
        assert rejected["target_actuation"] is False
        assert rejected["next_stage"] == "5.3"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_22_http_run_rejects_raw_command_field(tmp_path: Path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        boundary, _, task, _, _ = materialize(service.repository)
        orch, _, _, _ = service.repository.start_orchestration(task["pentest_task_id"], start_payload("http-invalid"))
        payload = recon_request(boundary, task, "http-invalid")
        payload["command"] = "nmap target"
        status, result = _post(base + f"/api/pentest/agentic-orchestrations/{orch['orchestration_id']}/reconnaissance/run", payload)
        assert status == 400 and result["status"] == "invalid"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_23_stage51_handler_is_preserved_and_stage52_is_active_successor():
    assert PentestSubsystemStage51Handler.server_version == "APTSPentestSubsystem/5.1"
    assert PentestSubsystemStage52Handler.server_version == SERVER_VERSION
    assert issubclass(PentestSubsystemStage52Handler, PentestSubsystemStage51Handler)


def test_24_recon_contract_and_output_explicitly_preserve_evidence_and_governance_semantics(tmp_path: Path):
    repo, boundary, task, orch, _, _ = _start_repo(tmp_path, "semantics")
    run, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "semantics"))
    contract = canonical_reconnaissance_agent_contract()
    assert contract["evidence_contract"]["stage4_9_lineage_required"] is True
    assert contract["governance"]["stage4_8_scope_roe_evaluation_required_for_action_proposals"] is True
    assert contract["governance"]["decision_is_authorization"] is False
    assert run["output"]["semantics"]["act_semantics"] == "PUBLISH_GOVERNED_ACTION_PROPOSAL_ONLY"
    assert run["output"]["semantics"]["controlled_execution_deferred_to_stage6"] is True
    assert run["output"]["semantics"]["authorization_minted"] is False
