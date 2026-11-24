from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .execution_result import verify_execution_result_capture_contract
from .task_outcome import verify_task_outcome_contract
from .task_terminality import verify_task_terminality_eligibility_contract

TASK_EVIDENCE_BINDING_STAGE_SCHEMA_VERSION = "apts-task-evidence-binding-verification-v1"
TASK_EVIDENCE_BINDING_CONTRACT_SCHEMA_VERSION = "apts-task-evidence-binding-verification-contract-v1"
TASK_EVIDENCE_BINDING_HASH_DOMAIN = "MISSION_TASK_EVIDENCE_BINDING_VERIFICATION_V1"
TASK_EVIDENCE_BINDING_REQUEST_HASH_DOMAIN = "MISSION_TASK_EVIDENCE_BINDING_VERIFICATION_REQUEST_V1"
TASK_EVIDENCE_BINDING_ID_PREFIX = "ebind-"
TASK_EVIDENCE_BINDING_MODE = "DETERMINISTIC_LOCAL_REFERENCE_AND_HASH_BINDING_VERIFICATION_NO_CONTENT_DEREFERENCE_NO_ACCEPTANCE_COMMIT"
TASK_EVIDENCE_BINDING_AUTHORITY = "MISSION_ORCHESTRATOR_TASK_EVIDENCE_BINDING_VERIFICATION"
TASK_EVIDENCE_BINDING_STATUS = "VERIFIED"
TASK_EVIDENCE_BINDING_ALLOWED_MISSION_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_task_outcome_id",
    "expected_task_outcome_sha256",
    "expected_eligibility_gate_id",
    "expected_eligibility_gate_sha256",
    "expected_result_capture_id",
    "expected_result_capture_sha256",
    "verified_by",
    "reason",
    "metadata",
}
_ALLOWED_MANIFEST_ITEM_FIELDS = frozenset({"id", "type", "uri", "sha256", "media_type", "size_bytes", "metadata"})
_FORBIDDEN_INLINE_FIELDS = frozenset({"content", "data", "payload", "bytes", "body", "base64", "blob"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_task_evidence_binding_verification_id() -> str:
    return f"{TASK_EVIDENCE_BINDING_ID_PREFIX}{uuid.uuid4()}"


def _string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return value


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _string(payload, key, 64).lower()
    if not _SHA_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_task_evidence_binding_verification_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task evidence-binding verification request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task evidence-binding verification field(s): "
            + ", ".join(unknown)
            + "; Stage 3.6.3 verifies immutable local evidence/artifact reference bindings only. "
              "Caller-supplied evidence contents, manifest overrides, acceptance decisions, completion commits, dependency release, "
              "readiness, plan progression, mission completion, Governance/runtime calls, dispatch, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_task_outcome_id": _string(payload, "expected_task_outcome_id"),
        "expected_eligibility_gate_id": _string(payload, "expected_eligibility_gate_id"),
        "expected_result_capture_id": _string(payload, "expected_result_capture_id"),
        "verified_by": _string(payload, "verified_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_task_outcome_id"].startswith("toutcome-"):
        raise MissionValidationError("expected_task_outcome_id must be a canonical toutcome-* identifier")
    if not values["expected_eligibility_gate_id"].startswith("telig-"):
        raise MissionValidationError("expected_eligibility_gate_id must be a canonical telig-* identifier")
    if not values["expected_result_capture_id"].startswith("xresult-"):
        raise MissionValidationError("expected_result_capture_id must be a canonical xresult-* identifier")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason not in (None, ""):
        if not isinstance(reason, str) or not reason.strip():
            raise MissionValidationError("reason must be a non-empty string when provided")
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    else:
        reason = None

    return {
        **values,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_task_outcome_sha256": _sha(payload, "expected_task_outcome_sha256"),
        "expected_eligibility_gate_sha256": _sha(payload, "expected_eligibility_gate_sha256"),
        "expected_result_capture_sha256": _sha(payload, "expected_result_capture_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_evidence_binding_verification_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_EVIDENCE_BINDING_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _verify_manifest_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if set(item) - _ALLOWED_MANIFEST_ITEM_FIELDS:
        return False
    if set(item) & _FORBIDDEN_INLINE_FIELDS:
        return False
    if not isinstance(item.get("id"), str) or not item["id"] or not _ID_RE.match(item["id"]):
        return False
    if not isinstance(item.get("type"), str) or not item["type"]:
        return False
    if not isinstance(item.get("uri"), str) or not item["uri"]:
        return False
    if not isinstance(item.get("sha256"), str) or not _SHA_RE.match(item["sha256"]):
        return False
    if item.get("media_type") is not None and (not isinstance(item.get("media_type"), str) or not item["media_type"]):
        return False
    if item.get("size_bytes") is not None:
        if isinstance(item["size_bytes"], bool) or not isinstance(item["size_bytes"], int) or item["size_bytes"] < 0:
            return False
    if not isinstance(item.get("metadata", {}), dict):
        return False
    canonical_json(item.get("metadata", {}))
    return True


def derive_evidence_binding_verification(
    *,
    task_outcome: Mapping[str, Any],
    eligibility_gate: Mapping[str, Any],
    result_capture: Mapping[str, Any],
) -> Dict[str, Any]:
    outcome_contract = task_outcome["task_outcome_contract"]
    eligibility_contract = eligibility_gate["task_terminality_eligibility_contract"]
    result_contract = result_capture["execution_result_capture_contract"]
    if not verify_task_outcome_contract(outcome_contract):
        raise MissionValidationError("Stage-3.6.1 task-outcome contract failed integrity verification")
    if not verify_task_terminality_eligibility_contract(eligibility_contract):
        raise MissionValidationError("Stage-3.6.2 terminality/completion-eligibility contract failed integrity verification")
    if not verify_execution_result_capture_contract(result_contract):
        raise MissionValidationError("Stage-3.5.7 execution-result capture contract failed integrity verification")

    if eligibility_gate["completion_eligible"] is not True:
        raise MissionValidationError("Stage-3.6.3 requires a completion-eligible Stage-3.6.2 gate")
    if eligibility_gate["terminality_status"] != "TERMINAL_SUCCESS":
        raise MissionValidationError("Stage-3.6.3 requires TERMINAL_SUCCESS from Stage 3.6.2")
    if task_outcome["source_task_outcome_status"] != "VERIFIED_COMPLETED":
        raise MissionValidationError("Stage-3.6.3 requires VERIFIED_COMPLETED Stage-3.6.1 task outcome")

    oi = outcome_contract["identity"]
    osrc = outcome_contract["source_bindings"]
    gi = eligibility_contract["identity"]
    gsrc = eligibility_contract["source_bindings"]
    ri = result_contract["identity"]
    evidence = result_contract["evidence_manifest"]
    artifacts = result_contract["artifact_manifest"]

    identity_consistent = (
        gi["task_outcome_id"] == task_outcome["task_outcome_id"]
        and gsrc["task_outcome_sha256"] == task_outcome["canonical_sha256"]
        and oi["result_capture_id"] == result_capture["result_capture_id"]
        and osrc["result_capture_sha256"] == result_capture["canonical_sha256"]
        and oi["mission_id"] == gi["mission_id"] == ri["mission_id"] == task_outcome["mission_id"]
        and oi["plan_version_record_id"] == gi["plan_version_record_id"] == ri["plan_version_record_id"]
        and int(oi["plan_version"]) == int(gi["plan_version"]) == int(ri["plan_version"])
        and oi["planned_task_id"] == gi["planned_task_id"] == ri["planned_task_id"]
        and oi["task_key"] == gi["task_key"] == ri["task_key"]
        and oi["execution_attempt_id"] == ri["execution_attempt_id"]
    )

    evidence_items = list(evidence.get("items") or [])
    artifact_items = list(artifacts.get("items") or [])
    evidence_ids = [x.get("id") if isinstance(x, dict) else None for x in evidence_items]
    artifact_ids = [x.get("id") if isinstance(x, dict) else None for x in artifact_items]
    evidence_manifest_sha256 = sha256_hex({"items": evidence_items})
    artifact_manifest_sha256 = sha256_hex({"items": artifact_items})

    evidence_items_valid = bool(evidence_items) and all(_verify_manifest_item(x) for x in evidence_items)
    artifact_items_valid = all(_verify_manifest_item(x) for x in artifact_items)
    evidence_unique = len(evidence_ids) == len(set(evidence_ids))
    artifact_unique = len(artifact_ids) == len(set(artifact_ids))

    evidence_hash_consistent = (
        int(evidence.get("evidence_count", -1)) == len(evidence_items)
        and int(result_capture["evidence_count"]) == len(evidence_items)
        and evidence.get("manifest_sha256") == evidence_manifest_sha256
        and result_capture["evidence_manifest_sha256"] == evidence_manifest_sha256
        and osrc["evidence_manifest_sha256"] == evidence_manifest_sha256
    )
    artifact_hash_consistent = (
        int(artifacts.get("artifact_count", -1)) == len(artifact_items)
        and int(result_capture["artifact_count"]) == len(artifact_items)
        and artifacts.get("manifest_sha256") == artifact_manifest_sha256
        and result_capture["artifact_manifest_sha256"] == artifact_manifest_sha256
        and osrc["artifact_manifest_sha256"] == artifact_manifest_sha256
    )
    reference_only = evidence.get("inline_payload_persisted") is False and artifacts.get("inline_payload_persisted") is False

    verified = all(
        (
            identity_consistent,
            evidence_items_valid,
            artifact_items_valid,
            evidence_unique,
            artifact_unique,
            evidence_hash_consistent,
            artifact_hash_consistent,
            reference_only,
        )
    )
    if not verified:
        raise MissionValidationError("Stage-3.6.3 evidence/artifact binding verification failed closed")

    return {
        "verification_status": TASK_EVIDENCE_BINDING_STATUS,
        "evidence_binding_verified": True,
        "artifact_binding_verified": True,
        "evidence_reference_count": len(evidence_items),
        "artifact_reference_count": len(artifact_items),
        "evidence_manifest_sha256": evidence_manifest_sha256,
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "identity_lineage_consistent": identity_consistent,
        "evidence_manifest_hash_consistent": evidence_hash_consistent,
        "artifact_manifest_hash_consistent": artifact_hash_consistent,
        "evidence_item_schema_verified": evidence_items_valid,
        "artifact_item_schema_verified": artifact_items_valid,
        "evidence_identifiers_unique": evidence_unique,
        "artifact_identifiers_unique": artifact_unique,
        "reference_only_manifest_verified": reference_only,
        "evidence_content_dereferenced": False,
        "artifact_content_dereferenced": False,
        "external_content_hash_recomputed": False,
    }


def build_task_evidence_binding_verification_contract(
    *,
    verification_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    task_outcome: Mapping[str, Any],
    eligibility_gate: Mapping[str, Any],
    result_capture: Mapping[str, Any],
    verified_at: str,
) -> Dict[str, Any]:
    verification = derive_evidence_binding_verification(
        task_outcome=task_outcome,
        eligibility_gate=eligibility_gate,
        result_capture=result_capture,
    )
    core = {
        "schema_version": TASK_EVIDENCE_BINDING_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": TASK_EVIDENCE_BINDING_STAGE_SCHEMA_VERSION,
        "identity": {
            "verification_id": verification_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": task_outcome["planned_task_id"],
            "task_key": task_outcome["task_key"],
            "task_outcome_id": task_outcome["task_outcome_id"],
            "eligibility_gate_id": eligibility_gate["eligibility_gate_id"],
            "result_capture_id": result_capture["result_capture_id"],
            "execution_attempt_id": result_capture["execution_attempt_id"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "task_outcome_sha256": task_outcome["canonical_sha256"],
            "eligibility_gate_sha256": eligibility_gate["canonical_sha256"],
            "result_capture_sha256": result_capture["canonical_sha256"],
            "source_task_outcome_status": task_outcome["source_task_outcome_status"],
            "terminality_status": eligibility_gate["terminality_status"],
            "completion_eligibility_status": eligibility_gate["completion_eligibility_status"],
            "completion_eligible": bool(eligibility_gate["completion_eligible"]),
        },
        "evidence_binding_verification": verification,
        "authority_boundary": {
            "authority": TASK_EVIDENCE_BINDING_AUTHORITY,
            "mode": TASK_EVIDENCE_BINDING_MODE,
            "verification_is_local_immutable_reference_check": True,
            "verification_is_content_authenticity_attestation": False,
            "task_outcome_acceptance_performed": False,
            "acceptance_criteria_evaluation_performed": False,
            "task_completion_commit_performed": False,
            "task_state_transition_performed": False,
            "dependency_release_performed": False,
            "readiness_recalculation_performed": False,
            "plan_progression_performed": False,
            "mission_success_completion_authority_exercised": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False,
            "new_target_action_dispatch_performed": False,
            "external_network_io_performed": False,
            "target_actuation": False,
            "mission_state_transition_performed": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "verified_by": request["verified_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "verified_at": verified_at,
        },
    }
    digest = sha256_hex({"hash_domain": TASK_EVIDENCE_BINDING_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_task_evidence_binding_verification_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        verification = contract["evidence_binding_verification"]
        boundary = contract["authority_boundary"]
        return (
            contract["schema_version"] == TASK_EVIDENCE_BINDING_CONTRACT_SCHEMA_VERSION
            and contract["stage_schema_version"] == TASK_EVIDENCE_BINDING_STAGE_SCHEMA_VERSION
            and str(identity["verification_id"]).startswith(TASK_EVIDENCE_BINDING_ID_PREFIX)
            and str(identity["plan_version_record_id"]).startswith("pver-")
            and str(identity["task_outcome_id"]).startswith("toutcome-")
            and str(identity["eligibility_gate_id"]).startswith("telig-")
            and str(identity["result_capture_id"]).startswith("xresult-")
            and source["source_task_outcome_status"] == "VERIFIED_COMPLETED"
            and source["terminality_status"] == "TERMINAL_SUCCESS"
            and source["completion_eligible"] is True
            and verification["verification_status"] == TASK_EVIDENCE_BINDING_STATUS
            and verification["evidence_binding_verified"] is True
            and verification["artifact_binding_verified"] is True
            and int(verification["evidence_reference_count"]) >= 1
            and int(verification["artifact_reference_count"]) >= 0
            and verification["identity_lineage_consistent"] is True
            and verification["evidence_manifest_hash_consistent"] is True
            and verification["artifact_manifest_hash_consistent"] is True
            and verification["reference_only_manifest_verified"] is True
            and verification["evidence_content_dereferenced"] is False
            and verification["artifact_content_dereferenced"] is False
            and verification["external_content_hash_recomputed"] is False
            and boundary["authority"] == TASK_EVIDENCE_BINDING_AUTHORITY
            and boundary["mode"] == TASK_EVIDENCE_BINDING_MODE
            and boundary["verification_is_local_immutable_reference_check"] is True
            and boundary["verification_is_content_authenticity_attestation"] is False
            and boundary["task_outcome_acceptance_performed"] is False
            and boundary["acceptance_criteria_evaluation_performed"] is False
            and boundary["task_completion_commit_performed"] is False
            and boundary["dependency_release_performed"] is False
            and boundary["plan_progression_performed"] is False
            and boundary["mission_success_completion_authority_exercised"] is False
            and boundary["governance_query_performed"] is False
            and boundary["runtime_query_performed"] is False
            and boundary["runtime_control_io_performed"] is False
            and boundary["dispatch_redelivery_performed"] is False
            and boundary["new_execution_attempt_created"] is False
            and boundary["new_target_action_dispatch_performed"] is False
            and boundary["external_network_io_performed"] is False
            and boundary["target_actuation"] is False
            and boundary["mission_state_transition_performed"] is False
            and digest == sha256_hex({"hash_domain": TASK_EVIDENCE_BINDING_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_task_evidence_binding_verification_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": TASK_EVIDENCE_BINDING_STAGE_SCHEMA_VERSION,
        "schema_version": TASK_EVIDENCE_BINDING_CONTRACT_SCHEMA_VERSION,
        "identity_prefix": TASK_EVIDENCE_BINDING_ID_PREFIX,
        "mode": TASK_EVIDENCE_BINDING_MODE,
        "authority": TASK_EVIDENCE_BINDING_AUTHORITY,
        "verification_status": TASK_EVIDENCE_BINDING_STATUS,
        "allowed_mission_states": sorted(TASK_EVIDENCE_BINDING_ALLOWED_MISSION_STATES),
        "requires_stage357_result_capture": True,
        "requires_stage361_task_outcome_identity": True,
        "requires_stage362_completion_eligible_gate": True,
        "requires_verified_completed_outcome": True,
        "requires_terminal_success": True,
        "requires_active_plan_version": True,
        "one_verification_per_eligibility_gate": True,
        "verifies_evidence_manifest_reference_hash_binding": True,
        "verifies_artifact_manifest_reference_hash_binding": True,
        "verifies_cross_stage_identity_lineage": True,
        "content_dereference_performed": False,
        "external_content_hash_recomputed": False,
        "content_authenticity_attestation_performed": False,
        "task_outcome_acceptance_performed": False,
        "acceptance_criteria_evaluation_performed": False,
        "task_completion_commit_performed": False,
        "task_state_transition_performed": False,
        "dependency_release_performed": False,
        "readiness_recalculation_performed": False,
        "plan_progression_performed": False,
        "mission_success_completion_authority_exercised": False,
        "governance_query_performed": False,
        "runtime_query_performed": False,
        "runtime_control_io_performed": False,
        "dispatch_redelivery_performed": False,
        "new_execution_attempt_created": False,
        "new_target_action_dispatch_performed": False,
        "external_network_io_performed": False,
        "target_actuation": False,
        "mission_state_transition_performed": False,
        "next_stage": "3.6.4",
    }
