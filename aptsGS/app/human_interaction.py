"""Explicit Human Interaction contract for APTS.

Human Interaction is the authenticated interface/workflow boundary between an operator and
authoritative APTS services.  It never becomes an alternative policy engine or executor.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

HUMAN_INTERACTION_ID = "HUMAN-INTERACTION"
HUMAN_INTERACTION_VERSION = "apts-human-interaction-v1"

WORKFLOWS = [
    {
        "id": "MISSION_AUTHORING",
        "label": "Mission authoring",
        "source_of_truth": "Global Mission Orchestrator",
        "states": ["DRAFT", "REGISTERED"],
        "side_effect": "mission_metadata_only",
    },
    {
        "id": "SCOPE_ROE_MANAGEMENT",
        "label": "Scope & RoE management",
        "source_of_truth": "aptsGSS + Mission scope contracts",
        "states": ["DRAFT", "ACTIVE", "REVOKED", "EXPIRED"],
        "side_effect": "governance_contract_only",
    },
    {
        "id": "HUMAN_APPROVAL",
        "label": "High-risk approval",
        "source_of_truth": "aptsGSS",
        "states": ["PENDING", "APPROVED", "DENIED", "EXPIRED", "CANCELLED"],
        "side_effect": "approval_artifact_only",
    },
    {
        "id": "OVERSIGHT",
        "label": "Mission review & oversight",
        "source_of_truth": "Mission observability + governance audit",
        "states": ["ATTENTION", "REVIEWED"],
        "side_effect": "none",
    },
    {
        "id": "EMERGENCY",
        "label": "Emergency control",
        "source_of_truth": "aptsGSS",
        "states": ["NORMAL", "EMERGENCY_STOP_ACTIVE"],
        "side_effect": "global_governance_preemption",
    },
]


def build_human_interaction_contract(*, principal_id: str, roles: Iterable[str], capabilities: Iterable[str]) -> Dict[str, Any]:
    return {
        "status": "completed",
        "component_id": HUMAN_INTERACTION_ID,
        "schema_version": HUMAN_INTERACTION_VERSION,
        "component_type": "Authenticated Human-System Interface / Workflow",
        "agent": False,
        "target_execution_authority": False,
        "principal": {
            "principal_id": principal_id,
            "roles": sorted(set(roles)),
            "capabilities": sorted(set(capabilities)),
        },
        "workflows": WORKFLOWS,
        "security_invariants": [
            "SERVER_OWNED_HUMAN_IDENTITY",
            "SHORT_LIVED_SERVER_SIDE_SESSION",
            "CSRF_REQUIRED_FOR_BROWSER_WRITES",
            "NO_CREDENTIAL_PERSISTENCE_IN_BROWSER",
            "NO_ARBITRARY_PROXY_PATHS",
            "NO_DIRECT_TOOL_OR_TARGET_EXECUTION",
        ],
    }
