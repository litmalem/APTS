from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError
from .plan_versioning import verify_plan_version_contract
from .task_evidence_binding import verify_task_evidence_binding_verification_contract

TASK_COMPLETION_STAGE_SCHEMA_VERSION = "apts-dependency-aware-task-completion-v1"
TASK_COMPLETION_CONTRACT_SCHEMA_VERSION = "apts-dependency-aware-task-completion-contract-v1"
TASK_COMPLETION_HASH_DOMAIN = "MISSION_DEPENDENCY_AWARE_TASK_COMPLETION_V1"
TASK_COMPLETION_REQUEST_HASH_DOMAIN = "MISSION_DEPENDENCY_AWARE_TASK_COMPLETION_REQUEST_V1"
TASK_COMPLETION_DEPENDENCY_BINDING_HASH_DOMAIN = "MISSION_TASK_COMPLETION_DEPENDENCY_BINDING_V1"
TASK_COMPLETION_ID_PREFIX = "tcomp-"
TASK_COMPLETION_MODE = (
    "DETERMINISTIC_DEPENDENCY_AWARE_TASK_COMPLETION_COMMIT_"
    "NO_DEPENDENCY_RELEASE_NO_READINESS_RECALCULATION_NO_PLAN_OR_MISSION_PROGRESSION"
)
TASK_COMPLETION_AUTHORITY = "MISSION_ORCHESTRATOR_DEPENDENCY_AWARE_TASK_COMPLETION"
TASK_COMPLETION_STATUS = "COMPLETED_DEPENDENCY_CONSISTENT"
TASK_COMPLETION_ACCEPTANCE_STATUS = "ACCEPTED_FOR_TASK_COMPLETION"
TASK_COMPLETION_DEPENDENCY_STATUS = "DEPENDENCIES_SATISFIED"
TASK_COMPLETION_ALLOWED_MISSION_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_evidence_binding_verification_id",
    "expected_evidence_binding_verification_sha256",
    "completed_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_task_completion_id() -> str:
    return f"{TASK_COMPLETION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_task_completion_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("dependency-aware task completion request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported dependency-aware task completion field(s): "
            + ", ".join(unknown)
            + "; Stage 3.6.4 derives task identity, dependency set, dependency completion bindings, acceptance, and completion status from the active Plan plus immutable Stage-3.6.3 evidence-binding state. Caller-supplied dependency lists, completion decisions, dependency release, readiness, Plan/Mission progression, Governance/runtime, dispatch, execution, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_evidence_binding_verification_id": _string(payload, "expected_evidence_binding_verification_id"),
        "completed_by": _string(payload, "completed_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_evidence_binding_verification_id"].startswith("ebind-"):
        raise MissionValidationError("expected_evidence_binding_verification_id must be a canonical ebind-* identifier")

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
        "expected_evidence_binding_verification_sha256": _sha(
            payload, "expected_evidence_binding_verification_sha256"
        ),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_completion_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_COMPLETION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _completion_ref(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "task_completion_id": item["task_completion_id"],
        "planned_task_id": item["planned_task_id"],
        "task_key": item["task_key"],
        "completion_status": item["completion_status"],
        "canonical_sha256": item["canonical_sha256"],
    }


