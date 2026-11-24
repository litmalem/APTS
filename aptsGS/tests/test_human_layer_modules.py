"""Explicit Human Layer/Human Interaction contract tests."""
from types import SimpleNamespace

from app.human_layer import build_human_layer_contract
from app.human_interaction import build_human_interaction_contract


def test_human_layer_is_external_authority_not_agent_or_executor():
    repo = SimpleNamespace(get_emergency_state=lambda: {"active": 0, "version": 7})
    contract = build_human_layer_contract(SimpleNamespace(repo=repo))
    assert contract["component_id"] == "HUMAN-LAYER"
    assert contract["agent"] is False
    assert contract["target_execution_authority"] is False
    assert {x["id"] for x in contract["responsibilities"]} == {
        "DEFINE_GOALS",
        "DEFINE_SCOPE_ROE",
        "APPROVE_HIGH_RISK",
        "REVIEW_OVERSIGHT",
        "EMERGENCY_CONTROL",
    }
    assert "NO_HUMAN_APPROVAL_BYPASSES_CURRENT_GOVERNANCE_REVALIDATION" in contract["invariants"]
    assert contract["authority_map"]["mission_orchestrator"] == [
        "mission_identity", "mission_state", "mission_lifecycle", "mission_lineage"
    ]
    assert contract["current_emergency_state"]["version"] == 7


def test_human_interaction_is_authenticated_workflow_not_policy_engine():
    contract = build_human_interaction_contract(
        principal_id="operator-01",
        roles=["OPERATOR"],
        capabilities=["read", "mission_author", "emergency_activate"],
    )
    assert contract["component_id"] == "HUMAN-INTERACTION"
    assert contract["agent"] is False
    assert contract["target_execution_authority"] is False
    assert contract["principal"]["principal_id"] == "operator-01"
    assert "MISSION_AUTHORING" in {x["id"] for x in contract["workflows"]}
    assert "HUMAN_APPROVAL" in {x["id"] for x in contract["workflows"]}
    assert "NO_DIRECT_TOOL_OR_TARGET_EXECUTION" in contract["security_invariants"]
