from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .e2e_adaptation_replanning_qualification import (
    ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES,
    ADAPTATION_REPLANNING_EXPECTED_NONZERO_COUNTS,
    canonical_adaptation_replanning_contract,
)
from .e2e_mission_acceptance import E2E_MISSION_SCENARIO_ID
from .replan_lineage import (
    REPLAN_EVENT_TYPES,
    REPLAN_RECOVERY_EVENT_TYPE,
    REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
    verify_replan_recovery_checkpoint_contract,
)

RESTART_REPLAY_RECOVERY_SCHEMA_VERSION = "apts-stage3.9-restart-replay-recovery-e2e-verification-v1"
RESTART_REPLAY_RECOVERY_HASH_DOMAIN = "MISSION_STAGE3_9_8_RESTART_REPLAY_RECOVERY_E2E_VERIFICATION_V1"
RESTART_REPLAY_RECOVERY_MODE = "DURABLE_RESTART_DETERMINISTIC_REPLAY_RECOVERY_EQUIVALENCE_VERIFICATION"
RESTART_REPLAY_RECOVERY_PREDECESSOR_CONTROL = "stage3.9.7-adaptation-replanning-e2e-scenario"
RESTART_REPLAY_RECOVERY_EXPECTED_MIGRATION_LEVEL = 53
RESTART_REPLAY_RECOVERY_NEXT_STAGE = "3.9.9"
RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES = (*ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES, REPLAN_RECOVERY_EVENT_TYPE)
RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES = tuple(REPLAN_EVENT_TYPES)
RESTART_REPLAY_RECOVERY_EXPECTED_NONZERO_COUNTS = {
    **ADAPTATION_REPLANNING_EXPECTED_NONZERO_COUNTS,
    "mission_events": len(RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES),
    "mission_replan_recovery_checkpoints": 1,
}


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_restart_replay_recovery_contract() -> dict[str, Any]:
    predecessor = canonical_adaptation_replanning_contract()
    core = {
        "schema_version": RESTART_REPLAY_RECOVERY_SCHEMA_VERSION,
        "mode": RESTART_REPLAY_RECOVERY_MODE,
        "predecessor_control": RESTART_REPLAY_RECOVERY_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": predecessor["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": RESTART_REPLAY_RECOVERY_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "persistence_mode": "EXISTING_STAGE3_7_9_RECOVERY_STORE_ONLY",
        "recovery_authority": "EXISTING_STAGE3_7_9_REPLAN_LINEAGE_REPLAY_RECOVERY",
        "qualified_restart_head": {
            "state": "RUNNING",
            "state_version": 4,
            "active_plan_version": 2,
            "replan_handoff_status": "HANDOFF_READY",
            "recovery_checkpoint_count": 1,
            "recovery_consistency": "PASS",
            "replan_event_count": len(RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES),
            "mission_event_count": len(RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES),
            "restart_source": "DURABLE_REPOSITORY_ONLY",
        },
        "expected_event_types": list(RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES),
        "expected_replan_event_types": list(RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(RESTART_REPLAY_RECOVERY_EXPECTED_NONZERO_COUNTS),
        "continuity_requirements": {
            "stage3_9_7_prefix_is_exact": True,
            "stage3_7_9_checkpoint_is_canonical": True,
            "checkpoint_binds_exact_handoff_and_active_plan_v2": True,
            "restart_uses_same_durable_repository": True,
            "mission_state_is_identical_after_restart": True,
            "active_plan_head_is_identical_after_restart": True,
            "repository_projection_is_identical_after_restart": True,
            "event_chain_is_identical_after_restart": True,
            "replan_replay_is_deterministic_after_restart": True,
            "recovery_projection_is_consistent_after_restart": True,
            "idempotent_checkpoint_replay_adds_no_event_or_record": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True,
            "planner_rerun_performed_by_verifier": False,
            "governance_query_performed_by_verifier": False,
            "runtime_query_performed_by_verifier": False,
            "routing_performed_by_verifier": False,
            "dispatch_performed_by_verifier": False,
            "new_execution_attempt_created_by_verifier": False,
            "mission_state_transition_performed_by_verifier": False,
            "target_actuation": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "new_recovery_authority_added": False,
        },
        "next_stage": RESTART_REPLAY_RECOVERY_NEXT_STAGE,
    }
    return {
        **core,
        "integrity": {
            "hash_domain": RESTART_REPLAY_RECOVERY_HASH_DOMAIN,
            "canonical_sha256": _sha({"hash_domain": RESTART_REPLAY_RECOVERY_HASH_DOMAIN, "core": core}),
        },
    }


def verify_restart_replay_recovery_contract(contract: Mapping[str, Any]) -> bool:
    try:
        return dict(contract) == canonical_restart_replay_recovery_contract()
    except Exception:
        return False


def canonical_restart_replay_recovery_definition() -> dict[str, Any]:
    contract = canonical_restart_replay_recovery_contract()
    return {
        "schema_version": RESTART_REPLAY_RECOVERY_SCHEMA_VERSION,
        "mode": RESTART_REPLAY_RECOVERY_MODE,
        "predecessor_control": RESTART_REPLAY_RECOVERY_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": RESTART_REPLAY_RECOVERY_EXPECTED_MIGRATION_LEVEL,
        "runtime_verifier_read_only": True,
        "recovery_checkpoint_schema_version": REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "restart_source": "DURABLE_REPOSITORY_ONLY",
        "replan_event_count_expected": len(RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES),
        "mission_event_count_expected": len(RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES),
        "new_database_migration_added": False,
        "new_durable_store_added": False,
        "new_recovery_authority_added": False,
        "next_stage": RESTART_REPLAY_RECOVERY_NEXT_STAGE,
    }


def _one(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return rows[0] if len(rows) == 1 else {}


def evaluate_restart_replay_recovery_qualification(
    *, mission_id: str, state: Mapping[str, Any], active_plan: Mapping[str, Any] | None,
    plan_versions: Sequence[Mapping[str, Any]], predecessor_qualification: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]], repository_counts: Mapping[str, int],
    event_integrity_status: str, repository_integrity_status: str,
    handoffs: Sequence[Mapping[str, Any]], recovery_checkpoints: Sequence[Mapping[str, Any]],
    replan_replay: Mapping[str, Any], recovery_projection: Mapping[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def check(check_id: str, ok: bool) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if ok else "FAIL"})

    handoff = _one(handoffs)
    checkpoint = _one(recovery_checkpoints)
    checkpoint_contract = checkpoint.get("replan_recovery_checkpoint", {}) if checkpoint else {}
    event_types = [x.get("event_type") for x in events]
    replay_events = replan_replay.get("events") or []
    plans = {int(x.get("plan_version") or 0): x for x in plan_versions}
    successor = plans.get(2, {})

    check("STAGE3_9_7_PREDECESSOR_QUALIFIED", predecessor_qualification.get("qualified") is True)
    check("MISSION_AND_REPOSITORY_INTEGRITY", event_integrity_status == "PASS" and repository_integrity_status == "PASS")
    check("EXACT_STAGE397_PREFIX", event_types[:len(ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES)] == list(ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES))
    check("EXACT_RECOVERY_EVENT_SUFFIX", event_types == list(RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES))
    check("EXACT_NONZERO_REPOSITORY_FOOTPRINT", {k: v for k, v in repository_counts.items() if int(v)} == RESTART_REPLAY_RECOVERY_EXPECTED_NONZERO_COUNTS)
    check("EXACT_SINGLE_HANDOFF_AND_CHECKPOINT", len(handoffs) == 1 and len(recovery_checkpoints) == 1)
    check("CANONICAL_RECOVERY_CHECKPOINT_INTEGRITY", bool(
        checkpoint_contract and verify_replan_recovery_checkpoint_contract(checkpoint_contract)
        and checkpoint.get("canonical_sha256") == checkpoint_contract.get("integrity", {}).get("canonical_sha256")
    ))
    src = checkpoint_contract.get("source_bindings", {})
    check("CHECKPOINT_BINDS_EXACT_HANDOFF_AND_SUCCESSOR_HEAD", bool(
        src.get("replan_handoff", {}).get("id") == handoff.get("replan_handoff_id")
        and src.get("replan_handoff", {}).get("canonical_sha256") == handoff.get("canonical_sha256")
        and src.get("successor_plan", {}).get("id") == successor.get("plan_version_record_id")
        and src.get("successor_plan", {}).get("canonical_sha256") == successor.get("canonical_sha256")
        and (active_plan or {}).get("plan_version_record_id") == successor.get("plan_version_record_id")
        and int((active_plan or {}).get("plan_version") or 0) == 2
    ))
    check("MISSION_STATE_SURVIVES_RESTART_BOUNDARY", bool(
        state.get("state") == "RUNNING" and int(state.get("state_version") or 0) == 4 and state.get("terminal") is False
    ))
    check("REPLAN_REPLAY_IS_EXACT_AND_DETERMINISTIC", bool(
        replan_replay.get("read_only") is True and replan_replay.get("side_effects_performed") is False
        and int(replan_replay.get("replan_event_count") or 0) == len(RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES)
        and [x.get("event_type") for x in replay_events] == list(RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES)
        and replan_replay.get("replan_event_tip_sha256") == events[-1].get("canonical_sha256")
    ))
    check("RECOVERY_RECONSTRUCTS_FROM_DURABLE_REPOSITORY", bool(
        recovery_projection.get("checkpoint_id") == checkpoint.get("checkpoint_id")
        and recovery_projection.get("canonical_sha256") == checkpoint.get("canonical_sha256")
        and recovery_projection.get("recovery_consistency") == "PASS"
        and recovery_projection.get("recovered_from_durable_repository") is True
    ))
    check("RECOVERY_SIDE_EFFECT_BOUNDARY_PRESERVED", all(recovery_projection.get(k) is False for k in (
        "runtime_query_performed", "governance_query_performed", "dispatch_performed", "target_actuation"
    )))

    contract = canonical_restart_replay_recovery_contract()
    failures = [x["check_id"] for x in checks if x["status"] != "PASS"]
    return {
        "schema_version": RESTART_REPLAY_RECOVERY_SCHEMA_VERSION,
        "segment": "RESTART_REPLAY_RECOVERY_E2E_VERIFICATION",
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "qualification_contract_sha256": contract["integrity"]["canonical_sha256"],
        "mission_id": mission_id,
        "status": "QUALIFIED" if not failures else "REJECTED",
        "qualified": not failures,
        "failed_check_ids": failures,
        "checks": checks,
        "segment_head": {
            "state": state.get("state"),
            "state_version": state.get("state_version"),
            "active_plan_version": (active_plan or {}).get("plan_version"),
            "replan_handoff_id": handoff.get("replan_handoff_id"),
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "recovery_consistency": recovery_projection.get("recovery_consistency"),
            "replan_event_count": replan_replay.get("replan_event_count"),
            "event_count": len(events),
            "restart_source": "DURABLE_REPOSITORY_ONLY",
        },
        "authority_boundary": {
            "verification_read_only": True,
            "planner_rerun_performed": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "routing_performed": False,
            "dispatch_performed": False,
            "new_execution_attempt_created": False,
            "mission_state_transition_performed": False,
            "target_actuation": False,
        },
    }
