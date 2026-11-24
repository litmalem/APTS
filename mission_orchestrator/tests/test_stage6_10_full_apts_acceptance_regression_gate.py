from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread

import pytest

from execution_subsystem.apts_acceptance_api import ExecutionSubsystemStage610Handler, serve
from execution_subsystem.apts_acceptance_contract import (
    CONTROL_VERSION, REQUIRED_GATES, canonical_apts_acceptance_contract, verify_apts_acceptance_contract)
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.cti_feedback_contract import canonical_feedback_contract, verify_knowledge_export
from execution_subsystem.cti_knowledge_repository import CTIKnowledgeRepository
from execution_subsystem.execution_contract import ExecutionRequestIntegrityError, ExecutionSourceRejected, canonical_json
from execution_subsystem.runtime_contract import TERMINAL
from mission_orchestrator.observability_forensics import verify_forensic_evidence_bundle, reconstruct_forensic_mission
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from tests._stage6_10_scenario import provision, native_authority, runtime_for, post_impact
from tests.test_stage6_1_canonical_execution_request_contract import intake_for, http
from tests.test_stage6_4_authorized_tool_adapters_sandboxing import target_server
from tests.test_stage6_5_execution_runtime_control import wait_for, cancellation, kill_payload
from tests.test_stage6_7_vep_construction_integrity import construction_payload
from tests.test_stage6_8_cleanup_rollback_post_action_verification import post_payload
from tests.test_stage6_9_closed_loop_cti_pentest_integration import feedback_payload, update_payload
from tests.test_stage3_7_2_adaptation_trigger_detection_classification import classification_request
from tests.test_stage3_7_3_replan_eligibility_governance_gate import evaluate
from tests.test_stage3_7_4_canonical_replan_snapshot_context_binding import bind
from tests.test_stage3_7_5_deterministic_replan_candidate_generation import generate
from tests.test_stage3_7_6_replan_candidate_validation_delta_feasibility_gate import validate
from tests.test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization import commit
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage6_10_evidence_verification import preflight_data


@pytest.fixture
def connected(tmp_path, target_server):
    ctx = provision(tmp_path, target_server[0])
    envelope = ExecutionAuthorizationProposalSource(ctx["pentest"].sqlite_path).build_envelope(
        intake_for(ctx["runs"]["5.6"], "stage610-connected"))
    context = MissionAuthorizationSource(ctx["mission"].repository.sqlite_path).current_context(ctx["mission_id"])
    with native_authority(envelope["execution_request"], context) as (url, repo, native):
        runtime_for(ctx, url)
        target_server[1].clear(); target_server[2].update(sleep=0, redirect=False)
        ctx.update(target=target_server, gss_repo=repo, native_gss=native)
        try:
            yield ctx
        finally:
            ctx["runtime"].close()
            target_server[2].update(sleep=0, redirect=False)


def knowledge(ctx):
    runtime = ctx["runtime"]
    item = wait_for(runtime, runtime.start_execution(ctx["start"])["attempt_id"])
    assert item["state"] == "SUCCEEDED", item
    vep = runtime.construct_vep(construction_payload(runtime, item))
    post = runtime.complete_post_action(post_payload(item, vep))
    assert post["execution_closed"], post
    feedback = runtime.create_feedback(feedback_payload(item, vep, post))
    record = runtime.update_knowledge(update_payload(feedback))
    ctx.update(attempt=item, vep=vep, post_action=post, feedback=feedback, knowledge=record)
    return record


def mission_intake(ctx):
    mission, mid, active, record = (ctx[k] for k in ("mission", "mission_id", "active", "knowledge"))
    return {"schema_version": "apts-mission-cti-pentest-feedback-intake-v1",
        "knowledge_id": record["knowledge_id"], "revision_id": record["revision_id"],
        "revision": record["revision"], "knowledge_sha256": record["knowledge_sha256"],
        "expected_version_sha256": mission.get_mission_version_vector(mid)["version_sha256"],
        "expected_state_version": mission.get_mission_state(mid)["mission_state"]["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"], "expected_active_plan_sha256": active["canonical_sha256"]}


@contextmanager
def http_server(runtime):
    handler = type("IsolatedStage610Handler", (ExecutionSubsystemStage610Handler,), {"service": runtime})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_address[1]}"
    finally: server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_exact_predecessor_and_declaration_cannot_certify_acceptance(connected):
    contract = canonical_apts_acceptance_contract()
    assert verify_apts_acceptance_contract(contract)
    assert len(REQUIRED_GATES) == 14
    assert contract["predecessor"]["contract_sha256"] == canonical_feedback_contract()["integrity"]["canonical_sha256"]
    health = connected["runtime"].health()
    assert health["control_version"] == CONTROL_VERSION
    assert health["execution_repository_migration_level"] == 9
    assert health["full_apts_acceptance_status"] == "DECLARED_ONLY"
    assert not health["runtime_self_certification"] and health["next_stage"] is None


