from __future__ import annotations

from typing import Any, Dict, Mapping

from .canonical import normalize_create_request, request_fingerprint
from .errors import MissionValidationError, MissionValidationPipelineError
from .scope_contract import normalize_contract_request, request_fingerprint as scope_request_fingerprint

VALIDATION_SCHEMA_VERSION = "apts-canonical-mission-validation-v1"
CANONICAL_MISSION_API_SCHEMA_VERSION = "apts-canonical-mission-api-v1"
VALIDATION_MODE = "PREFLIGHT_NO_PERSISTENCE_FAIL_CLOSED"
VALIDATION_PIPELINE = ("SCHEMA", "SEMANTIC", "SCOPE", "CONSTRAINTS")
SUPPORTED_REQUIRED_SUBSYSTEMS = frozenset({"CTI", "PENTEST"})

_DRAFT_FIELDS = {"mission", "scope_contract"}


def _pipeline_error(phase: str, check_id: str, message: str) -> MissionValidationPipelineError:
    return MissionValidationPipelineError(message, phase=phase, check_id=check_id)


def _classify_scope_error(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if lowered.startswith("constraints.") or lowered.startswith("constraints "):
        return "CONSTRAINTS", "CONSTRAINT_CONTRACT"
    if lowered.startswith("scope.") or lowered.startswith("scope ") or lowered.startswith("roe.") or lowered.startswith("roe "):
        return "SCOPE", "SCOPE_ROE_CONTRACT"
    if "action class" in lowered or "allowed_action_classes" in lowered or "prohibited_action_classes" in lowered:
        return "SCOPE", "SCOPE_ROE_CONTRACT"
    return "SCHEMA", "SCOPE_CONTRACT_SCHEMA"


def _validate_wrapper(payload: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(payload, dict):
        raise _pipeline_error("SCHEMA", "DRAFT_WRAPPER_SCHEMA", "validation request body must be a JSON object")
    unknown = sorted(set(payload) - _DRAFT_FIELDS)
    if unknown:
        raise _pipeline_error(
            "SCHEMA",
            "DRAFT_WRAPPER_SCHEMA",
            "unsupported validation draft field(s): " + ", ".join(unknown),
        )
    mission = payload.get("mission")
    scope_contract = payload.get("scope_contract")
    if not isinstance(mission, dict):
        raise _pipeline_error("SCHEMA", "MISSION_CREATE_SCHEMA", "mission must be a JSON object")
    if not isinstance(scope_contract, dict):
        raise _pipeline_error("SCHEMA", "SCOPE_CONTRACT_SCHEMA", "scope_contract must be a JSON object")
    return mission, scope_contract


def _validate_semantics(mission: Mapping[str, Any]) -> None:
    objective = mission.get("objective") or {}
    objective_type = objective.get("type")
    if not isinstance(objective_type, str) or not objective_type.strip():
        raise _pipeline_error(
            "SEMANTIC",
            "MISSION_OBJECTIVE_SEMANTICS",
            "mission.objective.type is required for canonical mission admission",
        )

    required = set(mission.get("required_subsystems") or [])
    if not required:
        raise _pipeline_error(
            "SEMANTIC",
            "MISSION_SUBSYSTEM_SEMANTICS",
            "mission.required_subsystems must declare at least one canonical subsystem",
        )
    unsupported = sorted(required - SUPPORTED_REQUIRED_SUBSYSTEMS)
    if unsupported:
        raise _pipeline_error(
            "SEMANTIC",
            "MISSION_SUBSYSTEM_SEMANTICS",
            "unsupported required_subsystems for the Stage-3 canonical mission API: " + ", ".join(unsupported),
        )


def _validate_scope_semantics(scope_contract: Mapping[str, Any]) -> None:
    scope = scope_contract["scope"]
    has_positive_scope = any(
        scope.get(key)
        for key in ("targets", "network_ranges", "domains", "services")
    )
    if not has_positive_scope:
        raise _pipeline_error(
            "SCOPE",
            "SCOPE_NON_EMPTY_ADMISSION",
            "canonical scope must contain at least one positive target, network range, domain, or service",
        )


def _mission_budget_seconds(mission: Mapping[str, Any]) -> int | None:
    budgets = mission.get("budgets") or {}
    for key in ("time_seconds", "max_duration", "duration_seconds"):
        raw = budgets.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool):
            raise _pipeline_error(
                "CONSTRAINTS",
                "MISSION_BUDGET_ALIGNMENT",
                f"mission.budgets.{key} must be an integer when used as a canonical duration budget",
            )
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise _pipeline_error(
                "CONSTRAINTS",
                "MISSION_BUDGET_ALIGNMENT",
                f"mission.budgets.{key} must be an integer when used as a canonical duration budget",
            ) from exc
        if value < 1:
            raise _pipeline_error(
                "CONSTRAINTS",
                "MISSION_BUDGET_ALIGNMENT",
                f"mission.budgets.{key} must be >= 1",
            )
        return value
    return None


def _validate_constraint_alignment(mission: Mapping[str, Any], scope_contract: Mapping[str, Any]) -> None:
    budget_seconds = _mission_budget_seconds(mission)
    max_duration = int(scope_contract["constraints"]["max_duration"])
    if budget_seconds is not None and max_duration > budget_seconds:
        raise _pipeline_error(
            "CONSTRAINTS",
            "MISSION_BUDGET_ALIGNMENT",
            f"scope constraints.max_duration={max_duration} exceeds mission duration budget={budget_seconds}",
        )


def validate_canonical_mission_draft(payload: Any) -> Dict[str, Any]:
    """Validate a mission + Scope/RoE/Constraint draft without persistence or authority calls.

    Stage 3.1.8 intentionally reuses the canonical normalizers that back the write APIs. The
    preflight endpoint therefore cannot validate one contract and persist a materially different
    representation later. This function is local-only: it does not consult Governance, CTI, or
    any planner/execution component.
    """

    mission_raw, scope_raw = _validate_wrapper(payload)
    checks: list[Dict[str, str]] = []

    try:
        mission = normalize_create_request(mission_raw)
    except MissionValidationError as exc:
        raise _pipeline_error("SCHEMA", "MISSION_CREATE_SCHEMA", str(exc)) from exc
    checks.append({"phase": "SCHEMA", "check_id": "MISSION_CREATE_SCHEMA", "status": "PASS"})

    _validate_semantics(mission)
    checks.append({"phase": "SEMANTIC", "check_id": "MISSION_OBJECTIVE_AND_SUBSYSTEM_SEMANTICS", "status": "PASS"})

    try:
        scope_contract = normalize_contract_request(scope_raw)
    except MissionValidationError as exc:
        phase, check_id = _classify_scope_error(str(exc))
        raise _pipeline_error(phase, check_id, str(exc)) from exc

    _validate_scope_semantics(scope_contract)
    checks.append({"phase": "SCOPE", "check_id": "SCOPE_ROE_CONTRACT", "status": "PASS"})

    _validate_constraint_alignment(mission, scope_contract)
    checks.append({"phase": "CONSTRAINTS", "check_id": "MISSION_BUDGET_CONSTRAINT_ALIGNMENT", "status": "PASS"})

    return {
        "status": "valid",
        "valid": True,
        "validation_schema_version": VALIDATION_SCHEMA_VERSION,
        "canonical_mission_api_schema_version": CANONICAL_MISSION_API_SCHEMA_VERSION,
        "validation_mode": VALIDATION_MODE,
        "validation_pipeline": list(VALIDATION_PIPELINE),
        "checks": checks,
        "mission_request_sha256": request_fingerprint(mission),
        "scope_contract_request_sha256": scope_request_fingerprint(scope_contract),
        "normalized": {
            "mission": mission,
            "scope_contract": scope_contract,
        },
        "persistence_performed": False,
        "authority_query_performed": False,
        "planning_performed": False,
        "target_action_performed": False,
    }
