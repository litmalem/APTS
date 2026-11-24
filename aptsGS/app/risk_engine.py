from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .models import ActionClass, RiskLevel


@dataclass(frozen=True)
class RiskAssessment:
    score: float
    level: RiskLevel
    factors: List[Dict[str, Any]]


class DeterministicRiskEngine:
    """Transparent pre-action risk assessment.

    This service classifies risk only. It never authorizes an action.
    """

    BASE_SCORE = {
        ActionClass.INTERNAL_REASONING: 0,
        ActionClass.REPORTING: 5,
        # Delegation authorizes only a logical handoff; it grants no target action.
        ActionClass.TASK_DELEGATION: 10,
        ActionClass.CTI_SOURCE_READ: 5,
        ActionClass.TARGET_RECON: 20,
        ActionClass.TARGET_ENUMERATION: 30,
        ActionClass.VULNERABILITY_VALIDATION: 45,
        ActionClass.CONTROLLED_EXPLOITATION: 65,
        ActionClass.POST_EXPLOITATION: 75,
        ActionClass.CREDENTIAL_USE: 70,
        ActionClass.PRIVILEGE_ESCALATION: 80,
        ActionClass.LATERAL_MOVEMENT: 85,
        ActionClass.DATA_ACCESS: 75,
        ActionClass.DESTRUCTIVE_ACTION: 100,
    }

    def assess(self, action_class: ActionClass, context: Dict[str, Any]) -> RiskAssessment:
        score = float(self.BASE_SCORE[action_class])
        factors: List[Dict[str, Any]] = [
            {"factor": "base_action_class", "delta": score, "value": action_class.value}
        ]

        def add(name: str, delta: float, value: Any) -> None:
            nonlocal score
            score += delta
            factors.append({"factor": name, "delta": delta, "value": value})

        environment = str(context.get("environment") or "").upper()
        if environment in {"PROD", "PRODUCTION"}:
            add("production_environment", 15, environment)

        if bool(context.get("uses_credentials")):
            add("credential_use", 15, True)

        if context.get("reversible") is False:
            add("non_reversible", 10, False)

        blast_radius = int(context.get("blast_radius") or 1)
        if blast_radius > 1:
            add("blast_radius", min(20, 5 + (blast_radius - 2) * 3), blast_radius)

        sensitivity = str(context.get("data_sensitivity") or "").upper()
        if sensitivity in {"CONFIDENTIAL", "RESTRICTED"}:
            add("sensitive_data", 10, sensitivity)
        elif sensitivity in {"CRITICAL", "SECRET"}:
            add("critical_data", 15, sensitivity)

        if bool(context.get("internet_facing")) and action_class not in {
            ActionClass.CTI_SOURCE_READ,
            ActionClass.INTERNAL_REASONING,
            ActionClass.REPORTING,
        }:
            add("internet_facing_target", 5, True)

        score = max(0.0, min(100.0, score))
        if score < 30:
            level = RiskLevel.LOW
        elif score < 50:
            level = RiskLevel.MODERATE
        elif score < 70:
            level = RiskLevel.HIGH
        else:
            level = RiskLevel.CRITICAL

        return RiskAssessment(score=score, level=level, factors=factors)
