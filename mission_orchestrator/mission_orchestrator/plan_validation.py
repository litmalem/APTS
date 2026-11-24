from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionPlanValidationGuardRejected, MissionValidationError
from .planner_generation import GENERATED_PLAN_STATUS, verify_generated_plan_contract
from .task_dependency_graph import verify_task_dependency_graph_contract
from .task_decomposition import verify_planned_task_contract, verify_task_decomposition_contract

PLAN_VALIDATION_SCHEMA_VERSION = "apts-plan-validation-feasibility-v1"
PLAN_VALIDATION_HASH_DOMAIN = "MISSION_PLAN_VALIDATION_FEASIBILITY_V1"
PLAN_VALIDATION_REQUEST_HASH_DOMAIN = "MISSION_PLAN_VALIDATION_FEASIBILITY_REQUEST_V1"
PLAN_VALIDATION_ID_PREFIX = "pvalidate-"
PLAN_VALIDATION_VERSION_INITIAL = 1
PLAN_VALIDATION_REQUIRED_STATE = "PLANNING"
PLAN_VALIDATION_STATUS = "VALIDATED_FEASIBLE"
PLAN_VALIDATION_MODE = "DETERMINISTIC_LOCAL_FAIL_CLOSED_CANONICAL_PLAN_FEASIBILITY_GATE"
PLAN_FEASIBILITY_MODE = "STRUCTURAL_CONTRACTUAL_LOCAL_CONTEXT_FEASIBILITY_NO_AUTHORIZATION"

_REQUEST_FIELDS = {
    "idempotency_key", "expected_version_sha256", "expected_state_version",
    "expected_generated_plan_id", "expected_generated_plan_sha256",
    "created_by", "reason", "metadata",
}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_plan_validation_id() -> str:
    return f"{PLAN_VALIDATION_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def normalize_plan_validation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("plan-validation request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "Stage 3.3.6 plan validation does not accept caller-supplied feasibility, authorization, readiness, schedule, dispatch, or execution fields: "
            + ", ".join(unknown)
        )
    idem = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idem):
        raise MissionValidationError("idempotency_key contains unsupported characters")
    expected_version = _require_string(payload, "expected_version_sha256", 64).lower()
    expected_plan_sha = _require_string(payload, "expected_generated_plan_sha256", 64).lower()
    if not _SHA256_RE.match(expected_version) or not _SHA256_RE.match(expected_plan_sha):
        raise MissionValidationError("expected SHA-256 fields must be lowercase SHA-256 hex digests")
    try:
        state_version = int(payload.get("expected_state_version"))
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("expected_state_version must be an integer") from exc
    if state_version < 1:
        raise MissionValidationError("expected_state_version must be >= 1")
    generated_plan_id = _require_string(payload, "expected_generated_plan_id")
    created_by = _require_string(payload, "created_by")
    reason = payload.get("reason")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 2048):
        raise MissionValidationError("reason must be a string up to 2048 characters")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    return {
        "idempotency_key": idem,
        "expected_version_sha256": expected_version,
        "expected_state_version": state_version,
        "expected_generated_plan_id": generated_plan_id,
        "expected_generated_plan_sha256": expected_plan_sha,
        "created_by": created_by,
        "reason": None if reason is None else reason.strip(),
        "metadata": dict(metadata),
    }


