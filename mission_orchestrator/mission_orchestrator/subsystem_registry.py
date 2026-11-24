from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, Mapping, Optional

from .errors import MissionValidationError

SUBSYSTEM_REGISTRY_SCHEMA_VERSION = "apts-canonical-subsystem-registry-v1"
SUBSYSTEM_CONTRACT_SCHEMA_VERSION = "apts-canonical-subsystem-contract-v1"
SUBSYSTEM_CAPABILITY_CONTRACT_SCHEMA_VERSION = "apts-subsystem-capability-contract-v1"
SUBSYSTEM_REGISTRY_HASH_DOMAIN = "MISSION_SUBSYSTEM_REGISTRY_V1"
SUBSYSTEM_CONTRACT_HASH_DOMAIN = "MISSION_SUBSYSTEM_CONTRACT_V1"
SUBSYSTEM_CAPABILITY_HASH_DOMAIN = "MISSION_SUBSYSTEM_CAPABILITY_CONTRACT_V1"
SUBSYSTEM_REGISTRY_ID = "canonical-subsystem-registry"
SUBSYSTEM_REGISTRY_VERSION = 1
SUBSYSTEM_REGISTRY_MODE = "IMMUTABLE_CANONICAL_SUBSYSTEM_IDENTITY_AND_CAPABILITY_CONTRACTS"
SUBSYSTEM_REGISTRY_AUTHORITY = "APTS-MO01_CANONICAL_ROUTING_DEFINITION"
SUBSYSTEM_RUNTIME_BINDING_MODE = "DEFERRED_TO_LATER_ROUTING_AND_DELEGATION_STAGES"
SUBSYSTEM_AVAILABILITY_MODE = "NOT_PROBED_BY_STAGE_3_4_1"
SUBSYSTEM_STATUS_REGISTERED = "REGISTERED"
CAPABILITY_STATUS_REGISTERED = "REGISTERED"
CAPABILITY_CONTRACT_MODE = "IMMUTABLE_DECLARED_CAPABILITY_NO_ROUTE_SELECTION_NO_DISPATCH"

CANONICAL_SUBSYSTEM_IDS = ("CTI", "PENTEST")
SUPPORTED_REQUIRED_SUBSYSTEMS = frozenset(CANONICAL_SUBSYSTEM_IDS)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _with_integrity(core: Mapping[str, Any], *, hash_domain: str) -> Dict[str, Any]:
    body = dict(core)
    return {
        **body,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": hash_domain,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": sha256_hex(body),
        },
    }


def verify_hashed_contract(contract: Mapping[str, Any], *, hash_domain: str) -> bool:
    try:
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        return (
            integrity.get("hash_domain") == hash_domain
            and integrity.get("canonical_sha256") == sha256_hex(core)
        )
    except Exception:
        return False


