"""Explicit Human Layer contract for APTS.

The Human Layer is an authority/oversight boundary, not an autonomous agent and not an
execution component.  It composes existing authoritative services instead of duplicating
their state: Mission owns mission identity/lifecycle, aptsGSS owns scope/policy/approval
and emergency authority, and execution remains behind the controlled execution gateway.
"""
from __future__ import annotations

from typing import Any, Dict

HUMAN_LAYER_ID = "HUMAN-LAYER"
HUMAN_LAYER_VERSION = "apts-human-layer-v1"

RESPONSIBILITIES = [
    {
        "id": "DEFINE_GOALS",
        "name": "Define Goals",
        "authority": "Human operator defines the mission objective and success criteria; Mission Orchestrator persists canonical mission identity and lifecycle.",
    },
    {
        "id": "DEFINE_SCOPE_ROE",
        "name": "Define Scope & Rules of Engagement",
        "authority": "Human authority defines/revises bounded targets, action classes, validity windows, constraints, and approval requirements through authoritative scope contracts.",
    },
    {
        "id": "APPROVE_HIGH_RISK",
        "name": "Approve High-Risk Actions",
        "authority": "Human approval may satisfy an approval requirement, but aptsGSS must re-evaluate current scope, policy, risk, expiry, revocation, and emergency state before dispatch.",
    },
    {
        "id": "REVIEW_OVERSIGHT",
        "name": "Review & Oversight",
        "authority": "Human operators inspect mission state, evidence, decision lineage, diagnostics, and audit records and may request bounded lifecycle intervention.",
    },
    {
        "id": "EMERGENCY_CONTROL",
        "name": "Emergency Control",
        "authority": "Human authority can activate emergency stop. Governance remains online and fail-closed while execution components are expected to honor revocation/termination controls.",
    },
]

INVARIANTS = [
    "HUMAN_LAYER_IS_NOT_AN_AGENT",
    "HUMAN_LAYER_HAS_NO_DIRECT_TARGET_EXECUTION",
    "NO_HUMAN_APPROVAL_BYPASSES_CURRENT_GOVERNANCE_REVALIDATION",
    "MISSION_IDENTITY_AND_LIFECYCLE_REMAIN_MISSION_ORCHESTRATOR_AUTHORITY",
    "SCOPE_POLICY_APPROVAL_AND_EMERGENCY_REMAIN_APTSGSS_AUTHORITY",
    "EVERY_HUMAN_DECISION_REQUIRES_IDENTITY_RATIONALE_TIMESTAMP_AND_AUDIT",
    "EMERGENCY_STOP_PREEMPTS_NORMAL_AUTHORIZATION",
]


def build_human_layer_contract(service: Any) -> Dict[str, Any]:
    """Return the explicit Human Layer contract plus the current emergency state.

    This intentionally does not invent a second source of truth.  Live scope/approval/audit
    data continue to be queried from their existing authoritative GSS endpoints.
    """
    try:
        emergency = service.repo.get_emergency_state()
    except Exception:
        emergency = None
    return {
        "status": "completed",
        "component_id": HUMAN_LAYER_ID,
        "schema_version": HUMAN_LAYER_VERSION,
        "component_type": "External Human Authority / Oversight Layer",
        "agent": False,
        "target_execution_authority": False,
        "responsibilities": RESPONSIBILITIES,
        "invariants": INVARIANTS,
        "authority_map": {
            "human_layer": ["goal_definition", "scope_intent", "approval", "review", "emergency_command"],
            "mission_orchestrator": ["mission_identity", "mission_state", "mission_lifecycle", "mission_lineage"],
            "aptsGSS": ["scope_contract", "policy", "authorization", "approval_binding", "emergency_state", "audit"],
            "execution_gateway": ["deterministic_enforcement", "controlled_side_effect"],
        },
        "current_emergency_state": emergency,
    }
