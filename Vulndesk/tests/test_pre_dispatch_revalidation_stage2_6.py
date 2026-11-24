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
    AUTHORIZATION_REQUIRED,
    PolicyDecisionBinding,
    policy_decision_hash_payload,
)
from cti_services.cti_subsystem_orchestrator import (
    CtiSubsystemOrchestrator,
    MissionRuntime,
    RuntimeVersions,
)
from cti_services.governance_client import GovernanceUnavailableError


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


class FakeGovernance:
    def __init__(self, mode="VALID"):
        self.mode = mode
        self.last_kwargs = None

    def revalidate_policy_decision(self, **kwargs):
        self.last_kwargs = dict(kwargs)
        if self.mode == "UNAVAILABLE":
            raise GovernanceUnavailableError("governance offline")
        valid = self.mode == "VALID"
        return {
            "revalidation_id": "greval-stage26",
            "status": "VALID" if valid else "INVALID",
            "valid": valid,
            "execution_authorized": valid,
            "reason_codes": ["POLICY_DECISION_STILL_VALID"] if valid else ["DECISION_STATUS_REVOKED"],
            "decision_id": kwargs["decision_id"],
            "request_id": kwargs["request_id"],
            "mission_id": kwargs["mission_id"],
            "decision": "ALLOW",
            "decision_status": "ACTIVE" if valid else "REVOKED",
            "decision_hash": kwargs["decision_hash"],
            "scope_contract_id": kwargs["scope_contract_id"],
            "scope_version": kwargs["scope_version"],
            "current_scope_version": kwargs["scope_version"],
            "policy_set_id": kwargs["policy_set_id"],
            "policy_version": kwargs["policy_version"],
            "current_policy_version": kwargs["policy_version"],
            "emergency_stop_active": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
        }


class Stage26PreDispatchTests(unittest.TestCase):
    @staticmethod
    def _decision():
        now = datetime.now(timezone.utc)
        decision = {
            "request_id": "greq-stage26",
            "decision_id": "gdec-stage26",
            "mission_id": "mission-stage26",
            "decision": "ALLOW",
            "risk_score": 5.0,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "SOURCE_ALLOWLIST_MATCH"],
            "constraints": {"read_only": True, "max_pages": 1},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": (now - timedelta(seconds=5)).isoformat(),
            "valid_until": (now + timedelta(minutes=5)).isoformat(),
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "scope_contract_id": "scope-stage26",
            "scope_version": 1,
            "supersedes_decision_id": None,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "decision_status": "ACTIVE",
            "authorization_request": {
                "mission_id": "mission-stage26",
                "scope_contract_id": "scope-stage26",
                "subject_component": "CTI-A02",
                "action_class": "CTI_SOURCE_READ",
                "action_name": "INCREMENTAL_FETCH",
                "resource_type": "CTI_SOURCE",
                "resource_value": "nvd-cve",
                "requested_by": "CTI-A02",
            },
        }
        decision["decision_hash"] = sha256_object(policy_decision_hash_payload(decision))
        return decision

    def _runtime_and_contract(self, mode="VALID"):
        db = CaptureDb()
        governance = FakeGovernance(mode)
        orch = CtiSubsystemOrchestrator(
            db=db,
            registry=AlwaysOnRegistry(),
            governance_client=governance,
        )
        binding = PolicyDecisionBinding.from_policy_decision(
            self._decision(),
            expected_mission_id="mission-stage26",
            expected_action_class="CTI_SOURCE_READ",
            expected_action_name="INCREMENTAL_FETCH",
            expected_resource_type="CTI_SOURCE",
            expected_resource_value="nvd-cve",
            expected_scope_contract_id="scope-stage26",
        )
        versions = RuntimeVersions(policy_version="1")
        contract = orch._commit_task(
            "task-stage26",
            {"proposal_id": "proposal-stage26", "priority_utility": 0.9},
            {"decision": "ALLOW", "reasons": []},
            "mission-stage26",
            "plan-stage26",
            versions,
            "cti_acquisition_freshness_agent",
            "SYNC_SELECTED_CTI_SOURCE",
            ["nvd-cve"],
            authorization_mode=AUTHORIZATION_REQUIRED,
            policy_decision_binding=binding,
        )
        runtime = MissionRuntime(
            mission_id="mission-stage26",
            plan_id="plan-stage26",
            versions=versions,
            scan_payload={},
            mission_context={},
            policy_context={},
        )
        return orch, db, governance, runtime, contract, binding

    def test_valid_revalidation_authorizes_dispatch_and_persists_evidence(self):
        orch, db, governance, runtime, contract, binding = self._runtime_and_contract("VALID")
        result = orch._pre_dispatch_revalidate(runtime, contract, binding)
        self.assertTrue(result["valid"])
        self.assertEqual(governance.last_kwargs["decision_id"], "gdec-stage26")
        updates = [c for c in db.calls if "pre_dispatch_revalidation_status" in c[0]]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1]["revalidation_status"], "VALID")
        self.assertEqual(updates[0][1]["valid"], 1)

    def test_revoked_revalidation_blocks_dispatch(self):
        orch, db, _, runtime, contract, binding = self._runtime_and_contract("INVALID")
        result = orch._pre_dispatch_revalidate(runtime, contract, binding)
        self.assertFalse(result["valid"])
        self.assertIn("DECISION_STATUS_REVOKED", result["reason_codes"])
        updates = [c for c in db.calls if "pre_dispatch_revalidation_status" in c[0]]
        self.assertEqual(updates[-1][1]["valid"], 0)

    def test_governance_unavailable_fails_closed(self):
        orch, db, _, runtime, contract, binding = self._runtime_and_contract("UNAVAILABLE")
        result = orch._pre_dispatch_revalidate(runtime, contract, binding)
        self.assertFalse(result["valid"])
        self.assertIn("GOVERNANCE_REVALIDATION_UNAVAILABLE_FAIL_CLOSED", result["reason_codes"])
        updates = [c for c in db.calls if "pre_dispatch_revalidation_status" in c[0]]
        self.assertEqual(updates[-1][1]["revalidation_status"], "ERROR")
        self.assertEqual(updates[-1][1]["valid"], 0)


if __name__ == "__main__":
    unittest.main()
