"""Admission policy only. Runtime controls must also be enforced by Stage 6.4.

Unrecognized GSS constraints block admission instead of being silently dropped.
Source runtime constraints are retained in the sealed authorization context;
an admission is never a capability for target I/O.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .authorization_contract import parse_time
from .execution_contract import require_id, require_text

SUPPORTED_POLICY_CONSTRAINTS = (
    "max_actions", "allowed_action_classes", "prohibited_action_classes",
    "allowed_targets", "excluded_targets", "allowed_techniques", "prohibited_techniques",
    "risk_threshold", "impact_limit", "allowed_time_window", "requires_human_approval",
    "credential_usage_allowed", "persistence_allowed", "destructive_actions_allowed",
)
IMPACTS = {"NONE": 0, "LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3,
           "CRITICAL": 4, "DESTRUCTIVE": 5}


def admission_policy(authorization: dict[str, Any], now) -> dict[str, Any]:
    request = authorization["evaluation"]["execution_request"]
    context = authorization["evaluation"]["current_context"]
    constraints = authorization["policy_decision"]["constraints"]
    unsupported = sorted(set(constraints) - set(SUPPORTED_POLICY_CONSTRAINTS))
    reasons = []
    review_required = False
    limits = {}
    sources = {"mission": context["mission_scope"],
               "pentest": context["pentest_context"]["boundary"],
               "task": context["pentest_context"]["task"]}
    for name, source in sources.items():
        limit = source["constraints"].get("max_actions")
        if type(limit) is not int or not 1 <= limit <= 2**63 - 1:
            reasons.append("INVALID_SOURCE_ACTION_BUDGET:" + name)
        else:
            limits[name] = limit
    for key in sorted(set(constraints) & set(SUPPORTED_POLICY_CONSTRAINTS)):
        value = constraints[key]
        try:
            if key == "max_actions":
                if type(value) is not int or not 0 <= value <= 2**63 - 1:
                    raise ValueError("invalid max_actions")
                limits["mission"] = min(limits.get("mission", value), value)
            elif key in {"allowed_action_classes", "prohibited_action_classes", "allowed_techniques", "prohibited_techniques"}:
                if not isinstance(value, list) or len(value) > 500:
                    raise ValueError("expected a bounded string list")
                for item in value:
                    require_text(item, key)
                if len(set(value)) != len(value):
                    raise ValueError("duplicate policy values")
                current = request["action"]["technique" if "techniques" in key else "action_class"]
                if (key.startswith("allowed_") and current not in value) or (key.startswith("prohibited_") and current in value):
                    reasons.append("POLICY_RESTRICTS:" + key)
            elif key in {"allowed_targets", "excluded_targets"}:
                if not isinstance(value, list) or len(value) > 500:
                    raise ValueError("expected a bounded exact-target list")
                for target in value:
                    if not isinstance(target, dict) or set(target) != {"target_type", "target_value"}:
                        raise ValueError("expected an exact target identity")
                    require_id(target["target_type"], "target_type")
                    require_text(target["target_value"], "target_value")
                present = request["target"] in value
                if (key == "allowed_targets" and not present) or (key == "excluded_targets" and present):
                    reasons.append("POLICY_RESTRICTS:" + key)
            elif key in {"risk_threshold", "impact_limit"}:
                if type(value) is not str or value not in IMPACTS:
                    raise ValueError("invalid impact level")
                if IMPACTS[request["parameters"]["estimated_impact"]] > IMPACTS[value]:
                    reasons.append("POLICY_RESTRICTS:" + key)
            elif key == "allowed_time_window":
                if not isinstance(value, dict) or set(value) != {"start_at", "end_at"}:
                    raise ValueError("invalid time window")
                start, end = parse_time(value["start_at"], "start_at"), parse_time(value["end_at"], "end_at")
                if end <= start:
                    raise ValueError("invalid window order")
                if not start <= now < end:
                    reasons.append("POLICY_RESTRICTS:" + key)
            else:
                if type(value) is not bool:
                    raise ValueError("explicit policy boolean required")
                if key == "requires_human_approval":
                    review_required = value and not authorization["policy_decision"]["execution_revalidation"]["human_approval_verified"]
                elif not value:
                    relevant = {"credential_usage_allowed": "CREDENTIAL_USE",
                                "persistence_allowed": "PERSISTENCE",
                                "destructive_actions_allowed": "DESTRUCTIVE_ACTION"}[key]
                    if (request["action"]["action_class"] == relevant
                            or (key == "destructive_actions_allowed" and request["parameters"]["estimated_impact"] == "DESTRUCTIVE")):
                        reasons.append("POLICY_RESTRICTS:" + key)
        except (ValueError, TypeError, RuntimeError):
            reasons.append("MALFORMED_POLICY_CONSTRAINT:" + key)
    return {"supported_constraints": list(SUPPORTED_POLICY_CONSTRAINTS),
            "policy_constraints": deepcopy(constraints), "unsupported_constraints": unsupported,
            "reason_codes": sorted(set(reasons)), "human_review_required": review_required,
            "action_limits": limits,
            "runtime_constraints_preserved_in_authorization_context": True,
            "runtime_enforcement_required_before_target_io": True}
