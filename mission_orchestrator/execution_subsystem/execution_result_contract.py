"""Read-only, Action-Request-bound ExecutionResult projection for Recon."""
from __future__ import annotations

from .execution_contract import verify_integrity, with_integrity
from .evidence_contract import EVIDENCE_CONTROL_VERSION, canonical_evidence_contract

RESULT_SCHEMA = "apts-recon-execution-result-v1"
RESULT_DOMAIN = "APTS_RECON_EXECUTION_RESULT_V1"
RESULT_CONTRACT_SCHEMA = "apts-recon-execution-result-contract-v1"
RESULT_CONTRACT_DOMAIN = "APTS_RECON_EXECUTION_RESULT_CONTRACT_V1"
ENUM_RESULT_SCHEMA = "apts-enumeration-execution-result-v1"
ENUM_RESULT_DOMAIN = "APTS_ENUMERATION_EXECUTION_RESULT_V1"


def canonical_recon_execution_result_contract():
    return with_integrity({
        "schema_version": RESULT_CONTRACT_SCHEMA,
        "control_version": "stage6-recon-execution-result-return",
        "result_schema_version": RESULT_SCHEMA,
        "predecessor": {"control": EVIDENCE_CONTROL_VERSION,
            "contract_sha256": canonical_evidence_contract()["integrity"]["canonical_sha256"]},
        "source": "DURABLE_RUNTIME_ATTEMPT_AND_SEALED_STAGE6_6_EVIDENCE_ONLY",
        "lookup": "EXACT_RECON_ACTION_REQUEST_ID",
        "lineage": ["action_id", "proposal_ref", "execution_id", "attempt_id", "authorization_id",
                    "terminal_event_sha256", "evidence_id", "evidence_manifest_sha256"],
        "retries": "RETURN_ALL_ATTEMPTS_IN_CREATION_ORDER; LATEST_RESULT_IS_LAST",
        "caller_supplied_result_accepted": False,
        "source_run_mutated": False,
        "result_is_authorization": False,
        "result_is_vulnerability_finding": False,
        "result_is_vep": False,
        "raw_target_bytes_returned": False,
        "read_only": True,
        "fail_closed": True,
    }, RESULT_CONTRACT_DOMAIN)


def canonical_enumeration_execution_result_contract():
    return with_integrity({"schema_version": "apts-enumeration-execution-result-contract-v1",
        "control_version": "stage6-enumeration-execution-result-return",
        "result_schema_version": ENUM_RESULT_SCHEMA,
        "predecessor": {"control": EVIDENCE_CONTROL_VERSION,
            "contract_sha256": canonical_evidence_contract()["integrity"]["canonical_sha256"]},
        "source": "DURABLE_STAGE6_RUNTIME_AND_SEALED_STAGE6_6_EVIDENCE_ONLY",
        "lookup": "EXACT_STAGE5_3_ACTION_PROPOSAL_REF",
        "allowed_execution_tuple": {"capability_id": "enumeration", "action_class": "TARGET_RECON",
            "technique": "TCP_BANNER_READ"},
        "source_run_mutated": False, "result_is_authorization": False,
        "result_is_vulnerability_finding": False, "result_is_vep": False,
        "raw_target_bytes_returned": False, "read_only": True, "fail_closed": True},
        "APTS_ENUMERATION_EXECUTION_RESULT_CONTRACT_V1")


def build_recon_execution_result(*, action_id, proposal_ref, orchestration_id, item, manifest):
    """Project only durable Stage 6 runtime/evidence records; never accepts caller result data."""
    record = item["record"]
    runtime_result = item["invocation"]["result"]
    terminal = item["state"] in {"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED", "ABORTED"}
    if terminal and manifest is None:
        raise ValueError("terminal Recon attempt has no sealed Stage 6.6 evidence")
    if manifest is not None and (
        manifest["recon_action_id"] != action_id
        or manifest["proposal_ref"] != proposal_ref
        or manifest["attempt_id"] != item["attempt_id"]
        or manifest["terminal_event_sha256"] != item["head_sha256"]
    ):
        raise ValueError("Recon result evidence binding mismatch")
    safe_result = None
    if runtime_result is not None:
        safe_result = {
            "status": runtime_result["status"],
            "reason_codes": list(runtime_result["reason_codes"]),
            "observation": runtime_result["observation"],
            "semantics": dict(runtime_result["semantics"]),
            "adapter_result_sha256": runtime_result["integrity"]["canonical_sha256"],
        }
    core = {
        "schema_version": RESULT_SCHEMA,
        "action_id": action_id,
        "proposal_ref": proposal_ref,
        "mission_id": record["mission_id"],
        "pentest_id": record["pentest_id"],
        "task_id": record["task_id"],
        "pentest_task_id": record["pentest_task_id"],
        "orchestration_id": orchestration_id,
        "execution_id": record["execution_id"],
        "attempt_id": item["attempt_id"],
        "attempt_number": record["attempt_number"],
        "attempt_sha256": record["integrity"]["canonical_sha256"],
        "runtime_state": item["state"],
        "terminal": terminal,
        "execution_result": safe_result,
        "evidence": None if manifest is None else {
            "evidence_id": manifest["evidence_id"],
            "manifest_sha256": manifest["integrity"]["canonical_sha256"],
            # Stage 6.6 calls a complete terminal capture CAPTURED. Recon's
            # read model calls that same sealed state SEALED; partial captures
            # retain their explicit status and cannot authorize an iteration.
            "capture_status": "SEALED" if manifest["capture_status"] == "CAPTURED"
                else manifest["capture_status"],
            "target_io_uncertain": manifest["target_io_uncertain"],
            "artifact_refs": [{"artifact_id": a["artifact_id"], "kind": a["kind"],
                               "content_sha256": a["content_sha256"]} for a in manifest["artifacts"]],
        },
        "lineage": {
            "authorization_id": item["events"][0]["data"].get("authorization_id"),
            "terminal_event_id": item["events"][-1]["event_id"] if terminal else None,
            "terminal_event_sha256": item["head_sha256"] if terminal else None,
            "retry_of_attempt_id": record["retry_of_attempt_id"],
        },
        "semantics": {
            "result_is_authorization": False,
            "result_is_vulnerability_finding": False,
            "result_is_vep": False,
            "target_state_measurement_performed": False,
            "raw_target_bytes_returned": False,
        },
    }
    return with_integrity(core, RESULT_DOMAIN)


