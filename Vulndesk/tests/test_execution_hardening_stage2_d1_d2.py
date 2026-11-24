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

# Keep tests independent from the optional GUI/CPE stack.
if "cpe_dictionary_services" not in sys.modules:
    cpe_module = types.ModuleType("cpe_dictionary_services")

    class _FakeCpeDictionaryService:
        def match_technologies(self, *args, **kwargs):
            return []

    cpe_module.CpeDictionaryService = _FakeCpeDictionaryService
    sys.modules["cpe_dictionary_services"] = cpe_module

from cti_services.acquisition_freshness_agent import AcquisitionFreshnessAgent
from cti_services.attack_path_reasoning_agent import AttackPathReasoningAgent
from cti_services.common import sha256_object
from cti_services.contracts import policy_decision_hash_payload
from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class NoDb:
    def table_exists(self, name):
        return False


class SourceStateDb:
    def __init__(self, current=None):
        self.current = current or {
            "source_id": "nvd-cve",
            "status": "DEGRADED",
            "failure_count": 3,
            "circuit_state": "OPEN",
            "health_score": 0.55,
            "watermark_value": None,
            "last_success_at": None,
        }
        self.calls = []

    def table_exists(self, name):
        return name == "cti_source_state"

    def fetch_one(self, sql, params=None):
        return dict(self.current)

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1


class PersistenceCaptureDb:
    def __init__(self):
        self.calls = []

    def table_exists(self, name):
        return name in {"cti_attack_graph_snapshots", "cti_attack_paths"}

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1


class AllowGovernance:
    def evaluate_cti_source_read(self, **kwargs):
        now = datetime.now(timezone.utc)
        result = {
            "request_id": "greq-execution-hardening",
            "decision_id": "gdec-execution-hardening",
            "mission_id": kwargs["mission_id"],
            "decision": "ALLOW",
            "risk_score": 5.0,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "SOURCE_ALLOWLIST_MATCH"],
            "constraints": {"read_only": True, "target_actuation": False, "max_pages": 1},
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
                return {
                    "enabled": True,
                    "base_url": "http://test",
                    "timeout_seconds": 1.0,
                    "task_binding_mode": "POLICY_DECISION_BOUND_TASK_CONTRACT",
                }

        return _Status()


