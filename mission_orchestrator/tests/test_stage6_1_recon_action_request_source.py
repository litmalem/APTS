from __future__ import annotations

from copy import deepcopy
import shutil

import pytest

from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource
from execution_subsystem.execution_contract import (
    RECON_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION, ExecutionRequestIntegrityError,
    ExecutionSourceRejected, verify_canonical_action_envelope,
)
from execution_subsystem.proposal_source import PentestProposalSource
from execution_subsystem.request_repository import ExecutionRequestRepository
from execution_subsystem.request_service import ExecutionRequestService
from execution_subsystem.vep_source import PentestVEPSource
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline


@pytest.fixture
def recon_source(tmp_path):
    repo, _, _, _, runs = _pipeline(tmp_path, "stage61recon", through_stage="5.2")
    source_path = tmp_path / "source.db"
    shutil.copy2(repo.sqlite_path, source_path)
    run = runs["5.2"]
    action_request = run["output"]["action_requests"][0]
    intake = {
        "schema_version": RECON_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
        "source_type": "STAGE5_2_RECON_ACTION_REQUEST",
        "request_id": "ereq-stage61-recon",
        "idempotency_key": "idem-stage61-recon",
        "recon_action_id": action_request["action_id"],
        "recon_request_sha256": action_request["integrity"]["canonical_sha256"],
    }
    execution_service = ExecutionRequestService(
        ExecutionRequestRepository(tmp_path / "execution.db"), PentestProposalSource(source_path))
    return source_path, action_request, intake, execution_service


def test_recon_action_request_becomes_stage61_envelope_without_authorization_or_io(recon_source):
    _, source_request, intake, service = recon_source
    result = service.create_request(intake)
    envelope = result["envelope"]
    request = envelope["execution_request"]
    assert result["created"] is True
    assert verify_canonical_action_envelope(envelope)
    assert request["proposing_agent"]["agent_id"] == source_request["agent_id"]
    assert request["action"] == {
        "action_class": "TARGET_RECON",
        "capability_id": source_request["capability_id"],
        "technique": source_request["technique"],
    }
    assert request["parameters"]["source_action_id"] == source_request["action_id"]
    assert request["target"]["target_value"] == source_request["target_ref"]["target_value"]
    assert request["authorization_requirement"]["authority"] == "EXTERNAL_APTS_GSS"
    assert envelope["status"] == "AWAITING_AUTHORIZATION"
    assert envelope["semantics"]["authorization_minted"] is False
    assert envelope["semantics"]["external_network_io_performed"] is False
    replay = service.create_request(intake)
    assert replay["created"] is False
    assert replay["execution_id"] == result["execution_id"]


def test_recon_source_hash_tampering_is_rejected_without_materializing_a_request(recon_source):
    _, _, intake, service = recon_source
    forged = {**intake, "recon_request_sha256": "a" * 64}
    with pytest.raises(ExecutionRequestIntegrityError):
        service.create_request(forged)
    assert service.repository.list_requests() == []


def test_recon_envelope_reaches_stage62_but_stage67_remains_closed(recon_source):
    _, _, intake, service = recon_source
    envelope = service.create_request(intake)["envelope"]
    # Stage 6.2 uses a dedicated Mission source and is covered end-to-end in
    # test_stage6_2_recon_action_request_authorization.py. At this boundary the
    # Pentest source accepts only an intact, persisted Recon envelope.
    current = ExecutionAuthorizationProposalSource(service.proposal_source.sqlite_path).current_context(envelope)
    assert current["source_type"] == "STAGE5_2_RECON_ACTION_REQUEST"
    with pytest.raises(ExecutionSourceRejected, match="Stage 6.7 VEP source snapshots for Recon requests are not enabled"):
        PentestVEPSource(service.proposal_source.sqlite_path).snapshot(envelope)