def derive_dependency_aware_completion(
    *,
    active_plan: Mapping[str, Any],
    evidence_binding_verification: Mapping[str, Any],
    dependency_completions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    plan_contract = active_plan.get("plan_version_contract")
    if not isinstance(plan_contract, Mapping) or not verify_plan_version_contract(plan_contract):
        raise MissionValidationError("active Stage-3.3.7 Plan version failed integrity verification")

    ebind_contract = evidence_binding_verification.get("task_evidence_binding_verification_contract")
    if not isinstance(ebind_contract, Mapping) or not verify_task_evidence_binding_verification_contract(ebind_contract):
        raise MissionValidationError("Stage-3.6.3 evidence-binding verification failed integrity verification")
    verification = ebind_contract["evidence_binding_verification"]
    if verification.get("verification_status") != "VERIFIED":
        raise MissionValidationError("Stage-3.6.3 evidence-binding verification is not VERIFIED")
    if verification.get("evidence_binding_verified") is not True or verification.get("artifact_binding_verified") is not True:
        raise MissionValidationError("Stage-3.6.3 evidence/artifact binding verification is incomplete")

    identity = ebind_contract["identity"]
    if identity.get("plan_version_record_id") != active_plan.get("plan_version_record_id"):
        raise MissionValidationError("Stage-3.6.3 evidence binding is not bound to the active Plan version")
    if int(identity.get("plan_version", -1)) != int(active_plan.get("plan_version", -2)):
        raise MissionValidationError("Stage-3.6.3 evidence binding Plan version is stale")

    candidate = plan_contract["candidate_plan"]
    steps = list(candidate.get("plan_steps") or [])
    matching = [
        step
        for step in steps
        if step.get("planned_task_id") == identity.get("planned_task_id")
        and step.get("task_key") == identity.get("task_key")
    ]
    if len(matching) != 1:
        raise MissionValidationError("Stage-3.6.3 task identity is not an exact task in the active Plan")
    task_step = matching[0]
    dependency_keys = list(task_step.get("dependency_task_keys") or [])
    if len(dependency_keys) != len(set(dependency_keys)):
        raise MissionValidationError("active Plan task contains duplicate dependency keys")

    plan_by_key = {str(step.get("task_key")): step for step in steps}
    if len(plan_by_key) != len(steps):
        raise MissionValidationError("active Plan task keys are not unique")
    if any(key not in plan_by_key for key in dependency_keys):
        raise MissionValidationError("active Plan task references an unknown dependency")

    completion_by_key: Dict[str, Mapping[str, Any]] = {}
    for item in dependency_completions:
        key = str(item.get("task_key") or "")
        if not key or key in completion_by_key:
            raise MissionValidationError("dependency completion set contains an invalid or duplicate task key")
        completion_by_key[key] = item

    missing = [key for key in dependency_keys if key not in completion_by_key]
    unexpected = [key for key in completion_by_key if key not in dependency_keys]
    if missing:
        raise MissionValidationError("dependency-aware task completion blocked by incomplete prerequisite task(s): " + ", ".join(missing))
    if unexpected:
        raise MissionValidationError("dependency completion set contains non-prerequisite task(s): " + ", ".join(sorted(unexpected)))

    refs: list[Dict[str, Any]] = []
    for key in dependency_keys:
        item = completion_by_key[key]
        expected_step = plan_by_key[key]
        if item.get("planned_task_id") != expected_step.get("planned_task_id"):
            raise MissionValidationError(f"dependency completion planned_task_id mismatch for {key}")
        if item.get("plan_version_record_id") != active_plan.get("plan_version_record_id"):
            raise MissionValidationError(f"dependency completion is from a stale/superseded Plan for {key}")
        if int(item.get("plan_version", -1)) != int(active_plan.get("plan_version", -2)):
            raise MissionValidationError(f"dependency completion Plan version mismatch for {key}")
        if item.get("completion_status") != TASK_COMPLETION_STATUS:
            raise MissionValidationError(f"dependency task is not canonically completed: {key}")
        if not isinstance(item.get("canonical_sha256"), str) or _SHA_RE.match(str(item.get("canonical_sha256"))) is None:
            raise MissionValidationError(f"dependency completion canonical SHA-256 is invalid for {key}")
        if not str(item.get("task_completion_id") or "").startswith(TASK_COMPLETION_ID_PREFIX):
            raise MissionValidationError(f"dependency completion identity is invalid for {key}")
        refs.append(_completion_ref(item))

    dependency_binding_sha256 = sha256_hex(
        {
            "hash_domain": TASK_COMPLETION_DEPENDENCY_BINDING_HASH_DOMAIN,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "task_key": identity["task_key"],
            "dependencies": refs,
        }
    )

    return {
        "task_outcome_acceptance_status": TASK_COMPLETION_ACCEPTANCE_STATUS,
        "completion_status": TASK_COMPLETION_STATUS,
        "dependency_status": TASK_COMPLETION_DEPENDENCY_STATUS,
        "dependency_count": len(dependency_keys),
        "completed_dependency_count": len(refs),
        "dependency_task_keys": dependency_keys,
        "dependency_completions": refs,
        "dependency_binding_sha256": dependency_binding_sha256,
        "all_dependencies_completed": True,
        "active_plan_dependency_consistent": True,
        "superseded_plan_dependency_used": False,
        "task_outcome_accepted": True,
        "task_completion_committed": True,
    }


def build_task_completion_contract(
    *,
    task_completion_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    evidence_binding_verification: Mapping[str, Any],
    dependency_completions: Sequence[Mapping[str, Any]],
    committed_at: str,
) -> Dict[str, Any]:
    derived = derive_dependency_aware_completion(
        active_plan=active_plan,
        evidence_binding_verification=evidence_binding_verification,
        dependency_completions=dependency_completions,
    )
    ebind_contract = evidence_binding_verification["task_evidence_binding_verification_contract"]
    ebind_identity = ebind_contract["identity"]
    ebind_source = ebind_contract["source_bindings"]
    core = {
        "schema_version": TASK_COMPLETION_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": TASK_COMPLETION_STAGE_SCHEMA_VERSION,
        "identity": {
            "task_completion_id": task_completion_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": ebind_identity["planned_task_id"],
            "task_key": ebind_identity["task_key"],
            "evidence_binding_verification_id": evidence_binding_verification["verification_id"],
            "task_outcome_id": ebind_identity["task_outcome_id"],
            "eligibility_gate_id": ebind_identity["eligibility_gate_id"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "evidence_binding_verification_sha256": evidence_binding_verification["canonical_sha256"],
            "task_outcome_sha256": ebind_source["task_outcome_sha256"],
            "eligibility_gate_sha256": ebind_source["eligibility_gate_sha256"],
            "result_capture_sha256": ebind_source["result_capture_sha256"],
            "evidence_manifest_sha256": ebind_contract["evidence_binding_verification"]["evidence_manifest_sha256"],
            "artifact_manifest_sha256": ebind_contract["evidence_binding_verification"]["artifact_manifest_sha256"],
        },
        "dependency_completion": derived,
        "completion_decision": {
            "task_outcome_acceptance_status": TASK_COMPLETION_ACCEPTANCE_STATUS,
            "completion_status": TASK_COMPLETION_STATUS,
            "reason_code": "VERIFIED_TERMINAL_SUCCESS_EVIDENCE_BOUND_DEPENDENCIES_SATISFIED",
            "task_outcome_accepted": True,
            "task_completion_committed": True,
        },
        "authority_boundary": {
            "authority": TASK_COMPLETION_AUTHORITY,
            "mode": TASK_COMPLETION_MODE,
            "task_outcome_acceptance_performed": True,
            "dependency_precondition_evaluation_performed": True,
            "task_completion_commit_performed": True,
            "canonical_completion_record_created": True,
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
            "completed_by": request["completed_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "committed_at": committed_at,
        },
    }
    digest = sha256_hex({"hash_domain": TASK_COMPLETION_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_task_completion_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        dep = contract["dependency_completion"]
        decision = contract["completion_decision"]
        boundary = contract["authority_boundary"]
        dependencies = list(dep.get("dependency_completions") or [])
        dependency_keys = list(dep.get("dependency_task_keys") or [])
        recomputed_dependency_hash = sha256_hex(
            {
                "hash_domain": TASK_COMPLETION_DEPENDENCY_BINDING_HASH_DOMAIN,
                "plan_version_record_id": identity["plan_version_record_id"],
                "task_key": identity["task_key"],
                "dependencies": dependencies,
            }
        )
        return (
            contract.get("schema_version") == TASK_COMPLETION_CONTRACT_SCHEMA_VERSION
            and contract.get("stage_schema_version") == TASK_COMPLETION_STAGE_SCHEMA_VERSION
            and str(identity.get("task_completion_id") or "").startswith(TASK_COMPLETION_ID_PREFIX)
            and str(identity.get("mission_id") or "") != ""
            and str(identity.get("plan_version_record_id") or "").startswith("pver-")
            and int(identity.get("plan_version")) >= 1
            and str(identity.get("planned_task_id") or "").startswith("ptask-")
            and bool(identity.get("task_key"))
            and str(identity.get("evidence_binding_verification_id") or "").startswith("ebind-")
            and str(identity.get("task_outcome_id") or "").startswith("toutcome-")
            and str(identity.get("eligibility_gate_id") or "").startswith("telig-")
            and source.get("source_state") in TASK_COMPLETION_ALLOWED_MISSION_STATES
            and int(source.get("source_state_version")) >= 1
            and all(_SHA_RE.match(str(source.get(k) or "")) is not None for k in (
                "source_version_sha256", "active_plan_sha256", "evidence_binding_verification_sha256",
                "task_outcome_sha256", "eligibility_gate_sha256", "result_capture_sha256",
                "evidence_manifest_sha256", "artifact_manifest_sha256",
            ))
            and dep.get("task_outcome_acceptance_status") == TASK_COMPLETION_ACCEPTANCE_STATUS
            and dep.get("completion_status") == TASK_COMPLETION_STATUS
            and dep.get("dependency_status") == TASK_COMPLETION_DEPENDENCY_STATUS
            and int(dep.get("dependency_count")) == len(dependency_keys)
            and int(dep.get("completed_dependency_count")) == len(dependencies) == len(dependency_keys)
            and [x.get("task_key") for x in dependencies] == dependency_keys
            and dep.get("dependency_binding_sha256") == recomputed_dependency_hash
            and dep.get("all_dependencies_completed") is True
            and dep.get("active_plan_dependency_consistent") is True
            and dep.get("superseded_plan_dependency_used") is False
            and dep.get("task_outcome_accepted") is True
            and dep.get("task_completion_committed") is True
            and decision.get("task_outcome_acceptance_status") == TASK_COMPLETION_ACCEPTANCE_STATUS
            and decision.get("completion_status") == TASK_COMPLETION_STATUS
            and decision.get("task_outcome_accepted") is True
            and decision.get("task_completion_committed") is True
            and boundary.get("authority") == TASK_COMPLETION_AUTHORITY
            and boundary.get("mode") == TASK_COMPLETION_MODE
            and boundary.get("task_outcome_acceptance_performed") is True
            and boundary.get("dependency_precondition_evaluation_performed") is True
            and boundary.get("task_completion_commit_performed") is True
            and boundary.get("canonical_completion_record_created") is True
            and boundary.get("task_state_transition_performed") is False
            and boundary.get("dependency_release_performed") is False
            and boundary.get("readiness_recalculation_performed") is False
            and boundary.get("plan_progression_performed") is False
            and boundary.get("mission_success_completion_authority_exercised") is False
            and boundary.get("governance_query_performed") is False
            and boundary.get("runtime_query_performed") is False
            and boundary.get("runtime_control_io_performed") is False
            and boundary.get("dispatch_redelivery_performed") is False
            and boundary.get("new_execution_attempt_created") is False
            and boundary.get("new_target_action_dispatch_performed") is False
            and boundary.get("external_network_io_performed") is False
            and boundary.get("target_actuation") is False
            and boundary.get("mission_state_transition_performed") is False
            and contract.get("canonical_sha256") == sha256_hex({"hash_domain": TASK_COMPLETION_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_task_completion_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": TASK_COMPLETION_STAGE_SCHEMA_VERSION,
        "schema_version": TASK_COMPLETION_CONTRACT_SCHEMA_VERSION,
        "identity_prefix": TASK_COMPLETION_ID_PREFIX,
        "mode": TASK_COMPLETION_MODE,
        "authority": TASK_COMPLETION_AUTHORITY,
        "completion_status": TASK_COMPLETION_STATUS,
        "acceptance_status": TASK_COMPLETION_ACCEPTANCE_STATUS,
        "dependency_status": TASK_COMPLETION_DEPENDENCY_STATUS,
        "allowed_mission_states": sorted(TASK_COMPLETION_ALLOWED_MISSION_STATES),
        "requires_stage363_verified_evidence_binding": True,
        "requires_active_stage337_plan_version": True,
        "requires_exact_active_plan_task_identity": True,
        "requires_all_active_plan_dependencies_completed": True,
        "rejects_superseded_plan_dependencies": True,
        "one_completion_per_plan_task": True,
        "task_outcome_acceptance_performed": True,
        "dependency_precondition_evaluation_performed": True,
        "task_completion_commit_performed": True,
        "canonical_completion_record_created": True,
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
        "next_stage": "3.6.5",
    }