def test_preflight_accepts_native_services_bound_to_same_database_sources(connected, preflight_data):
    from pentest_subsystem.agentic_pentest_acceptance_service import AgenticPentestAcceptanceService
    from run.stage6_10_acceptance import validate_preflight
    preflight_data["mission"]["health"] = connected["mission"].health()
    preflight_data["pentest"]["health"] = AgenticPentestAcceptanceService(connected["pentest"]).health()
    with http_server(connected["runtime"]) as base:
        code, preflight_data["execution"]["health"], preflight_data["execution"]["headers"] = http(base + "/health")
        assert code == 200 and validate_preflight(preflight_data)


@pytest.mark.parametrize("area", ["predecessor", "regression", "authority_boundary", "trajectory", "repositories"])
def test_contract_tampering_fails_closed(area):
    value = canonical_apts_acceptance_contract()
    value[area] = {"forged": True}
    assert not verify_apts_acceptance_contract(value)


def test_connected_objective_to_cti_replan_and_forensic_reconstruction(connected):
    ctx = connected
    record = knowledge(ctx)
    post_impact(ctx)
    mission, mid, active = ctx["mission"], ctx["mission_id"], ctx["active"]
    assert ctx["execution_request"]["envelope"]["execution_request"]["task_id"] == ctx["boundary"]["task_id"]
    assert ctx["boundary"]["task_id"] in active["plan_version_contract"]["candidate_plan"]["ordered_planned_task_ids"]
    assert ctx["pip"]["pip_id"] == record["knowledge"]["subject"]["pip_reference"]["pip_id"]
    assert ctx["pip"]["source_cti"]["artifact_sha256"] == ctx["native_pip"]["canonical_sha256"]
    assert ctx["runs"]["5.4"]["request"]["knowledge_items"][0]["content_sha256"] == ctx["native_pip"]["canonical_sha256"]
    assert len(ctx["target"][1]) == 1 and len(ctx["gss_repo"].decisions) >= 2
    assert all(kwargs["payload"]["execution_revalidation"]["checks"]["ROE"] == "PASS"
               for args, kwargs in ctx["native_gss"].events.items)
    intake = mission_intake(ctx)
    detected = mission.ingest_cti_pentest_feedback(mid, intake)
    classification = mission.classify_adaptation_trigger(mid, detected["adaptation_episode_id"],
        classification_request(mission, mid, active, detected, "stage610", reason_code="PLAN_STALE", severity="MEDIUM"))
    eligibility, _ = evaluate(mission, mid, active, ctx["scope"], ctx["binding"], detected, classification, "stage610")
    snapshot, _ = bind(mission, mid, active, ctx["scope"], ctx["binding"], detected, classification, eligibility, "stage610")
    candidate, _ = generate(mission, mid, snapshot, "stage610")
    validation, _ = validate(mission, mid, candidate, "stage610")
    assert validation["validation_status"] == "VALIDATED_FOR_COMMIT", validation
    committed, _ = commit(mission, mid, snapshot, candidate, validation, "stage610")
    assert committed["successor_plan_version"] == 2
    assert mission.get_active_plan_version(mid)["canonical_sha256"] == committed["successor_plan_sha256"]
    export = ctx["runtime"].export_knowledge(record["knowledge_id"], mid)
    assert verify_knowledge_export(export)
    bundle = mission.get_forensic_evidence_bundle(mid)["bundle"]
    assert verify_forensic_evidence_bundle(bundle) and bundle["status"] == "VERIFIED", bundle.get("reason_code")
    reconstruction = reconstruct_forensic_mission(bundle)
    assert reconstruction["status"] == "VERIFIED"
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=mission.repository.sqlite_path),
        governance_client=ctx["mission_governance"], cti_feedback_source=CTIKnowledgeRepository(ctx["root"] / "knowledge.db", read_only=True))
    assert restarted.get_forensic_evidence_bundle(mid)["bundle"] == bundle
    assert restarted.ingest_cti_pentest_feedback(mid, intake)["idempotent_replay"]
    assert ctx["runtime"].start_execution(ctx["start"])["attempt_id"] == ctx["attempt"]["attempt_id"]
    assert len(ctx["target"][1]) == 1
    assert record["knowledge"]["assessment"]["hypothesis_outcome"] == "INCONCLUSIVE"
    assert mission.get_mission_state(mid)["mission_state"]["state"] == "RUNNING"
    destination = os.getenv("APTS_ACCEPTANCE_TRAJECTORY_OUTPUT")
    if destination:
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        (path / "knowledge_export.json").write_text(canonical_json(export), encoding="utf-8")
        (path / "mission_forensic_bundle.json").write_text(canonical_json(bundle), encoding="utf-8")
        (path / "cti_pip.json").write_text(canonical_json(ctx["native_pip"]), encoding="utf-8")
        (path / "pentest_pip.json").write_text(canonical_json(ctx["pip"]), encoding="utf-8")


