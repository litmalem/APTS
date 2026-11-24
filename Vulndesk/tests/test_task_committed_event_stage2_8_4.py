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
from cti_services.event_bus import CTI_EVENT_SCHEMA_V2


class CaptureDb:
    def __init__(self):
        self.calls = []

    def table_exists(self, name):
        # Event persistence is intentionally off here; the event is validated
        # from the in-memory canonical bus envelope.
        return name in {"cti_action_proposals", "cti_task_contracts"}

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class Stage284TaskCommittedTests(unittest.TestCase):
    @staticmethod
    def _decision():
        now = datetime.now(timezone.utc)
        decision = {
            "request_id": "greq-284",
            "decision_id": "gdec-284",
            "mission_id": "mission-284",
            "decision": "ALLOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW"],
            "constraints": {"read_only": True},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": (now - timedelta(seconds=5)).isoformat(),
            "valid_until": (now + timedelta(minutes=5)).isoformat(),
            "policy_set_id": "default-policy",
            "policy_version": 7,
            "scope_contract_id": "scope-284",
            "scope_version": 3,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "decision_status": "ACTIVE",
            "authorization_request": {
                "mission_id": "mission-284",
                "scope_contract_id": "scope-284",
                "subject_component": "CTI-A02",
                "action_class": "CTI_SOURCE_READ",
                "action_name": "INCREMENTAL_FETCH",
                "resource_type": "CTI_SOURCE",
                "resource_value": "nvd-cve",
            },
        }
        decision["decision_hash"] = sha256_object(policy_decision_hash_payload(decision))
        return decision

    def _binding(self):
        return PolicyDecisionBinding.from_policy_decision(
            self._decision(),
            expected_mission_id="mission-284",
            expected_action_class="CTI_SOURCE_READ",
            expected_action_name="INCREMENTAL_FETCH",
            expected_resource_type="CTI_SOURCE",
            expected_resource_value="nvd-cve",
            expected_scope_contract_id="scope-284",
        )

    def _pop_only_event(self, orch):
        event = orch.event_bus.pop()
        self.assertIsNotNone(event)
        self.assertIsNone(orch.event_bus.pop())
        return event

    def test_internal_commit_emits_task_committed_with_stable_trace(self):
        orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
        contract = orch._commit_task(
            "task-internal-284",
            {"proposal_id": "proposal-internal-284", "priority_utility": 0.5},
            {"decision": "ALLOW", "reasons": []},
            "mission-284",
            "plan-284",
            RuntimeVersions(state_version=4, plan_version=2, policy_version="7"),
            "normalization_provenance_service",
            "NORMALIZE_CTI",
            ["artifact-1"],
        )
        event = self._pop_only_event(orch)
        self.assertEqual(event["event_schema_version"], CTI_EVENT_SCHEMA_V2)
        self.assertEqual(event["event_type"], "TASK_COMMITTED")
        self.assertEqual(event["trace_id"], contract.trace_id)
        self.assertEqual(event["proposal_id"], "proposal-internal-284")
        self.assertEqual(event["task_id"], "task-internal-284")
        self.assertIsNone(event["policy_decision_id"])
        self.assertEqual(event["payload"]["authorization_mode"], AUTHORIZATION_NOT_REQUIRED_INTERNAL)
        self.assertEqual(event["payload"]["status"], "COMMITTED")

    def test_authorized_commit_emits_exact_policydecision_references(self):
        orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
        orch._commit_task(
            "task-auth-284",
            {"proposal_id": "proposal-auth-284", "priority_utility": 0.9},
            {"decision": "ALLOW", "reasons": []},
            "mission-284",
            "plan-284",
            RuntimeVersions(state_version=5, plan_version=3, policy_version="7"),
            "cti_acquisition_freshness_agent",
            "SYNC_SELECTED_CTI_SOURCE",
            ["nvd-cve"],
            authorization_mode=AUTHORIZATION_REQUIRED,
            policy_decision_binding=self._binding(),
        )
        event = self._pop_only_event(orch)
        self.assertEqual(event["trace_id"], "proposal-auth-284")
        self.assertEqual(event["policy_decision_id"], "gdec-284")
        self.assertEqual(event["authorization_request_id"], "greq-284")
        self.assertEqual(event["payload"]["scope_contract_id"], "scope-284")
        self.assertEqual(event["payload"]["scope_version"], 3)
        self.assertEqual(event["payload"]["policy_set_id"], "default-policy")
        self.assertEqual(event["payload"]["policy_version"], "7")
        self.assertEqual(event["payload"]["authorization_mode"], AUTHORIZATION_REQUIRED)
        self.assertNotIn("decision_hash", event["payload"])
        self.assertNotIn("constraints", event["payload"])

    def test_invalid_required_commit_does_not_emit_task_committed(self):
        orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
        with self.assertRaises(ContractValidationError):
            orch._commit_task(
                "task-invalid-284",
                {"proposal_id": "proposal-invalid-284", "priority_utility": 0.8},
                {"decision": "ALLOW", "reasons": []},
                "mission-284",
                "plan-284",
                RuntimeVersions(policy_version="7"),
                "cti_acquisition_freshness_agent",
                "SYNC_SELECTED_CTI_SOURCE",
                ["nvd-cve"],
                authorization_mode=AUTHORIZATION_REQUIRED,
            )
        self.assertIsNone(orch.event_bus.pop())

    def test_commit_event_occurs_after_taskcontract_insert_attempt(self):
        db = CaptureDb()
        orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry())
        orch._commit_task(
            "task-order-284",
            {"proposal_id": "proposal-order-284", "priority_utility": 0.5},
            {"decision": "ALLOW", "reasons": []},
            "mission-284",
            "plan-284",
            RuntimeVersions(policy_version="7"),
            "normalization_provenance_service",
            "NORMALIZE_CTI",
            ["artifact-1"],
        )
        inserts = [sql for sql, _ in db.calls if "INSERT INTO cti_task_contracts" in sql]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(orch.event_bus.pending_count(), 1)


if __name__ == "__main__":
    unittest.main()
