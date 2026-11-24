from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .adaptation_replan import ADAPTATION_REPLAN_ALLOWED_MISSION_STATES, REPLAN_SNAPSHOT_ID_PREFIX, verify_adaptation_replan_contract
from .adaptation_trigger import verify_adaptation_trigger_classification_contract
from .errors import MissionValidationError
from .governance_binding import verify_binding_contract
from .plan_versioning import verify_plan_version_contract
from .replan_eligibility import REPLAN_ELIGIBLE_STATUS, verify_replan_eligibility_contract
from .scope_contract import verify_contract

REPLAN_SNAPSHOT_STAGE_SCHEMA_VERSION = "apts-canonical-replan-snapshot-context-binding-v1"
REPLAN_SNAPSHOT_CONTRACT_SCHEMA_VERSION = "apts-replan-snapshot-context-binding-contract-v1"
REPLAN_SNAPSHOT_HASH_DOMAIN = "MISSION_CANONICAL_REPLAN_SNAPSHOT_CONTEXT_BINDING_V1"
REPLAN_SNAPSHOT_REQUEST_HASH_DOMAIN = "MISSION_REPLAN_SNAPSHOT_CONTEXT_BINDING_REQUEST_V1"
REPLAN_SNAPSHOT_CONTEXT_HASH_DOMAIN = "MISSION_REPLAN_SNAPSHOT_BOUND_CONTEXT_V1"
REPLAN_SNAPSHOT_STATUS = "SNAPSHOT_BOUND"
REPLAN_SNAPSHOT_EVENT_TYPE = "MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND"
REPLAN_SNAPSHOT_MODE = (
    "IMMUTABLE_CANONICAL_REPLAN_SNAPSHOT_BOUND_TO_ELIGIBLE_EPISODE_CURRENT_PLAN_"
    "LOCAL_DURABLE_CONTEXT_NO_EXTERNAL_REFRESH_NO_REPLAN_COMMAND_NO_PLANNER_NO_ACTUATION"
)
REPLAN_SNAPSHOT_AUTHORITY = "MISSION_ORCHESTRATOR_REPLAN_CONTEXT_BINDING"
REPLAN_SNAPSHOT_CONTEXT_MODE = "CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_adaptation_episode_id",
    "expected_classification_id",
    "expected_eligibility_gate_id",
    "expected_adaptation_replan_sha256",
    "expected_classification_sha256",
    "expected_eligibility_sha256",
    "expected_policy_decision_hash",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_scope_snapshot_id",
    "expected_scope_sha256",
    "expected_governance_binding_snapshot_id",
    "expected_governance_binding_version",
    "expected_governance_binding_sha256",
    "bound_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_replan_snapshot_id() -> str:
    return f"{REPLAN_SNAPSHOT_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_replan_snapshot_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("replan snapshot/context-binding request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported replan snapshot/context-binding field(s): " + ", ".join(unknown)
            + "; Stage 3.7.4 accepts binding/concurrency tokens only. Caller-supplied lifecycle REPLAN, "
              "planner input/output, task mutation, plan delta, candidate/successor Plan, validation, commit, "
              "supersession, Governance decision, dispatch, execution, target-action, or actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_adaptation_episode_id": _string(payload, "expected_adaptation_episode_id"),
        "expected_classification_id": _string(payload, "expected_classification_id"),
        "expected_eligibility_gate_id": _string(payload, "expected_eligibility_gate_id"),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_scope_snapshot_id": _string(payload, "expected_scope_snapshot_id"),
        "expected_governance_binding_snapshot_id": _string(payload, "expected_governance_binding_snapshot_id"),
        "bound_by": _string(payload, "bound_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_adaptation_episode_id"].startswith("adpt-"):
        raise MissionValidationError("expected_adaptation_episode_id must be a canonical adpt-* identifier")
    if not values["expected_classification_id"].startswith("rcls-"):
        raise MissionValidationError("expected_classification_id must be a canonical rcls-* identifier")
    if not values["expected_eligibility_gate_id"].startswith("rpelig-"):
        raise MissionValidationError("expected_eligibility_gate_id must be a canonical rpelig-* identifier")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_scope_snapshot_id"].startswith("mscope-snap-"):
        raise MissionValidationError("expected_scope_snapshot_id must be a canonical mscope-snap-* identifier")
    if not values["expected_governance_binding_snapshot_id"].startswith("mgbind-snap-"):
        raise MissionValidationError("expected_governance_binding_snapshot_id must be a canonical mgbind-snap-* identifier")
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
        "expected_adaptation_replan_sha256": _sha(payload, "expected_adaptation_replan_sha256"),
        "expected_classification_sha256": _sha(payload, "expected_classification_sha256"),
        "expected_eligibility_sha256": _sha(payload, "expected_eligibility_sha256"),
        "expected_policy_decision_hash": _sha(payload, "expected_policy_decision_hash"),
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_scope_sha256": _sha(payload, "expected_scope_sha256"),
        "expected_governance_binding_version": _positive_int(payload, "expected_governance_binding_version"),
        "expected_governance_binding_sha256": _sha(payload, "expected_governance_binding_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def replan_snapshot_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": REPLAN_SNAPSHOT_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _task_context(
    planned_tasks: list[Mapping[str, Any]],
    dependency_graph: Mapping[str, Any] | None,
    dependency_edges: list[Mapping[str, Any]],
    task_outcomes: list[Mapping[str, Any]],
    task_completions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    tasks = [
        {
            "planned_task_id": x["planned_task_id"],
            "task_key": x["task_key"],
            "task_index": int(x["task_index"]),
            "canonical_sha256": x["canonical_sha256"],
        }
        for x in sorted(planned_tasks, key=lambda item: int(item["task_index"]))
    ]
    edges = [
        {
            "dependency_edge_id": x["dependency_edge_id"],
            "from_planned_task_id": x["from_planned_task_id"],
            "to_planned_task_id": x["to_planned_task_id"],
            "dependency_type": (x.get("edge") or {}).get("dependency_type", "HARD"),
            "canonical_sha256": x["canonical_sha256"],
        }
        for x in sorted(dependency_edges, key=lambda item: item["dependency_edge_id"])
    ]
    outcomes = [
        {
            "task_outcome_id": x["task_outcome_id"],
            "planned_task_id": x["planned_task_id"],
            "source_task_outcome_status": x["source_task_outcome_status"],
            "outcome_classification": x["outcome_classification"],
            "canonical_sha256": x["canonical_sha256"],
        }
        for x in sorted(task_outcomes, key=lambda item: item["planned_task_id"])
    ]
    completions = [
        {
            "task_completion_id": x["task_completion_id"],
            "planned_task_id": x["planned_task_id"],
            "completion_status": x["completion_status"],
            "canonical_sha256": x["canonical_sha256"],
        }
        for x in sorted(task_completions, key=lambda item: item["planned_task_id"])
    ]
    graph = None
    if dependency_graph is not None:
        graph = {
            "graph_id": dependency_graph["graph_id"],
            "graph_version": int(dependency_graph["graph_version"]),
            "canonical_sha256": dependency_graph["canonical_sha256"],
            "node_count": int(dependency_graph["node_count"]),
            "edge_count": int(dependency_graph["edge_count"]),
        }
    return {
        "task_count": len(tasks),
        "tasks": tasks,
        "dependency_graph": graph,
        "dependency_edge_count": len(edges),
        "dependency_edges": edges,
        "task_outcome_count": len(outcomes),
        "task_outcomes": outcomes,
        "task_completion_count": len(completions),
        "task_completions": completions,
    }


def build_replan_snapshot_contract(
    *,
    replan_snapshot_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    adaptation_replan: Mapping[str, Any],
    classification: Mapping[str, Any],
    eligibility_gate: Mapping[str, Any],
    detection_event: Mapping[str, Any],
    classification_event: Mapping[str, Any],
    eligibility_event: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
    planned_tasks: list[Mapping[str, Any]],
    dependency_graph: Mapping[str, Any] | None,
    dependency_edges: list[Mapping[str, Any]],
    task_outcomes: list[Mapping[str, Any]],
    task_completions: list[Mapping[str, Any]],
    bound_at: str,
) -> Dict[str, Any]:
    repl = adaptation_replan["adaptation_replan_contract"]
    cls = classification["adaptation_trigger_classification_contract"]
    elig = eligibility_gate["replan_eligibility_governance_contract"]
    plan_contract = active_plan["plan_version_contract"]
    if not verify_adaptation_replan_contract(repl):
        raise MissionValidationError("Stage-3.7.1 adaptation/replan contract integrity verification failed")
    if not verify_adaptation_trigger_classification_contract(cls):
        raise MissionValidationError("Stage-3.7.2 classification contract integrity verification failed")
    if not verify_replan_eligibility_contract(elig):
        raise MissionValidationError("Stage-3.7.3 eligibility/governance contract integrity verification failed")
    if elig["eligibility"]["eligibility_status"] != REPLAN_ELIGIBLE_STATUS or elig["eligibility"]["replan_eligible"] is not True:
        raise MissionValidationError("Stage-3.7.4 ReplanSnapshot requires an ELIGIBLE Stage-3.7.3 gate")
    if not verify_plan_version_contract(plan_contract):
        raise MissionValidationError("active Plan-version contract integrity verification failed")
    if not verify_contract(scope_record["contract"]):
        raise MissionValidationError("Mission scope contract integrity verification failed")
    if not verify_binding_contract(governance_binding["binding"]):
        raise MissionValidationError("Governance binding integrity verification failed")

    task_context = _task_context(planned_tasks, dependency_graph, dependency_edges, task_outcomes, task_completions)
    cti_knowledge = (repl["provenance"].get("metadata") or {}).get("cti_knowledge_revision")
    if cti_knowledge is not None:
        from execution_subsystem.cti_feedback_contract import KNOWLEDGE_DOMAIN
        from execution_subsystem.execution_contract import verify_integrity
        if not verify_integrity(cti_knowledge, KNOWLEDGE_DOMAIN) or cti_knowledge["subject"]["mission_id"] != mission_id:
            raise MissionValidationError("replan CTI knowledge revision failed integrity/scope verification")
    source_context = {
        "mission_id": mission_id,
        "source_state": state["state"],
        "source_state_version": int(state["state_version"]),
        "source_version_sha256": version_vector["version_sha256"],
        "source_plan_version_record_id": active_plan["plan_version_record_id"],
        "source_plan_version": int(active_plan["plan_version"]),
        "source_plan_sha256": active_plan["canonical_sha256"],
        "adaptation_replan_sha256": adaptation_replan["canonical_sha256"],
        "classification_sha256": classification["canonical_sha256"],
        "eligibility_sha256": eligibility_gate["canonical_sha256"],
        "policy_decision_hash": eligibility_gate["policy_decision_hash"],
        "mission_scope_snapshot_id": scope_record["snapshot_id"],
        "mission_scope_sha256": scope_record["canonical_sha256"],
        "governance_binding_snapshot_id": governance_binding["binding_snapshot_id"],
        "governance_binding_version": int(governance_binding["binding_version"]),
        "governance_binding_sha256": governance_binding["canonical_sha256"],
        "detection_event_sha256": detection_event["canonical_sha256"],
        "classification_event_sha256": classification_event["canonical_sha256"],
        "eligibility_event_sha256": eligibility_event["canonical_sha256"],
        "task_context_sha256": sha256_hex(task_context),
    }
    if cti_knowledge is not None:
        source_context["cti_knowledge_sha256"] = cti_knowledge["integrity"]["canonical_sha256"]
    source_context_sha256 = sha256_hex({"hash_domain": REPLAN_SNAPSHOT_CONTEXT_HASH_DOMAIN, "context": source_context})

    core = {
        "schema_version": REPLAN_SNAPSHOT_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": REPLAN_SNAPSHOT_STAGE_SCHEMA_VERSION,
        "identity": {
            "replan_snapshot_id": replan_snapshot_id,
            "mission_id": mission_id,
            "adaptation_episode_id": adaptation_replan["adaptation_episode_id"],
            "replan_trigger_id": adaptation_replan["replan_trigger_id"],
            "classification_id": classification["classification_id"],
            "eligibility_gate_id": eligibility_gate["eligibility_gate_id"],
        },
        "source_bindings": {
            **source_context,
            "source_plan_generation": int(active_plan["plan_version"]),
            "target_plan_generation": int(repl["source_bindings"]["target_plan_generation"]),
            "canonical_plan_id": active_plan["canonical_plan_id"],
            "detection_event_id": detection_event["event_id"],
            "classification_event_id": classification_event["event_id"],
            "eligibility_event_id": eligibility_event["event_id"],
            "governance_scope_contract_hash": governance_binding["governance_scope_contract_hash"],
        },
        "eligibility_binding": {
            "eligibility_status": elig["eligibility"]["eligibility_status"],
            "replan_eligible": True,
            "governance_decision": elig["governance_decision"]["decision"],
            "policy_decision_id": elig["governance_decision"]["decision_id"],
            "policy_decision_hash": elig["governance_decision"]["decision_hash"],
            "policy_version": int(elig["governance_decision"]["policy_version"]),
            "requires_human_approval": bool(elig["governance_decision"]["requires_human_approval"]),
        },
        "scope_context": {
            "mission_scope_snapshot_id": scope_record["snapshot_id"],
            "mission_scope_version": int(scope_record["contract_version"]),
            "mission_scope_sha256": scope_record["canonical_sha256"],
            "scope_contract": dict(scope_record["contract"]),
        },
        "governance_context": {
            "governance_binding_snapshot_id": governance_binding["binding_snapshot_id"],
            "governance_binding_version": int(governance_binding["binding_version"]),
            "governance_binding_sha256": governance_binding["canonical_sha256"],
            "governance_scope_contract_id": governance_binding["governance_scope_contract_id"],
            "governance_scope_version": int(governance_binding["governance_scope_version"]),
            "governance_scope_contract_hash": governance_binding["governance_scope_contract_hash"],
            "governance_binding": dict(governance_binding["binding"]),
            "governance_query_performed": False,
        },
        "trigger_context": {
            "trigger_source": adaptation_replan["trigger_source"],
            "trigger_code": adaptation_replan["trigger_code"],
            "classification_reason_code": classification["reason_code"],
            "severity": classification["severity"],
            "replan_scope_level": classification["replan_scope_level"],
            "evidence_refs": list(adaptation_replan.get("evidence_refs") or []),
            "classification_evidence_refs": list(classification.get("evidence_refs") or []),
        },
        "task_dependency_outcome_context": task_context,
        "context_binding": {
            "mode": REPLAN_SNAPSHOT_CONTEXT_MODE,
            "source_context": source_context,
            "source_context_sha256": source_context_sha256,
            "fact_policy": "CANONICAL_DURABLE_LOCAL_FACTS_ONLY",
            "freshness_semantics": "IMMUTABLE_AS_OF_CAPTURE",
            "external_context_refresh_performed": False,
            "governance_query_performed": False,
        },
        "snapshot_state": {
            "snapshot_status": REPLAN_SNAPSHOT_STATUS,
            "effective_episode_state": REPLAN_SNAPSHOT_STATUS,
            "immutable_snapshot": True,
            "context_bound": True,
            "planner_input_ready_for_next_stage": True,
        },
        "authority_boundary": {
            "authority": REPLAN_SNAPSHOT_AUTHORITY,
            "mode": REPLAN_SNAPSHOT_MODE,
            "lifecycle_replan_requested": False,
            "planner_invocation_performed": False,
            "replan_candidate_created": False,
            "successor_plan_created": False,
            "plan_delta_computed": False,
            "plan_validation_performed": False,
            "replan_decision_committed": False,
            "plan_supersession_performed": False,
            "historical_plan_mutation_performed": False,
            "mission_state_transition_performed": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "dispatch_performed": False,
            "new_execution_attempt_created": False,
            "external_target_network_io_performed": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "bound_by": request["bound_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "bound_at": bound_at,
        },
    }
    if cti_knowledge is not None:
        core["cti_feedback_context"] = dict(cti_knowledge)
    digest = sha256_hex({"hash_domain": REPLAN_SNAPSHOT_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_replan_snapshot_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != REPLAN_SNAPSHOT_CONTRACT_SCHEMA_VERSION:
            return False
        if contract.get("stage_schema_version") != REPLAN_SNAPSHOT_STAGE_SCHEMA_VERSION:
            return False
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if digest != sha256_hex({"hash_domain": REPLAN_SNAPSHOT_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]
        src = contract["source_bindings"]
        ctx = contract["context_binding"]
        state = contract["snapshot_state"]
        boundary = contract["authority_boundary"]
        eligibility = contract["eligibility_binding"]
        if not str(ident.get("replan_snapshot_id") or "").startswith(REPLAN_SNAPSHOT_ID_PREFIX):
            return False
        if not str(ident.get("adaptation_episode_id") or "").startswith("adpt-"):
            return False
        if not str(ident.get("classification_id") or "").startswith("rcls-"):
            return False
        if not str(ident.get("eligibility_gate_id") or "").startswith("rpelig-"):
            return False
        if src.get("source_state") not in ADAPTATION_REPLAN_ALLOWED_MISSION_STATES:
            return False
        if not str(src.get("source_plan_version_record_id") or "").startswith("pver-"):
            return False
        for key in (
            "source_version_sha256", "source_plan_sha256", "adaptation_replan_sha256", "classification_sha256",
            "eligibility_sha256", "policy_decision_hash", "mission_scope_sha256", "governance_binding_sha256",
            "detection_event_sha256", "classification_event_sha256", "eligibility_event_sha256", "task_context_sha256",
        ):
            if not _SHA_RE.match(str(src.get(key) or "")):
                return False
        if eligibility.get("eligibility_status") != REPLAN_ELIGIBLE_STATUS or eligibility.get("replan_eligible") is not True:
            return False
        if eligibility.get("governance_decision") != "ALLOW" or eligibility.get("requires_human_approval") is not False:
            return False
        if state.get("snapshot_status") != REPLAN_SNAPSHOT_STATUS or state.get("effective_episode_state") != REPLAN_SNAPSHOT_STATUS:
            return False
        if state.get("immutable_snapshot") is not True or state.get("context_bound") is not True:
            return False
        source_context = ctx.get("source_context") or {}
        knowledge = contract.get("cti_feedback_context")
        if knowledge is not None:
            from execution_subsystem.cti_feedback_contract import KNOWLEDGE_DOMAIN
            from execution_subsystem.execution_contract import verify_integrity
            if (not verify_integrity(knowledge, KNOWLEDGE_DOMAIN)
                or knowledge["subject"]["mission_id"] != ident["mission_id"]
                or source_context.get("cti_knowledge_sha256") != knowledge["integrity"]["canonical_sha256"]):
                return False
        elif "cti_knowledge_sha256" in source_context:
            return False
        if ctx.get("source_context_sha256") != sha256_hex({"hash_domain": REPLAN_SNAPSHOT_CONTEXT_HASH_DOMAIN, "context": source_context}):
            return False
        if ctx.get("mode") != REPLAN_SNAPSHOT_CONTEXT_MODE:
            return False
        if ctx.get("external_context_refresh_performed") is not False or ctx.get("governance_query_performed") is not False:
            return False
        if boundary.get("authority") != REPLAN_SNAPSHOT_AUTHORITY or boundary.get("mode") != REPLAN_SNAPSHOT_MODE:
            return False
        for key in (
            "lifecycle_replan_requested", "planner_invocation_performed", "replan_candidate_created", "successor_plan_created",
            "plan_delta_computed", "plan_validation_performed", "replan_decision_committed", "plan_supersession_performed",
            "historical_plan_mutation_performed", "mission_state_transition_performed", "governance_query_performed",
            "runtime_query_performed", "runtime_control_io_performed", "dispatch_performed", "new_execution_attempt_created",
            "external_target_network_io_performed", "target_action_dispatch_performed", "target_actuation",
        ):
            if boundary.get(key) is not False:
                return False
        return True
    except Exception:
        return False


def canonical_replan_snapshot_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": REPLAN_SNAPSHOT_STAGE_SCHEMA_VERSION,
        "contract_schema_version": REPLAN_SNAPSHOT_CONTRACT_SCHEMA_VERSION,
        "mode": REPLAN_SNAPSHOT_MODE,
        "authority": REPLAN_SNAPSHOT_AUTHORITY,
        "identity_prefix": REPLAN_SNAPSHOT_ID_PREFIX,
        "snapshot_status": REPLAN_SNAPSHOT_STATUS,
        "event_type": REPLAN_SNAPSHOT_EVENT_TYPE,
        "context_mode": REPLAN_SNAPSHOT_CONTEXT_MODE,
        "requires_stage371_adaptation_replan": True,
        "requires_stage372_classification": True,
        "requires_stage373_eligible_gate": True,
        "requires_governance_allow_without_human_approval": True,
        "requires_unchanged_mission_state_version": True,
        "requires_unchanged_active_plan_head": True,
        "requires_current_scope_and_governance_binding": True,
        "binds_task_dependency_outcome_context": True,
        "context_sources_are_local_durable_only": True,
        "external_context_refresh_performed": False,
        "governance_query_performed": False,
        "one_snapshot_per_adaptation_episode": True,
        "idempotent_recovery_supported": True,
        "lifecycle_replan_requested": False,
        "planner_invocation_performed": False,
        "replan_candidate_created": False,
        "successor_plan_created": False,
        "plan_delta_computed": False,
        "plan_validation_performed": False,
        "replan_decision_committed": False,
        "plan_supersession_performed": False,
        "mission_state_transition_performed": False,
        "dispatch_performed": False,
        "target_actuation": False,
        "next_stage": "3.7.5",
    }