@pytest.mark.parametrize("mode", ["DENY", "REVIEW", "TIMEOUT", "EMERGENCY", "REVOKED"])
def test_connected_native_gss_blocks_target_io(connected, mode):
    ctx = connected
    if mode == "REVOKED": ctx["gss_repo"].old["decision_status"] = "REVOKED"
    else: ctx["gss_repo"].mode = mode
    if mode == "TIMEOUT": ctx["runtime"].governance_client.timeout_seconds = 0.02
    from execution_subsystem.authorization_contract import ExecutionGovernanceUnavailable
    with pytest.raises((ExecutionSourceRejected, ExecutionGovernanceUnavailable)):
        ctx["runtime"].start_execution(ctx["start"])
    assert not ctx["target"][1]


def test_connected_mission_abort_blocks_execution_from_same_source(connected):
    ctx = connected
    execute(ctx["mission"], ctx["mission_id"], "ABORT", "stage610-before-start")
    with pytest.raises(ExecutionSourceRejected): ctx["runtime"].start_execution(ctx["start"])
    assert not ctx["gss_repo"].requests and not ctx["target"][1]


def test_connected_mission_scope_drift_is_not_replaced_by_pentest_allow(connected):
    ctx = connected
    # Update through the canonical Mission owner, retaining all RoE restrictions.
    from tests.test_stage3_7_3_replan_eligibility_governance_gate import scope_payload
    payload = scope_payload("stage610-drift")
    payload["expected_contract_version"] = ctx["scope"]["contract_version"]
    payload["scope"]["targets"] = [{"target_type": "HOST", "target_value": "outside.invalid"}]
    ctx["mission"].put_mission_scope_contract(ctx["mission_id"], payload)
    with pytest.raises((ExecutionSourceRejected, ExecutionRequestIntegrityError)):
        ctx["runtime"].start_execution(ctx["start"])
    assert not ctx["target"][1]


@pytest.mark.parametrize("command", ["CANCEL", "KILL"])
def test_connected_kill_cancel_terminate_without_retry(connected, command):
    ctx = connected
    ctx["target"][2]["sleep"] = 1.1
    started = ctx["runtime"].start_execution(ctx["start"])
    running = wait_for(ctx["runtime"], started["attempt_id"], lambda item: item["state"] == "RUNNING" and bool(ctx["target"][1]))
    if command == "CANCEL": ctx["runtime"].control(cancellation(running))
    else:
        payload = {"schema_version": "apts-execution-emergency-kill-command-v1", "command_request_id": "rtcmd-stage610-kill",
            "idempotency_key": "idem-stage610-kill", "requested_by": "acceptance-operator", "reason": "Stop isolated acceptance",
            "mission_id": ctx["mission_id"]}
        from execution_subsystem.runtime_contract import KILL_SCHEMA
        payload["schema_version"] = KILL_SCHEMA
        ctx["runtime"].control(payload, kill=True)
    terminal = wait_for(ctx["runtime"], started["attempt_id"])
    assert terminal["state"] == ("CANCELLED" if command == "CANCEL" else "ABORTED")
    assert ctx["runtime"].start_execution(ctx["start"])["attempt_id"] == started["attempt_id"]
    assert len(ctx["target"][1]) == 1


def test_http_gate_declaration_is_read_only_and_cannot_accept_caller_pass(connected):
    runtime = connected["runtime"]
    before = [Path(runtime.repository.sqlite_path).read_bytes(), Path(connected["mission"].repository.sqlite_path).read_bytes()]
    with http_server(runtime) as base:
        code, value, headers = http(base + "/api/execution/full-apts-acceptance-contract")
        assert code == 200 and verify_apts_acceptance_contract(value["contract"])
        assert "APTSExecutionSubsystem/6.10" in headers["Server"]
        assert http(base + "/api/contracts/full-apts-acceptance?decision=ALLOW")[0] == 400
        assert http(base + "/api/execution/full-apts-acceptance", {"status": "PASS"})[0] == 409
        assert http(base + "/api/execution/full-apts-acceptance-contract", {"evidence": {}})[0] == 409
    assert before == [Path(runtime.repository.sqlite_path).read_bytes(), Path(connected["mission"].repository.sqlite_path).read_bytes()]
    assert not connected["gss_repo"].requests and not connected["target"][1]


def test_nonloopback_acceptance_bind_rejected():
    with pytest.raises(ValueError): serve("0.0.0.0", 0)
