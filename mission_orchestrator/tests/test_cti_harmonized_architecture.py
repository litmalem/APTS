from __future__ import annotations

import os
import sys
import types
import unittest

# Import CTI submodules without executing the project's eager cti_services
# __init__, so the pure architecture tests do not require GUI/DB drivers.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_PATH = os.path.join(ROOT, "cti_services")
if "cti_services" not in sys.modules:
    pkg = types.ModuleType("cti_services")
    pkg.__path__ = [PKG_PATH]
    sys.modules["cti_services"] = pkg

from cti_services.acquisition_freshness_agent import AcquisitionFreshnessAgent
from cti_services.attack_path_reasoning_agent import AttackPathReasoningAgent
from cti_services.pip_assembly_validation_service import PipAssemblyValidationService
from cti_services.risk_prioritization_agent import RiskPrioritizationAgent
from cti_services.service_registry import ServiceRegistry
from cti_services.db_adapter import normalize_sql_params


class NoDb:
    def table_exists(self, name):
        return False


class CaptureDb:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return 1


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class HarmonizedCtiTests(unittest.TestCase):
    def setUp(self):
        self.db = NoDb()
        self.registry = AlwaysOnRegistry()

    def test_attack_path_remains_non_executable(self):
        agent = AttackPathReasoningAgent(self.db, self.registry)
        result = agent.reason(
            "mission-1",
            [{"asset_id": "asset-1", "confidence": 0.9, "evidence_refs": ["ev:asset"]}],
            [{
                "correlation_id": "corr-1", "asset_id": "asset-1", "cve_id": "CVE-2026-0001",
                "status": "CORRELATED_APPLICABLE", "symbolic_result": "TRUE", "confidence": 0.8,
                "matched_evidence": ["ev:cve"], "missing_prerequisites": [],
            }],
            [{
                "mapping_id": "map-1", "correlation_id": "corr-1", "asset_id": "asset-1",
                "cve_id": "CVE-2026-0001", "technique_id": "T1190", "technique_name": "Technique",
                "verification_state": "VERIFIED", "confidence": 0.75, "evidence_refs": ["ev:attack"],
            }],
            {"scope_allowed": True},
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["paths"][0]["feasibility_state"], "FEASIBLE_INTELLIGENCE_PATH")
        self.assertFalse(result["paths"][0]["execution_authorized"])

    def test_bdi_hard_policy_constraint_cannot_be_overridden(self):
        agent = RiskPrioritizationAgent(self.db, self.registry)
        feasibility = agent._hard_feasibility(
            {"status": "CORRELATED_APPLICABLE", "symbolic_result": "TRUE"},
            {"asset_id": "asset-1"},
            {"scope_allowed": False},
            0.99,
        )
        self.assertFalse(feasibility["admissible"])
        self.assertIn("OUTSIDE_POLICY_SCOPE", feasibility["hard_constraint_failures"])
        self.assertFalse(feasibility["policy_can_be_overridden_by_utility"])

    def test_pip_hard_gates_and_secret_redaction(self):
        service = PipAssemblyValidationService(self.db, self.registry)
        result = service.build(
            mission_id="mission-1",
            mission_binding={"target_url": "https://example.test", "scope_allowed": True},
            asset_profiles=[{"asset_id": "asset-1", "evidence_refs": ["ev:asset"]}],
            cpe_claims=[{"resolution_id": "cpe-1", "asset_id": "asset-1", "status": "VERIFIED", "evidence_refs": ["ev:cpe"]}],
            vulnerability_correlations=[{
                "correlation_id": "corr-1", "asset_id": "asset-1", "cve_id": "CVE-2026-0001",
                "status": "CORRELATED_APPLICABLE", "symbolic_result": "TRUE", "confidence": 0.8,
                "matched_evidence": ["ev:cve"], "contradictions": [],
            }],
            attack_mappings=[{
                "mapping_id": "map-1", "correlation_id": "corr-1", "asset_id": "asset-1",
                "technique_id": "T1190", "verification_state": "VERIFIED", "confidence": 0.75,
                "evidence_refs": ["ev:attack"], "contradictions": [],
            }],
            attack_paths=[],
            threat_contexts=[],
            risk_priorities=[{
                "intention_id": "intent-1", "correlation_id": "corr-1", "priority_band": "P2_HIGH",
                "evidence_refs": ["ev:cve"], "execution_authorized": False,
            }],
            policy_context={"api_key": "must-not-leak", "scope_allowed": True},
        )
        pip = result["pip"]
        self.assertNotEqual(pip["readiness"], "REJECTED")
        self.assertEqual(pip["artifact"]["policy_context"]["api_key"], "[REDACTED]")
        self.assertTrue(all(r["passed"] for r in result["validation_results"]))
        self.assertFalse(pip["artifact"]["semantics"]["execution_authorized"])

    def test_rao_source_score_is_deterministic(self):
        agent = AcquisitionFreshnessAgent(self.db, self.registry)
        descriptor = {"source_id": "nvd-cve", "freshness_sla_seconds": 3600, "criticality": 0.9, "enabled": 1}
        state = {"source_id": "nvd-cve", "health_score": 1.0, "failure_count": 0, "last_success_at": None}
        objective = {"mission_relevance": 0.8}
        a = agent.score_source(descriptor, state, objective)
        b = agent.score_source(descriptor, state, objective)
        self.assertEqual(a["score"], b["score"])
        self.assertGreater(a["freshness"]["due_pressure"], 0.9)

    def test_service_registry_never_binds_native_config_dict(self):
        db = CaptureDb()
        registry = ServiceRegistry(db)
        registry.ensure_default_services()

        # First call is CREATE TABLE; all following calls are registry INSERTs.
        insert_calls = [
            (sql, params)
            for sql, params in db.calls
            if "INSERT INTO cti_component_registry" in sql
        ]
        self.assertGreater(len(insert_calls), 0)

        for _sql, params in insert_calls:
            self.assertIsInstance(params, dict)
            self.assertNotIn("config", params)
            self.assertIn("config_json", params)
            self.assertIsInstance(params["config_json"], str)
            self.assertFalse(any(isinstance(value, dict) for value in params.values()))

        api_params = next(
            params
            for _sql, params in insert_calls
            if params.get("service_key") == "pentest_enrichment_api_service"
        )
        self.assertIn('"host": "127.0.0.1"', api_params["config_json"])
        self.assertIn('"port": 8765', api_params["config_json"])

    def test_db_adapter_serializes_dict_parameter_only(self):
        params = normalize_sql_params({
            "payload": {"architecture_version": "2026-08-harmonized"},
            "ids": (1, 2, 3),
            "name": "cti",
        })
        self.assertIsInstance(params["payload"], str)
        self.assertIn('"architecture_version": "2026-08-harmonized"', params["payload"])
        self.assertEqual(params["ids"], (1, 2, 3))
        self.assertEqual(params["name"], "cti")


if __name__ == "__main__":
    unittest.main()
