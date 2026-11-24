from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .canonical import verify_envelope
from .e2e_mission_acceptance import (
    E2E_MISSION_SCENARIO_ID,
    canonical_e2e_mission_acceptance_contract,
    materialize_canonical_e2e_mission_request,
)

INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION = (
    "apts-stage3.9-intake-lifecycle-segment-qualification-v1"
)
INTAKE_LIFECYCLE_QUALIFICATION_HASH_DOMAIN = (
    "MISSION_STAGE3_9_2_INTAKE_LIFECYCLE_QUALIFICATION_CONTRACT_V1"
)
INTAKE_LIFECYCLE_QUALIFICATION_MODE = (
    "EXTERNAL_ACCEPTANCE_HARNESS_EXISTING_INTAKE_AND_LIFECYCLE_AUTHORITIES_"
    "READ_ONLY_RUNTIME_VERIFICATION_NO_NEW_AUTHORITY"
)
INTAKE_LIFECYCLE_QUALIFICATION_PREDECESSOR_CONTROL = (
    "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract"
)
INTAKE_LIFECYCLE_QUALIFICATION_EXPECTED_MIGRATION_LEVEL = 53
INTAKE_LIFECYCLE_QUALIFICATION_PERSISTENCE_MODE = (
    "EXISTING_MISSION_ENVELOPE_STATE_TRANSITION_COMMAND_AND_EVENT_STORES_ONLY"
)
INTAKE_LIFECYCLE_QUALIFICATION_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE = "PLANNING"
INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION = 3
INTAKE_LIFECYCLE_QUALIFICATION_NEXT_STAGE = "3.9.3"

INTAKE_LIFECYCLE_COMMAND_SEQUENCE = (
    ("BIND_PIP", "CREATED", "PIP_BOUND", 1, 2),
    ("START_PLANNING", "PIP_BOUND", "PLANNING", 2, 3),
)

INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES = (
    "MISSION_REGISTERED",
    "MISSION_STATE_TRANSITIONED",
    "MISSION_COMMAND_COMPLETED",
    "MISSION_STATE_TRANSITIONED",
    "MISSION_COMMAND_COMPLETED",
)

INTAKE_LIFECYCLE_ALLOWED_NONZERO_REPOSITORY_COUNTS = {
    "global_missions": 1,
    "mission_envelopes": 1,
    "mission_states": 1,
    "mission_state_transitions": 2,
    "mission_command_journal": 2,
    "mission_events": 5,
}

