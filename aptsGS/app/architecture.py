from __future__ import annotations

ARCHITECTURE_VERSION = "2026-08-governance-v1"
SERVICE_ID = "GOV-PLANE"
SERVICE_NAME = "APTS Governance & Safety Service"

COMPONENTS = [
    {
        "id": "HUMAN-LAYER",
        "name": "Human Layer",
        "type": "External Human Authority / Oversight Layer",
        "mechanism": "Authenticated human goal/scope intent, approval, review, and emergency command",
        "authority": "Human judgement boundary; no direct target execution and no policy-engine bypass",
    },
    {
        "id": "HUMAN-INTERACTION",
        "name": "Human Interaction",
        "type": "Human-System Interface",
        "mechanism": "Server-authenticated UI/BFF workflow over authoritative Mission and Governance APIs",
        "authority": "Interaction boundary only; does not own Mission state, Governance decisions, or execution",
    },
    {
        "id": "GOV-S01",
        "name": "Scope & Rules of Engagement Service",
        "type": "Service",
        "mechanism": "Deterministic scope matching + versioned RoE",
        "authority": "Defines admissible mission/target/source scope",
    },
    {
        "id": "GOV-S02",
        "name": "Policy & Authorization Service",
        "type": "Service",
        "mechanism": "Rule-based policy evaluation; deny-by-default",
        "authority": "Issues authoritative ALLOW/DENY/REVIEW decisions",
    },
    {
        "id": "GOV-S03",
        "name": "Risk Assessment Service",
        "type": "Service",
        "mechanism": "Deterministic pre-action risk scoring",
        "authority": "Risk classification only; cannot authorize",
    },
    {
        "id": "GOV-S04",
        "name": "Deterministic Action Gate",
        "type": "Service",
        "mechanism": "Hard constraints + policy precedence",
        "authority": "Final policy gate before controlled action boundary",
    },
    {
        "id": "GOV-S05",
        "name": "Compliance & Regulatory Service",
        "type": "Service",
        "mechanism": "Obligation lookup + audit evidence",
        "authority": "Compliance obligations only",
    },
    {
        "id": "GOV-S06",
        "name": "Kill Switch & Emergency Stop Service",
        "type": "Service",
        "mechanism": "Deterministic global stop state",
        "authority": "Immediate deny/preemption authority",
    },
    {
        "id": "GOV-D01",
        "name": "Policy Decision",
        "type": "Data Artifact",
        "mechanism": "Canonical immutable decision record",
        "authority": "Carries authorization outcome; no autonomous behavior",
    },
    {
        "id": "GOV-D02",
        "name": "Rules of Engagement Contract",
        "type": "Data Artifact",
        "mechanism": "Versioned scope/constraint contract",
        "authority": "Defines authorized boundary; no autonomous behavior",
    },
    {
        "id": "GOV-D03",
        "name": "Approval Record",
        "type": "Data Artifact",
        "mechanism": "Immutable human approval/denial evidence",
        "authority": "Human decision evidence",
    },
]

INVARIANTS = [
    "governance_is_independent_and_non_agent",
    "reasoning_does_not_imply_authority",
    "recommendation_does_not_imply_authorization",
    "deny_by_default",
    "no_target_action_without_active_scope_contract",
    "human_approval_does_not_bypass_hard_denies",
    "emergency_stop_preempts_all_target_actions",
    "policy_decisions_are_versioned_and_auditable",
    "external_authority_is_revalidated_immediately_before_dispatch",
    "unknown_action_classes_are_denied",
    "human_layer_is_not_an_agent_or_executor",
    "human_interaction_is_not_an_alternative_authority",
]
