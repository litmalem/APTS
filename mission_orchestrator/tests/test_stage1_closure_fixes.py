from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PKG_PATH = os.path.join(ROOT, "cti_services")
if "cti_services" not in sys.modules:
    pkg = types.ModuleType("cti_services")
    pkg.__path__ = [PKG_PATH]
    sys.modules["cti_services"] = pkg

# Keep this unit test independent from the real MariaDB/PyMySQL stack.
if "cpe_dictionary_services" not in sys.modules:
    cpe_module = types.ModuleType("cpe_dictionary_services")

    class _FakeCpeDictionaryService:
        def match_technologies(self, *args, **kwargs):
            return []

    cpe_module.CpeDictionaryService = _FakeCpeDictionaryService
    sys.modules["cpe_dictionary_services"] = cpe_module

from cti_services.asset_profiling_cpe_resolution_service import AssetProfilingCpeResolutionService
from cti_services.common import to_db_datetime
from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator
from cti_services.governance_client import GovernanceUnavailableError


class NoDb:
    def table_exists(self, name):
        return False


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class DecisionGovernance:
    def __init__(self, decision: str):
        self.decision = decision

    def evaluate_cti_source_read(self, **kwargs):
        return {
            "request_id": "greq-test",
            "decision_id": "gdec-test",
            "mission_id": kwargs["mission_id"],
            "decision": self.decision,
            "risk_score": 5.0,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_DENY"],
            "constraints": {},
            "requires_human_approval": False,
            "valid_from": "2026-08-14T00:00:00Z",
            "valid_until": "2026-08-14T00:05:00Z",
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "scope_contract_id": kwargs.get("scope_contract_id"),
            "scope_version": 1,
            "decision_hash": "hash-test",
            "authority": "aptsGSS",
            "execution_authorized": self.decision == "ALLOW",
            "target_actuation": False,
        }

    @property
    def status(self):
        class _Status:
            def as_dict(self):
                return {"enabled": True, "base_url": "http://test", "timeout_seconds": 1.0}

        return _Status()


class UnavailableGovernance(DecisionGovernance):
    def __init__(self):
        super().__init__("DENY")

    def evaluate_cti_source_read(self, **kwargs):
        raise GovernanceUnavailableError("simulated governance outage")


class CaptureDb:
    def __init__(self):
        self.calls = []

    def table_exists(self, name):
        return True

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1


