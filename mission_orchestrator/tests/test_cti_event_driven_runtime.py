from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PKG_PATH = os.path.join(ROOT, "cti_services")
if "cti_services" not in sys.modules:
    pkg = types.ModuleType("cti_services")
    pkg.__path__ = [PKG_PATH]
    sys.modules["cti_services"] = pkg

from cti_services.common import sha256_object
from cti_services.contracts import policy_decision_hash_payload
from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator, MissionRuntime, RuntimeVersions
from cti_services.event_bus import CtiEventBus
from cti_services.event_dispatcher import CtiEventDispatcher
from cti_services.governance_client import GovernanceUnavailableError


# Keep this unit test independent from the real MariaDB/PyMySQL stack.
if "cpe_dictionary_services" not in sys.modules:
    cpe_module = types.ModuleType("cpe_dictionary_services")

    class _FakeCpeDictionaryService:
        def match_technologies(self, *args, **kwargs):
            return []

    cpe_module.CpeDictionaryService = _FakeCpeDictionaryService
    sys.modules["cpe_dictionary_services"] = cpe_module


class NoDb:
    def table_exists(self, name):
        return False


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None




class AllowGovernance:
    def evaluate_cti_source_read(self, **kwargs):
        now = datetime.now(timezone.utc)
        result = {
            "request_id": "greq-test",
            "decision_id": "gdec-test",
            "mission_id": kwargs["mission_id"],
            "decision": "ALLOW",
            "risk_score": 5.0,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "SOURCE_ALLOWED"],
            "constraints": {"read_only": True},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": (now - timedelta(seconds=5)).isoformat(),
            "valid_until": (now + timedelta(minutes=5)).isoformat(),
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "scope_contract_id": kwargs.get("scope_contract_id"),
            "scope_version": 1,
            "supersedes_decision_id": None,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "execution_authorized": True,
            "target_actuation": False,
        }
        result["decision_hash"] = sha256_object(policy_decision_hash_payload(result))
        result["decision_hash_verified"] = True
        return result

    def revalidate_policy_decision(self, **kwargs):
        return {
            "revalidation_id": "greval-test",
            "status": "VALID",
            "valid": True,
            "execution_authorized": True,
            "reason_codes": ["POLICY_DECISION_STILL_VALID"],
            "decision_id": kwargs["decision_id"],
            "request_id": kwargs["request_id"],
            "mission_id": kwargs["mission_id"],
            "decision": "ALLOW",
            "decision_status": "ACTIVE",
            "decision_hash": kwargs["decision_hash"],
            "scope_contract_id": kwargs.get("scope_contract_id"),
            "scope_version": kwargs.get("scope_version"),
            "current_scope_version": kwargs.get("scope_version"),
            "policy_set_id": kwargs.get("policy_set_id"),
            "policy_version": kwargs.get("policy_version"),
            "current_policy_version": kwargs.get("policy_version"),
            "emergency_stop_active": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
        }

    @property
    def status(self):
        class _Status:
            def as_dict(self):
                return {"enabled": True, "base_url": "http://test", "timeout_seconds": 1.0}
        return _Status()


class DecisionGovernance(AllowGovernance):
    def __init__(self, decision):
        self.decision = decision

    def evaluate_cti_source_read(self, **kwargs):
        result = super().evaluate_cti_source_read(**kwargs)
        result["decision"] = self.decision
        result["execution_authorized"] = self.decision == "ALLOW"
        if self.decision == "REVIEW":
            result["requires_human_approval"] = True
            result["approval_request_id"] = "gapproval-test"
        return result


class UnavailableGovernance(AllowGovernance):
    def evaluate_cti_source_read(self, **kwargs):
        raise GovernanceUnavailableError("simulated governance outage")