INTAKE_LIFECYCLE_FORBIDDEN_NEW_AUTHORITIES = (
    "governance_authorization",
    "routing",
    "delegation",
    "dispatch",
    "execution",
    "target_action_dispatch",
    "target_actuation",
    "external_network_io",
    "telemetry_export",
    "planner_invocation",
    "plan_materialization",
    "task_materialization",
    "database_migration",
    "durable_store_creation",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = _canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_intake_lifecycle_qualification_contract() -> dict[str, Any]:
    source = canonical_e2e_mission_acceptance_contract()
    core = {
        "schema_version": INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION,
        "mode": INTAKE_LIFECYCLE_QUALIFICATION_MODE,
        "predecessor_control": INTAKE_LIFECYCLE_QUALIFICATION_PREDECESSOR_CONTROL,
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "source_acceptance_contract_sha256": source["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": INTAKE_LIFECYCLE_QUALIFICATION_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": INTAKE_LIFECYCLE_QUALIFICATION_DATABASE_CHANGE_MODE,
        "persistence_mode": INTAKE_LIFECYCLE_QUALIFICATION_PERSISTENCE_MODE,
        "entry_state": {"state": "CREATED", "state_version": 1},
        "command_sequence": [
            {
                "command": command,
                "from_state": from_state,
                "to_state": to_state,
                "from_state_version": from_version,
                "to_state_version": to_version,
            }
            for command, from_state, to_state, from_version, to_version in INTAKE_LIFECYCLE_COMMAND_SEQUENCE
        ],
        "qualified_segment_head": {
            "state": INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE,
            "state_version": INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION,
            "plan_materialized": False,
            "planner_invoked": False,
        },
        "expected_event_types": list(INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(INTAKE_LIFECYCLE_ALLOWED_NONZERO_REPOSITORY_COUNTS),
        "replay_requirements": {
            "mission_create_exact_replay_is_idempotent": True,
            "lifecycle_command_exact_replay_is_idempotent": True,
            "no_duplicate_transition": True,
            "no_duplicate_command": True,
            "no_duplicate_event": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True,
            "acceptance_execution_uses_existing_public_intake_and_lifecycle_routes": True,
            "new_governance_authority_added": False,
            "new_routing_authority_added": False,
            "new_delegation_authority_added": False,
            "new_dispatch_authority_added": False,
            "new_execution_authority_added": False,
            "new_target_actuation_authority_added": False,
            "new_external_network_io_added": False,
            "new_telemetry_export_added": False,
            "new_planner_authority_added": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "forbidden_new_authorities": list(INTAKE_LIFECYCLE_FORBIDDEN_NEW_AUTHORITIES),
        },
    }
    return {
        **core,
        "integrity": {
            "hash_domain": INTAKE_LIFECYCLE_QUALIFICATION_HASH_DOMAIN,
            "canonical_sha256": _sha256_hex({
                "hash_domain": INTAKE_LIFECYCLE_QUALIFICATION_HASH_DOMAIN,
                "core": core,
            }),
        },
    }


def verify_intake_lifecycle_qualification_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION:
            return False
        core = dict(contract)
        integrity = core.pop("integrity")
        expected = _sha256_hex({
            "hash_domain": INTAKE_LIFECYCLE_QUALIFICATION_HASH_DOMAIN,
            "core": core,
        })
        if integrity.get("hash_domain") != INTAKE_LIFECYCLE_QUALIFICATION_HASH_DOMAIN:
            return False
        if integrity.get("canonical_sha256") != expected:
            return False
        return dict(contract) == canonical_intake_lifecycle_qualification_contract()
    except (KeyError, TypeError, ValueError):
        return False


def build_intake_lifecycle_command_request(
    *,
    run_id: str,
    command: str,
    expected_version_sha256: str,
    expected_state_version: int,
) -> dict[str, Any]:
    # Reuse Stage 3.9.1 run-id validation without materializing or persisting a Mission.
    materialize_canonical_e2e_mission_request(run_id)
    normalized_command = str(command or "").strip().upper()
    allowed = {item[0] for item in INTAKE_LIFECYCLE_COMMAND_SEQUENCE}
    if normalized_command not in allowed:
        raise ValueError(f"command must be one of {sorted(allowed)}")
    if not isinstance(expected_version_sha256, str) or len(expected_version_sha256) != 64:
        raise ValueError("expected_version_sha256 must be a 64-character digest")
    if not isinstance(expected_state_version, int) or isinstance(expected_state_version, bool) or expected_state_version < 1:
        raise ValueError("expected_state_version must be a positive integer")
    token = "bind-pip" if normalized_command == "BIND_PIP" else "start-planning"
    return {
        "command_id": f"stage392-{run_id}-{token}",
        "idempotency_key": f"stage392-{run_id}-{token}",
        "command": normalized_command,
        "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version,
        "actor": "stage3.9.2-acceptance-runner",
        "reason_code": f"STAGE392_{normalized_command}",
        "reason": f"Stage 3.9.2 canonical E2E segment command {normalized_command}",
        "evidence_refs": [f"evidence:stage3.9.2:{run_id}:{token}"],
        "metadata": {
            "stage": "3.9.2",
            "scenario_id": E2E_MISSION_SCENARIO_ID,
            "run_id": run_id,
            "segment": "INTAKE_TO_LIFECYCLE",
        },
    }


def _expected_envelope_projection(run_id: str) -> dict[str, Any]:
    request = materialize_canonical_e2e_mission_request(run_id)
    return {
        "provenance": {
            "source_system": request["source_system"],
            "created_by": request["created_by"],
            "idempotency_key": request["idempotency_key"],
        },
        "mission": {
            "mission_kind": request["mission_kind"],
            "objective": request["objective"],
            "success_criteria": request["success_criteria"],
            "budgets": request["budgets"],
            "required_subsystems": request["required_subsystems"],
        },
        "bindings": {
            "scope": {
                "scope_contract_id": request["scope_contract_id"],
                "scope_version": request["scope_version"],
                "scope_snapshot_id": f"{request['scope_contract_id']}@v{request['scope_version']}",
                "roe_version": request["roe_version"],
            },
            "pip": {"pip_id": request["pip_id"], "pip_version": request["pip_version"]},
            "governance": {
                "authority": "aptsGSS",
                "authority_component": "GOV-PLANE",
                "policy_version": request["policy_version"],
            },
        },
        "metadata": request["metadata"],
    }


def _check(checks: list[dict[str, Any]], check_id: str, passed: bool, observed: Any, required: Any) -> None:
    checks.append({
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "observed": observed,
        "required": required,
    })


def evaluate_intake_lifecycle_qualification(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    state: Mapping[str, Any],
    transitions: Sequence[Mapping[str, Any]],
    commands: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    repository_counts: Mapping[str, int],
    event_integrity_status: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    run_id = envelope.get("metadata", {}).get("run_id") if isinstance(envelope.get("metadata"), Mapping) else None
    run_valid = isinstance(run_id, str)
    if run_valid:
        try:
            expected_envelope = _expected_envelope_projection(run_id)
        except ValueError:
            run_valid = False
            expected_envelope = None
    else:
        expected_envelope = None

    _check(checks, "CANONICAL_RUN_BINDING_PRESENT", run_valid, run_id, "VALID_STAGE3_9_RUN_ID")
    _check(checks, "CANONICAL_ENVELOPE_INTEGRITY", verify_envelope(envelope), "VERIFIED" if verify_envelope(envelope) else "FAILED", "VERIFIED")
    _check(
        checks,
        "CANONICAL_SCENARIO_ID",
        envelope.get("metadata", {}).get("scenario_id") == E2E_MISSION_SCENARIO_ID,
        envelope.get("metadata", {}).get("scenario_id"),
        E2E_MISSION_SCENARIO_ID,
    )
    if expected_envelope is not None:
        observed_projection = {
            "provenance": {k: envelope.get("provenance", {}).get(k) for k in expected_envelope["provenance"]},
            "mission": envelope.get("mission"),
            "bindings": envelope.get("bindings"),
            "metadata": envelope.get("metadata"),
        }
        _check(checks, "FROZEN_STAGE391_REQUEST_SEMANTICS", observed_projection == expected_envelope, observed_projection, expected_envelope)
    else:
        _check(checks, "FROZEN_STAGE391_REQUEST_SEMANTICS", False, None, "CANONICAL_STAGE391_REQUEST")

    _check(checks, "MISSION_IDENTITY_PREFIX", isinstance(mission_id, str) and mission_id.startswith("mission-gmo-"), mission_id, "mission-gmo-*")
    _check(checks, "ENVELOPE_IDENTITY_PREFIX", str(envelope.get("identity", {}).get("envelope_id") or "").startswith("menv-"), envelope.get("identity", {}).get("envelope_id"), "menv-*")
    _check(checks, "FINAL_LIFECYCLE_STATE", state.get("state") == INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE, state.get("state"), INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE)
    _check(checks, "FINAL_STATE_VERSION", state.get("state_version") == INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION, state.get("state_version"), INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION)
    _check(checks, "FINAL_STATE_NONTERMINAL", state.get("terminal") is False, state.get("terminal"), False)

    transition_projection = [
        (x.get("from_state"), x.get("to_state"), x.get("from_state_version"), x.get("to_state_version"))
        for x in transitions
    ]
    expected_transition_projection = [
        (from_state, to_state, from_version, to_version)
        for _, from_state, to_state, from_version, to_version in INTAKE_LIFECYCLE_COMMAND_SEQUENCE
    ]
    _check(checks, "EXACT_LIFECYCLE_TRANSITION_SEQUENCE", transition_projection == expected_transition_projection, transition_projection, expected_transition_projection)
    transition_ids_ok = len(transitions) == 2 and all(str(x.get("transition_id") or "").startswith("mtrans-") for x in transitions)
    _check(checks, "TRANSITION_IDENTITY_FAMILY", transition_ids_ok, [x.get("transition_id") for x in transitions], "2 x mtrans-*")

    command_projection = []
    command_metadata_ok = True
    activation_lineage_ok = True
    for row in commands:
        result = row.get("result") if isinstance(row.get("result"), Mapping) else {}
        transition = result.get("transition") if isinstance(result.get("transition"), Mapping) else {}
        metadata = transition.get("metadata") if isinstance(transition.get("metadata"), Mapping) else {}
        command = metadata.get("lifecycle_command")
        command_projection.append((row.get("operation"), row.get("status"), command))
        request_metadata = row.get("metadata", {}).get("request_metadata", {}) if isinstance(row.get("metadata"), Mapping) else {}
        if not (request_metadata.get("stage") == "3.9.2" and request_metadata.get("run_id") == run_id and request_metadata.get("scenario_id") == E2E_MISSION_SCENARIO_ID):
            command_metadata_ok = False
        if command == "BIND_PIP":
            activation = result.get("mission_activation") or {}
            activation_lineage_ok = activation_lineage_ok and activation.get("activation_ready") is True and activation.get("execution_authorized") is False
        elif command == "START_PLANNING":
            activation = result.get("planning_run_activation") or {}
            activation_lineage_ok = activation_lineage_ok and activation.get("activation_ready") is True and activation.get("pip_activation_proof", {}).get("valid") is True and activation.get("planner_invocation_performed") is False and activation.get("plan_artifact_created") is False and activation.get("execution_authorized") is False
    expected_commands = [("LIFECYCLE_COMMAND", "COMPLETED", item[0]) for item in INTAKE_LIFECYCLE_COMMAND_SEQUENCE]
    _check(checks, "EXACT_LIFECYCLE_COMMAND_SEQUENCE", command_projection == expected_commands, command_projection, expected_commands)
    _check(checks, "STAGE392_COMMAND_RUN_BINDING", command_metadata_ok and len(commands) == 2, command_metadata_ok, True)
    _check(checks, "PIP_AND_PLANNING_ACTIVATION_LINEAGE", activation_lineage_ok and len(commands) == 2, activation_lineage_ok, True)

    observed_event_types = [x.get("event_type") for x in events]
    _check(checks, "EXACT_EVENT_SEQUENCE", observed_event_types == list(INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES), observed_event_types, list(INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES))
    _check(checks, "EVENT_LEDGER_INTEGRITY", event_integrity_status == "PASS", event_integrity_status, "PASS")
    event_identity_ok = len(events) == 5 and all(str(x.get("event_id") or "").startswith("mevent-") for x in events)
    _check(checks, "EVENT_IDENTITY_FAMILY", event_identity_ok, [x.get("event_id") for x in events], "5 x mevent-*")
    mission_binding_ok = all(x.get("mission_id") == mission_id for x in events) and all(x.get("mission_id") == mission_id for x in transitions)
    _check(checks, "SINGLE_MISSION_ROOT_BINDING", mission_binding_ok, mission_binding_ok, True)

    expected_counts = dict(INTAKE_LIFECYCLE_ALLOWED_NONZERO_REPOSITORY_COUNTS)
    nonzero = {k: int(v) for k, v in repository_counts.items() if int(v) != 0}
    _check(checks, "EXACT_SEGMENT_REPOSITORY_FOOTPRINT", nonzero == expected_counts, nonzero, expected_counts)

    failures = [x["check_id"] for x in checks if x["status"] != "PASS"]
    qualified = not failures
    contract = canonical_intake_lifecycle_qualification_contract()
    return {
        "schema_version": INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION,
        "segment": "INTAKE_TO_LIFECYCLE",
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "source_acceptance_contract_sha256": contract["source_acceptance_contract_sha256"],
        "qualification_contract_sha256": contract["integrity"]["canonical_sha256"],
        "mission_id": mission_id,
        "run_id": run_id,
        "status": "QUALIFIED" if qualified else "REJECTED",
        "qualified": qualified,
        "failed_check_ids": failures,
        "checks": checks,
        "segment_head": {
            "state": state.get("state"),
            "state_version": state.get("state_version"),
            "transition_count": len(transitions),
            "command_count": len(commands),
            "event_count": len(events),
        },
        "authority_boundary": {
            "verification_read_only": True,
            "new_governance_authority_added": False,
            "new_routing_authority_added": False,
            "new_delegation_authority_added": False,
            "new_dispatch_authority_added": False,
            "new_execution_authority_added": False,
            "new_target_actuation_authority_added": False,
            "new_external_network_io_added": False,
            "new_telemetry_export_added": False,
            "new_planner_authority_added": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
        },
    }


def canonical_intake_lifecycle_qualification_definition() -> dict[str, Any]:
    contract = canonical_intake_lifecycle_qualification_contract()
    return {
        "schema_version": INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION,
        "mode": INTAKE_LIFECYCLE_QUALIFICATION_MODE,
        "predecessor_control": INTAKE_LIFECYCLE_QUALIFICATION_PREDECESSOR_CONTROL,
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "source_acceptance_contract_sha256": contract["source_acceptance_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": INTAKE_LIFECYCLE_QUALIFICATION_EXPECTED_MIGRATION_LEVEL,
        "qualified_segment_head_state": INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE,
        "qualified_segment_head_state_version": INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION,
        "runtime_verifier_read_only": True,
        "acceptance_execution_uses_existing_public_routes": True,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "new_execution_authority_added": False,
        "next_stage": INTAKE_LIFECYCLE_QUALIFICATION_NEXT_STAGE,
    }
