from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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

from cti_services.contracts import AUTHORIZATION_REQUIRED, TaskContract
from cti_services.cti_subsystem_orchestrator import (
    CtiSubsystemOrchestrator,
    MissionRuntime,
    RuntimeVersions,
)


class Stage26NegativeE2EGateTests(unittest.TestCase):
    @staticmethod
    def _runtime() -> MissionRuntime:
        return MissionRuntime(
            mission_id="mission-stage26-negative-gate",
            plan_id="plan-stage26-negative-gate",
            versions=RuntimeVersions(policy_version="1"),
            scan_payload={},
            mission_context={},
            policy_context={},
        )

    @staticmethod
    def _contract() -> TaskContract:
        return TaskContract(
            task_id="task-stage26-negative-gate",
            mission_id="mission-stage26-negative-gate",
            plan_id="plan-stage26-negative-gate",
            assigned_component="cti_acquisition_freshness_agent",
            task_type="SYNC_SELECTED_CTI_SOURCE",
            priority=1,
            input_refs=["nvd-cve"],
            local_guard={"decision": "ALLOW"},
            plan_version=1,
            policy_version="1",
            state_version=1,
            trace_id="proposal-stage26-negative-gate",
            authorization_mode=AUTHORIZATION_REQUIRED,
            governance=None,
        )

    @staticmethod
    def _orchestrator(event_sink):
        orch = object.__new__(CtiSubsystemOrchestrator)

        def emit_event(mission_id, event_type, source_component, payload, versions, *, severity="INFO"):
            event_sink.append(
                {
                    "mission_id": mission_id,
                    "event_type": event_type,
                    "source_component": source_component,
                    "payload": dict(payload),
                    "severity": severity,
                }
            )
            return f"event-{len(event_sink)}"

        orch._emit_event = emit_event
        return orch

    def test_gate_is_disabled_by_default(self):
        events = []
        orch = self._orchestrator(events)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CTI_STAGE26_NEGATIVE_TEST_GATE", None)
            self.assertTrue(orch._wait_pre_dispatch_test_gate(self._runtime(), self._contract()))
        self.assertEqual(events, [])

    def test_gate_waits_until_mission_specific_release_file_exists(self):
        events = []
        orch = self._orchestrator(events)
        runtime = self._runtime()
        contract = self._contract()

        with tempfile.TemporaryDirectory() as temp_dir:
            waiting = threading.Event()
            original_emit = orch._emit_event

            def emit_and_signal(*args, **kwargs):
                result = original_emit(*args, **kwargs)
                if args[1] == "PRE_DISPATCH_TEST_GATE_WAITING":
                    waiting.set()
                return result

            orch._emit_event = emit_and_signal

            env = {
                "CTI_STAGE26_NEGATIVE_TEST_GATE": "1",
                "CTI_STAGE26_NEGATIVE_TEST_GATE_DIR": temp_dir,
                "CTI_STAGE26_NEGATIVE_TEST_GATE_TIMEOUT_SECONDS": "2",
            }
            result_box = {}

            def run_gate():
                result_box["result"] = orch._wait_pre_dispatch_test_gate(runtime, contract)

            with patch.dict(os.environ, env, clear=False):
                thread = threading.Thread(target=run_gate)
                thread.start()
                self.assertTrue(waiting.wait(timeout=1.0))
                release_file = Path(temp_dir) / f".stage26-release-{runtime.mission_id}.gate"
                release_file.touch()
                thread.join(timeout=2.0)

            self.assertFalse(thread.is_alive())
            self.assertTrue(result_box.get("result"))
            self.assertFalse(release_file.exists())
            self.assertEqual(
                [event["event_type"] for event in events],
                ["PRE_DISPATCH_TEST_GATE_WAITING", "PRE_DISPATCH_TEST_GATE_RELEASED"],
            )

    def test_gate_timeout_fails_closed(self):
        events = []
        orch = self._orchestrator(events)
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "CTI_STAGE26_NEGATIVE_TEST_GATE": "true",
                "CTI_STAGE26_NEGATIVE_TEST_GATE_DIR": temp_dir,
                "CTI_STAGE26_NEGATIVE_TEST_GATE_TIMEOUT_SECONDS": "0.2",
            }
            with patch.dict(os.environ, env, clear=False):
                started = time.monotonic()
                result = orch._wait_pre_dispatch_test_gate(self._runtime(), self._contract())
                elapsed = time.monotonic() - started

        self.assertFalse(result)
        self.assertGreaterEqual(elapsed, 0.1)
        self.assertEqual(events[-1]["event_type"], "PRE_DISPATCH_TEST_GATE_TIMEOUT")
        self.assertEqual(events[-1]["severity"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