class EventDrivenRuntimeTests(unittest.TestCase):
    def test_event_bus_and_dispatcher_route_typed_event(self):
        bus = CtiEventBus(NoDb())
        dispatcher = CtiEventDispatcher(bus)
        received = []
        bus.subscribe("MISSION_STARTED", lambda e: received.append(e), subscriber_id="test")
        bus.publish(
            "MISSION_STARTED",
            mission_id="m1",
            source_component="CTI-A01",
            payload={"x": 1},
        )
        self.assertEqual(bus.pending_count(), 1)
        self.assertEqual(dispatcher.dispatch_pending(), 1)
        self.assertEqual(received[0]["event_type"], "MISSION_STARTED")
        self.assertEqual(received[0]["payload"]["x"], 1)

    def _orchestrator(self, governance_client=None):
        return CtiSubsystemOrchestrator(
            db=NoDb(),
            registry=AlwaysOnRegistry(),
            governance_client=governance_client or AllowGovernance(),
        )

    def _stub_domain_components(self, orch):
        orch.asset_cpe.profile_scan = lambda payload, mission_id: {
            "status": "completed", "asset_profiles": [], "cpe_claims": [], "enrichment_requirements": []
        }
        orch.vulnerability.correlate = lambda *args, **kwargs: {"status": "completed", "correlations": []}
        orch.attack_mapping.map_correlations = lambda *args, **kwargs: {"status": "completed", "mappings": []}
        orch.attack_path.reason = lambda *args, **kwargs: {"status": "completed", "paths": []}
        orch.threat_context.synthesize = lambda *args, **kwargs: {"status": "completed", "contexts": []}
        orch.risk.prioritize = lambda *args, **kwargs: {"status": "completed", "intentions": []}
        orch.pip.build = lambda *args, **kwargs: {
            "status": "completed",
            "pip": {"pip_id": "pip-test", "readiness": "READY", "artifact": {}},
            "validation_results": [],
        }

    def test_event_driven_dag_completes_without_source_refresh(self):
        orch = self._orchestrator()
        self._stub_domain_components(orch)
        result = orch.run_scan({
            "mission_id": "m-event-1",
            "target_url": "http://localhost/test",
            "auto_acquire_cti": False,
        })
        self.assertEqual(result["mission_status"], "COMPLETED")
        self.assertEqual(result["runtime_model"], "EVENT_DRIVEN_HYBRID_REACTIVE_DELIBERATIVE")
        self.assertEqual(result["component_outputs"]["acquisition"]["status"], "not_required")

    def test_cti_a02_triggers_source_sync_connector(self):
        orch = self._orchestrator()
        self._stub_domain_components(orch)

        proposal = {
            "decision_id": "acq-1",
            "mission_id": "m-event-2",
            "source_id": "nvd-cve",
            "action_type": "INCREMENTAL_FETCH",
            "reason_code": "FRESHNESS_DUE",
            "score_components": {
                "mission_relevance": 0.8,
                "freshness_due": 1.0,
                "criticality": 0.95,
                "change_signal": 0.0,
                "recovery_need": 0.0,
                "health": 1.0,
                "rate_pressure": 0.0,
                "cost": 0.1,
            },
            "policy_context_id": "policy-default-1",
            "authority_state": "PROPOSED_NOT_AUTHORIZED",
        }
        orch.acquisition.propose_next_action = lambda objective: dict(proposal)

        class FakeConnector:
            called = 0

            def __init__(self, progress_publisher=None):
                self.progress_publisher = progress_publisher

            def execute(self, p):
                FakeConnector.called += 1
                return {
                    "source_id": p["source_id"],
                    "http_status": 200,
                    "validation_status": "valid",
                    "sync_status": "SUCCESS",
                    "watermark_after_candidate": "2026-08-11T00:00:00Z",
                    "result": {"status": "SUCCESS"},
                }

        with patch("cti_services.cti_subsystem_orchestrator.SourceSyncConnector", FakeConnector):
            result = orch.run_scan({
                "mission_id": "m-event-2",
                "target_url": "http://localhost/test",
                "auto_acquire_cti": True,
                "cti_acquisition_max_actions": 1,
            })

        self.assertEqual(FakeConnector.called, 1)
        self.assertEqual(result["mission_status"], "COMPLETED")
        self.assertEqual(result["acquisition"]["sources"], ["nvd-cve"])
        self.assertEqual(result["acquisition"]["actions"], 1)

    def _acquisition_proposal(self, mission_id):
        return {
            "decision_id": "acq-1",
            "mission_id": mission_id,
            "source_id": "nvd-cve",
            "action_type": "INCREMENTAL_FETCH",
            "reason_code": "FRESHNESS_DUE",
            "score_components": {
                "mission_relevance": 0.8,
                "freshness_due": 1.0,
                "criticality": 0.95,
                "change_signal": 0.0,
                "recovery_need": 0.0,
                "health": 1.0,
                "rate_pressure": 0.0,
                "cost": 0.1,
            },
            "policy_context_id": "policy-default-1",
            "authority_state": "PROPOSED_NOT_AUTHORIZED",
        }

    def _assert_governance_blocks_connector(self, governance_client, expected_decision):
        orch = self._orchestrator(governance_client=governance_client)
        self._stub_domain_components(orch)
        proposal = self._acquisition_proposal("m-gov-block")
        orch.acquisition.propose_next_action = lambda objective: dict(proposal)

        class FakeConnector:
            called = 0

            def __init__(self, progress_publisher=None):
                self.progress_publisher = progress_publisher

            def execute(self, p):
                FakeConnector.called += 1
                return {"http_status": 200, "validation_status": "valid", "sync_status": "SUCCESS"}

        with patch("cti_services.cti_subsystem_orchestrator.SourceSyncConnector", FakeConnector):
            result = orch.run_scan({
                "mission_id": "m-gov-block",
                "target_url": "http://localhost/test",
                "auto_acquire_cti": True,
                "cti_acquisition_max_actions": 1,
                "scope_contract_id": "scope-test",
            })

        self.assertEqual(FakeConnector.called, 0)
        self.assertEqual(result["mission_status"], "COMPLETED")
        self.assertEqual(result["component_outputs"]["acquisition"]["status"], "denied")
        self.assertEqual(
            result["component_outputs"]["acquisition"]["policy_decision"]["decision"],
            expected_decision,
        )

    def test_governance_deny_blocks_source_sync_connector(self):
        self._assert_governance_blocks_connector(DecisionGovernance("DENY"), "DENY")

    def test_governance_review_blocks_source_sync_connector(self):
        self._assert_governance_blocks_connector(DecisionGovernance("REVIEW"), "REVIEW")

    def test_governance_unavailable_fails_closed_and_blocks_connector(self):
        orch = self._orchestrator(governance_client=UnavailableGovernance())
        self._stub_domain_components(orch)
        proposal = self._acquisition_proposal("m-gov-down")
        orch.acquisition.propose_next_action = lambda objective: dict(proposal)

        class FakeConnector:
            called = 0

            def __init__(self, progress_publisher=None):
                self.progress_publisher = progress_publisher

            def execute(self, p):
                FakeConnector.called += 1
                return {"http_status": 200, "validation_status": "valid", "sync_status": "SUCCESS"}

        with patch("cti_services.cti_subsystem_orchestrator.SourceSyncConnector", FakeConnector):
            result = orch.run_scan({
                "mission_id": "m-gov-down",
                "target_url": "http://localhost/test",
                "auto_acquire_cti": True,
                "cti_acquisition_max_actions": 1,
            })

        self.assertEqual(FakeConnector.called, 0)
        decision = result["component_outputs"]["acquisition"]["policy_decision"]
        self.assertEqual(decision["decision"], "DENY")
        self.assertEqual(decision["reason_code"], "GOVERNANCE_UNAVAILABLE_FAIL_CLOSED")

    def test_reactive_proposal_preempts_deliberative_proposal(self):
        orch = self._orchestrator()
        runtime = MissionRuntime(
            mission_id="m-arb",
            plan_id="p1",
            versions=RuntimeVersions(),
            scan_payload={},
            mission_context={"priority": 50},
            policy_context={"scope_allowed": True},
        )
        reactive = orch.handle_reactive_event("m-arb", {"event_type": "AUTHORIZATION_REVOKED"}, runtime.versions)
        deliberative = {
            "proposal_id": "d1",
            "proposal_kind": "DELIBERATIVE",
            "precedence": "DELIBERATIVE_OPTIMIZATION",
            "priority_utility": 1.0,
            "reason_code": "READY",
        }
        selected = orch._arbitrate(runtime, reactive, deliberative)
        self.assertEqual(selected["proposal_kind"], "REACTIVE")
        self.assertEqual(selected["precedence"], "SAFETY_POLICY")

    def test_task_failed_has_recovery_action(self):
        orch = self._orchestrator()
        proposal = orch.handle_reactive_event("m1", {"event_type": "TASK_FAILED"}, RuntimeVersions())
        self.assertEqual(proposal["action_type"], "RETRY_OR_REPLAN")
        self.assertEqual(proposal["precedence"], "RECOVERY")


if __name__ == "__main__":
    unittest.main()