class Stage1ClosureFixTests(unittest.TestCase):
    @staticmethod
    def _proposal(mission_id: str):
        return {
            "decision_id": "acq-test",
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

    def _orchestrator(self, governance_client):
        orch = CtiSubsystemOrchestrator(
            db=NoDb(),
            registry=AlwaysOnRegistry(),
            governance_client=governance_client,
        )
        mission_id = "m-no-degraded"
        orch.acquisition.propose_next_action = lambda objective: dict(self._proposal(mission_id))
        # Any call here would prove that the denied acquisition incorrectly
        # advanced into the downstream DAG.
        orch.asset_cpe.profile_scan = lambda *args, **kwargs: self.fail(
            "asset profiling must not run when degraded acquisition is disabled"
        )
        return orch, mission_id

    def _assert_non_allow_stops_mission(self, governance_client, expected_reason: str):
        orch, mission_id = self._orchestrator(governance_client)

        class FakeConnector:
            called = 0

            def __init__(self, progress_publisher=None):
                self.progress_publisher = progress_publisher

            def execute(self, proposal):
                FakeConnector.called += 1
                return {"sync_status": "SUCCESS"}

        with patch("cti_services.cti_subsystem_orchestrator.SourceSyncConnector", FakeConnector):
            with self.assertRaises(RuntimeError) as ctx:
                orch.run_scan(
                    {
                        "mission_id": mission_id,
                        "target_url": "http://127.0.0.1",
                        "auto_acquire_cti": True,
                        "cti_acquisition_max_actions": 1,
                        "cti_source_set": ["nvd-cve"],
                        "allow_degraded_acquisition": False,
                        "scope_contract_id": "scope-test",
                        "policy_context": {
                            "scope_contract_id": "scope-test",
                            "scope_allowed": True,
                            "source_acquisition_allowed": True,
                            "allowed_cti_sources": ["nvd-cve"],
                        },
                    }
                )

        self.assertEqual(FakeConnector.called, 0)
        self.assertIn(expected_reason, str(ctx.exception))
        status = orch.get_mission_status(mission_id)
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["task_states"]["cti_acquisition_freshness_agent"], "FAILED")
        runtime = orch._runtime(mission_id)
        self.assertEqual(runtime.outputs["acquisition"]["status"], "failed")
        self.assertFalse(runtime.outputs["acquisition"]["degraded_allowed"])

    def test_policy_deny_respects_allow_degraded_false(self):
        self._assert_non_allow_stops_mission(
            DecisionGovernance("DENY"),
            "ACTION_CONSTRAINT_DENY",
        )

    def test_governance_outage_respects_allow_degraded_false(self):
        self._assert_non_allow_stops_mission(
            UnavailableGovernance(),
            "GOVERNANCE_UNAVAILABLE_FAIL_CLOSED",
        )

    def test_to_db_datetime_converts_iso_z_to_naive_utc(self):
        value = to_db_datetime("2026-08-14T01:49:34.385403Z")
        self.assertIsInstance(value, datetime)
        self.assertIsNone(value.tzinfo)
        self.assertEqual(value, datetime(2026, 8, 14, 1, 49, 34, 385403))

    def test_asset_profile_persistence_uses_db_safe_observed_at(self):
        db = CaptureDb()
        service = AssetProfilingCpeResolutionService.__new__(AssetProfilingCpeResolutionService)
        service.db = db
        profile = {
            "asset_profile_id": "assetprof-1",
            "mission_id": "mission-1",
            "asset_id": "asset-1",
            "asset_type": "web_application",
            "exposure": "internet-facing",
            "criticality": 0.5,
            "observed_attributes": {"target_url": "http://127.0.0.1", "hostname": None, "ip": "127.0.0.1"},
            "inferred_attributes": {},
            "evidence_refs": [],
            "confidence": 0.95,
            "verification_status": "OBSERVED",
            "profile_version": 1,
            "observed_at": "2026-08-14T01:49:34.385403Z",
        }

        service._persist_profile(profile)
        params = db.calls[-1][1]
        self.assertIsInstance(params["observed_at"], datetime)
        self.assertIsNone(params["observed_at"].tzinfo)
        self.assertEqual(params["observed_at"], datetime(2026, 8, 14, 1, 49, 34, 385403))

    def test_cpe_claim_persistence_uses_db_safe_decision_time(self):
        db = CaptureDb()
        service = AssetProfilingCpeResolutionService.__new__(AssetProfilingCpeResolutionService)
        service.db = db
        claim = {
            "resolution_id": "cperes-1",
            "mission_id": "mission-1",
            "asset_profile_id": "assetprof-1",
            "asset_id": "asset-1",
            "technology_key": "nginx|1.0",
            "candidate_rank": 1,
            "cpe_wfn": "cpe:2.3:a:nginx:nginx:1.0:*:*:*:*:*:*:*",
            "cpe23_formatted": "cpe:2.3:a:nginx:nginx:1.0:*:*:*:*:*:*:*",
            "dictionary_ref": "dict-1",
            "status": "VERIFIED",
            "confidence": 0.95,
            "observed_attributes": {},
            "inferred_attributes": {},
            "evidence_refs": [],
            "contradiction_refs": [],
            "rule_trace": [],
            "model_version": "model-1",
            "dictionary_version": "dict-1",
            "decision_time": "2026-08-14T01:50:00Z",
        }

        service._persist_claim(claim)
        params = db.calls[-1][1]
        self.assertIsInstance(params["decision_time"], datetime)
        self.assertIsNone(params["decision_time"].tzinfo)
        self.assertEqual(params["decision_time"], datetime(2026, 8, 14, 1, 50, 0))


if __name__ == "__main__":
    unittest.main()
