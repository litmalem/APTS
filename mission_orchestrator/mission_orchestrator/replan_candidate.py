from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .replan_snapshot import verify_replan_snapshot_contract

REPLAN_CANDIDATE_STAGE_SCHEMA_VERSION = "apts-deterministic-replan-candidate-generation-v1"
REPLAN_CANDIDATE_CONTRACT_SCHEMA_VERSION = "apts-replan-candidate-generation-contract-v1"
REPLAN_CANDIDATE_HASH_DOMAIN = "MISSION_DETERMINISTIC_REPLAN_CANDIDATE_V1"
REPLAN_CANDIDATE_REQUEST_HASH_DOMAIN = "MISSION_REPLAN_CANDIDATE_GENERATION_REQUEST_V1"
REPLAN_CANDIDATE_PAYLOAD_HASH_DOMAIN = "MISSION_REPLAN_CANDIDATE_PAYLOAD_V1"
REPLAN_PLANNER_INVOCATION_HASH_DOMAIN = "MISSION_REPLAN_PLANNER_INVOCATION_V1"
REPLAN_CANDIDATE_ID_PREFIX = "rpcand-"
REPLAN_PLANNER_INVOCATION_ID_PREFIX = "rpinv-"
REPLAN_CANDIDATE_STATUS = "CANDIDATE_GENERATED"
REPLAN_CANDIDATE_EVENT_TYPE = "MISSION_REPLAN_CANDIDATE_GENERATED"
REPLAN_CANDIDATE_AUTHORITY = "MISSION_ORCHESTRATOR_DETERMINISTIC_REPLAN_CANDIDATE_GENERATION"
REPLAN_CANDIDATE_MODE = (
    "DETERMINISTIC_LOCAL_PURE_FUNCTION_OVER_IMMUTABLE_REPLAN_SNAPSHOT_"
    "CANDIDATE_ONLY_NO_VALIDATION_NO_COMMIT_NO_SUPERSESSION_NO_ACTUATION"
)
REPLAN_PLANNER_PROFILE = "CANONICAL_REPLAN_REMAINDER_DAG_V1"
REPLAN_PLANNER_ENGINE = "APTS_MO_LOCAL_DETERMINISTIC_REPLAN_PLANNER"
REPLAN_PLANNER_ENGINE_VERSION = "1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key", "expected_replan_snapshot_id", "expected_replan_snapshot_sha256",
    "expected_task_context_sha256", "expected_source_plan_version_record_id", "expected_source_plan_version",
    "expected_source_plan_sha256", "expected_source_state_version", "expected_source_version_sha256",
    "planner_profile", "generated_by", "reason", "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_replan_candidate_id() -> str:
    return f"{REPLAN_CANDIDATE_ID_PREFIX}{uuid.uuid4()}"


def new_replan_planner_invocation_id() -> str:
    return f"{REPLAN_PLANNER_INVOCATION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_replan_candidate_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("replan candidate generation request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported replan candidate generation field(s): " + ", ".join(unknown)
            + "; Stage 3.7.5 derives the candidate solely from the immutable Stage-3.7.4 ReplanSnapshot. "
              "Caller-supplied tasks, dependencies, planner output, plan delta, validation, commit, supersession, "
              "routing, dispatch, execution, target-action, or actuation fields are forbidden"
        )
    ids = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_replan_snapshot_id": _string(payload, "expected_replan_snapshot_id"),
        "expected_source_plan_version_record_id": _string(payload, "expected_source_plan_version_record_id"),
        "generated_by": _string(payload, "generated_by", 128),
    }
    for key, value in ids.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not ids["expected_replan_snapshot_id"].startswith("rpsnap-"):
        raise MissionValidationError("expected_replan_snapshot_id must be a canonical rpsnap-* identifier")
    if not ids["expected_source_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_source_plan_version_record_id must be a canonical pver-* identifier")
    profile = _string(payload, "planner_profile", 96).upper()
    if profile != REPLAN_PLANNER_PROFILE:
        raise MissionValidationError(f"planner_profile must be {REPLAN_PLANNER_PROFILE}")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason in (None, ""):
        reason = None
    elif not isinstance(reason, str) or not reason.strip():
        raise MissionValidationError("reason must be a non-empty string when provided")
    else:
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    return {
        **ids,
        "expected_replan_snapshot_sha256": _sha(payload, "expected_replan_snapshot_sha256"),
        "expected_task_context_sha256": _sha(payload, "expected_task_context_sha256"),
        "expected_source_plan_version": _positive_int(payload, "expected_source_plan_version"),
        "expected_source_plan_sha256": _sha(payload, "expected_source_plan_sha256"),
        "expected_source_state_version": _positive_int(payload, "expected_source_state_version"),
        "expected_source_version_sha256": _sha(payload, "expected_source_version_sha256"),
        "planner_profile": profile,
        "reason": reason,
        "metadata": dict(metadata),
    }


