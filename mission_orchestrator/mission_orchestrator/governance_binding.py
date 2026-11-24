from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .errors import (
    MissionGovernanceProtocolError,
    MissionGovernanceUnavailable,
    MissionValidationError,
)
from .scope_contract import ACTION_CLASSES, RISK_LEVELS, TARGET_TYPES
from .subsystem_registry import canonical_capability_contracts, canonical_subsystem_contracts

SAFE_VALIDATION_TECHNIQUES = (
    "HTTP_HEADER_INSPECTION",
    "SAFE_VERSION_CONFIGURATION_CONFIRMATION",
    "HTTP_RESPONSE_METADATA",
)


def project_validation_execution_authority(source_rules, validation_capability):
    """Project a VULNERABILITY_VALIDATION execution authority (an action constraint)
    for the safe validation techniques the source GSS scope explicitly permits and the
    bound validation capability requests. Returns None when the scope authorizes no
    safe validation technique, so a recon-only scope never gains validation authority.

    This never authorizes exploitation, credential use, or any state-changing action:
    only the fixed read-only SAFE_VALIDATION_TECHNIQUES are eligible.
    """
    if not validation_capability:
        return None
    validation_source = [r for r in (source_rules or [])
                         if r.get("action_class") == "VULNERABILITY_VALIDATION"
                         and r.get("action_name") in ("AUTHORIZE_TARGET_EXECUTION", "*")]
    if not validation_source:
        return None
    requested = validation_capability.get("constraints", {}).get("allowed_techniques", []) or []
    permitted = [technique for technique in requested
                 if technique in SAFE_VALIDATION_TECHNIQUES and all(
                     r.get("effect") == "ALLOW" and not r.get("requires_approval")
                     and technique in (r.get("constraints") or {}).get("allowed_techniques", [])
                     and technique not in (r.get("constraints") or {}).get("prohibited_techniques", [])
                     for r in validation_source)]
    if not permitted:
        return None
    methods = sorted(set(validation_capability.get("constraints", {}).get("allowed_methods", ["GET", "HEAD"])))
    return {"action_class": "VULNERABILITY_VALIDATION", "action_name": "AUTHORIZE_TARGET_EXECUTION",
            "effect": "ALLOW", "max_risk_level": "MODERATE", "requires_approval": False,
            "constraints": {"allowed_techniques": permitted, "read_only": True, "allowed_methods": methods}}


BINDING_SCHEMA_VERSION = "apts-mission-governance-authorization-binding-v1"
BINDING_HASH_DOMAIN = "MISSION_GOVERNANCE_AUTHORIZATION_BINDING_V1"
AUTHORIZATION_SCHEMA_VERSION = "apts-mission-authorization-decision-binding-v1"
AUTHORIZATION_HASH_DOMAIN = "MISSION_AUTHORIZATION_DECISION_BINDING_V1"
AUTHORITY = "aptsGSS"
AUTHORITY_COMPONENT = "GOV-PLANE"
BINDING_ID_PREFIX = "mgbind-"
BINDING_SNAPSHOT_ID_PREFIX = "mgbind-snap-"
BINDING_OPERATION_ID_PREFIX = "mgbind-op-"
AUTH_BINDING_ID_PREFIX = "mauth-"
AUTH_OPERATION_ID_PREFIX = "mauth-op-"

AUTHORIZATION_MODES = frozenset({"REQUIRED", "NOT_REQUIRED_INTERNAL"})
NON_ACTUATING_ACTIONS = frozenset({"INTERNAL_REASONING", "REPORTING"})
HARD_DENY_ACTIONS = frozenset({"DESTRUCTIVE_ACTION"})
DECISIONS = frozenset({"ALLOW", "DENY", "REVIEW"})
RISK_ORDER = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "CRITICAL": 4}
RESOURCE_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,63}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

