from __future__ import annotations

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

from cti_services.contracts import ContractValidationError, TaskContract
from cti_services.event_bus import CTI_EVENT_SCHEMA_V1, CTI_EVENT_SCHEMA_V2, CtiEvent, CtiEventBus


class MemoryDb:
    def __init__(self, *, v2=True):
        self.v2 = v2
        self.calls = []

    def table_exists(self, name):
        return name == "cti_events"

    def columns(self, name):
        base = {
            "id", "event_id", "mission_id", "event_type", "source_component",
            "severity", "payload_json", "state_version", "plan_version",
            "policy_version", "evidence_ref", "created_at",
        }
        if self.v2:
            base |= {
                "event_schema_version", "trace_id", "causation_event_id",
                "upstream_event_id", "proposal_id", "task_id",
                "policy_decision_id", "authorization_request_id", "revalidation_id",
            }
        return base

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1

    def fetch_all(self, sql, params=None):
        return []


class Stage28EventEnvelopeTests(unittest.TestCase):
    def test_cti_event_defaults_to_v2(self):
        event = CtiEvent("event-1", "TASK_COMMITTED", "CTI-A01").as_dict()
        self.assertEqual(event["event_schema_version"], CTI_EVENT_SCHEMA_V2)
        self.assertIn("trace_id", event)
        self.assertIn("causation_event_id", event)
        self.assertIn("upstream_event_id", event)

    def test_publish_preserves_first_class_lineage(self):
        bus = CtiEventBus(MemoryDb(v2=True))
        event = bus.publish(
            "TASK_COMMITTED",
            source_component="CTI-A01",
            mission_id="mission-1",
            trace_id="proposal-1",
            proposal_id="proposal-1",
            task_id="task-1",
            policy_decision_id="gdec-1",
            authorization_request_id="greq-1",
        )
        self.assertEqual(event["trace_id"], "proposal-1")
        self.assertEqual(event["task_id"], "task-1")
        self.assertEqual(event["policy_decision_id"], "gdec-1")

    def test_v2_persistence_writes_lineage_columns(self):
        db = MemoryDb(v2=True)
        bus = CtiEventBus(db)
        bus.publish(
            "TASK_COMMITTED",
            source_component="CTI-A01",
            mission_id="mission-1",
            trace_id="proposal-1",
            proposal_id="proposal-1",
            task_id="task-1",
        )
        self.assertEqual(len(db.calls), 1)
        sql, params = db.calls[0]
        self.assertIn("event_schema_version", sql)
        self.assertIn("trace_id", sql)
        self.assertEqual(params["event_schema_version"], CTI_EVENT_SCHEMA_V2)
        self.assertEqual(params["trace_id"], "proposal-1")
        self.assertEqual(params["task_id"], "task-1")

    def test_pre_migration_persistence_falls_back_to_v1_columns(self):
        db = MemoryDb(v2=False)
        bus = CtiEventBus(db)
        event = bus.publish(
            "MISSION_STARTED",
            source_component="CTI-A01",
            mission_id="mission-legacy",
            trace_id="trace-kept-in-memory",
        )
        self.assertEqual(event["event_schema_version"], CTI_EVENT_SCHEMA_V2)
        sql, params = db.calls[0]
        self.assertNotIn("event_schema_version, mission_id", sql)
        self.assertNotIn("trace_id", params)

    def test_task_contract_requires_non_empty_trace_id(self):
        contract = TaskContract(
            task_id="task-1",
            mission_id="mission-1",
            plan_id="plan-1",
            assigned_component="normalization_provenance_service",
            task_type="NORMALIZE_CTI",
            priority=50,
            input_refs=[],
            local_guard={"decision": "ALLOW"},
            plan_version=1,
            policy_version="1",
            state_version=1,
            trace_id="",
        )
        with self.assertRaises(ContractValidationError):
            contract.validate()


if __name__ == "__main__":
    unittest.main()
