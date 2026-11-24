from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import ActionClass, Decision, RiskLevel


RISK_ORDER = {
    RiskLevel.LOW: 1,
    RiskLevel.MODERATE: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    reason_codes: List[str]
    constraints: Dict[str, Any] = field(default_factory=dict)
    requires_human_approval: bool = False


class DeterministicActionGate:
    """Hard-constraint governance gate.

    Precedence:
      Emergency Stop > Hard Deny > Scope > Policy Constraint > Approval > Allow.

    No utility score can override a hard deny.
    """

    ALWAYS_NON_ACTUATING = {
        ActionClass.INTERNAL_REASONING,
        ActionClass.REPORTING,
    }

    ALWAYS_DENY = {
        ActionClass.DESTRUCTIVE_ACTION,
    }

    def evaluate(
        self,
        *,
        action_class: ActionClass,
        risk_level: RiskLevel,
        emergency_stop_active: bool,
        scope_active: bool,
        resource_in_scope: bool,
        source_allowed: bool,
        action_constraint: Optional[dict],
        human_approval_granted: bool = False,
    ) -> GateResult:
        if emergency_stop_active and action_class not in self.ALWAYS_NON_ACTUATING:
            return GateResult(Decision.DENY, ["EMERGENCY_STOP_ACTIVE"])

        if action_class in self.ALWAYS_DENY:
            return GateResult(Decision.DENY, ["HARD_DENY_DESTRUCTIVE_ACTION"])

        if action_class in self.ALWAYS_NON_ACTUATING:
            return GateResult(
                Decision.ALLOW,
                ["NON_ACTUATING_INTERNAL_OPERATION"],
                {"target_actuation": False},
            )

        if not scope_active:
            return GateResult(Decision.DENY, ["NO_ACTIVE_SCOPE_CONTRACT"])

        if action_class == ActionClass.CTI_SOURCE_READ:
            if not source_allowed:
                return GateResult(Decision.DENY, ["SOURCE_NOT_ALLOWLISTED"])
            if action_constraint is None:
                return GateResult(Decision.DENY, ["NO_ACTION_CONSTRAINT"])
        else:
            if not resource_in_scope:
                return GateResult(Decision.DENY, ["RESOURCE_OUT_OF_SCOPE"])
            if action_constraint is None:
                return GateResult(Decision.DENY, ["NO_ACTION_CONSTRAINT"])

        effect = str(action_constraint.get("effect") or "DENY").upper()
        if effect == Decision.DENY.value:
            return GateResult(Decision.DENY, ["ACTION_CONSTRAINT_DENY"])

        max_risk = RiskLevel(str(action_constraint.get("max_risk_level") or "LOW").upper())
        if RISK_ORDER[risk_level] > RISK_ORDER[max_risk]:
            return GateResult(
                Decision.DENY,
                ["RISK_EXCEEDS_SCOPE_LIMIT", f"RISK_{risk_level.value}_GT_{max_risk.value}"],
            )

        requires_approval = bool(action_constraint.get("requires_approval")) or effect == Decision.REVIEW.value
        constraints = dict(action_constraint.get("constraints") or {})

        if requires_approval and not human_approval_granted:
            return GateResult(
                Decision.REVIEW,
                ["HUMAN_APPROVAL_REQUIRED"],
                constraints,
                requires_human_approval=True,
            )

        reasons = ["ACTION_CONSTRAINT_ALLOW"]
        if human_approval_granted:
            reasons.append("HUMAN_APPROVAL_GRANTED")
        return GateResult(Decision.ALLOW, reasons, constraints)
