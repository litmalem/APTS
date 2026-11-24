import unittest

from app.workflow_profile import (
    DELEGATION_CAPABILITIES,
    DELEGATION_PURPOSE,
    DELEGATION_SUBJECT_COMPONENT,
    PROFILE_ID,
    apply_workflow_profile,
)


def _delegation(rules):
    found = [r for r in rules if r.get("action_class") == "TASK_DELEGATION"]
    assert len(found) == 1, found
    return found[0]


class WorkflowProfileDelegationBindingTest(unittest.TestCase):
    def test_generated_rule_binds_mission_subject_and_purpose(self):
        rules, _ = apply_workflow_profile([], PROFILE_ID)
        c = _delegation(rules)["constraints"]
        self.assertEqual(c["authorized_subject_component"], "APTS-MO01")
        self.assertEqual(c["authorization_purpose"], "PRE_DELEGATION_ONLY")
        self.assertIs(c["execution_authorized"], False)
        self.assertIs(c["target_actuation"], False)
        self.assertEqual(c["allowed_capabilities"], list(DELEGATION_CAPABILITIES))

    def test_existing_rule_without_binding_is_narrowed(self):
        existing = {
            "action_class": "TASK_DELEGATION", "action_name": "delegate_planned_task",
            "effect": "ALLOW", "max_risk_level": "LOW", "requires_approval": False,
            "constraints": {"allowed_capabilities": list(DELEGATION_CAPABILITIES),
                            "execution_authorized": False, "target_actuation": False},
        }
        rules, _ = apply_workflow_profile([existing], PROFILE_ID)
        c = _delegation(rules)["constraints"]
        self.assertEqual(c["authorized_subject_component"], DELEGATION_SUBJECT_COMPONENT)
        self.assertEqual(c["authorization_purpose"], DELEGATION_PURPOSE)
        self.assertEqual(c["workflow_profile"], PROFILE_ID)

    def test_existing_rule_bound_to_other_subject_is_rejected(self):
        existing = {
            "action_class": "TASK_DELEGATION", "action_name": "delegate_planned_task",
            "effect": "ALLOW", "max_risk_level": "LOW", "requires_approval": False,
            "constraints": {"allowed_capabilities": list(DELEGATION_CAPABILITIES),
                            "authorized_subject_component": "OTHER",
                            "execution_authorized": False, "target_actuation": False},
        }
        with self.assertRaises(ValueError):
            apply_workflow_profile([existing], PROFILE_ID)


    def test_capability_rule_keeps_execution_gate_rule(self):
        capability_rule = {
            "action_class": "TARGET_RECON", "action_name": "web_technology_fingerprinting",
            "effect": "ALLOW", "max_risk_level": "LOW", "requires_approval": False,
            "constraints": {"allowed_methods": ["GET"], "max_requests": 2},
        }
        rules, _ = apply_workflow_profile([capability_rule], PROFILE_ID)
        recon = {r["action_name"]: r for r in rules if r["action_class"] == "TARGET_RECON"}
        self.assertEqual(set(recon), {"web_technology_fingerprinting", "AUTHORIZE_TARGET_EXECUTION"})
        for rule in recon.values():
            self.assertTrue(rule["constraints"]["read_only"])
            self.assertIs(rule["constraints"]["target_actuation"], False)
            self.assertIn("WEB_TECHNOLOGY_FINGERPRINT", rule["constraints"]["allowed_techniques"])
        # Capability-specific limits are preserved, never widened.
        self.assertEqual(recon["web_technology_fingerprinting"]["constraints"]["max_requests"], 2)

    def test_existing_execution_rule_is_not_duplicated(self):
        execution_rule = {
            "action_class": "TARGET_RECON", "action_name": "AUTHORIZE_TARGET_EXECUTION",
            "effect": "ALLOW", "max_risk_level": "LOW", "requires_approval": False,
            "constraints": {},
        }
        rules, _ = apply_workflow_profile([execution_rule], PROFILE_ID)
        self.assertEqual(sum(1 for r in rules if r["action_class"] == "TARGET_RECON"), 1)


if __name__ == "__main__":
    unittest.main()