_BINDING_FIELDS = {
    "expected_binding_version",
    "idempotency_key",
    "actor",
    "policy_set_id",
    "name",
    "approved_by",
    "capabilities",
    "reason",
    "metadata",
}
_CAPABILITY_FIELDS = {
    "capability_id",
    "subject_component",
    "action_class",
    "action_name",
    "authorization_mode",
    "resource_types",
    "max_risk_level",
    "requires_human_approval",
    "source_allowlist",
    "constraints",
}
_AUTH_FIELDS = {
    "idempotency_key",
    "capability_id",
    "resource_type",
    "resource_value",
    "context",
    "evidence_refs",
    "requested_by",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


def new_binding_id() -> str:
    return _new(BINDING_ID_PREFIX)


def new_binding_snapshot_id() -> str:
    return _new(BINDING_SNAPSHOT_ID_PREFIX)


def new_binding_operation_id() -> str:
    return _new(BINDING_OPERATION_ID_PREFIX)


def new_authorization_binding_id() -> str:
    return _new(AUTH_BINDING_ID_PREFIX)


def new_authorization_operation_id() -> str:
    return _new(AUTH_OPERATION_ID_PREFIX)


def _require_object(value: Any, key: str) -> Dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def _require_string(obj: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 512) -> Optional[str]:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _identifier(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty identifier")
    value = value.strip()
    if not ID_RE.match(value):
        raise MissionValidationError(f"{key} contains unsupported characters or exceeds 128 characters")
    return value


def _non_negative_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must be an integer") from exc
    if result < 0:
        raise MissionValidationError(f"{key} must be >= 0")
    return result


def _normalize_resource_types(value: Any, *, action_class: str) -> list[str]:
    if value is None:
        if action_class in NON_ACTUATING_ACTIONS:
            return []
        if action_class == "CTI_SOURCE_READ":
            return ["CTI_SOURCE"]
        return ["IP", "CIDR", "HOST", "DOMAIN", "URL", "APPLICATION", "OTHER"]
    if not isinstance(value, list):
        raise MissionValidationError("capabilities.resource_types must be an array")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError("capabilities.resource_types entries must be non-empty strings")
        normalized = item.strip().upper()
        if not RESOURCE_TYPE_RE.match(normalized):
            raise MissionValidationError(f"unsupported resource_type syntax: {normalized}")
        if normalized not in out:
            out.append(normalized)
    if action_class not in NON_ACTUATING_ACTIONS and not out:
        raise MissionValidationError("target/source capabilities require at least one resource_type")
    return out


def _normalize_source_allowlist(value: Any, *, action_class: str) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise MissionValidationError("capabilities.source_allowlist must be an array")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError("capabilities.source_allowlist entries must be non-empty strings")
        item = item.strip()
        if len(item) > 255:
            raise MissionValidationError("capabilities.source_allowlist entry exceeds 255 characters")
        if item not in out:
            out.append(item)
    if action_class == "CTI_SOURCE_READ" and not out:
        raise MissionValidationError("CTI_SOURCE_READ capability requires a non-empty source_allowlist")
    if action_class != "CTI_SOURCE_READ" and out:
        raise MissionValidationError("source_allowlist is only valid for CTI_SOURCE_READ capabilities")
    return out


def normalize_binding_request(payload: Any, scope_contract: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("request body must be a JSON object")
    unknown = sorted(set(payload) - _BINDING_FIELDS)
    if unknown:
        raise MissionValidationError("unsupported governance-binding field(s): " + ", ".join(unknown))

    expected = _non_negative_int(payload.get("expected_binding_version", 0), "expected_binding_version")
    idempotency_key = _require_string(payload, "idempotency_key")
    actor = _require_string(payload, "actor")
    policy_set_id = _identifier(payload.get("policy_set_id", "default-policy"), "policy_set_id")
    name = _optional_string(payload.get("name"), "name", 255)
    approved_by = _optional_string(payload.get("approved_by"), "approved_by", 255)
    reason = _optional_string(payload.get("reason"), "reason", 2000)
    metadata = _require_object(payload.get("metadata"), "metadata")

    raw_capabilities = payload.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise MissionValidationError("capabilities must be a non-empty array")

    canonical = scope_contract["contract"] if "contract" in scope_contract else scope_contract
    roe = canonical.get("roe") or {}
    constraints = canonical.get("constraints") or {}
    allowed = set(roe.get("allowed_action_classes") or [])
    prohibited = set(roe.get("prohibited_action_classes") or [])
    approval_required = set(roe.get("human_approval_required_for") or [])
    mission_risk = str(constraints.get("risk_threshold") or "LOW").upper()
    if mission_risk not in RISK_LEVELS:
        raise MissionValidationError("persisted mission risk threshold is unsupported")

    capabilities: list[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_routes: set[tuple[str, str]] = set()
    for raw in raw_capabilities:
        if not isinstance(raw, dict):
            raise MissionValidationError("capabilities entries must be JSON objects")
        unknown_cap = sorted(set(raw) - _CAPABILITY_FIELDS)
        if unknown_cap:
            raise MissionValidationError("unsupported capability field(s): " + ", ".join(unknown_cap))
        capability_id = _identifier(raw.get("capability_id"), "capabilities.capability_id")
        if capability_id in seen_ids:
            raise MissionValidationError(f"duplicate capability_id: {capability_id}")
        seen_ids.add(capability_id)
        subject_component = _identifier(raw.get("subject_component"), "capabilities.subject_component")
        action_class = _require_string(raw, "action_class", 64).upper()
        if action_class not in ACTION_CLASSES:
            raise MissionValidationError(f"unsupported capability action_class: {action_class}")
        if action_class in HARD_DENY_ACTIONS:
            raise MissionValidationError(f"{action_class} is hard-denied by the authoritative Governance plane")
        if action_class not in allowed or action_class in prohibited:
            raise MissionValidationError(
                f"capability {capability_id} action_class {action_class} is not allowed by the current canonical RoE"
            )
        action_name = _require_string({"action_name": raw.get("action_name", "*")}, "action_name", 128)
        route = (action_class, action_name)
        if route in seen_routes:
            raise MissionValidationError(
                f"duplicate governance action route {action_class}/{action_name}; capability routes must be unique"
            )
        seen_routes.add(route)

        mode = str(raw.get("authorization_mode") or ("NOT_REQUIRED_INTERNAL" if action_class in NON_ACTUATING_ACTIONS else "REQUIRED")).strip().upper()
        if mode not in AUTHORIZATION_MODES:
            raise MissionValidationError(f"unsupported authorization_mode: {mode}")
        if action_class in NON_ACTUATING_ACTIONS and mode != "NOT_REQUIRED_INTERNAL":
            raise MissionValidationError(f"{action_class} must use NOT_REQUIRED_INTERNAL")
        if action_class not in NON_ACTUATING_ACTIONS and mode != "REQUIRED":
            raise MissionValidationError(f"{action_class} must use REQUIRED authorization")

        max_risk = str(raw.get("max_risk_level") or mission_risk).strip().upper()
        if max_risk == "MEDIUM":
            max_risk = "MODERATE"
        if max_risk not in RISK_LEVELS:
            raise MissionValidationError(f"unsupported max_risk_level: {max_risk}")
        if RISK_ORDER[max_risk] > RISK_ORDER[mission_risk]:
            raise MissionValidationError(
                f"capability {capability_id} max_risk_level cannot exceed canonical mission risk_threshold {mission_risk}"
            )

        requires_approval = bool(raw.get("requires_human_approval", action_class in approval_required))
        if action_class in approval_required and not requires_approval:
            raise MissionValidationError(
                f"capability {capability_id} cannot weaken canonical human approval requirement for {action_class}"
            )

        capabilities.append(
            {
                "capability_id": capability_id,
                "subject_component": subject_component,
                "action_class": action_class,
                "action_name": action_name,
                "authorization_mode": mode,
                "resource_types": _normalize_resource_types(raw.get("resource_types"), action_class=action_class),
                "max_risk_level": max_risk,
                "requires_human_approval": requires_approval,
                "source_allowlist": _normalize_source_allowlist(raw.get("source_allowlist"), action_class=action_class),
                "constraints": _require_object(raw.get("constraints"), "capabilities.constraints"),
            }
        )

    capabilities.sort(key=lambda item: item["capability_id"])
    return {
        "expected_binding_version": expected,
        "idempotency_key": idempotency_key,
        "actor": actor,
        "policy_set_id": policy_set_id,
        "name": name,
        "approved_by": approved_by,
        "capabilities": capabilities,
        "reason": reason,
        "metadata": metadata,
    }


def binding_request_fingerprint(normalized: Mapping[str, Any], *, scope_snapshot_id: str, scope_sha256: str) -> str:
    material = dict(normalized)
    material["scope_snapshot_id"] = scope_snapshot_id
    material["scope_sha256"] = scope_sha256
    return sha256_hex(material)


def build_governance_scope_payload(
    *,
    mission_id: str,
    scope_record: Mapping[str, Any],
    binding_request: Mapping[str, Any],
    operation_id: str,
    request_sha256: str,
) -> Dict[str, Any]:
    canonical = scope_record["contract"]
    scope = canonical["scope"]
    roe = canonical["roe"]
    scope_identity = canonical["identity"]
    scope_hash = canonical["integrity"]["canonical_sha256"]

    targets: list[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, bool]] = set()

    def add_target(target_type: str, target_value: str, environment: Optional[str], allowed: bool, notes: Optional[str]) -> None:
        env = (environment or "LAB").upper()
        sig = (target_type, target_value, env, allowed)
        if sig in seen:
            return
        seen.add(sig)
        targets.append(
            {
                "target_type": target_type,
                "target_value": target_value,
                "environment": env,
                "allowed": bool(allowed),
                "notes": notes,
            }
        )

    for target in scope.get("targets") or []:
        add_target(target["target_type"], target["target_value"], target.get("environment"), True, None)
    for cidr in scope.get("network_ranges") or []:
        add_target("CIDR", cidr, None, True, "Projected from canonical scope.network_ranges")
    for domain in scope.get("domains") or []:
        add_target("DOMAIN", domain, None, True, "Projected from canonical scope.domains")
    for target in scope.get("excluded_targets") or []:
        add_target(
            target["target_type"],
            target["target_value"],
            target.get("environment"),
            False,
            "Canonical exclusion; Mission Orchestrator performs mandatory precheck before authorization",
        )

    sources: list[Dict[str, Any]] = []
    source_seen: set[str] = set()
    action_constraints: list[Dict[str, Any]] = []
    for capability in binding_request["capabilities"]:
        if capability["action_class"] == "CTI_SOURCE_READ":
            for source_id in capability["source_allowlist"]:
                if source_id not in source_seen:
                    source_seen.add(source_id)
                    sources.append(
                        {
                            "source_id": source_id,
                            "source_type": "CTI",
                            "allowed": True,
                            "constraints": {"capability_id": capability["capability_id"]},
                        }
                    )
        if capability["authorization_mode"] != "REQUIRED":
            continue
        effect = "REVIEW" if capability["requires_human_approval"] else "ALLOW"
        constraint_payload = dict(capability["constraints"])
        constraint_payload.update(
            {
                "capability_id": capability["capability_id"],
                "subject_component": capability["subject_component"],
                "allowed_resource_types": capability["resource_types"],
                "canonical_scope_snapshot_id": scope_identity["snapshot_id"],
                "canonical_scope_sha256": scope_hash,
            }
        )
        action_constraints.append(
            {
                "action_class": capability["action_class"],
                "action_name": capability["action_name"],
                "effect": effect,
                "max_risk_level": capability["max_risk_level"],
                "requires_approval": capability["requires_human_approval"],
                "constraints": constraint_payload,
            }
        )

    # Stage 6 uses a separate execution action, rather than the capability's
    # planning action name. Project only the explicitly permitted WPT technique
    # from the authoritative source; never infer target permission from a task.
    source_rules = ((canonical.get('metadata') or {}).get('gss_scope_sync') or {}).get('action_constraints') or []
    execution_rules = [r for r in source_rules if r.get('action_class') == 'TARGET_RECON'
                       and r.get('action_name') in ('AUTHORIZE_TARGET_EXECUTION', '*')]
    permitted = []
    for capability_id, technique in (
            ('web_technology_fingerprinting','WEB_TECHNOLOGY_FINGERPRINT'),
            ('web_surface_enumeration','BOUNDED_WEB_SURFACE_ENUMERATION')):
        wpt = next((c for c in binding_request['capabilities']
            if c['capability_id'] == capability_id and c['action_class'] == 'TARGET_RECON'
            and c['authorization_mode'] == 'REQUIRED' and not c['requires_human_approval']), None)
        permits = [r for r in execution_rules if r.get('effect') == 'ALLOW'
            and not r.get('requires_approval')
            and technique in (r.get('constraints') or {}).get('allowed_techniques', [])]
        forbidden = any(r.get('effect') != 'ALLOW' or r.get('requires_approval')
            or technique in (r.get('constraints') or {}).get('prohibited_techniques', [])
            or ((r.get('constraints') or {}).get('allowed_techniques') is not None
                and technique not in r['constraints']['allowed_techniques']) for r in execution_rules)
        if wpt and permits and not forbidden:
            permitted.append((wpt, technique, permits))
    execution_route_bound = any(r['action_class']=='TARGET_RECON'
        and r['action_name']=='AUTHORIZE_TARGET_EXECUTION' for r in action_constraints)
    if permitted and not execution_route_bound:
        execution_limits = {'allowed_techniques':[t for _,t,_ in permitted], 'read_only':True}
        caps = [c['constraints'].get('max_requests',1) for c,_,_ in permitted]
        execution_limits['max_requests'] = min(caps)
        methods = [set(c['constraints'].get('allowed_methods',['GET'])) for c,_,_ in permitted]
        execution_limits['allowed_methods'] = sorted(set.intersection(*methods))
        if len(permitted) == 1 and permitted[0][0]['constraints'].get('execution_profile'):
            execution_limits['execution_profile'] = permitted[0][0]['constraints']['execution_profile']
        budgets = [r.get('constraints',{}).get('max_network_requests') for _,_,rules in permitted for r in rules]
        budgets = [b for b in budgets if type(b) is int and b > 0]
        if budgets:
            execution_limits['max_network_requests'] = min(budgets)
        action_constraints.append({'action_class':'TARGET_RECON',
            'action_name':'AUTHORIZE_TARGET_EXECUTION', 'effect':'ALLOW',
            'max_risk_level':'LOW', 'requires_approval':False, 'constraints':execution_limits})

    # Parallel projection for the safe, read-only validation stage. Project a
    # VULNERABILITY_VALIDATION execution authority only for techniques the source
    # scope explicitly permits and the bound validation capability requests. Never
    # inferred from a task; never covers exploitation or state-changing actions.
    validation_cap = next((c for c in binding_request['capabilities']
        if c['capability_id'] == 'pentest.validate' and c['action_class'] == 'VULNERABILITY_VALIDATION'
        and c['authorization_mode'] == 'REQUIRED' and not c['requires_human_approval']), None)
    validation_execution = project_validation_execution_authority(source_rules, validation_cap)
    validation_bound = any(r['action_class'] == 'VULNERABILITY_VALIDATION'
        and r['action_name'] == 'AUTHORIZE_TARGET_EXECUTION' for r in action_constraints)
    if validation_execution and not validation_bound:
        action_constraints.append(validation_execution)

    # Governance-bound delegation is derived from capabilities explicitly bound
    # in this new Mission Governance Binding and the canonical subsystem registry.
    # It does not inherit target authority: GSS receives a separate exact resource
    # allowlist and a low-risk logical-delegation constraint.
    subsystem_by_id = {
        item["identity"]["subsystem_id"]: item
        for item in canonical_subsystem_contracts()
    }
    capability_by_id = {
        item["identity"]["capability_id"]: item
        for item in canonical_capability_contracts()
    }
    allowed_delegation_resources: list[str] = []
    for capability in binding_request["capabilities"]:
        # Only explicitly bound low-risk logical CTI reads or Pentest Recon
        # may be delegated. Other target-interacting capabilities default-deny.
        if capability["authorization_mode"] != "REQUIRED" or capability["requires_human_approval"]:
            continue
        registry_capability = capability_by_id.get(capability["capability_id"])
        if registry_capability is None:
            continue
        subsystem_id = registry_capability["identity"]["subsystem_id"]
        subsystem = subsystem_by_id.get(subsystem_id)
        component_prefix = (subsystem or {}).get("classification", {}).get("component_selector", {}).get("value")
        if not component_prefix or not capability["subject_component"].startswith(component_prefix):
            continue
        is_recon = (subsystem_id == "PENTEST" and capability["capability_id"] == "pentest.recon"
                    and capability["action_class"] == "TARGET_RECON")
        is_cti_read = (subsystem_id == "CTI" and capability["capability_id"] == "cti.read.context"
                       and capability["action_class"] == "CTI_SOURCE_READ"
                       and registry_capability["classification"]["side_effect_class"] == "READ_ONLY_ANALYSIS")
        if is_recon or is_cti_read:
            allowed_delegation_resources.append(f"{subsystem_id}:{capability['capability_id']}")
    allowed_delegation_resources = sorted(set(allowed_delegation_resources))
    if allowed_delegation_resources:
        action_constraints.append(
            {
                "action_class": "TASK_DELEGATION",
                "action_name": "delegate_planned_task",
                "effect": "ALLOW",
                "max_risk_level": "LOW",
                "requires_approval": False,
                "constraints": {
                    "allowed_capabilities": allowed_delegation_resources,
                    "authorized_subject_component": "APTS-MO01",
                    "authorization_purpose": "PRE_DELEGATION_ONLY",
                    "execution_authorized": False,
                    "target_actuation": False,
                    "canonical_scope_snapshot_id": scope_identity["snapshot_id"],
                    "canonical_scope_sha256": scope_hash,
                },
            }
        )

    # Explicitly persist canonical prohibitions. Unbound allowed action classes remain
    # absent from this list, so the Governance plane denies them by default.
    bound_routes = {(c["action_class"], c["action_name"]) for c in action_constraints}
    for action_class in roe.get("prohibited_action_classes") or []:
        if action_class in NON_ACTUATING_ACTIONS:
            continue
        route = (action_class, "*")
        if route in bound_routes:
            continue
        action_constraints.append(
            {
                "action_class": action_class,
                "action_name": "*",
                "effect": "DENY",
                "max_risk_level": "LOW",
                "requires_approval": False,
                "constraints": {"canonical_prohibition": True, "canonical_scope_sha256": scope_hash},
            }
        )

    metadata = dict(binding_request["metadata"])
    metadata.update(
        {
            "mission_orchestrator_binding_operation_id": operation_id,
            "mission_orchestrator_binding_request_sha256": request_sha256,
            "mission_scope_contract_id": scope_identity["mission_scope_contract_id"],
            "mission_scope_contract_version": scope_identity["contract_version"],
            "mission_scope_snapshot_id": scope_identity["snapshot_id"],
            "mission_scope_sha256": scope_hash,
            "binding_schema_version": BINDING_SCHEMA_VERSION,
            "authority_boundary": "APTS-MO01_DEFINITION__APTSGSS_AUTHORIZATION",
            "negative_scope_enforcement": "MISSION_ORCHESTRATOR_PRECHECK_AND_GOVERNANCE_DEFAULT_DENY",
        }
    )
    time_window = roe.get("allowed_time_window") or {}
    return {
        "mission_id": mission_id,
        "name": binding_request.get("name") or f"Mission Orchestrator governance binding {scope_identity['snapshot_id']}",
        "policy_set_id": binding_request["policy_set_id"],
        "valid_from": time_window.get("start_at"),
        "valid_until": time_window.get("end_at"),
        "created_by": binding_request["actor"],
        "approved_by": binding_request.get("approved_by"),
        "targets": targets,
        "sources": sources,
        "action_constraints": action_constraints,
        "metadata": metadata,
    }


def validate_governance_scope_response(
    response: Any,
    *,
    mission_id: str,
    policy_set_id: str,
    operation_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise MissionGovernanceProtocolError("Governance scope response must be a JSON object")
    required = ["scope_contract_id", "mission_id", "status", "policy_set_id", "version", "contract_hash"]
    missing = [key for key in required if response.get(key) in (None, "")]
    if missing:
        raise MissionGovernanceProtocolError("Governance scope response missing: " + ", ".join(missing))
    if str(response["mission_id"]) != mission_id:
        raise MissionGovernanceProtocolError("Governance scope mission_id mismatch")
    if str(response["policy_set_id"]) != policy_set_id:
        raise MissionGovernanceProtocolError("Governance scope policy_set_id mismatch")
    if str(response["status"]).upper() != "ACTIVE":
        raise MissionGovernanceProtocolError("Governance scope contract is not ACTIVE")
    try:
        version = int(response["version"])
    except (TypeError, ValueError) as exc:
        raise MissionGovernanceProtocolError("Governance scope version is invalid") from exc
    if version < 1:
        raise MissionGovernanceProtocolError("Governance scope version must be >= 1")
    contract_hash = str(response["contract_hash"]).lower()
    if not HEX64_RE.match(contract_hash):
        raise MissionGovernanceProtocolError("Governance scope contract_hash must be 64 lowercase hex characters")
    if operation_id:
        metadata = response.get("metadata")
        if not isinstance(metadata, dict):
            raise MissionGovernanceProtocolError("Governance scope response is missing operation provenance metadata")
        if metadata.get("mission_orchestrator_binding_operation_id") != operation_id:
            raise MissionGovernanceProtocolError("Governance scope operation provenance mismatch")
    normalized = dict(response)
    normalized["version"] = version
    normalized["contract_hash"] = contract_hash
    return normalized


def build_binding_contract(
    *,
    mission_id: str,
    mission_governance_binding_id: str,
    binding_snapshot_id: str,
    binding_version: int,
    scope_record: Mapping[str, Any],
    normalized_request: Mapping[str, Any],
    governance_scope: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    scope_contract = scope_record["contract"]
    identity = scope_contract["identity"]
    core = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "identity": {
            "mission_id": mission_id,
            "mission_governance_binding_id": mission_governance_binding_id,
            "binding_snapshot_id": binding_snapshot_id,
            "binding_version": binding_version,
        },
        "canonical_scope_binding": {
            "mission_scope_contract_id": identity["mission_scope_contract_id"],
            "mission_scope_contract_version": identity["contract_version"],
            "mission_scope_snapshot_id": identity["snapshot_id"],
            "mission_scope_sha256": scope_contract["integrity"]["canonical_sha256"],
        },
        "governance_authority": {
            "governance_required": True,
            "authorization_authority": AUTHORITY,
            "authorization_authority_component": AUTHORITY_COMPONENT,
            "governance_scope_contract_id": governance_scope["scope_contract_id"],
            "governance_scope_version": int(governance_scope["version"]),
            "governance_scope_contract_hash": governance_scope["contract_hash"],
            "policy_set_id": governance_scope["policy_set_id"],
            "policy_version": None,
            "governance_status": "BOUND",
        },
        "capabilities": list(normalized_request["capabilities"]),
        "semantics": {
            "binding_mode": "CAPABILITY_BASED",
            "default_effect": "DENY",
            "fail_closed": True,
            "hard_deny_precedence": True,
            "emergency_stop_preemption": True,
            "unknown_capability_effect": "DENY",
            "pre_dispatch_revalidation_required_for_authorized_target_actions": True,
            "dispatch_enabled": False,
            "target_actuation": False,
        },
        "reason": normalized_request.get("reason"),
        "metadata": dict(normalized_request.get("metadata") or {}),
        "created_by": normalized_request["actor"],
        "created_at": created_at,
    }
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": BINDING_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": sha256_hex(core),
        },
    }


def verify_binding_contract(contract: Mapping[str, Any]) -> bool:
    try:
        integrity = contract["integrity"]
        core = {key: value for key, value in contract.items() if key != "integrity"}
        return (
            integrity.get("hash_domain") == BINDING_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex(core)
        )
    except Exception:
        return False


def normalize_authorization_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("request body must be a JSON object")
    unknown = sorted(set(payload) - _AUTH_FIELDS)
    if unknown:
        raise MissionValidationError("unsupported authorization-binding field(s): " + ", ".join(unknown))
    idempotency_key = _require_string(payload, "idempotency_key")
    capability_id = _identifier(payload.get("capability_id"), "capability_id")
    resource_type = _require_string(payload, "resource_type", 64).upper()
    if not RESOURCE_TYPE_RE.match(resource_type):
        raise MissionValidationError("resource_type contains unsupported characters")
    resource_value = _require_string(payload, "resource_value", 1000)
    context = _require_object(payload.get("context"), "context")
    evidence = payload.get("evidence_refs") or []
    if not isinstance(evidence, list):
        raise MissionValidationError("evidence_refs must be an array")
    evidence_refs: list[str] = []
    for item in evidence:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError("evidence_refs entries must be non-empty strings")
        item = item.strip()
        if len(item) > 1000:
            raise MissionValidationError("evidence_refs entry exceeds 1000 characters")
        if item not in evidence_refs:
            evidence_refs.append(item)
    requested_by = _optional_string(payload.get("requested_by"), "requested_by", 255)
    metadata = _require_object(payload.get("metadata"), "metadata")
    return {
        "idempotency_key": idempotency_key,
        "capability_id": capability_id,
        "resource_type": resource_type,
        "resource_value": resource_value,
        "context": context,
        "evidence_refs": evidence_refs,
        "requested_by": requested_by,
        "metadata": metadata,
    }


def authorization_request_fingerprint(
    normalized: Mapping[str, Any],
    *,
    governance_binding_version: int,
    scope_snapshot_id: str,
    capability: Mapping[str, Any],
) -> str:
    material = dict(normalized)
    material.update(
        {
            "governance_binding_version": governance_binding_version,
            "scope_snapshot_id": scope_snapshot_id,
            "capability": dict(capability),
        }
    )
    return sha256_hex(material)


def action_fingerprint(
    *,
    mission_id: str,
    governance_binding_version: int,
    scope_snapshot_id: str,
    capability: Mapping[str, Any],
    request: Mapping[str, Any],
) -> str:
    return sha256_hex(
        {
            "mission_id": mission_id,
            "governance_binding_version": governance_binding_version,
            "scope_snapshot_id": scope_snapshot_id,
            "capability_id": capability["capability_id"],
            "subject_component": capability["subject_component"],
            "action_class": capability["action_class"],
            "action_name": capability["action_name"],
            "resource_type": request["resource_type"],
            "resource_value": request["resource_value"],
            "context": request["context"],
            "evidence_refs": request["evidence_refs"],
        }
    )


def find_capability(binding_contract: Mapping[str, Any], capability_id: str) -> Optional[Dict[str, Any]]:
    for capability in binding_contract.get("capabilities") or []:
        if capability.get("capability_id") == capability_id:
            return dict(capability)
    return None


def _normalize_host(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if "://" in value:
        parsed = urlsplit(value)
        return (parsed.hostname or "").lower().rstrip(".")
    if value.count(":") == 1 and not value.startswith("["):
        return value.split(":", 1)[0]
    return value


def _target_matches(resource_value: str, target: Mapping[str, Any]) -> bool:
    target_type = str(target.get("target_type") or "").upper()
    target_value = str(target.get("target_value") or "").strip()
    resource = resource_value.strip()
    resource_host = _normalize_host(resource)
    if target_type == "CIDR":
        try:
            return ipaddress.ip_address(resource_host) in ipaddress.ip_network(target_value, strict=False)
        except ValueError:
            return False
    if target_type == "IP":
        return resource_host == _normalize_host(target_value)
    if target_type in {"HOST", "DOMAIN"}:
        target_host = _normalize_host(target_value)
        if target_host.startswith("*."):
            suffix = target_host[1:]
            return resource_host.endswith(suffix) and resource_host != suffix.lstrip(".")
        return resource_host == target_host
    if target_type == "URL":
        return resource.rstrip("/") == target_value.rstrip("/")
    if target_type in {"APPLICATION", "OTHER"}:
        return resource == target_value
    return False


def resource_in_canonical_scope(scope_contract: Mapping[str, Any], resource_value: str) -> tuple[bool, str]:
    scope = scope_contract["scope"] if "scope" in scope_contract else scope_contract["contract"]["scope"]
    for excluded in scope.get("excluded_targets") or []:
        if _target_matches(resource_value, excluded):
            return False, "RESOURCE_EXPLICITLY_EXCLUDED"

    allowed_targets = list(scope.get("targets") or [])
    allowed_targets.extend(
        {"target_type": "CIDR", "target_value": value} for value in (scope.get("network_ranges") or [])
    )
    allowed_targets.extend(
        {"target_type": "DOMAIN", "target_value": value} for value in (scope.get("domains") or [])
    )
    for target in allowed_targets:
        if _target_matches(resource_value, target):
            return True, "RESOURCE_IN_CANONICAL_SCOPE"
    return False, "RESOURCE_OUT_OF_CANONICAL_SCOPE"


def parse_timestamp(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionGovernanceProtocolError(f"{key} must be an ISO-8601 timestamp")
    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise MissionGovernanceProtocolError(f"{key} is not a valid ISO-8601 timestamp") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_policy_decision(
    response: Any,
    *,
    mission_id: str,
    governance_scope_contract_id: str,
    governance_scope_version: int,
    policy_set_id: str,
) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise MissionGovernanceProtocolError("Governance authorization response must be a JSON object")
    required = [
        "decision_id", "request_id", "mission_id", "decision", "decision_hash",
        "valid_from", "valid_until", "scope_contract_id", "scope_version",
        "policy_set_id", "policy_version",
    ]
    missing = [key for key in required if response.get(key) in (None, "")]
    if missing:
        raise MissionGovernanceProtocolError("Governance PolicyDecision missing: " + ", ".join(missing))
    if str(response["mission_id"]) != mission_id:
        raise MissionGovernanceProtocolError("PolicyDecision mission_id mismatch")
    decision = str(response["decision"]).upper()
    if decision not in DECISIONS:
        raise MissionGovernanceProtocolError(f"unsupported Governance decision: {decision}")
    if str(response["scope_contract_id"]) != governance_scope_contract_id:
        raise MissionGovernanceProtocolError("PolicyDecision scope_contract_id mismatch")
    try:
        scope_version = int(response["scope_version"])
    except (TypeError, ValueError) as exc:
        raise MissionGovernanceProtocolError("PolicyDecision scope_version is invalid") from exc
    if scope_version != int(governance_scope_version):
        raise MissionGovernanceProtocolError("PolicyDecision scope_version mismatch")
    if str(response["policy_set_id"]) != policy_set_id:
        raise MissionGovernanceProtocolError("PolicyDecision policy_set_id mismatch")
    try:
        policy_version = int(response["policy_version"])
    except (TypeError, ValueError) as exc:
        raise MissionGovernanceProtocolError("PolicyDecision policy_version is invalid") from exc
    if policy_version < 1:
        raise MissionGovernanceProtocolError("PolicyDecision policy_version must be >= 1")
    decision_hash = str(response["decision_hash"]).lower()
    if not HEX64_RE.match(decision_hash):
        raise MissionGovernanceProtocolError("PolicyDecision decision_hash must be 64 lowercase hex characters")
    valid_from = parse_timestamp(response["valid_from"], "valid_from")
    valid_until = parse_timestamp(response["valid_until"], "valid_until")
    if datetime.fromisoformat(valid_until.replace("Z", "+00:00")) <= datetime.fromisoformat(valid_from.replace("Z", "+00:00")):
        raise MissionGovernanceProtocolError("PolicyDecision valid_until must be later than valid_from")
    normalized = dict(response)
    normalized["decision"] = decision
    normalized["scope_version"] = scope_version
    normalized["policy_version"] = policy_version
    normalized["decision_hash"] = decision_hash
    normalized["valid_from"] = valid_from
    normalized["valid_until"] = valid_until
    normalized["reason_codes"] = list(response.get("reason_codes") or [])
    normalized["constraints"] = dict(response.get("constraints") or {})
    normalized["requires_human_approval"] = bool(response.get("requires_human_approval"))
    return normalized


def validate_task_delegation_allow_against_scope(
    scope: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
    action_class: str,
    action_name: str,
    subject_component: str,
    resource_type: str,
    resource_value: str,
) -> None:
    """Require every delegation ALLOW to be explicitly backed by the fetched GSS scope.

    A PolicyDecision response is not sufficient evidence by itself: a malformed or
    forged ALLOW must not expand a scope that omits the exact delegation resource.
    This check only constrains control-plane delegation and never grants execution.
    """
    if str(decision.get("decision") or "").upper() != "ALLOW":
        return

    constraints = scope.get("action_constraints")
    if not isinstance(constraints, list):
        raise MissionGovernanceProtocolError(
            "ALLOW decision is not supported by the authoritative scope: action_constraints is missing"
        )

    matching = []
    for item in constraints:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("action_class") or "").upper() != action_class.upper():
            continue
        if item.get("action_name") not in (action_name, "*"):
            continue
        matching.append(item)

    # Explicit DENY is authoritative even if a broader ALLOW is also present.
    if any(str(item.get("effect") or "").upper() == "DENY" for item in matching):
        raise MissionGovernanceProtocolError(
            "ALLOW decision conflicts with DENY in the authoritative scope"
        )

    required_resource = resource_value
    explicitly_allowed = any(
        str(item.get("effect") or "").upper() == "ALLOW"
        and item.get("requires_approval") is not True
        and resource_type == "SUBSYSTEM_CAPABILITY"
        and isinstance(item.get("constraints"), Mapping)
        and required_resource in (item["constraints"].get("allowed_capabilities") or [])
        and item["constraints"].get("authorized_subject_component") == subject_component
        and item["constraints"].get("authorization_purpose") == "PRE_DELEGATION_ONLY"
        and item["constraints"].get("execution_authorized") is False
        and item["constraints"].get("target_actuation") is False
        for item in matching
    )
    if not explicitly_allowed:
        raise MissionGovernanceProtocolError(
            "ALLOW decision is not supported by the authoritative scope for the exact delegation resource"
        )


def build_authorization_binding(
    *,
    authorization_binding_id: str,
    mission_id: str,
    governance_binding: Mapping[str, Any],
    capability: Mapping[str, Any],
    request: Mapping[str, Any],
    action_sha256: str,
    decision: Mapping[str, Any],
    created_at: str,
    reconciliation: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    binding_contract = governance_binding["binding"]
    gov = binding_contract["governance_authority"]
    core = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorization_binding_id": authorization_binding_id,
        "mission_id": mission_id,
        "mission_governance_binding_id": binding_contract["identity"]["mission_governance_binding_id"],
        "governance_binding_version": binding_contract["identity"]["binding_version"],
        "canonical_scope_binding": dict(binding_contract["canonical_scope_binding"]),
        "capability": dict(capability),
        "action_fingerprint": action_sha256,
        "resource": {
            "resource_type": request["resource_type"],
            "resource_value": request["resource_value"],
        },
        "decision_provenance": {
            "authorization_mode": capability["authorization_mode"],
            "authorization_authority": AUTHORITY,
            "authorization_authority_component": AUTHORITY_COMPONENT,
            "authorization_request_id": decision["request_id"],
            "policy_decision_id": decision["decision_id"],
            "policy_decision_hash": decision["decision_hash"],
            "decision": decision["decision"],
            "reason_codes": decision.get("reason_codes") or [],
            "constraints": decision.get("constraints") or {},
            "requires_human_approval": bool(decision.get("requires_human_approval")),
            "approval_request_id": decision.get("approval_request_id"),
            "policy_set_id": decision["policy_set_id"],
            "policy_version": decision["policy_version"],
            "scope_contract_id": decision["scope_contract_id"],
            "scope_version": decision["scope_version"],
            "valid_from": decision["valid_from"],
            "valid_until": decision["valid_until"],
            "governance_event_id": decision.get("governance_event_id"),
        },
        "governance_status": (
            "AUTHORIZED" if decision["decision"] == "ALLOW" else
            "REVIEW_REQUIRED" if decision["decision"] == "REVIEW" else "DENIED"
        ),
        "authorization_granted": decision["decision"] == "ALLOW",
        "pre_dispatch_revalidation_required": capability["authorization_mode"] == "REQUIRED",
        "execution_authorized": False,
        "dispatch_enabled": False,
        "target_actuation": False,
        "metadata": dict(request.get("metadata") or {}),
        "created_at": created_at,
    }
    if reconciliation is not None:
        core["reconciliation"] = dict(reconciliation)
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": AUTHORIZATION_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": sha256_hex(core),
        },
    }


def verify_authorization_binding(binding: Mapping[str, Any]) -> bool:
    try:
        integrity = binding["integrity"]
        core = {key: value for key, value in binding.items() if key != "integrity"}
        return (
            integrity.get("hash_domain") == AUTHORIZATION_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex(core)
        )
    except Exception:
        return False


class GovernanceClient:
    """Small fail-closed HTTP client for the authoritative aptsGSS Governance plane."""

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: Optional[float] = None):
        self.base_url = (base_url or os.getenv("MISSION_GOVERNANCE_BASE_URL", "http://127.0.0.1:8770")).rstrip("/")
        self.timeout_seconds = float(timeout_seconds or os.getenv("MISSION_GOVERNANCE_TIMEOUT_SECONDS", "3.0"))
        if self.timeout_seconds <= 0:
            raise ValueError("MISSION_GOVERNANCE_TIMEOUT_SECONDS must be > 0")

    def _request(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        body = None if payload is None else canonical_json(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Accept": "application/json", "User-Agent": "APTS-MO01-stage3.1.4", **({"Content-Type": "application/json"} if body is not None else {})},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
            except Exception:
                detail = ""
            raise MissionGovernanceProtocolError(
                f"Governance endpoint {path} returned HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MissionGovernanceUnavailable(f"Governance endpoint unavailable: {path}: {exc}") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MissionGovernanceProtocolError(f"Governance endpoint {path} returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise MissionGovernanceProtocolError(f"Governance endpoint {path} returned non-object JSON")
        return decoded

    @staticmethod
    def _unwrap_completed(response: Mapping[str, Any], field: str, path: str) -> Dict[str, Any]:
        """Validate the aptsGSS HTTP envelope and return its authoritative payload.

        aptsGSS intentionally wraps API results as
        ``{"status": "completed", "<field>": {...}}``.  Treating the
        transport envelope itself as a ScopeContract or PolicyDecision would silently
        break the authority binding.  Therefore the adapter fails closed if either the
        completion marker or the expected payload field is absent.
        """
        if str(response.get("status", "")).lower() != "completed":
            raise MissionGovernanceProtocolError(
                f"Governance endpoint {path} did not return status=completed"
            )
        payload = response.get(field)
        if not isinstance(payload, dict):
            raise MissionGovernanceProtocolError(
                f"Governance endpoint {path} missing object field {field}"
            )
        return dict(payload)

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def create_scope_contract(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        path = "/api/governance/scope-contracts"
        return self._unwrap_completed(self._request("POST", path, payload), "scope_contract", path)

    def get_scope_contract(self, scope_contract_id: str) -> Dict[str, Any]:
        path = f"/api/governance/scope-contracts/{scope_contract_id}"
        return self._unwrap_completed(self._request("GET", path), "scope_contract", path)

    def evaluate_authorization(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        path = "/api/governance/authorization/evaluate"
        return self._unwrap_completed(self._request("POST", path, payload), "policy_decision", path)

    def revalidate_policy_decision(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        path = "/api/governance/authorization/revalidate"
        return self._unwrap_completed(self._request("POST", path, payload), "revalidation", path)

    def mission_correlation_snapshot(self, mission_id: str) -> Dict[str, Any]:
        path = f"/api/governance/correlation/missions/{mission_id}"
        return self._unwrap_completed(self._request("GET", path), "correlation_snapshot", path)

    def get_approval_request(self, approval_request_id: str) -> Dict[str, Any]:
        """Read an authoritative human-approval request without making a decision."""
        path = f"/api/governance/approvals/{approval_request_id}"
        return self._unwrap_completed(self._request("GET", path), "approval_request", path)