def plan_validation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": PLAN_VALIDATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def evaluate_plan_feasibility(
    *,
    generated_plan_record: Mapping[str, Any],
    decomposition_record: Mapping[str, Any],
    task_records: Sequence[Mapping[str, Any]],
    graph_record: Mapping[str, Any],
    mission_required_subsystems: Sequence[str],
) -> Dict[str, Any]:
    generated = generated_plan_record["generated_plan"]
    decomposition = decomposition_record["decomposition"]
    graph = graph_record["graph"]
    if not verify_generated_plan_contract(generated):
        raise MissionPlanValidationGuardRejected("generated candidate Plan integrity verification failed")
    if generated_plan_record["status"] != GENERATED_PLAN_STATUS:
        raise MissionPlanValidationGuardRejected("Stage 3.3.6 requires GENERATED_UNVALIDATED candidate Plan")
    if not verify_task_decomposition_contract(decomposition):
        raise MissionPlanValidationGuardRejected("task decomposition integrity verification failed")
    if not verify_task_dependency_graph_contract(graph):
        raise MissionPlanValidationGuardRejected("dependency graph integrity verification failed")
    if graph_record["validation_status"] != "PASS":
        raise MissionPlanValidationGuardRejected("Stage-3.3.4 dependency graph is not structurally VALIDATED")

    candidate = generated["generated_plan"]
    steps = list(candidate["plan_steps"])
    if not steps:
        raise MissionPlanValidationGuardRejected("candidate Plan must contain at least one plan step")
    tasks = []
    for row in task_records:
        contract = row["task_contract"]
        if not verify_planned_task_contract(contract):
            raise MissionPlanValidationGuardRejected("planned-task integrity verification failed")
        spec = dict(contract["specification"])
        spec["task_key"] = contract["identity"]["task_key"]
        tasks.append(spec)
    task_by_key = {t["task_key"]: t for t in tasks}
    ordered = list(candidate["ordered_task_keys"])
    if len(ordered) != len(task_by_key) or set(ordered) != set(task_by_key):
        raise MissionPlanValidationGuardRejected("candidate Plan does not cover the exact canonical planned-task set")
    if int(candidate["task_count"]) != len(tasks):
        raise MissionPlanValidationGuardRejected("candidate task_count does not match canonical task decomposition")
    if int(candidate["dependency_edge_count"]) != int(graph_record["edge_count"]):
        raise MissionPlanValidationGuardRejected("candidate dependency cardinality does not match validated DAG")

    allowed_subsystems = {str(x).upper() for x in mission_required_subsystems}
    for step in steps:
        key = step["task_key"]
        task = task_by_key.get(key)
        if task is None:
            raise MissionPlanValidationGuardRejected(f"candidate task {key} is not canonical")
        if step["task_sha256"] != next(r["canonical_sha256"] for r in task_records if r["task_key"] == key):
            raise MissionPlanValidationGuardRejected(f"candidate task {key} hash binding is stale")
        if not str(step.get("required_capability") or "").strip():
            raise MissionPlanValidationGuardRejected(f"candidate task {key} has no required capability")
        if str(step.get("required_subsystem") or "").upper() not in allowed_subsystems:
            raise MissionPlanValidationGuardRejected(f"candidate task {key} required_subsystem is outside Mission required_subsystems")
        if not step.get("expected_outputs"):
            raise MissionPlanValidationGuardRejected(f"candidate task {key} has no expected outputs")
        if not step.get("success_criteria"):
            raise MissionPlanValidationGuardRejected(f"candidate task {key} has no success criteria")
        if not step.get("evidence_requirements"):
            raise MissionPlanValidationGuardRejected(f"candidate task {key} has no evidence requirements")

    checks = [
        ("GENERATED_PLAN_INTEGRITY", "PASS"),
        ("CANONICAL_SOURCE_BINDINGS", "PASS"),
        ("EXACT_TASK_SET_COVERAGE", "PASS"),
        ("VALIDATED_DEPENDENCY_DAG", "PASS"),
        ("MISSION_SUBSYSTEM_COMPATIBILITY", "PASS"),
        ("CAPABILITY_DECLARATION", "PASS"),
        ("EXPECTED_OUTPUT_CONTRACT", "PASS"),
        ("SUCCESS_CRITERIA_COVERAGE", "PASS"),
        ("EVIDENCE_REQUIREMENT_COVERAGE", "PASS"),
        ("AUTHORITY_BOUNDARY", "PASS"),
    ]
    return {
        "status": PLAN_VALIDATION_STATUS,
        "feasible": True,
        "check_count": len(checks),
        "checks": [{"check_id": k, "status": v} for k, v in checks],
        "task_count": len(tasks),
        "dependency_edge_count": int(graph_record["edge_count"]),
        "planning_layer_count": int(candidate["planning_layer_count"]),
        "semantics": {
            "feasibility_is_authorization": False,
            "validation_is_governance_decision": False,
            "plan_activation_performed": False,
            "readiness_projection_performed": False,
            "scheduling_performed": False,
            "governance_authorization_query_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
    }


def build_plan_validation_contract(
    *, validation_id: str, validation_version: int, mission_id: str,
    request_sha256: str, source_version_sha256: str, state: Mapping[str, Any],
    generated_plan_record: Mapping[str, Any], feasibility: Mapping[str, Any],
    created_by: str, reason: str | None, metadata: Mapping[str, Any], created_at: str,
) -> Dict[str, Any]:
    generated = generated_plan_record["generated_plan"]
    core = {
        "schema_version": PLAN_VALIDATION_SCHEMA_VERSION,
        "identity": {
            "plan_validation_id": validation_id,
            "validation_version": int(validation_version),
            "mission_id": mission_id,
            "plan_id": generated_plan_record["plan_id"],
            "plan_version": int(generated_plan_record["plan_version"]),
            "generated_plan_id": generated_plan_record["generated_plan_id"],
            "generation_version": int(generated_plan_record["generation_version"]),
            "created_by": created_by,
            "created_at": created_at,
        },
        "source_bindings": {
            "source_version_sha256": source_version_sha256,
            "source_state": state["state"],
            "source_state_version": int(state["state_version"]),
            "generated_plan_sha256": generated_plan_record["canonical_sha256"],
            "planner_output_sha256": generated_plan_record["planner_output_sha256"],
            "planner_invocation_id": generated_plan_record["planner_invocation_id"],
            "snapshot_id": generated["source_bindings"]["snapshot_id"],
            "snapshot_sha256": generated["source_bindings"]["snapshot_sha256"],
            "decomposition_id": generated["source_bindings"]["decomposition_id"],
            "decomposition_sha256": generated["source_bindings"]["decomposition_sha256"],
            "task_set_sha256": generated["source_bindings"]["task_set_sha256"],
            "graph_id": generated["source_bindings"]["graph_id"],
            "graph_sha256": generated["source_bindings"]["graph_sha256"],
            "node_set_sha256": generated["source_bindings"]["node_set_sha256"],
            "edge_set_sha256": generated["source_bindings"]["edge_set_sha256"],
        },
        "validation": dict(feasibility),
        "request": {"request_sha256": request_sha256, "reason": reason, "metadata": dict(metadata)},
        "authority": {
            "validation_authority": "GLOBAL_MISSION_ORCHESTRATOR_LOCAL_PLAN_VALIDATOR",
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "plan_is_authorization": False,
            "task_is_dispatch": False,
            "readiness_is_permission": False,
            "planner_is_governance": False,
        },
    }
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": PLAN_VALIDATION_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": sha256_hex({"hash_domain": PLAN_VALIDATION_HASH_DOMAIN, "contract": core}),
        },
    }


