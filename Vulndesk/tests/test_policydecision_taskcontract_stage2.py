from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_PATH = os.path.join(ROOT, "cti_services")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if "cti_services" not in sys.modules:
    pkg = types.ModuleType("cti_services")
    pkg.__path__ = [PKG_PATH]
    sys.modules["cti_services"] = pkg

if "cpe_dictionary_services" not in sys.modules:
    cpe_module = types.ModuleType("cpe_dictionary_services")

    class _FakeCpeDictionaryService:
        def match_technologies(self, *args, **kwargs):
            return []

    cpe_module.CpeDictionaryService = _FakeCpeDictionaryService
    sys.modules["cpe_dictionary_services"] = cpe_module

from cti_services.common import sha256_object
from cti_services.contracts import (
    AUTHORIZATION_NOT_REQUIRED_INTERNAL,
    AUTHORIZATION_REQUIRED,
    ContractValidationError,
    PolicyDecisionBinding,
    policy_decision_hash_payload,
)
from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator, RuntimeVersions


class CaptureDb:
    def __init__(self):
        self.calls = []

    def table_exists(self, name):
        return name in {"cti_action_proposals", "cti_task_contracts"}

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class Stage2PolicyDecisionTaskContractTests(unittest.TestCase):
    @staticmethod
    def _decision(*, mission_id="mission-1", source_id="nvd-cve", minutes=5):
        now = datetime.now(timezone.utc)
        decision = {
            "request_id": "greq-stage2",
            "decision_id": "gdec-stage2",
            "mission_id": mission_id,
            "decision": "ALLOW",
            "risk_score": 5.0,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "SOURCE_ALLOWLIST_MATCH"],
            "constraints": {"read_only": True},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": (now - timedelta(seconds=5)).isoformat(),
            "valid_until": (now + timedelta(minutes=minutes)).isoformat(),
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "scope_contract_id": "scope-stage2",
            "scope_version": 1,
            "supersedes_decision_id": None,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "decision_status": "ACTIVE",
            "authorization_request": {
                "mission_id": mission_id,
                "scope_contract_id": "scope-stage2",
                "subject_component": "CTI-A02",
                "action_class": "CTI_SOURCE_READ",
                "action_name": "INCREMENTAL_FETCH",
                "resource_type": "CTI_SOURCE",
                "resource_value": source_id,
                "requested_by": "CTI-A02",
            },
        }
        decision["decision_hash"] = sha256_object(policy_decision_hash_payload(decision))
        decision["decision_hash_verified"] = True
        return decision

    def _binding(self):
        return PolicyDecisionBinding.from_policy_decision(
            self._decision(),
            expected_mission_id="mission-1",
            expected_action_class="CTI_SOURCE_READ",
            expected_action_name="INCREMENTAL_FETCH",
            expected_resource_type="CTI_SOURCE",
            expected_resource_value="nvd-cve",
            expected_scope_contract_id="scope-stage2",
        )

    def test_policy_binding_accepts_exact_authoritative_decision(self):
        binding = self._binding()
        self.assertEqual(binding.decision_id, "gdec-stage2")
        self.assertEqual(binding.request_id, "greq-stage2")
        self.assertEqual(binding.resource_value, "nvd-cve")
        self.assertTrue(binding.hash_verified)

    def test_policy_binding_rejects_resource_mismatch(self):
        with self.assertRaises(ContractValidationError):
            PolicyDecisionBinding.from_policy_decision(
                self._decision(source_id="mitre-attack"),
                expected_mission_id="mission-1",
                expected_action_class="CTI_SOURCE_READ",
                expected_action_name="INCREMENTAL_FETCH",
                expected_resource_type="CTI_SOURCE",
                expected_resource_value="nvd-cve",
                expected_scope_contract_id="scope-stage2",
            )

    def test_policy_binding_rejects_hash_tampering(self):
        decision = self._decision()
        decision["decision_hash_verified"] = False
        decision["constraints"] = {"read_only": False}
        with self.assertRaises(ContractValidationError):
            PolicyDecisionBinding.from_policy_decision(
                decision,
                expected_mission_id="mission-1",
                expected_resource_value="nvd-cve",
            )

    def test_required_task_cannot_commit_without_policy_binding(self):
        orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
        with self.assertRaises(ContractValidationError):
            orch._commit_task(
                "task-1",
                {"proposal_id": "proposal-1", "priority_utility": 0.8},
                {"decision": "ALLOW", "reasons": []},
                "mission-1",
                "plan-1",
                RuntimeVersions(policy_version="1"),
                "cti_acquisition_freshness_agent",
                "SYNC_SELECTED_CTI_SOURCE",
                ["nvd-cve"],
                authorization_mode=AUTHORIZATION_REQUIRED,
            )

    def test_required_task_persists_policydecision_binding(self):
        db = CaptureDb()
        orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry())
        contract = orch._commit_task(
            "task-stage2",
            {"proposal_id": "proposal-stage2", "priority_utility": 0.8},
            {"decision": "ALLOW", "reasons": []},
            "mission-1",
            "plan-stage2",
            RuntimeVersions(policy_version="1"),
            "cti_acquisition_freshness_agent",
            "SYNC_SELECTED_CTI_SOURCE",
            ["nvd-cve"],
            authorization_mode=AUTHORIZATION_REQUIRED,
            policy_decision_binding=self._binding(),
        )
        self.assertEqual(contract.authorization_mode, AUTHORIZATION_REQUIRED)
        insert_calls = [item for item in db.calls if "INSERT INTO cti_task_contracts" in item[0]]
        self.assertEqual(len(insert_calls), 1)
        params = insert_calls[0][1]
        self.assertEqual(params["policy_decision_id"], "gdec-stage2")
        self.assertEqual(params["authorization_request_id"], "greq-stage2")
        self.assertEqual(params["authorization_decision"], "ALLOW")
        self.assertEqual(params["scope_contract_id"], "scope-stage2")
        self.assertEqual(params["governance_action_class"], "CTI_SOURCE_READ")
        self.assertEqual(params["governance_resource_value"], "nvd-cve")
        self.assertEqual(len(params["policy_decision_hash"]), 64)

    def test_internal_task_is_explicitly_not_authorized_external(self):
        db = CaptureDb()
        orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry())
        contract = orch._commit_task(
            "task-internal",
            {"proposal_id": "proposal-internal", "priority_utility": 0.5},
            {"decision": "ALLOW", "reasons": []},
            "mission-1",
            "plan-1",
            RuntimeVersions(),
            "normalization_provenance_service",
            "NORMALIZE_CTI",
            ["artifact-1"],
        )
        self.assertEqual(contract.authorization_mode, AUTHORIZATION_NOT_REQUIRED_INTERNAL)
        self.assertIsNone(contract.governance)
        insert_call = [item for item in db.calls if "INSERT INTO cti_task_contracts" in item[0]][0]
        params = insert_call[1]
        self.assertEqual(params["authorization_mode"], AUTHORIZATION_NOT_REQUIRED_INTERNAL)
        self.assertIsNone(params["policy_decision_id"])


if __name__ == "__main__":
    unittest.main()
