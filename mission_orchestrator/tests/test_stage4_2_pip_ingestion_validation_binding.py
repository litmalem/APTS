from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from tests._localhost_http import urlopen_local_with_retry

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CONTROL_VERSION as MO_CONTROL_VERSION
from pentest_subsystem.api_service import (
    PentestSubsystemHandler,
    PentestSubsystemStage42Handler,
)
from pentest_subsystem.boundary_contract import (
    PENTEST_BOUNDARY_CONTROL_VERSION,
    build_pentest_boundary_envelope,
    canonical_pentest_boundary_contract,
    verify_pentest_boundary_contract,
)
from pentest_subsystem.pip_contract import (
    PIP_ARTIFACT_HASH_DOMAIN,
    PIP_BINDING_ENVELOPE_SCHEMA_VERSION,
    PIP_INGESTION_CONTROL_VERSION,
    PIP_INGESTION_INVARIANTS,
    PIP_INGESTION_MODE,
    PIP_INGESTION_NEXT_STAGE,
    PIP_INGESTION_SCHEMA_VERSION,
    PIP_REQUIRED_FIELDS,
    PIP_SCHEMA_VERSION,
    PIP_VALIDATION_DIMENSIONS,
    PentestPIPValidationError,
    build_pip_ingestion_binding,
    canonical_pip_ingestion_contract,
    canonical_pip_ingestion_definition,
    normalize_pip_artifact,
    seal_pip_artifact,
    verify_pip_artifact,
    verify_pip_ingestion_binding,
    verify_pip_ingestion_contract,
)
from pentest_subsystem.pip_service import PentestPIPService
from pentest_subsystem.service import PentestBoundaryService

CONTROL = "stage4.2-pip-ingestion-validation-binding"
SERVER_VERSION = "APTSPentestSubsystem/4.2"
FIXED_NOW = datetime(2026, 9, 30, 0, 0, 0, tzinfo=timezone.utc)


def _z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sample_boundary() -> dict:
    return {
        "pentest_id": f"pentest-{uuid.uuid4()}",
        "mission_id": f"mission-gmo-{uuid.uuid4()}",
        "task_id": f"ptask-{uuid.uuid4()}",
        "scope": {
            "targets": [{"target_type": "HOST", "target_value": "lab-target.internal"}],
            "excluded_targets": [],
        },
        "objective": {
            "type": "SECURITY_VALIDATION",
            "description": "Validate the authorized lab target from CTI-derived intelligence.",
        },
        "constraints": {
            "max_actions": 10,
            "risk_threshold": "MODERATE",
            "data_handling_policy": {"retain_sensitive_output": False},
        },
        "roe": {
            "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "destructive_actions_allowed": False,
        },
        "authorization_reference": {
            "policy_decision_id": "decision-stage4-2-test",
            "policy_decision_hash": "b" * 64,
            "policy_version": 8,
            "execution_authorized": True,
            "pre_dispatch_revalidation_id": "xreval-stage4-2-test",
        },
    }


def sample_pip(boundary: dict | None = None, *, now: datetime = FIXED_NOW) -> dict:
    boundary = boundary or sample_boundary()
    core = {
        "schema_version": PIP_SCHEMA_VERSION,
        "pip_id": f"pip-{uuid.uuid4()}",
        "pip_version": "1",
        "mission_id": boundary["mission_id"],
        "pentest_id": boundary["pentest_id"],
        "task_id": boundary["task_id"],
        "source_cti": {
            "source_type": "CTI",
            "source_system": "VULNDESK_CTI",
            "artifact_id": f"cti-{uuid.uuid4()}",
            "artifact_version": "7",
            "artifact_sha256": "c" * 64,
        },
        "issued_at": _z(now - timedelta(minutes=5)),
        "expires_at": _z(now + timedelta(hours=6)),
        "scope": deepcopy(boundary["scope"]),
        "confidence": 0.87,
        "provenance": {
            "producer": "VULNDESK_CTI",
            "source_refs": ["cti-report-2026-09-30", "cve-CVE-2026-4242"],
            "collection_method": "CTI_CORRELATION",
            "correlation_id": "corr-stage4-2",
        },
        "intelligence": {
            "hypotheses": [
                {
                    "hypothesis_id": "hyp-001",
                    "summary": "Authorized lab target may expose a vulnerable service.",
                    "technique_hint": "SERVICE_ENUMERATION",
                }
            ],
            "observations": [{"kind": "CTI_INDICATOR", "value": "service-family-x"}],
        },
    }
    return seal_pip_artifact(core)


