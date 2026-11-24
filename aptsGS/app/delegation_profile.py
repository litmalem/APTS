"""Preapproved, non-actuating GSS profile for autonomous Recon handoff."""
from __future__ import annotations


def scope_action_constraints_with_profiles(action_constraints, *, auto_recon_task_delegation=False):
    """Derive only the exact Recon handoff rule under an explicit GSS profile.

    A target-scoped Recon ALLOW must already exist. Existing delegation rules,
    including DENY/REVIEW and wildcard rules, remain authoritative.
    """
    rules = [dict(item) for item in action_constraints]
    if not auto_recon_task_delegation:
        return rules, False

    recon_allowed = any(
        item.get("action_class") == "TARGET_RECON"
        and item.get("effect") == "ALLOW"
        for item in rules
    )
    delegation_rule_exists = any(
        item.get("action_class") == "TASK_DELEGATION"
        and item.get("action_name") in ("*", "delegate_planned_task")
        for item in rules
    )
    if not recon_allowed or delegation_rule_exists:
        return rules, False

    rules.append({
        "action_class": "TASK_DELEGATION",
        "action_name": "delegate_planned_task",
        "effect": "ALLOW",
        "max_risk_level": "LOW",
        "requires_approval": False,
        "constraints": {
            "allowed_capabilities": ["PENTEST:pentest.recon"],
            "execution_authorized": False,
            "target_actuation": False,
            "policy_profile": "GSS_AUTO_RECON_TASK_DELEGATION_V1",
        },
    })
    return rules, True
