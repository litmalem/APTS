from __future__ import annotations

import json
import os
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_PATH = os.path.join(ROOT, "cti_services")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if "cti_services" not in sys.modules:
    pkg = types.ModuleType("cti_services")
    pkg.__path__ = [PKG_PATH]
    sys.modules["cti_services"] = pkg

from cti_services.pip_assembly_validation_service import PipAssemblyValidationService


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class StrictTransactionDb:
    """Capture transaction statements and fail on structured SQL scalar leakage."""

    def __init__(self):
        self.statements = []

    def table_exists(self, name):
        return name in {"cti_pip_artifacts", "cti_pip_validation_results"}

    def execute_transaction(self, statements):
        captured = []
        for sql, params in statements:
            params = dict(params or {})
            for key, value in params.items():
                if isinstance(value, (dict, list, tuple, set)):
                    raise TypeError(f"structured SQL parameter leaked: {key}={type(value).__name__}")
            captured.append((sql, params))
        self.statements.extend(captured)
        return [1 for _ in captured]


class PipPersistenceHardeningD3Tests(unittest.TestCase):
    def _artifact(self):
        return {
            "pip_id": "pip-d3-test",
            "mission_id": "mission-d3-test",
            "revision": 1,
            "schema_version": "1.0-harmonized-2026-08",
            "readiness": "READY",
            "canonical_sha256": "a" * 64,
            "artifact": {
                "mission_binding": {
                    "mission_id": "mission-d3-test",
                    "scope_contract_id": "scope-d3-test",
                },
                "intelligence": {
                    "asset_profiles": [
                        {
                            "asset_id": "asset-1",
                            "metadata": {"nested": True},
                        }
                    ],
                    "attack_paths": [],
                },
                "quality": {
                    "hard_gate_passed": True,
                    "validation_results": [
                        {
                            "gate_id": "QG-H1",
                            "passed": True,
                            "details": {"nested": {"ok": True}},
                        }
                    ],
                },
                "semantics": {
                    "data_artifact": True,
                    "immutable_after_publication": True,
                    "execution_authorized": False,
                },
            },
            "validation_results": [
                {
                    "gate_id": "QG-H1",
                    "name": "Schema validity",
                    "passed": True,
                    "reason": "SCHEMA_VALID",
                    "details": {
                        "nested": {"ok": True},
                        "items": [{"id": 1}, {"id": 2}],
                    },
                },
                {
                    "gate_id": "QG-H9",
                    "name": "Authorization semantics",
                    "passed": True,
                    "reason": None,
                    "details": {
                        "execution_authorized": False,
                        "authority_state": "INTELLIGENCE_ONLY",
                    },
                },
            ],
            "immutable": True,
            "execution_authorized": False,
        }

    def test_pip_persistence_uses_explicit_scalar_json_params(self):
        db = StrictTransactionDb()
        service = PipAssemblyValidationService(db=db, registry=AlwaysOnRegistry())

        service._persist(self._artifact())

        self.assertEqual(len(db.statements), 3)
        pip_sql, pip_params = db.statements[0]
        self.assertIn("INSERT INTO cti_pip_artifacts", pip_sql)
        self.assertEqual(
            set(pip_params),
            {
                "pip_id",
                "mission_id",
                "revision",
                "schema_version",
                "readiness",
                "canonical_sha256",
                "artifact_json",
                "validation_summary_json",
            },
        )
        self.assertNotIn("artifact", pip_params)
        self.assertNotIn("validation_results", pip_params)
        self.assertNotIn("immutable", pip_params)
        self.assertNotIn("execution_authorized", pip_params)
        self.assertIsInstance(pip_params["artifact_json"], str)
        self.assertIsInstance(pip_params["validation_summary_json"], str)

    def test_nested_pip_document_round_trips_through_artifact_json(self):
        db = StrictTransactionDb()
        service = PipAssemblyValidationService(db=db, registry=AlwaysOnRegistry())
        artifact = self._artifact()

        service._persist(artifact)

        persisted = json.loads(db.statements[0][1]["artifact_json"])
        self.assertEqual(persisted["mission_binding"]["scope_contract_id"], "scope-d3-test")
        self.assertTrue(persisted["intelligence"]["asset_profiles"][0]["metadata"]["nested"])
        self.assertFalse(persisted["semantics"]["execution_authorized"])

    def test_validation_summary_and_details_are_serialized_before_sql_boundary(self):
        db = StrictTransactionDb()
        service = PipAssemblyValidationService(db=db, registry=AlwaysOnRegistry())
        artifact = self._artifact()

        service._persist(artifact)

        summary = json.loads(db.statements[0][1]["validation_summary_json"])
        self.assertEqual(len(summary), 2)
        self.assertEqual(summary[0]["details"]["items"][1]["id"], 2)

        first_gate_params = db.statements[1][1]
        gate_details = json.loads(first_gate_params["details_json"])
        self.assertTrue(gate_details["nested"]["ok"])
        self.assertEqual(gate_details["items"][0]["id"], 1)

    def test_pip_publication_keeps_non_executable_authority_invariant(self):
        db = StrictTransactionDb()
        service = PipAssemblyValidationService(db=db, registry=AlwaysOnRegistry())

        service._persist(self._artifact())

        pip_sql, pip_params = db.statements[0]
        normalized_sql = " ".join(pip_sql.split())
        self.assertIn("immutable, execution_authorized", normalized_sql)
        self.assertIn("1, 0, CURRENT_TIMESTAMP", normalized_sql)
        self.assertNotIn("execution_authorized", pip_params)
        self.assertNotIn("immutable", pip_params)


if __name__ == "__main__":
    unittest.main()
