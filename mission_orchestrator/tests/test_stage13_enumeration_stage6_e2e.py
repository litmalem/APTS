from __future__ import annotations

from socketserver import BaseRequestHandler, ThreadingTCPServer
from threading import Thread

import pytest

from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.evidence_repository import ExecutionEvidenceRepository
from execution_subsystem.evidence_service import ExecutionEvidenceService
from execution_subsystem.execution_contract import ExecutionSourceRejected
from execution_subsystem.execution_result_contract import verify_enumeration_execution_result
from execution_subsystem.gateway_contract import GATEWAY_INTAKE_SCHEMA
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.gateway_service import ExecutionGatewayService
from execution_subsystem.proposal_source import PentestProposalSource
from execution_subsystem.runtime_contract import START_SCHEMA
from execution_subsystem.request_service import ExecutionRequestService
from execution_subsystem.request_repository import ExecutionRequestRepository
from execution_subsystem.adapter_service import ExecutionAdapterService
from execution_subsystem.adapter_repository import ExecutionAdapterRepository
from execution_subsystem.execution_contract import ENUMERATION_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION
from pentest_subsystem.enumeration import EnumerationAgentRepository, EnumerationAgentService
from tests import test_stage4_6_pentest_workflow_orchestrator_skeleton as materialize_module
from tests.test_stage5_3_enumeration_agent import enumeration_request
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline
from tests.test_stage6_2_authoritative_execution_authorization import NOW, seed_mission
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority
from tests.test_stage6_5_execution_runtime_control import wait_for