def verify_recon_execution_result(value):
    try:
        if value["schema_version"] != RESULT_SCHEMA:
            return False
        expected = {
            "result_is_authorization": False,
            "result_is_vulnerability_finding": False,
            "result_is_vep": False,
            "target_state_measurement_performed": False,
            "raw_target_bytes_returned": False,
        }
        return value["semantics"] == expected and verify_integrity(value, RESULT_DOMAIN)
    except (KeyError, TypeError, ValueError):
        return False


def build_enumeration_execution_result(*, proposal_ref, orchestration_id, item, manifest):
    """Read-only, evidence-bound projection for one Stage-5.3 proposal."""
    record = item["record"]
    terminal = item["state"] in {"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED", "ABORTED"}
    if terminal and manifest is None:
        raise ValueError("terminal Enumeration attempt has no Stage 6.6 evidence")
    if manifest is not None and (manifest["recon_action_id"] is not None
            or manifest["proposal_ref"] != proposal_ref
            or manifest["attempt_id"] != item["attempt_id"]
            or manifest["terminal_event_sha256"] != item["head_sha256"]):
        raise ValueError("Enumeration result evidence binding mismatch")
    runtime_result = item["invocation"]["result"]
    safe_result = None if runtime_result is None else {
        "status": runtime_result["status"], "reason_codes": list(runtime_result["reason_codes"]),
        "observation": runtime_result["observation"], "semantics": dict(runtime_result["semantics"]),
        "adapter_result_sha256": runtime_result["integrity"]["canonical_sha256"]}
    core = {"schema_version": ENUM_RESULT_SCHEMA, "action_id": proposal_ref,
        "proposal_ref": proposal_ref, "mission_id": record["mission_id"],
        "pentest_id": record["pentest_id"], "task_id": record["task_id"],
        "pentest_task_id": record["pentest_task_id"], "orchestration_id": orchestration_id,
        "execution_id": record["execution_id"], "attempt_id": item["attempt_id"],
        "attempt_number": record["attempt_number"], "attempt_sha256": record["integrity"]["canonical_sha256"],
        "runtime_state": item["state"], "terminal": terminal, "execution_result": safe_result,
        "evidence": None if manifest is None else {"evidence_id": manifest["evidence_id"],
            "manifest_sha256": manifest["integrity"]["canonical_sha256"],
            "capture_status": "SEALED" if manifest["capture_status"] == "CAPTURED" else manifest["capture_status"],
            "target_io_uncertain": manifest["target_io_uncertain"],
            "artifact_refs": [{"artifact_id": a["artifact_id"], "kind": a["kind"],
                               "content_sha256": a["content_sha256"]} for a in manifest["artifacts"]]},
        "lineage": {"authorization_id": item["events"][0]["data"].get("authorization_id"),
            "terminal_event_id": item["events"][-1]["event_id"] if terminal else None,
            "terminal_event_sha256": item["head_sha256"] if terminal else None,
            "retry_of_attempt_id": record["retry_of_attempt_id"]},
        "semantics": {"result_is_authorization": False, "result_is_vulnerability_finding": False,
            "result_is_vep": False, "target_state_measurement_performed": False,
            "raw_target_bytes_returned": False, "source_run_mutated": False}}
    return with_integrity(core, ENUM_RESULT_DOMAIN)


def verify_enumeration_execution_result(value):
    try:
        return (value["schema_version"] == ENUM_RESULT_SCHEMA
            and value["semantics"] == {"result_is_authorization": False,
                "result_is_vulnerability_finding": False, "result_is_vep": False,
                "target_state_measurement_performed": False, "raw_target_bytes_returned": False,
                "source_run_mutated": False}
            and value["action_id"] == value["proposal_ref"]
            and verify_integrity(value, ENUM_RESULT_DOMAIN))
    except (KeyError, TypeError, ValueError):
        return False
