from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .replan_candidate import (
    REPLAN_CANDIDATE_STATUS,
    deterministic_replan_candidate_payload,
    verify_replan_candidate_contract,
)
from .replan_snapshot import verify_replan_snapshot_contract

REPLAN_VALIDATION_STAGE_SCHEMA_VERSION = "apts-replan-candidate-validation-delta-feasibility-gate-v1"
REPLAN_VALIDATION_CONTRACT_SCHEMA_VERSION = "apts-replan-candidate-validation-decision-contract-v1"
REPLAN_VALIDATION_HASH_DOMAIN = "MISSION_REPLAN_CANDIDATE_VALIDATION_DECISION_V1"
REPLAN_VALIDATION_REQUEST_HASH_DOMAIN = "MISSION_REPLAN_CANDIDATE_VALIDATION_REQUEST_V1"
REPLAN_VALIDATION_ID_PREFIX = "rpdec-"
REPLAN_VALIDATION_EVENT_TYPE = "MISSION_REPLAN_DECISION_RECORDED"
REPLAN_VALIDATION_AUTHORITY = "MISSION_ORCHESTRATOR_REPLAN_CANDIDATE_VALIDATION_DELTA_FEASIBILITY_GATE"
REPLAN_VALIDATION_MODE = (
    "DETERMINISTIC_FAIL_CLOSED_LOCAL_VALIDATION_OVER_IMMUTABLE_STAGE375_CANDIDATE_"
    "NO_COMMIT_NO_SUPERSESSION_NO_STATE_TRANSITION_NO_DISPATCH_NO_ACTUATION"
)
REPLAN_VALIDATION_STATUS_VALIDATED = "VALIDATED_FOR_COMMIT"
REPLAN_VALIDATION_STATUS_REJECTED = "REJECTED_INFEASIBLE"

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_REQUEST_FIELDS = {
    "idempotency_key", "expected_replan_candidate_id", "expected_replan_candidate_sha256",
    "expected_candidate_payload_sha256", "expected_replan_snapshot_id", "expected_replan_snapshot_sha256",
    "expected_source_plan_version_record_id", "expected_source_plan_version", "expected_source_plan_sha256",
    "expected_source_state_version", "expected_source_version_sha256", "validated_by", "reason", "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_replan_validation_id() -> str:
    return f"{REPLAN_VALIDATION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_replan_validation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("replan candidate validation request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported replan candidate validation field(s): " + ", ".join(unknown)
            + "; Stage 3.7.6 validates the immutable Stage-3.7.5 candidate only. "
              "Caller-supplied validation result, feasibility override, tasks, dependencies, commit, supersession, "
              "state transition, governance decision, routing, dispatch, execution, or actuation fields are forbidden"
        )
    ids = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_replan_candidate_id": _string(payload, "expected_replan_candidate_id"),
        "expected_replan_snapshot_id": _string(payload, "expected_replan_snapshot_id"),
        "expected_source_plan_version_record_id": _string(payload, "expected_source_plan_version_record_id"),
        "validated_by": _string(payload, "validated_by", 128),
    }
    for key, value in ids.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not ids["expected_replan_candidate_id"].startswith("rpcand-"):
        raise MissionValidationError("expected_replan_candidate_id must be a canonical rpcand-* identifier")
    if not ids["expected_replan_snapshot_id"].startswith("rpsnap-"):
        raise MissionValidationError("expected_replan_snapshot_id must be a canonical rpsnap-* identifier")
    if not ids["expected_source_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_source_plan_version_record_id must be a canonical pver-* identifier")
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
        "expected_replan_candidate_sha256": _sha(payload, "expected_replan_candidate_sha256"),
        "expected_candidate_payload_sha256": _sha(payload, "expected_candidate_payload_sha256"),
        "expected_replan_snapshot_sha256": _sha(payload, "expected_replan_snapshot_sha256"),
        "expected_source_plan_version": _positive_int(payload, "expected_source_plan_version"),
        "expected_source_plan_sha256": _sha(payload, "expected_source_plan_sha256"),
        "expected_source_state_version": _positive_int(payload, "expected_source_state_version"),
        "expected_source_version_sha256": _sha(payload, "expected_source_version_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def replan_validation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": REPLAN_VALIDATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _is_completed(completion: Mapping[str, Any]) -> bool:
    # Stage 3.7.5 treats every bound completion record as historical completed work.
    return bool(completion.get("planned_task_id"))


def _acyclic(nodes: set[str], edges: list[tuple[str, str]]) -> bool:
    outgoing = {n: [] for n in nodes}
    indegree = {n: 0 for n in nodes}
    for src, dst in edges:
        if src not in nodes or dst not in nodes:
            return False
        outgoing[src].append(dst)
        indegree[dst] += 1
    ready = sorted(n for n, d in indegree.items() if d == 0)
    seen = 0
    while ready:
        node = ready.pop(0)
        seen += 1
        for nxt in sorted(outgoing[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort()
    return seen == len(nodes)


def evaluate_replan_candidate_feasibility(
    candidate_contract: Mapping[str, Any], snapshot_contract: Mapping[str, Any]
) -> Dict[str, Any]:
    findings: list[Dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        findings.append({"check_id": check_id, "passed": bool(passed), "detail": detail})

    check("CANDIDATE_INTEGRITY", verify_replan_candidate_contract(candidate_contract), "Stage-3.7.5 candidate integrity")
    check("SNAPSHOT_INTEGRITY", verify_replan_snapshot_contract(snapshot_contract), "Stage-3.7.4 snapshot integrity")
    if not findings[-2]["passed"] or not findings[-1]["passed"]:
        return {"feasible": False, "findings": findings, "rejection_codes": [x["check_id"] for x in findings if not x["passed"]]}

    ident = candidate_contract["identity"]
    src = candidate_contract["source_bindings"]
    cand = candidate_contract["candidate_successor_plan"]
    snap_src = snapshot_contract["source_bindings"]
    ctx = snapshot_contract["task_dependency_outcome_context"]

    check("CANDIDATE_STATUS", cand.get("candidate_status") == REPLAN_CANDIDATE_STATUS and cand.get("candidate_only") is True,
          "candidate remains immutable candidate-only material")
    check("SNAPSHOT_ID_BINDING", ident.get("replan_snapshot_id") == snapshot_contract["identity"].get("replan_snapshot_id"),
          "candidate binds exact source ReplanSnapshot")
    check("SNAPSHOT_HASH_BINDING", src.get("replan_snapshot_sha256") == snapshot_contract.get("canonical_sha256"),
          "candidate binds exact ReplanSnapshot hash")
    check("TASK_CONTEXT_BINDING", src.get("task_context_sha256") == snap_src.get("task_context_sha256"),
          "candidate binds exact task/dependency/outcome context")
    check("SOURCE_PLAN_BINDING",
          src.get("source_plan_version_record_id") == snap_src.get("source_plan_version_record_id")
          and int(src.get("source_plan_version", 0)) == int(snap_src.get("source_plan_version", 0))
          and src.get("source_plan_sha256") == snap_src.get("source_plan_sha256"),
          "candidate source Plan identity/version/hash matches snapshot")
    check("SOURCE_MISSION_VERSION_BINDING",
          int(src.get("source_state_version", 0)) == int(snap_src.get("source_state_version", 0))
          and src.get("source_version_sha256") == snap_src.get("source_version_sha256"),
          "candidate source Mission version matches snapshot")
    check("NEXT_PLAN_VERSION", int(cand.get("candidate_plan_version", 0)) == int(src.get("source_plan_version", 0)) + 1,
          "candidate targets exactly source Plan version + 1")
    check("TARGET_GENERATION", int(cand.get("candidate_plan_generation", 0)) == int(snap_src.get("target_plan_generation", 0)),
          "candidate targets snapshot-authorized next plan generation")

    expected_payload = deterministic_replan_candidate_payload(snapshot_contract)
    expected_payload = {k: v for k, v in expected_payload.items() if k != "candidate_payload_sha256"}
    observed_payload = {k: cand[k] for k in (
        "planning_strategy", "task_generation_semantics", "source_task_count", "source_dependency_edge_count",
        "completed_source_task_count", "candidate_task_count", "candidate_dependency_edge_count",
        "satisfied_predecessor_count", "candidate_tasks", "candidate_dependency_edges", "satisfied_source_predecessors"
    )}
    # Stage 6.9 CTI context is part of the deterministic candidate payload.
    # Omitting it here rejects every CTI-bound candidate even when the exact
    # trusted snapshot reproduces it. Include the observed field only when
    # present: a missing or forged requirement still fails exact equality.
    if "cti_feedback_requirements" in cand:
        observed_payload["cti_feedback_requirements"] = cand["cti_feedback_requirements"]
    check("DETERMINISTIC_REPRODUCTION", observed_payload == expected_payload,
          "candidate payload exactly reproduces deterministic Stage-3.7.5 projection")

    tasks = list(cand.get("candidate_tasks") or [])
    edges = list(cand.get("candidate_dependency_edges") or [])
    satisfied = list(cand.get("satisfied_source_predecessors") or [])
    source_tasks = {str(t.get("planned_task_id")): t for t in (ctx.get("tasks") or [])}
    completed_ids = {str(c.get("planned_task_id")) for c in (ctx.get("task_completions") or []) if _is_completed(c)}
    ids = [str(t.get("source_planned_task_id")) for t in tasks]
    indices = [int(t.get("candidate_task_index", 0)) for t in tasks]

    check("NON_EMPTY_DELTA", len(tasks) > 0, "candidate contains at least one unfinished task")
    check("UNIQUE_TASKS", len(ids) == len(set(ids)) and all(x for x in ids), "candidate task identities are unique")
    check("CONTIGUOUS_TASK_ORDER", indices == list(range(1, len(tasks) + 1)), "candidate task indices are contiguous and canonical")
    check("TASK_SOURCE_MEMBERSHIP", all(x in source_tasks for x in ids), "every candidate task exists in source snapshot")
    check("NO_COMPLETED_TASK_RECURRENCE", not (set(ids) & completed_ids), "completed source tasks are never regenerated")
    task_hash_ok = all(
        x in source_tasks and t.get("source_task_sha256") == source_tasks[x].get("canonical_sha256")
        for t, x in zip(tasks, ids)
    )
    check("TASK_HASH_BINDING", task_hash_ok, "candidate task hashes bind source task records")

    edge_pairs = [(str(e.get("from_source_planned_task_id")), str(e.get("to_source_planned_task_id"))) for e in edges]
    check("EDGE_ENDPOINT_MEMBERSHIP", all(a in set(ids) and b in set(ids) for a, b in edge_pairs),
          "retained dependency edges reference retained candidate tasks only")
    check("NO_SELF_DEPENDENCY", all(a != b for a, b in edge_pairs), "candidate has no self dependency")
    check("ACYCLIC_REMAINDER_DAG", _acyclic(set(ids), edge_pairs), "remaining dependency graph is acyclic")
    check("SATISFIED_PREDECESSORS",
          all(str(e.get("from_source_planned_task_id")) in completed_ids and str(e.get("to_source_planned_task_id")) in set(ids) for e in satisfied),
          "removed predecessor edges are justified by bound source completions")
    check("COUNT_CONSISTENCY",
          int(cand.get("candidate_task_count", -1)) == len(tasks)
          and int(cand.get("candidate_dependency_edge_count", -1)) == len(edges)
          and int(cand.get("satisfied_predecessor_count", -1)) == len(satisfied),
          "declared candidate counts match materialized delta")

    rejection_codes = [x["check_id"] for x in findings if not x["passed"]]
    return {"feasible": not rejection_codes, "findings": findings, "rejection_codes": rejection_codes}


def build_replan_validation_contract(*, validation_id: str, mission_id: str, request: Mapping[str, Any],
                                     request_sha256: str, candidate_record: Mapping[str, Any],
                                     snapshot_record: Mapping[str, Any], validated_at: str) -> Dict[str, Any]:
    candidate_contract = candidate_record["replan_candidate_contract"]
    result = evaluate_replan_candidate_feasibility(candidate_contract, snapshot_record["replan_snapshot_contract"])
    src = candidate_contract["source_bindings"]
    cand = candidate_contract["candidate_successor_plan"]
    status = REPLAN_VALIDATION_STATUS_VALIDATED if result["feasible"] else REPLAN_VALIDATION_STATUS_REJECTED
    core = {
        "schema_version": REPLAN_VALIDATION_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": REPLAN_VALIDATION_STAGE_SCHEMA_VERSION,
        "identity": {
            "replan_validation_id": validation_id,
            "mission_id": mission_id,
            "replan_candidate_id": candidate_record["replan_candidate_id"],
            "replan_snapshot_id": candidate_record["replan_snapshot_id"],
            "adaptation_episode_id": candidate_record["adaptation_episode_id"],
        },
        "source_bindings": {
            "replan_candidate_sha256": candidate_record["canonical_sha256"],
            "candidate_payload_sha256": candidate_record["candidate_payload_sha256"],
            "replan_snapshot_sha256": snapshot_record["canonical_sha256"],
            "source_plan_version_record_id": src["source_plan_version_record_id"],
            "source_plan_version": int(src["source_plan_version"]),
            "source_plan_sha256": src["source_plan_sha256"],
            "candidate_plan_version": int(cand["candidate_plan_version"]),
            "candidate_plan_generation": int(cand["candidate_plan_generation"]),
            "source_state": src["source_state"],
            "source_state_version": int(src["source_state_version"]),
            "source_version_sha256": src["source_version_sha256"],
        },
        "validation": {
            "validation_status": status,
            "feasible": bool(result["feasible"]),
            "check_count": len(result["findings"]),
            "passed_check_count": sum(1 for x in result["findings"] if x["passed"]),
            "failed_check_count": sum(1 for x in result["findings"] if not x["passed"]),
            "rejection_codes": list(result["rejection_codes"]),
            "findings": list(result["findings"]),
        },
        "authority_boundary": {
            "authority": REPLAN_VALIDATION_AUTHORITY,
            "mode": REPLAN_VALIDATION_MODE,
            "candidate_integrity_verified": True,
            "snapshot_integrity_verified": True,
            "plan_validation_performed": True,
            "delta_feasibility_evaluated": True,
            "validated_for_commit": status == REPLAN_VALIDATION_STATUS_VALIDATED,
            "successor_plan_created": False,
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
            "validated_by": request["validated_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "validated_at": validated_at,
        },
    }
    return {**core, "canonical_sha256": sha256_hex({"hash_domain": REPLAN_VALIDATION_HASH_DOMAIN, "contract": core})}


def verify_replan_validation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != REPLAN_VALIDATION_CONTRACT_SCHEMA_VERSION:
            return False
        if contract.get("stage_schema_version") != REPLAN_VALIDATION_STAGE_SCHEMA_VERSION:
            return False
        digest = contract.get("canonical_sha256")
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if digest != sha256_hex({"hash_domain": REPLAN_VALIDATION_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]; src = contract["source_bindings"]; val = contract["validation"]; b = contract["authority_boundary"]
        if not str(ident.get("replan_validation_id", "")).startswith(REPLAN_VALIDATION_ID_PREFIX): return False
        if not str(ident.get("replan_candidate_id", "")).startswith("rpcand-"): return False
        if not str(ident.get("replan_snapshot_id", "")).startswith("rpsnap-"): return False
        for key in ("replan_candidate_sha256", "candidate_payload_sha256", "replan_snapshot_sha256", "source_plan_sha256", "source_version_sha256"):
            if not _SHA_RE.match(str(src.get(key) or "")): return False
        status = val.get("validation_status")
        if status not in {REPLAN_VALIDATION_STATUS_VALIDATED, REPLAN_VALIDATION_STATUS_REJECTED}: return False
        if bool(val.get("feasible")) != (status == REPLAN_VALIDATION_STATUS_VALIDATED): return False
        findings = list(val.get("findings") or [])
        if int(val.get("check_count", -1)) != len(findings): return False
        failed = [x for x in findings if not x.get("passed")]
        if int(val.get("failed_check_count", -1)) != len(failed): return False
        if list(val.get("rejection_codes") or []) != [x.get("check_id") for x in failed]: return False
        if b.get("authority") != REPLAN_VALIDATION_AUTHORITY or b.get("mode") != REPLAN_VALIDATION_MODE: return False
        for key in ("candidate_integrity_verified", "snapshot_integrity_verified", "plan_validation_performed", "delta_feasibility_evaluated"):
            if b.get(key) is not True: return False
        if b.get("validated_for_commit") is not (status == REPLAN_VALIDATION_STATUS_VALIDATED): return False
        for key in ("successor_plan_created", "replan_decision_committed", "plan_supersession_performed", "historical_plan_mutation_performed",
                    "mission_state_transition_performed", "governance_query_performed", "external_context_refresh_performed", "routing_performed",
                    "delegation_performed", "dispatch_performed", "execution_attempt_created", "target_actuation"):
            if b.get(key) is not False: return False
        return True
    except Exception:
        return False


def canonical_replan_validation_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": REPLAN_VALIDATION_STAGE_SCHEMA_VERSION,
        "contract_schema_version": REPLAN_VALIDATION_CONTRACT_SCHEMA_VERSION,
        "validation_identity_prefix": REPLAN_VALIDATION_ID_PREFIX,
        "event_type": REPLAN_VALIDATION_EVENT_TYPE,
        "authority": REPLAN_VALIDATION_AUTHORITY,
        "mode": REPLAN_VALIDATION_MODE,
        "requires_stage375_candidate": True,
        "requires_stage374_snapshot": True,
        "deterministic_reproduction_required": True,
        "candidate_source_binding_required": True,
        "active_plan_head_drift_rejected": True,
        "mission_version_drift_rejected": True,
        "next_plan_version_required": True,
        "target_generation_required": True,
        "completed_task_recurrence_rejected": True,
        "canonical_task_order_required": True,
        "remainder_dag_must_be_acyclic": True,
        "satisfied_predecessors_must_have_source_completion": True,
        "empty_delta_rejected": True,
        "validated_status": REPLAN_VALIDATION_STATUS_VALIDATED,
        "rejected_status": REPLAN_VALIDATION_STATUS_REJECTED,
        "successor_plan_created": False,
        "replan_decision_committed": False,
        "plan_supersession_performed": False,
        "mission_state_transition_performed": False,
        "dispatch_performed": False,
        "target_actuation": False,
        "one_validation_decision_per_candidate": True,
        "idempotent_recovery_supported": True,
        "next_stage": "3.7.7",
    }