def replan_candidate_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": REPLAN_CANDIDATE_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _is_completed(completion: Mapping[str, Any]) -> bool:
    status = str(completion.get("completion_status") or completion.get("task_completion_status") or "").upper()
    return status in {"COMPLETED", "VERIFIED_COMPLETE", "COMPLETION_COMMITTED", "SUCCESS"}


def deterministic_replan_candidate_payload(snapshot_contract: Mapping[str, Any]) -> Dict[str, Any]:
    if not verify_replan_snapshot_contract(snapshot_contract):
        raise MissionValidationError("source ReplanSnapshot failed integrity verification")
    task_ctx = snapshot_contract["task_dependency_outcome_context"]
    tasks = list(task_ctx.get("tasks") or [])
    edges = list(task_ctx.get("dependency_edges") or [])
    completions = list(task_ctx.get("task_completions") or [])
    completed_ids = {
        str(x.get("planned_task_id")) for x in completions
        if x.get("planned_task_id") and _is_completed(x)
    }
    # Completion records in Stage 3.7.4 are authoritative historical facts. Even if a legacy
    # status vocabulary is unfamiliar, a bound completion record means the source task has
    # reached the completion pipeline and is not regenerated as new executable work.
    completed_ids.update(str(x.get("planned_task_id")) for x in completions if x.get("planned_task_id"))

    ordered = sorted(tasks, key=lambda x: (int(x.get("task_index", 0)), str(x.get("planned_task_id"))))
    candidate_tasks = []
    for new_index, t in enumerate((x for x in ordered if str(x["planned_task_id"]) not in completed_ids), start=1):
        candidate_tasks.append({
            "source_planned_task_id": t["planned_task_id"],
            "task_key": t["task_key"],
            "source_task_index": int(t["task_index"]),
            "candidate_task_index": new_index,
            "source_task_sha256": t["canonical_sha256"],
            "disposition": "RETAIN_UNFINISHED",
        })
    retained = {x["source_planned_task_id"] for x in candidate_tasks}
    candidate_edges = []
    satisfied_predecessors = []
    for e in sorted(edges, key=lambda x: str(x.get("dependency_edge_id"))):
        src = str(e["from_planned_task_id"]); dst = str(e["to_planned_task_id"])
        projection = {
            "source_dependency_edge_id": e["dependency_edge_id"],
            "from_source_planned_task_id": src,
            "to_source_planned_task_id": dst,
            "dependency_type": e.get("dependency_type", "HARD"),
            "source_edge_sha256": e["canonical_sha256"],
        }
        if dst in retained and src in retained:
            candidate_edges.append({**projection, "disposition": "RETAIN_EDGE"})
        elif dst in retained and src in completed_ids:
            satisfied_predecessors.append({**projection, "disposition": "SATISFIED_BY_SOURCE_COMPLETION"})

    payload = {
        "planning_strategy": "RETAIN_UNFINISHED_SOURCE_TASKS_PRESERVE_REMAINING_DAG_V1",
        "task_generation_semantics": "DETERMINISTIC_PROJECTION_NO_FREEFORM_MODEL_GENERATION",
        "source_task_count": len(tasks),
        "source_dependency_edge_count": len(edges),
        "completed_source_task_count": len(completed_ids),
        "candidate_task_count": len(candidate_tasks),
        "candidate_dependency_edge_count": len(candidate_edges),
        "satisfied_predecessor_count": len(satisfied_predecessors),
        "candidate_tasks": candidate_tasks,
        "candidate_dependency_edges": candidate_edges,
        "satisfied_source_predecessors": satisfied_predecessors,
    }
    knowledge = snapshot_contract.get("cti_feedback_context")
    if knowledge is not None:
        payload["cti_feedback_requirements"] = {
            "knowledge_id":knowledge["knowledge_id"], "revision_id":knowledge["revision_id"],
            "knowledge_sha256":knowledge["integrity"]["canonical_sha256"],
            "hypothesis_outcome":knowledge["assessment"]["hypothesis_outcome"],
            "target":dict(knowledge["subject"]["target"]), "required_capability":"validation",
            "validation_still_required":True, "review_required":knowledge["mission_signal"]["review_required"],
            "blocking_reasons":list(knowledge["mission_signal"]["blocking_reasons"]),
            "execution_authorized":False}
    return {**payload, "candidate_payload_sha256": sha256_hex({"hash_domain": REPLAN_CANDIDATE_PAYLOAD_HASH_DOMAIN, "payload": payload})}