@pytest.fixture
def tcp_banner_server():
    calls = []
    class Handler(BaseRequestHandler):
        def handle(self):
            calls.append(self.client_address)
            self.request.sendall(b"Authorized-Loopback-Banner")
    server = ThreadingTCPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/", calls
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_stage13_enumeration_tcp_banner_handoff_to_stage66_and_read_only_iteration(tmp_path, tcp_banner_server):
    target_url, calls = tcp_banner_server
    original = materialize_module.sample_boundary
    def lab_boundary():
        boundary = original()
        boundary["scope"]["targets"][0] = {"target_type": "URL", "target_value": target_url}
        boundary["roe"]["allowed_action_classes"] = ["TARGET_RECON"]
        # Permit the semantic proposal to be persisted for the negative intake check;
        # Stage 6 must still reject it because no exact adapter is registered.
        boundary["roe"]["allowed_techniques"] = ["TCP_CONNECT_SCAN", "TCP_BANNER_READ", "SERVICE_ENUMERATION"]
        boundary["roe"]["maximum_concurrency"] = 1
        boundary["constraints"]["resource_budget"] = {"max_network_requests": 1}
        return boundary
    materialize_module.sample_boundary = lab_boundary
    try:
        pentest_repo, boundary, task, orchestration_id, runs = _pipeline(
            tmp_path, "stage13-e2e", through_stage="5.2")
    finally:
        materialize_module.sample_boundary = original

    # Reopen the advanced Stage-5.9 repository without downgrading its schema head.
    enum_repo = EnumerationAgentRepository(pentest_repo.sqlite_path)
    enum_service = EnumerationAgentService(enum_repo)
    enum_request = enumeration_request(boundary, task, runs["5.2"], "stage13-e2e")
    enum_request["enumeration_proposals"][0]["technique"] = "TCP_BANNER_READ"
    enum_request["enumeration_proposals"][0]["target"] = {"target_type": "URL", "target_value": target_url}
    enum_request["enumeration_proposals"].append({
        "proposal_key": "stage13-semantic-only", "target": {"target_type": "URL", "target_value": target_url},
        "technique": "SERVICE_ENUMERATION", "estimated_impact": "LOW", "rate_cost": 1,
        "active_concurrency": 1, "stop_signals": []})
    enum_result = enum_service.run_enumeration(orchestration_id, enum_request)
    parent = enum_result["run"]
    proposals = parent["output"]["action_proposals"]
    banner_proposal = next(item for item in proposals if item["technique"] == "TCP_BANNER_READ")
    semantic_proposal = next(item for item in proposals if item["technique"] == "SERVICE_ENUMERATION")

    mission_db = tmp_path / "mission.db"
    seed_mission(mission_db, boundary)
    execution_db = tmp_path / "execution.db"
    authority = UniqueAuthority()
    source = ExecutionAuthorizationProposalSource(pentest_repo.sqlite_path)
    mission = MissionAuthorizationSource(mission_db)
    gateway = ExecutionGatewayService(ExecutionGatewayRepository(execution_db), source, mission,
        authority, clock=lambda: NOW)
    intake = {"schema_version": ENUMERATION_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
        "source_type": "STAGE5_3_ENUMERATION_ACTION_PROPOSAL", "request_id": "ereq-stage13-e2e",
        "idempotency_key": "idem-stage13-e2e", "enumeration_run_id": parent["enumeration_run_id"],
        "enumeration_proposal_ref": banner_proposal["action_proposal_ref"],
        "proposal_sha256": banner_proposal["action_proposal_sha256"]}
    request = gateway.create_request(intake)
    envelope = request["envelope"]
    assert envelope["execution_request"]["action"] == {
        "action_class": "TARGET_RECON", "capability_id": "enumeration", "technique": "TCP_BANNER_READ"}
    assert envelope["execution_request"]["target"] == {"target_type": "URL", "target_value": target_url}

    rejected = {**intake, "request_id": "ereq-stage13-semantic", "idempotency_key": "idem-stage13-semantic",
        "enumeration_proposal_ref": semantic_proposal["action_proposal_ref"],
        "proposal_sha256": semantic_proposal["action_proposal_sha256"]}
    with pytest.raises(ExecutionSourceRejected, match="only an explicit TCP_BANNER_READ"):
        gateway.create_request(rejected)

    admission = gateway.submit_execution({"schema_version": GATEWAY_INTAKE_SCHEMA,
        "submission_id": "gwreq-stage13-e2e", "idempotency_key": "idem-gateway-stage13-e2e",
        "execution_id": request["execution_id"], "envelope_sha256": envelope["integrity"]["canonical_sha256"],
        "requested_by": "stage13-acceptance-test"})
    assert admission["gateway_admitted"] is True and admission["execution_authorized"] is False

    service = ExecutionEvidenceService(ExecutionEvidenceRepository(execution_db), source, mission,
        authority, clock=lambda: NOW)
    start = {"schema_version": START_SCHEMA, "invocation_request_id": "toolreq-stage13-e2e",
        "idempotency_key": "idem-tool-stage13-e2e", "execution_id": request["execution_id"],
        "envelope_sha256": envelope["integrity"]["canonical_sha256"], "requested_by": "stage13-acceptance-test"}
    try:
        attempt = service.start_execution(start)
        item = wait_for(service, attempt["attempt_id"])
        assert item["state"] == "SUCCEEDED", service._failures
        assert authority.calls[0]["context"]["execution_authorization_evaluation"]["execution_request"]["action"]["technique"] == "TCP_BANNER_READ"
        capture = service.get_evidence(attempt["attempt_id"])
        manifest = capture["manifest"]
        assert capture["sealed"] is True and capture["status"] == "CAPTURED"
        assert manifest["recon_action_id"] is None
        assert manifest["proposal_ref"] == banner_proposal["action_proposal_ref"]
        assert all("Authorized-Loopback-Banner" not in str(a) for a in capture["artifacts"])

        readback = service.get_enumeration_execution_results(banner_proposal["action_proposal_ref"])
        result = readback["latest_result"]
        assert readback["read_only"] is True and verify_enumeration_execution_result(result)
        consumer = EnumerationAgentService(enum_repo,
            execution_result_provider=lambda proposal_ref: service.get_enumeration_execution_results(proposal_ref))
        iteration = consumer.run_enumeration_iteration(orchestration_id, {
            "schema_version": "apts-stage5.3-enumeration-iteration-request-v1",
            "parent_enumeration_run_id": parent["enumeration_run_id"],
            "proposal_ref": banner_proposal["action_proposal_ref"]})
        assert iteration["read_only"] is True and iteration["parent_run_mutated"] is False
        assert iteration["iteration"]["execution_result_sha256"] == result["integrity"]["canonical_sha256"]
        assert enum_repo.get_enumeration_run(parent["enumeration_run_id"]) == parent
        assert len(calls) == 1
    finally:
        service.close()
