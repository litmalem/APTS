from __future__ import annotations

import pytest

from execution_subsystem.adapter_contract import ADAPTER_INTAKE_SCHEMA
from execution_subsystem.adapter_repository import ExecutionAdapterRepository
from execution_subsystem.adapter_service import ExecutionAdapterService
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.execution_contract import ExecutionSourceRejected
from execution_subsystem.gateway_contract import GATEWAY_INTAKE_SCHEMA
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.gateway_service import ExecutionGatewayService
from execution_subsystem.tool_registry import select_adapter
from tests.test_stage6_2_authoritative_execution_authorization import NOW, seed_mission
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline


class NoNetworkBroker:
    """Stops at the broker boundary; this test never resolves or contacts a target."""

    def __init__(self):
        self.pin_calls = 0

    def pin(self, *args, **kwargs):
        self.pin_calls += 1
        raise ExecutionSourceRejected("TEST_STOP_BEFORE_TARGET_IO")


@pytest.fixture
def recon_flow(tmp_path):
    pentest_repo, boundary, _, _, runs = _pipeline(tmp_path, "stage634-recon", through_stage="5.2")
    pentest_db = pentest_repo.sqlite_path
    mission_db = tmp_path / "mission.db"
    seed_mission(mission_db, boundary)
    execution_db = tmp_path / "execution.db"
    action = runs["5.2"]["output"]["action_requests"][0]
    stage61_intake = {
        "schema_version": "apts-execution-request-intake-v2",
        "source_type": "STAGE5_2_RECON_ACTION_REQUEST",
        "request_id": "ereq-stage634-recon",
        "idempotency_key": "idem-stage634-recon",
        "recon_action_id": action["action_id"],
        "recon_request_sha256": action["integrity"]["canonical_sha256"],
    }
    source = ExecutionAuthorizationProposalSource(pentest_db)
    mission = MissionAuthorizationSource(mission_db)
    authority = UniqueAuthority()
    gateway = ExecutionGatewayService(
        ExecutionGatewayRepository(execution_db), source, mission, authority, clock=lambda: NOW)
    request = gateway.create_request(stage61_intake)
    return execution_db, pentest_db, mission_db, authority, request


def gateway_intake(request):
    return {
        "schema_version": GATEWAY_INTAKE_SCHEMA,
        "submission_id": "gwreq-stage634-recon",
        "idempotency_key": "idem-gateway-stage634-recon",
        "execution_id": request["execution_id"],
        "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"],
        "requested_by": "stage634-recon-test",
    }


def adapter_intake(request):
    return {
        "schema_version": ADAPTER_INTAKE_SCHEMA,
        "invocation_request_id": "toolreq-stage634-recon",
        "idempotency_key": "idem-tool-stage634-recon",
        "execution_id": request["execution_id"],
        "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"],
        "requested_by": "stage634-recon-test",
    }


def test_stage63_admits_exact_registered_recon_capability(recon_flow):
    execution_db, pentest_db, mission_db, authority, request = recon_flow
    admission = ExecutionGatewayService(
        ExecutionGatewayRepository(execution_db), ExecutionAuthorizationProposalSource(pentest_db),
        MissionAuthorizationSource(mission_db), authority, clock=lambda: NOW
    )
    execution_request = request["envelope"]["execution_request"]
    assert execution_request["action"] == {
        "action_class": "TARGET_RECON", "capability_id": "reconnaissance",
        "technique": "TCP_CONNECT_SCAN",
    }
    submitted = admission.submit_execution(gateway_intake(request))
    assert submitted["gateway_admitted"] is True
    assert submitted["execution_authorized"] is False
    assert authority.calls[0]["context"]["execution_authorization_evaluation"]["execution_request"]["action"]["technique"] == "TCP_CONNECT_SCAN"


def test_server_registry_resolves_only_exact_action_tuples(recon_flow):
    _, _, _, _, request = recon_flow
    recon_action = request["envelope"]["execution_request"]
    selected_actual = select_adapter(recon_action)
    assert selected_actual.adapter_id == "scanner.tcp-connect.v1"
    # A registered reconnaissance tuple resolves unambiguously; adapter choice
    # is derived from the server registry, never accepted from the caller.
    compatible = {
        **recon_action,
        "action": {"action_class": "TARGET_RECON", "capability_id": "reconnaissance",
                   "technique": "TCP_CONNECT_SCAN"},
        "target": {"target_type": "IP", "target_value": "127.0.0.1"},
    }
    selected = select_adapter(compatible)
    assert selected.adapter_id == "scanner.tcp-connect.v1"


def test_stage64_recon_action_without_stage63_admission_is_rejected_before_broker(recon_flow):
    execution_db, pentest_db, mission_db, authority, request = recon_flow
    broker = NoNetworkBroker()
    adapter_service = ExecutionAdapterService(
        ExecutionAdapterRepository(execution_db), ExecutionAuthorizationProposalSource(pentest_db),
        MissionAuthorizationSource(mission_db), authority, clock=lambda: NOW, broker=broker)
    with pytest.raises(ExecutionSourceRejected, match="RECON_ACTION_REQUIRES_STAGE6_3_GATEWAY_ADMISSION"):
        adapter_service.invoke_tool(adapter_intake(request))
    assert broker.pin_calls == 0