def _start_server(handler_cls=PentestSubsystemStage42Handler):
    service = PentestPIPService() if handler_cls is PentestSubsystemStage42Handler else PentestBoundaryService()
    handler = type("IsolatedPentestHandler", (handler_cls,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _post_json(url: str, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen_local_with_retry(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_01_canonical_stage42_contract_binds_exact_stage41_predecessor():
    contract = canonical_pip_ingestion_contract()
    predecessor = canonical_pentest_boundary_contract()
    assert verify_pip_ingestion_contract(contract)
    assert contract["control_version"] == CONTROL == PIP_INGESTION_CONTROL_VERSION
    assert contract["predecessor"]["control"] == PENTEST_BOUNDARY_CONTROL_VERSION
    assert contract["predecessor"]["contract_sha256"] == predecessor["integrity"]["canonical_sha256"]
    assert contract["next_stage"] == PIP_INGESTION_NEXT_STAGE == "4.3"


def test_02_stage42_contract_is_sha_bound_and_tamper_fails_closed():
    contract = canonical_pip_ingestion_contract()
    forged = deepcopy(contract)
    forged["semantics"]["accepted_for_execution"] = True
    assert verify_pip_ingestion_contract(forged) is False
    forged = deepcopy(contract)
    forged["validation_pipeline"]["fail_closed"] = False
    assert verify_pip_ingestion_contract(forged) is False


def test_03_validation_dimensions_and_non_execution_invariants_match_roadmap():
    contract = canonical_pip_ingestion_contract()
    assert tuple(contract["validation_pipeline"]["dimensions"]) == PIP_VALIDATION_DIMENSIONS
    assert PIP_VALIDATION_DIMENSIONS == (
        "PIP_IDENTITY", "MISSION_BINDING", "SOURCE_CTI", "FRESHNESS",
        "INTEGRITY", "SCOPE", "CONFIDENCE", "PROVENANCE",
    )
    assert "PIP_IS_INTELLIGENCE_INPUT_NOT_EXECUTION_COMMAND" in PIP_INGESTION_INVARIANTS
    assert contract["semantics"]["pip_is_execution_command"] is False
    assert contract["semantics"]["accepted_for_execution"] is False


def test_04_canonical_pip_schema_is_strict_versioned_and_integrity_bound():
    boundary = sample_boundary()
    pip = sample_pip(boundary)
    normalized = normalize_pip_artifact(pip, now=FIXED_NOW)
    assert normalized == pip
    assert verify_pip_artifact(pip, now=FIXED_NOW)
    assert tuple(PIP_REQUIRED_FIELDS) == tuple(contract_field for contract_field in canonical_pip_ingestion_contract()["pip_schema"]["required_fields"])
    assert pip["schema_version"] == PIP_SCHEMA_VERSION
    assert pip["integrity"]["hash_domain"] == PIP_ARTIFACT_HASH_DOMAIN


def test_05_pip_content_tamper_or_unknown_execution_field_is_rejected():
    pip = sample_pip()
    forged = deepcopy(pip)
    forged["intelligence"]["observations"][0]["value"] = "tampered"
    with pytest.raises(PentestPIPValidationError, match="integrity mismatch"):
        normalize_pip_artifact(forged, now=FIXED_NOW)
    forged = deepcopy(pip)
    forged["execute_now"] = True
    with pytest.raises(PentestPIPValidationError, match="unsupported PIP field"):
        normalize_pip_artifact(forged, now=FIXED_NOW)


def test_06_pip_identity_requires_canonical_pip_mission_pentest_and_task_ids():
    boundary = sample_boundary()
    pip = sample_pip(boundary)
    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["pip_id"] = "not-pip-namespace"
    with pytest.raises(PentestPIPValidationError, match="pip_id must use canonical prefix pip-"):
        seal_pip_artifact(core)
    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["mission_id"] = "mission-noncanonical"
    with pytest.raises(PentestPIPValidationError, match="mission_id must use canonical prefix mission-gmo-"):
        seal_pip_artifact(core)


def test_07_source_cti_requires_cti_type_version_and_sha256_metadata():
    pip = sample_pip()
    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["source_cti"]["source_type"] = "EXECUTOR"
    with pytest.raises(PentestPIPValidationError, match="source_cti.source_type must be CTI"):
        seal_pip_artifact(core)
    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["source_cti"]["artifact_sha256"] = "bad-hash"
    with pytest.raises(PentestPIPValidationError, match="artifact_sha256 must be a SHA-256"):
        seal_pip_artifact(core)


def test_08_freshness_rejects_future_expired_and_invalid_intervals():
    boundary = sample_boundary()
    future = sample_pip(boundary, now=FIXED_NOW + timedelta(hours=2))
    with pytest.raises(PentestPIPValidationError, match="issued_at is in the future"):
        normalize_pip_artifact(future, now=FIXED_NOW)

    expired = sample_pip(boundary, now=FIXED_NOW - timedelta(days=1))
    with pytest.raises(PentestPIPValidationError, match="stale or expired"):
        normalize_pip_artifact(expired, now=FIXED_NOW)

    core = {k: deepcopy(v) for k, v in sample_pip(boundary).items() if k != "integrity"}
    core["expires_at"] = core["issued_at"]
    with pytest.raises(PentestPIPValidationError, match="expires_at must be later"):
        seal_pip_artifact(core)


def test_09_confidence_is_numeric_and_bounded_zero_to_one():
    pip = sample_pip()
    for bad in (-0.01, 1.01, True, "0.9"):
        core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
        core["confidence"] = bad
        with pytest.raises(PentestPIPValidationError, match="confidence"):
            seal_pip_artifact(core)


def test_10_provenance_requires_producer_nonempty_unique_source_refs():
    pip = sample_pip()
    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["provenance"] = {"producer": "VULNDESK_CTI", "source_refs": []}
    with pytest.raises(PentestPIPValidationError, match="source_refs must be a non-empty"):
        seal_pip_artifact(core)
    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["provenance"]["source_refs"] = ["same-ref", "same-ref"]
    with pytest.raises(PentestPIPValidationError, match="must not contain duplicates"):
        seal_pip_artifact(core)


def test_11_binding_proves_exact_identity_scope_and_all_eight_validation_dimensions():
    boundary = sample_boundary()
    pip = sample_pip(boundary)
    binding = build_pip_ingestion_binding(boundary_payload=boundary, pip_payload=pip, now=FIXED_NOW)
    assert binding["schema_version"] == PIP_BINDING_ENVELOPE_SCHEMA_VERSION
    assert verify_pip_ingestion_binding(binding, now=FIXED_NOW)
    assert binding["stage4_1_boundary_envelope_sha256"] == build_pentest_boundary_envelope(boundary)["integrity"]["canonical_sha256"]
    assert binding["binding"]["mission_id"] == boundary["mission_id"]
    assert binding["binding"]["pentest_id"] == boundary["pentest_id"]
    assert binding["binding"]["task_id"] == boundary["task_id"]
    dimensions = [item["dimension"] for item in binding["validation"]["dimensions"]]
    assert dimensions == list(PIP_VALIDATION_DIMENSIONS)
    assert all(item["status"] == "PASS" for item in binding["validation"]["dimensions"])


def test_12_binding_rejects_identity_mismatch_and_scope_mismatch_fail_closed():
    boundary = sample_boundary()
    pip = sample_pip(boundary)
    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["mission_id"] = f"mission-gmo-{uuid.uuid4()}"
    mismatched = seal_pip_artifact(core)
    with pytest.raises(PentestPIPValidationError, match="identity binding mismatch"):
        build_pip_ingestion_binding(boundary_payload=boundary, pip_payload=mismatched, now=FIXED_NOW)

    core = {k: deepcopy(v) for k, v in pip.items() if k != "integrity"}
    core["scope"] = {"targets": [{"target_type": "HOST", "target_value": "other.internal"}], "excluded_targets": []}
    wrong_scope = seal_pip_artifact(core)
    with pytest.raises(PentestPIPValidationError, match="scope must exactly match"):
        build_pip_ingestion_binding(boundary_payload=boundary, pip_payload=wrong_scope, now=FIXED_NOW)


def test_13_binding_semantics_are_ingestion_only_stateless_and_non_executing():
    boundary = sample_boundary()
    binding = build_pip_ingestion_binding(boundary_payload=boundary, pip_payload=sample_pip(boundary), now=FIXED_NOW)
    semantics = binding["semantics"]
    assert semantics["ingested"] is True
    assert semantics["validated"] is True
    assert semantics["bound"] is True
    assert semantics["intelligence_input_only"] is True
    assert semantics["accepted_for_execution"] is False
    assert semantics["pentest_task_materialized"] is False
    assert semantics["workflow_materialized"] is False
    assert semantics["persisted"] is False
    assert semantics["authorization_minted"] is False
    assert semantics["tool_invocation_performed"] is False
    assert semantics["target_actuation"] is False


def test_14_http_stage42_health_contract_ingestion_and_execution_negative_boundary():
    server, thread, base = _start_server()
    try:
        with urlopen_local_with_retry(base + "/health", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
        with urlopen_local_with_retry(base + "/api/pentest/pip-contract", timeout=5) as response:
            contract1 = json.loads(response.read().decode("utf-8"))
        with urlopen_local_with_retry(base + "/api/contracts/pip-ingestion", timeout=5) as response:
            contract2 = json.loads(response.read().decode("utf-8"))
        assert health["control_version"] == CONTROL
        assert health["stage4_2_pip_ingestion_enabled"] is True
        assert health["stage4_2_execution_intake_enabled"] is False
        assert health["stage4_2_durable_persistence_enabled"] is False
        assert health["stage4_2_next_stage"] == "4.3"
        assert contract1 == contract2
        assert contract1["definition"]["schema_version"] == PIP_INGESTION_SCHEMA_VERSION
        assert contract1["pip_is_intelligence_input"] is True
        assert contract1["pip_is_execution_command"] is False

        now = datetime.now(timezone.utc)
        boundary = sample_boundary()
        pip = sample_pip(boundary, now=now)
        status, result = _post_json(base + "/api/pentest/pip/ingest", {"boundary": boundary, "pip": pip})
        assert status == 200
        assert result["status"] == "valid"
        assert result["ingested"] is True and result["validated"] is True and result["bound"] is True
        assert result["accepted_for_execution"] is False
        assert result["persisted"] is False
        assert result["target_actuation"] is False
        assert verify_pip_ingestion_binding(result["binding"], now=now)

        req = Request(
            base + "/api/execution/dispatches",
            data=b'{"probe":true}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc:
            urlopen_local_with_retry(req, timeout=5)
        assert exc.value.code == 409
        body = json.loads(exc.value.read().decode("utf-8"))
        assert body["error_code"] == "STAGE4_2_EXECUTION_INTAKE_NOT_ENABLED"
        assert body["pip_is_intelligence_input"] is True
        assert body["execution_started"] is False
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_15_stage41_and_stage3_controls_remain_regression_compatible_and_unmodified():
    definition = canonical_pip_ingestion_definition()
    assert verify_pentest_boundary_contract(canonical_pentest_boundary_contract())
    assert definition["predecessor_control"] == PENTEST_BOUNDARY_CONTROL_VERSION
    assert PentestSubsystemHandler.server_version == "APTSPentestSubsystem/4.1"
    assert PentestSubsystemStage42Handler.server_version == SERVER_VERSION
    assert PentestBoundaryService().health()["control_version"] == PENTEST_BOUNDARY_CONTROL_VERSION
    assert PentestPIPService().health()["control_version"] == CONTROL
    assert MO_CONTROL_VERSION == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert definition["pentest_repository_migration_level"] == 0
    assert definition["durable_persistence_enabled"] is False
    assert definition["next_stage"] == "4.3"