def _subsystem_contract(
    *,
    subsystem_id: str,
    subsystem_type: str,
    component_prefix: str,
    description: str,
) -> Dict[str, Any]:
    core = {
        "schema_version": SUBSYSTEM_CONTRACT_SCHEMA_VERSION,
        "identity": {
            "subsystem_id": subsystem_id,
            "registry_id": SUBSYSTEM_REGISTRY_ID,
            "registry_version": SUBSYSTEM_REGISTRY_VERSION,
        },
        "classification": {
            "subsystem_type": subsystem_type,
            "component_selector": {
                "mode": "PREFIX",
                "value": component_prefix,
            },
            "description": description,
        },
        "registration": {
            "status": SUBSYSTEM_STATUS_REGISTERED,
            "enabled": True,
            "runtime_binding_mode": SUBSYSTEM_RUNTIME_BINDING_MODE,
            "availability_mode": SUBSYSTEM_AVAILABILITY_MODE,
            "runtime_endpoint_bound": False,
            "runtime_health_probed": False,
        },
        "contract": {
            "accepted_task_schema_versions": ["apts-canonical-planned-task-v1"],
            "capability_contract_required": True,
            "network_endpoint_is_identity": False,
            "component_instance_is_identity": False,
        },
        "authority": {
            "registry_definition_authority": SUBSYSTEM_REGISTRY_AUTHORITY,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authority_component": "GOV-PLANE",
            "execution_authority": "DOWNSTREAM_SUBSYSTEM_PLUS_APTS_GSS",
            "registry_is_authorization": False,
            "registration_is_runtime_availability": False,
            "registration_is_permission": False,
            "registration_is_route_selection": False,
            "registration_is_dispatch": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
    }
    return _with_integrity(core, hash_domain=SUBSYSTEM_CONTRACT_HASH_DOMAIN)


def _capability_contract(
    *,
    subsystem_id: str,
    capability_id: str,
    capability_kind: str,
    description: str,
    side_effect_class: str,
) -> Dict[str, Any]:
    capability_contract_id = f"{subsystem_id.lower()}:{capability_id}:v1"
    core = {
        "schema_version": SUBSYSTEM_CAPABILITY_CONTRACT_SCHEMA_VERSION,
        "identity": {
            "capability_contract_id": capability_contract_id,
            "capability_id": capability_id,
            "capability_version": 1,
            "subsystem_id": subsystem_id,
            "registry_id": SUBSYSTEM_REGISTRY_ID,
            "registry_version": SUBSYSTEM_REGISTRY_VERSION,
        },
        "classification": {
            "capability_kind": capability_kind,
            "description": description,
            "side_effect_class": side_effect_class,
        },
        "compatibility": {
            "accepted_task_schema_versions": ["apts-canonical-planned-task-v1"],
            "required_subsystem": subsystem_id,
            "required_capability_match": "EXACT_CAPABILITY_ID",
        },
        "registration": {
            "status": CAPABILITY_STATUS_REGISTERED,
            "enabled": True,
            "runtime_availability": "UNKNOWN_NOT_PROBED",
        },
        "semantics": {
            "capability_contract_mode": CAPABILITY_CONTRACT_MODE,
            "delegation_eligible": True,
            "capability_is_route_selection": False,
            "capability_is_authorization": False,
            "capability_is_dispatch": False,
            "runtime_endpoint_resolution_performed": False,
            "resource_assignment_performed": False,
            "governance_query_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "execution_authority": "DOWNSTREAM_SUBSYSTEM_PLUS_APTS_GSS",
        },
    }
    return _with_integrity(core, hash_domain=SUBSYSTEM_CAPABILITY_HASH_DOMAIN)


def canonical_subsystem_contracts() -> list[Dict[str, Any]]:
    return [
        _subsystem_contract(
            subsystem_id="CTI",
            subsystem_type="CYBER_THREAT_INTELLIGENCE",
            component_prefix="CTI-",
            description="Cyber Threat Intelligence subsystem",
        ),
        _subsystem_contract(
            subsystem_id="PENTEST",
            subsystem_type="PENETRATION_TESTING",
            component_prefix="PENTEST-",
            description="Controlled penetration-testing subsystem",
        ),
    ]


def canonical_capability_contracts() -> list[Dict[str, Any]]:
    return [
        _capability_contract(
            subsystem_id="CTI",
            capability_id="cti.read.context",
            capability_kind="CTI_CONTEXT_RETRIEVAL",
            description="Retrieve canonical CTI context for a planned task",
            side_effect_class="READ_ONLY_ANALYSIS",
        ),
        _capability_contract(
            subsystem_id="CTI",
            capability_id="cti.analyze.context",
            capability_kind="CTI_CONTEXT_ANALYSIS",
            description="Analyze CTI context and produce structured intelligence",
            side_effect_class="READ_ONLY_ANALYSIS",
        ),
        _capability_contract(
            subsystem_id="PENTEST",
            capability_id="pentest.recon",
            capability_kind="PENTEST_RECONNAISSANCE",
            description="Perform governed reconnaissance within canonical mission scope",
            side_effect_class="CONTROLLED_TARGET_INTERACTION",
        ),
        _capability_contract(
            subsystem_id="PENTEST",
            capability_id="pentest.validate",
            capability_kind="PENTEST_VALIDATION",
            description="Perform governed security validation within canonical mission scope",
            side_effect_class="CONTROLLED_TARGET_INTERACTION",
        ),
    ]


def build_canonical_registry_snapshot() -> Dict[str, Any]:
    subsystems = canonical_subsystem_contracts()
    capabilities = canonical_capability_contracts()
    core = {
        "schema_version": SUBSYSTEM_REGISTRY_SCHEMA_VERSION,
        "identity": {
            "registry_id": SUBSYSTEM_REGISTRY_ID,
            "registry_version": SUBSYSTEM_REGISTRY_VERSION,
        },
        "mode": SUBSYSTEM_REGISTRY_MODE,
        "authority": {
            "registry_definition_authority": SUBSYSTEM_REGISTRY_AUTHORITY,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authority_component": "GOV-PLANE",
        },
        "subsystems": subsystems,
        "capabilities": capabilities,
        "counts": {
            "subsystems": len(subsystems),
            "capabilities": len(capabilities),
        },
        "semantics": {
            "canonical_identity_independent_of_endpoint": True,
            "capability_contracts_immutable": True,
            "runtime_endpoint_binding_performed": False,
            "runtime_health_probe_performed": False,
            "candidate_resolution_performed": False,
            "route_selection_performed": False,
            "delegation_performed": False,
            "governance_query_performed": False,
            "registry_is_authorization": False,
            "capability_is_permission": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
    }
    return _with_integrity(core, hash_domain=SUBSYSTEM_REGISTRY_HASH_DOMAIN)


def canonical_subsystem_registry_definition() -> Dict[str, Any]:
    snapshot = build_canonical_registry_snapshot()
    return {
        "schema_version": SUBSYSTEM_REGISTRY_SCHEMA_VERSION,
        "registry_id": SUBSYSTEM_REGISTRY_ID,
        "registry_version": SUBSYSTEM_REGISTRY_VERSION,
        "mode": SUBSYSTEM_REGISTRY_MODE,
        "registry_definition_authority": SUBSYSTEM_REGISTRY_AUTHORITY,
        "runtime_binding_mode": SUBSYSTEM_RUNTIME_BINDING_MODE,
        "availability_mode": SUBSYSTEM_AVAILABILITY_MODE,
        "canonical_subsystem_ids": list(CANONICAL_SUBSYSTEM_IDS),
        "subsystem_contract_schema_version": SUBSYSTEM_CONTRACT_SCHEMA_VERSION,
        "capability_contract_schema_version": SUBSYSTEM_CAPABILITY_CONTRACT_SCHEMA_VERSION,
        "subsystem_count": snapshot["counts"]["subsystems"],
        "capability_count": snapshot["counts"]["capabilities"],
        "canonical_sha256": snapshot["integrity"]["canonical_sha256"],
        "registry_is_authorization": False,
        "route_selection_performed": False,
        "delegation_performed": False,
        "runtime_endpoint_binding_performed": False,
        "runtime_health_probe_performed": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def verify_subsystem_contract(contract: Mapping[str, Any]) -> bool:
    return verify_hashed_contract(contract, hash_domain=SUBSYSTEM_CONTRACT_HASH_DOMAIN)


def verify_capability_contract(contract: Mapping[str, Any]) -> bool:
    return verify_hashed_contract(contract, hash_domain=SUBSYSTEM_CAPABILITY_HASH_DOMAIN)


def verify_registry_snapshot(snapshot: Mapping[str, Any]) -> bool:
    if not verify_hashed_contract(snapshot, hash_domain=SUBSYSTEM_REGISTRY_HASH_DOMAIN):
        return False
    try:
        subsystems = snapshot["subsystems"]
        capabilities = snapshot["capabilities"]
        return (
            all(verify_subsystem_contract(item) for item in subsystems)
            and all(verify_capability_contract(item) for item in capabilities)
            and int(snapshot["counts"]["subsystems"]) == len(subsystems)
            and int(snapshot["counts"]["capabilities"]) == len(capabilities)
        )
    except Exception:
        return False


def normalize_subsystem_id(subsystem_id: Any) -> str:
    if not isinstance(subsystem_id, str) or not subsystem_id.strip():
        raise MissionValidationError("subsystem_id must be a non-empty string")
    value = subsystem_id.strip().upper()
    if not _ID_RE.match(value):
        raise MissionValidationError("subsystem_id contains unsupported characters")
    return value


def normalize_capability_id(capability_id: Any) -> str:
    if not isinstance(capability_id, str) or not capability_id.strip():
        raise MissionValidationError("capability_id must be a non-empty string")
    value = capability_id.strip()
    if not _ID_RE.match(value):
        raise MissionValidationError("capability_id contains unsupported characters")
    return value


def subsystem_for_component(component_id: Any) -> Optional[str]:
    if not isinstance(component_id, str) or not component_id.strip():
        return None
    subject = component_id.strip().upper()
    for subsystem in canonical_subsystem_contracts():
        selector = subsystem["classification"]["component_selector"]
        if selector["mode"] == "PREFIX" and subject.startswith(selector["value"]):
            return subsystem["identity"]["subsystem_id"]
    return None


def capability_contract_for(capability_id: Any, *, subsystem_id: Any = None) -> Optional[Dict[str, Any]]:
    capability = normalize_capability_id(capability_id)
    subsystem = None if subsystem_id is None else normalize_subsystem_id(subsystem_id)
    for contract in canonical_capability_contracts():
        identity = contract["identity"]
        if identity["capability_id"] == capability and (subsystem is None or identity["subsystem_id"] == subsystem):
            return contract
    return None


def capability_ids_for_subsystem(subsystem_id: Any) -> tuple[str, ...]:
    subsystem = normalize_subsystem_id(subsystem_id)
    return tuple(
        contract["identity"]["capability_id"]
        for contract in canonical_capability_contracts()
        if contract["identity"]["subsystem_id"] == subsystem
    )
