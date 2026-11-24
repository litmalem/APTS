from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.evidence_repository import ExecutionEvidenceRepository
from execution_subsystem.evidence_service import ExecutionEvidenceService
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.gateway_service import ExecutionGatewayService
from execution_subsystem.execution_result_contract import build_recon_execution_result, verify_recon_execution_result
from execution_subsystem.gateway_contract import GATEWAY_INTAKE_SCHEMA
from execution_subsystem.runtime_contract import START_SCHEMA
from tests import test_stage4_6_pentest_workflow_orchestrator_skeleton as materialize_module
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline
from tests.test_stage6_2_authoritative_execution_authorization import NOW, seed_mission
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority
from tests.test_stage6_5_execution_runtime_control import wait_for
from pentest_subsystem.reconnaissance import ReconnaissanceAgentService


@pytest.fixture
def target_server():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            calls.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/status", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_stage12_active_recon_acceptance_through_stage66_and_iteration(tmp_path, target_server):
    """A single explicitly authorized loopback TCP connect completes the full handoff."""
    original = materialize_module.sample_boundary

    def lab_boundary():
        boundary = original()
        boundary["scope"]["targets"][0] = {"target_type": "URL", "target_value": target_server[0]}
        boundary["roe"]["allowed_action_classes"] = ["TARGET_RECON"]
        boundary["roe"]["allowed_techniques"] = ["TCP_CONNECT_SCAN"]
        boundary["roe"]["maximum_concurrency"] = 1
        boundary["constraints"]["resource_budget"] = {"max_network_requests": 1}
        return boundary

    materialize_module.sample_boundary = lab_boundary
    try:
        pentest_repo, boundary, task, orchestration_id, runs = _pipeline(
            tmp_path, "stage12-e2e", through_stage="5.2")
    finally:
        materialize_module.sample_boundary = original

    parent = runs["5.2"]
    action = parent["output"]["action_requests"][0]
    assert action["technique"] == "TCP_CONNECT_SCAN"
    assert action["target_ref"]["target_value"] == target_server[0]
    assert action["binding"]["roe_sha256"]

    mission_db = tmp_path / "mission.db"
    seed_mission(mission_db, boundary)
    authority = UniqueAuthority()
    gateway = ExecutionGatewayService(
        ExecutionGatewayRepository(tmp_path / "execution.db"),
        ExecutionAuthorizationProposalSource(pentest_repo.sqlite_path),
        MissionAuthorizationSource(mission_db), authority, clock=lambda: NOW)
    intake_request = {
        "schema_version": "apts-execution-request-intake-v2",
        "source_type": "STAGE5_2_RECON_ACTION_REQUEST",
        "request_id": "ereq-stage12-e2e",
        "idempotency_key": "idem-stage12-e2e",
        "recon_action_id": action["action_id"],
        "recon_request_sha256": action["integrity"]["canonical_sha256"],
    }
    request = gateway.create_request(intake_request)
    assert request["envelope"]["execution_request"]["action"] == {
        "action_class": "TARGET_RECON", "capability_id": "reconnaissance",
        "technique": "TCP_CONNECT_SCAN",
    }
    start = {
        "schema_version": START_SCHEMA,
        "invocation_request_id": "toolreq-stage12-e2e",
        "idempotency_key": "idem-tool-stage12-e2e",
        "execution_id": request["execution_id"],
        "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"],
        "requested_by": "stage12-acceptance-test",
    }
    gateway_receipt = gateway.submit_execution({
        "schema_version": GATEWAY_INTAKE_SCHEMA,
        "submission_id": "gwreq-stage12-e2e",
        "idempotency_key": "idem-gateway-stage12-e2e",
        "execution_id": request["execution_id"],
        "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"],
        "requested_by": "stage12-acceptance-test",
    })
    assert gateway_receipt["gateway_admitted"] is True
    assert gateway_receipt["execution_authorized"] is False

    # Stage 6.5/6.6 upgrades the existing repository after Stage 6.3 admission.
    service = ExecutionEvidenceService(
        ExecutionEvidenceRepository(tmp_path / "execution.db"),
        ExecutionAuthorizationProposalSource(pentest_repo.sqlite_path),
        MissionAuthorizationSource(mission_db), authority, clock=lambda: NOW)
    try:
        attempt = service.start_execution(start)
        item = wait_for(service, attempt["attempt_id"])
        assert item["state"] == "SUCCEEDED", service._failures
        gss_evaluation = authority.calls[0]["context"]["execution_authorization_evaluation"]["execution_request"]
        assert gss_evaluation["action"]["technique"] == "TCP_CONNECT_SCAN"
        capture = service.get_evidence(attempt["attempt_id"])
        assert capture["sealed"] is True and capture["status"] == "CAPTURED"
        manifest = capture["manifest"]
        assert manifest["recon_action_id"] == action["action_id"]
        assert manifest["proposal_ref"] == action["proposal_ref"]

        result = build_recon_execution_result(
            action_id=action["action_id"], proposal_ref=action["proposal_ref"],
            orchestration_id=orchestration_id, item=item, manifest=manifest)
        assert verify_recon_execution_result(result)
        provider = lambda action_id: {
            "action_id": action_id, "results": [result], "latest_result": result,
        }
        recon = ReconnaissanceAgentService(pentest_repo, execution_result_provider=provider)
        monitored = recon.get_stage6_execution_results(action["action_id"])
        assert monitored["read_only"] is True
        assert monitored["latest_result"] == result

        iteration = recon.run_reconnaissance_iteration(orchestration_id, {
            "schema_version": "apts-stage5.2-recon-iteration-request-v1",
            "parent_recon_run_id": parent["recon_run_id"],
            "action_id": action["action_id"],
        })["run"]
        assert iteration["parent_recon_run_id"] == parent["recon_run_id"]
        assert iteration["source_action_id"] == action["action_id"]
        assert iteration["source_result_sha256"] == result["integrity"]["canonical_sha256"]
        assert iteration["request"]["observations"][-1]["source"]["source_kind"] == "STAGE6_EXECUTION_RESULT"
        assert pentest_repo.get_recon_run(parent["recon_run_id"]) == parent
        # TCP_CONNECT_SCAN must establish one local socket and send no HTTP request.
        assert target_server[1] == []
    finally:
        service.close()
