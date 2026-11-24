from app.models import ActionClass, RiskLevel
from app.risk_engine import DeterministicRiskEngine


def test_cti_read_is_low_risk():
    result = DeterministicRiskEngine().assess(ActionClass.CTI_SOURCE_READ, {})
    assert result.level == RiskLevel.LOW
    assert result.score == 5


def test_controlled_exploitation_in_production_is_critical():
    result = DeterministicRiskEngine().assess(
        ActionClass.CONTROLLED_EXPLOITATION,
        {"environment": "PRODUCTION", "uses_credentials": True},
    )
    assert result.level == RiskLevel.CRITICAL
    assert result.score >= 70


def test_risk_score_is_bounded():
    result = DeterministicRiskEngine().assess(
        ActionClass.DESTRUCTIVE_ACTION,
        {
            "environment": "PRODUCTION",
            "uses_credentials": True,
            "reversible": False,
            "blast_radius": 100,
            "data_sensitivity": "SECRET",
        },
    )
    assert result.score == 100
    assert result.level == RiskLevel.CRITICAL