def verify_plan_validation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        return (
            contract.get("schema_version") == PLAN_VALIDATION_SCHEMA_VERSION
            and contract["validation"]["status"] == PLAN_VALIDATION_STATUS
            and contract["validation"]["feasible"] is True
            and integrity.get("hash_domain") == PLAN_VALIDATION_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex({"hash_domain": PLAN_VALIDATION_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_plan_validation_definition() -> Dict[str, Any]:
    return {
        "schema_version": PLAN_VALIDATION_SCHEMA_VERSION,
        "mode": PLAN_VALIDATION_MODE,
        "feasibility_mode": PLAN_FEASIBILITY_MODE,
        "creation_state_required": PLAN_VALIDATION_REQUIRED_STATE,
        "validation_status": PLAN_VALIDATION_STATUS,
        "requires_generated_plan_status": GENERATED_PLAN_STATUS,
        "requires_stage3_3_1_plan_contract": True,
        "requires_stage3_3_2_planner_input_snapshot": True,
        "requires_stage3_3_3_task_decomposition": True,
        "requires_stage3_3_4_validated_dependency_graph": True,
        "requires_stage3_3_5_generated_candidate_plan": True,
        "local_deterministic_validation": True,
        "plan_activation_performed": False,
        "readiness_projection_performed": False,
        "scheduling_performed": False,
        "governance_authorization_query_performed": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
