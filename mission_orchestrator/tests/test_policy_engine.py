from app.models import ActionClass, Decision, RiskLevel
from app.policy_engine import DeterministicActionGate


def test_emergency_stop_preempts_target_action():
    result = DeterministicActionGate().evaluate(
        action_class=ActionClass.TARGET_RECON,
        risk_level=RiskLevel.LOW,
        emergency_stop_active=True,
        scope_active=True,
        resource_in_scope=True,
        source_allowed=False,
        action_constraint={
            "effect": "ALLOW",
            "max_risk_level": "MODERATE",
            "requires_approval": 0,
            "constraints": {},
        },
    )
    assert result.decision == Decision.DENY
    assert "EMERGENCY_STOP_ACTIVE" in result.reason_codes


def test_destructive_action_is_always_denied_even_with_approval():
    result = DeterministicActionGate().evaluate(
        action_class=ActionClass.DESTRUCTIVE_ACTION,
        risk_level=RiskLevel.LOW,
        emergency_stop_active=False,
        scope_active=True,
        resource_in_scope=True,
        source_allowed=False,
        action_constraint={
            "effect": "ALLOW",
            "max_risk_level": "CRITICAL",
            "requires_approval": 0,
            "constraints": {},
        },
        human_approval_granted=True,
    )
    assert result.decision == Decision.DENY
    assert "HARD_DENY_DESTRUCTIVE_ACTION" in result.reason_codes


def test_cti_source_read_requires_allowlist():
    result = DeterministicActionGate().evaluate(
        action_class=ActionClass.CTI_SOURCE_READ,
        risk_level=RiskLevel.LOW,
        emergency_stop_active=False,
        scope_active=True,
        resource_in_scope=False,
        source_allowed=False,
        action_constraint={
            "effect": "ALLOW",
            "max_risk_level": "LOW",
            "requires_approval": 0,
            "constraints": {"read_only": True},
        },
    )
    assert result.decision == Decision.DENY


def test_review_requires_human_approval():
    result = DeterministicActionGate().evaluate(
        action_class=ActionClass.VULNERABILITY_VALIDATION,
        risk_level=RiskLevel.HIGH,
        emergency_stop_active=False,
        scope_active=True,
        resource_in_scope=True,
        source_allowed=False,
        action_constraint={
            "effect": "REVIEW",
            "max_risk_level": "HIGH",
            "requires_approval": 1,
            "constraints": {"required_approver_role": "SECURITY_APPROVER"},
        },
    )
    assert result.decision == Decision.REVIEW
    assert result.requires_human_approval is True


def test_review_becomes_allow_after_approval_but_still_respects_risk_limit():
    gate = DeterministicActionGate()
    allowed = gate.evaluate(
        action_class=ActionClass.VULNERABILITY_VALIDATION,
        risk_level=RiskLevel.HIGH,
        emergency_stop_active=False,
        scope_active=True,
        resource_in_scope=True,
        source_allowed=False,
        action_constraint={
            "effect": "REVIEW",
            "max_risk_level": "HIGH",
            "requires_approval": 1,
            "constraints": {},
        },
        human_approval_granted=True,
    )
    assert allowed.decision == Decision.ALLOW

    denied = gate.evaluate(
        action_class=ActionClass.VULNERABILITY_VALIDATION,
        risk_level=RiskLevel.CRITICAL,
        emergency_stop_active=False,
        scope_active=True,
        resource_in_scope=True,
        source_allowed=False,
        action_constraint={
            "effect": "REVIEW",
            "max_risk_level": "HIGH",
            "requires_approval": 1,
            "constraints": {},
        },
        human_approval_granted=True,
    )
    assert denied.decision == Decision.DENY
    assert "RISK_EXCEEDS_SCOPE_LIMIT" in denied.reason_codes