class ExecutionHardeningTests(unittest.TestCase):
    def test_partial_sync_classifies_as_degraded_not_failed(self):
        outcome = {
            "source_id": "nvd-cve",
            "http_status": 200,
            "validation_status": "partial",
            "sync_status": "PARTIAL",
            "result": {"status": "PARTIAL", "total_fetched": 500, "total_failed": 0},
        }
        self.assertEqual(AcquisitionFreshnessAgent.classify_outcome(outcome), "DEGRADED")

    def test_degraded_partial_resets_false_failures_and_closes_circuit(self):
        db = SourceStateDb()
        agent = AcquisitionFreshnessAgent(db=db, registry=AlwaysOnRegistry())
        outcome = {
            "source_id": "nvd-cve",
            "http_status": 200,
            "validation_status": "partial",
            "sync_status": "PARTIAL",
            "watermark_after_candidate": "2026-07-22T22:33:54.971411+00:00",
            "result": {"status": "PARTIAL", "total_fetched": 500, "total_failed": 0},
        }

        agent.update_source_state("nvd-cve", "DEGRADED", outcome)

        self.assertEqual(len(db.calls), 1)
        params = db.calls[0][1]
        self.assertEqual(params["status"], "DEGRADED")
        self.assertEqual(params["failure_count"], 0)
        self.assertEqual(params["circuit_state"], "CLOSED")
        self.assertIsNone(params["next_retry_at"])
        self.assertEqual(params["health_score"], 0.90)
        self.assertIsInstance(params["last_attempt_at"], datetime)
        self.assertIsNone(params["last_attempt_at"].tzinfo)

    def test_actual_transient_failure_still_contributes_to_circuit_breaker(self):
        db = SourceStateDb(current={
            "source_id": "nvd-cve",
            "status": "TRANSIENT",
            "failure_count": 2,
            "circuit_state": "CLOSED",
            "health_score": 0.70,
            "watermark_value": None,
            "last_success_at": None,
        })
        agent = AcquisitionFreshnessAgent(db=db, registry=AlwaysOnRegistry())
        agent.update_source_state(
            "nvd-cve",
            "TRANSIENT",
            {"http_status": 503, "validation_status": "failed", "transient_error": True},
        )
        params = db.calls[0][1]
        self.assertEqual(params["failure_count"], 3)
        self.assertEqual(params["circuit_state"], "OPEN")
        self.assertIsNotNone(params["next_retry_at"])

    def test_attack_path_persistence_uses_explicit_scalar_json_params(self):
        db = PersistenceCaptureDb()
        agent = AttackPathReasoningAgent(db=db, registry=AlwaysOnRegistry())

        graph = {
            "graph_snapshot_id": "attackgraph-test",
            "mission_id": "mission-test",
            "graph_version": 1,
            "nodes": [{"node_id": "asset:a1", "meta": {"nested": True}}],
            "edges": [{"source": "asset:a1", "target": "vuln:a1:CVE-TEST"}],
            "policy_context": {"scope_allowed": True},
            "model_version": agent.MODEL_VERSION,
            "rule_version": agent.RULE_VERSION,
            "semantics": {"execution_authorized": False},
        }
        path = {
            "path_id": "attackpath-test",
            "mission_id": "mission-test",
            "graph_snapshot_id": "attackgraph-test",
            "rank": 1,
            "asset_id": "a1",
            "correlation_id": "corr-1",
            "cve_id": "CVE-TEST",
            "mapping_id": "map-1",
            "technique_id": "T1190",
            "technique_name": "Exploit Public-Facing Application",
            "path_nodes": ["asset:a1", "vuln:a1:CVE-TEST", "technique:T1190"],
            "path_confidence": 0.8,
            "feasibility_state": "FEASIBLE_INTELLIGENCE_PATH",
            "reason_code": "EVIDENCE_BOUND_PATH",
            "preconditions": [{"kind": "evidence", "required": True}],
            "postconditions": [],
            "evidence_refs": ["ev:1"],
            "policy_state": {"scope_allowed": True, "authorization_required_for_execution": True},
            "rule_trace": ["R_CORRELATION_EDGE_NOT_BLOCKED"],
            "model_version": agent.MODEL_VERSION,
            "rule_version": agent.RULE_VERSION,
            "execution_authorized": False,
            "authority_state": "PROPOSED_INTELLIGENCE_PATH_ONLY",
        }

        agent._persist_graph(graph)
        agent._persist_path(path)

        self.assertEqual(len(db.calls), 2)
        graph_params = db.calls[0][1]
        path_params = db.calls[1][1]

        # Structured objects must only cross the SQL boundary as explicit JSON strings.
        for params in (graph_params, path_params):
            self.assertFalse(any(isinstance(value, dict) for value in params.values()))
            self.assertFalse(any(isinstance(value, list) for value in params.values()))

        self.assertNotIn("nodes", graph_params)
        self.assertNotIn("edges", graph_params)
        self.assertNotIn("semantics", graph_params)
        self.assertIsInstance(graph_params["nodes_json"], str)
        self.assertIsInstance(graph_params["edges_json"], str)
        self.assertNotIn("path_nodes", path_params)
        self.assertNotIn("policy_state", path_params)
        self.assertIsInstance(path_params["path_nodes_json"], str)
        self.assertIsInstance(path_params["policy_state_json"], str)

    def test_bounded_partial_emits_degraded_event_and_pipeline_completes(self):
        orch = CtiSubsystemOrchestrator(
            db=NoDb(),
            registry=AlwaysOnRegistry(),
            governance_client=AllowGovernance(),
        )

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

        proposal = {
            "decision_id": "acq-hardening-1",
            "mission_id": "m-hardening-partial",
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
            "source_sync_config": {
                "max_pages": 1,
                "page_size": 500,
                "bounded_agent_refresh": True,
            },
            "policy_context_id": "policy-default-1",
            "authority_state": "PROPOSED_NOT_AUTHORIZED",
        }
        orch.acquisition.propose_next_action = lambda objective: dict(proposal)

        class PartialConnector:
            def __init__(self, progress_publisher=None):
                self.progress_publisher = progress_publisher

            def execute(self, p):
                return {
                    "source_id": p["source_id"],
                    "http_status": 200,
                    "validation_status": "partial",
                    "sync_status": "PARTIAL",
                    "watermark_after_candidate": "2026-07-22T22:33:54.971411+00:00",
                    "result": {
                        "status": "PARTIAL",
                        "mode": "INCREMENTAL",
                        "total_fetched": 500,
                        "total_failed": 0,
                    },
                }

        degraded_events = []
        failed_events = []
        orch.event_bus.subscribe(
            "SOURCE_SYNC_DEGRADED",
            lambda event: degraded_events.append(event),
            subscriber_id="test:source-sync-degraded",
        )
        orch.event_bus.subscribe(
            "SOURCE_SYNC_FAILED",
            lambda event: failed_events.append(event),
            subscriber_id="test:source-sync-failed",
        )

        with patch("cti_services.cti_subsystem_orchestrator.SourceSyncConnector", PartialConnector):
            result = orch.run_scan({
                "mission_id": "m-hardening-partial",
                "scope_contract_id": "scope-hardening-test",
                "target_url": "http://127.0.0.1:3000",
                "auto_acquire_cti": True,
                "cti_acquisition_max_actions": 1,
            })

        self.assertEqual(result["mission_status"], "COMPLETED")
        self.assertEqual(result["acquisition"]["status"], "degraded")
        self.assertEqual(result["acquisition"]["reason_code"], "BOUNDED_SYNC_PARTIAL")
        self.assertEqual(len(degraded_events), 1)
        self.assertEqual(len(failed_events), 0)
        self.assertEqual(degraded_events[0]["payload"]["classification"], "DEGRADED")
        self.assertEqual(degraded_events[0]["payload"]["reason_code"], "BOUNDED_SYNC_PARTIAL")


if __name__ == "__main__":
    unittest.main()