def build_replan_candidate_contract(*, replan_candidate_id: str, planner_invocation_id: str, mission_id: str,
                                    request: Mapping[str, Any], request_sha256: str,
                                    snapshot_record: Mapping[str, Any], generated_at: str) -> Dict[str, Any]:
    snapshot = snapshot_record["replan_snapshot_contract"]
    if not verify_replan_snapshot_contract(snapshot):
        raise MissionValidationError("source ReplanSnapshot failed integrity verification")
    src = snapshot["source_bindings"]
    ident = snapshot["identity"]
    payload = deterministic_replan_candidate_payload(snapshot)
    invocation_core = {
        "planner_invocation_id": planner_invocation_id,
        "planner_profile": REPLAN_PLANNER_PROFILE,
        "planner_engine": REPLAN_PLANNER_ENGINE,
        "planner_engine_version": REPLAN_PLANNER_ENGINE_VERSION,
        "input_replan_snapshot_id": snapshot_record["replan_snapshot_id"],
        "input_replan_snapshot_sha256": snapshot_record["canonical_sha256"],
        "input_task_context_sha256": snapshot_record["task_context_sha256"],
        "deterministic": True,
        "external_context_refresh_performed": False,
        "governance_query_performed": False,
        "generated_at": generated_at,
    }
    invocation = {**invocation_core, "canonical_sha256": sha256_hex({"hash_domain": REPLAN_PLANNER_INVOCATION_HASH_DOMAIN, "invocation": invocation_core})}
    core = {
        "schema_version": REPLAN_CANDIDATE_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": REPLAN_CANDIDATE_STAGE_SCHEMA_VERSION,
        "identity": {
            "replan_candidate_id": replan_candidate_id,
            "planner_invocation_id": planner_invocation_id,
            "mission_id": mission_id,
            "adaptation_episode_id": ident["adaptation_episode_id"],
            "replan_trigger_id": ident["replan_trigger_id"],
            "classification_id": ident["classification_id"],
            "eligibility_gate_id": ident["eligibility_gate_id"],
            "replan_snapshot_id": snapshot_record["replan_snapshot_id"],
        },
        "source_bindings": {
            "replan_snapshot_sha256": snapshot_record["canonical_sha256"],
            "task_context_sha256": snapshot_record["task_context_sha256"],
            "source_plan_version_record_id": src["source_plan_version_record_id"],
            "source_plan_version": int(src["source_plan_version"]),
            "source_plan_generation": int(src["source_plan_generation"]),
            "source_plan_sha256": src["source_plan_sha256"],
            "canonical_plan_id": src["canonical_plan_id"],
            "source_state": src["source_state"],
            "source_state_version": int(src["source_state_version"]),
            "source_version_sha256": src["source_version_sha256"],
            "mission_scope_sha256": src["mission_scope_sha256"],
            "governance_binding_sha256": src["governance_binding_sha256"],
            "policy_decision_hash": src["policy_decision_hash"],
            **({"cti_knowledge_sha256":src["cti_knowledge_sha256"]} if "cti_knowledge_sha256" in src else {}),
        },
        "planner_invocation": invocation,
        "candidate_successor_plan": {
            "candidate_status": REPLAN_CANDIDATE_STATUS,
            "candidate_only": True,
            "source_plan_version": int(src["source_plan_version"]),
            "candidate_plan_version": int(src["source_plan_version"]) + 1,
            "source_plan_generation": int(src["source_plan_generation"]),
            "candidate_plan_generation": int(src["target_plan_generation"]),
            **payload,
        },
        "authority_boundary": {
            "authority": REPLAN_CANDIDATE_AUTHORITY,
            "mode": REPLAN_CANDIDATE_MODE,
            "planner_invocation_performed": True,
            "replan_candidate_created": True,
            "successor_plan_created": False,
            "plan_delta_computed": True,
            "plan_validation_performed": False,
            "replan_decision_committed": False,
            "plan_supersession_performed": False,
            "historical_plan_mutation_performed": False,
            "mission_state_transition_performed": False,
            "governance_query_performed": False,
            "external_context_refresh_performed": False,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "execution_attempt_created": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "generated_by": request["generated_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "generated_at": generated_at,
        },
    }
    return {**core, "canonical_sha256": sha256_hex({"hash_domain": REPLAN_CANDIDATE_HASH_DOMAIN, "contract": core})}


def verify_replan_candidate_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != REPLAN_CANDIDATE_CONTRACT_SCHEMA_VERSION or contract.get("stage_schema_version") != REPLAN_CANDIDATE_STAGE_SCHEMA_VERSION:
            return False
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if digest != sha256_hex({"hash_domain": REPLAN_CANDIDATE_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]; src = contract["source_bindings"]; inv = contract["planner_invocation"]
        cand = contract["candidate_successor_plan"]; b = contract["authority_boundary"]
        if not str(ident.get("replan_candidate_id", "")).startswith(REPLAN_CANDIDATE_ID_PREFIX): return False
        if not str(ident.get("planner_invocation_id", "")).startswith(REPLAN_PLANNER_INVOCATION_ID_PREFIX): return False
        if not str(ident.get("replan_snapshot_id", "")).startswith("rpsnap-"): return False
        for key in ("replan_snapshot_sha256", "task_context_sha256", "source_plan_sha256", "source_version_sha256", "mission_scope_sha256", "governance_binding_sha256", "policy_decision_hash"):
            if not _SHA_RE.match(str(src.get(key) or "")): return False
        inv_core = {k: v for k, v in inv.items() if k != "canonical_sha256"}
        if inv.get("canonical_sha256") != sha256_hex({"hash_domain": REPLAN_PLANNER_INVOCATION_HASH_DOMAIN, "invocation": inv_core}): return False
        if inv.get("deterministic") is not True or inv.get("planner_profile") != REPLAN_PLANNER_PROFILE: return False
        payload = {k: v for k, v in cand.items() if k not in {"candidate_status", "candidate_only", "source_plan_version", "candidate_plan_version", "source_plan_generation", "candidate_plan_generation", "candidate_payload_sha256"}}
        # reconstruct exact payload core
        ph = {k: cand[k] for k in ("planning_strategy", "task_generation_semantics", "source_task_count", "source_dependency_edge_count", "completed_source_task_count", "candidate_task_count", "candidate_dependency_edge_count", "satisfied_predecessor_count", "candidate_tasks", "candidate_dependency_edges", "satisfied_source_predecessors")}
        requirements = cand.get("cti_feedback_requirements")
        if requirements is not None:
            if (set(requirements) != {"knowledge_id", "revision_id", "knowledge_sha256", "hypothesis_outcome", "target",
                "required_capability", "validation_still_required", "review_required", "blocking_reasons", "execution_authorized"}
                or requirements["knowledge_sha256"] != src.get("cti_knowledge_sha256")
                or requirements["hypothesis_outcome"] != "INCONCLUSIVE"
                or requirements["required_capability"] != "validation"
                or requirements["validation_still_required"] is not True or requirements["execution_authorized"] is not False):
                return False
            ph["cti_feedback_requirements"] = requirements
        elif "cti_knowledge_sha256" in src:
            return False
        if cand.get("candidate_payload_sha256") != sha256_hex({"hash_domain": REPLAN_CANDIDATE_PAYLOAD_HASH_DOMAIN, "payload": ph}): return False
        if cand.get("candidate_status") != REPLAN_CANDIDATE_STATUS or cand.get("candidate_only") is not True: return False
        if int(cand.get("candidate_plan_version")) != int(src["source_plan_version"]) + 1: return False
        if b.get("authority") != REPLAN_CANDIDATE_AUTHORITY or b.get("mode") != REPLAN_CANDIDATE_MODE: return False
        for key in ("planner_invocation_performed", "replan_candidate_created", "plan_delta_computed"):
            if b.get(key) is not True: return False
        for key in ("successor_plan_created", "plan_validation_performed", "replan_decision_committed", "plan_supersession_performed", "historical_plan_mutation_performed", "mission_state_transition_performed", "governance_query_performed", "external_context_refresh_performed", "routing_performed", "delegation_performed", "dispatch_performed", "execution_attempt_created", "target_actuation"):
            if b.get(key) is not False: return False
        return True
    except Exception:
        return False


def canonical_replan_candidate_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": REPLAN_CANDIDATE_STAGE_SCHEMA_VERSION,
        "contract_schema_version": REPLAN_CANDIDATE_CONTRACT_SCHEMA_VERSION,
        "candidate_identity_prefix": REPLAN_CANDIDATE_ID_PREFIX,
        "planner_invocation_identity_prefix": REPLAN_PLANNER_INVOCATION_ID_PREFIX,
        "candidate_status": REPLAN_CANDIDATE_STATUS,
        "event_type": REPLAN_CANDIDATE_EVENT_TYPE,
        "authority": REPLAN_CANDIDATE_AUTHORITY,
        "mode": REPLAN_CANDIDATE_MODE,
        "planner_profile": REPLAN_PLANNER_PROFILE,
        "requires_stage374_replan_snapshot": True,
        "snapshot_is_sole_authoritative_planning_input": True,
        "deterministic_local_planner": True,
        "canonical_task_dependency_ordering": True,
        "completed_source_tasks_are_not_regenerated": True,
        "preserves_source_plan_predecessor_binding": True,
        "candidate_only": True,
        "planner_invocation_performed": True,
        "replan_candidate_created": True,
        "plan_delta_computed": True,
        "successor_plan_created": False,
        "plan_validation_performed": False,
        "replan_decision_committed": False,
        "plan_supersession_performed": False,
        "mission_state_transition_performed": False,
        "dispatch_performed": False,
        "target_actuation": False,
        "one_candidate_per_replan_snapshot": True,
        "idempotent_recovery_supported": True,
        "next_stage": "3.7.6",
    }
