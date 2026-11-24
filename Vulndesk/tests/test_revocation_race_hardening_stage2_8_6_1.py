from __future__ import annotations

import os
import sys
import types

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

from cti_services.cti_subsystem_orchestrator import (
    CtiSubsystemOrchestrator,
    MissionRuntime,
    RuntimeVersions,
)


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class SqlCaptureDb:
    def __init__(self):
        self.calls = []

    def table_exists(self, name):
        return name == "cti_task_contracts"

    def has_column(self, table, column):
        return table == "cti_task_contracts" and column == "pre_dispatch_revalidation_status"

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1


class QueueOnlyDb:
    def table_exists(self, name):
        return False



def _drain(orch):
    events = []
    while True:
        event = orch.event_bus.pop()
        if event is None:
            return events
        events.append(event)



def test_pre_dispatch_persistence_preserves_verified_revocation_precedence():
    db = SqlCaptureDb()
    orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry())

    orch._persist_pre_dispatch_revalidation(
        "task-race-2861",
        {
            "revalidation_id": "greval-race-2861",
            "status": "INVALID",
            "valid": False,
            "execution_authorized": False,
            "reason_codes": ["POLICY_DECISION_REVOKED"],
            "decision_status": "REVOKED",
            "decision_hash": "a" * 64,
            "checked_at": "2026-08-19T12:30:12+00:00",
        },
    )

    sql, params = db.calls[-1]
    assert params["valid"] == 0
    assert "revocation_status LIKE 'VERIFIED_REVOKED%%'" in sql
    assert "revocation_status LIKE 'FAIL_CLOSED%%'" in sql
    assert "OR revoked_at IS NOT NULL" in sql
    assert "THEN 'BLOCKED_REVOKED'" in sql
    assert "ELSE 'BLOCKED_AUTHORIZATION'" in sql



def test_terminal_revocation_still_materializes_task_audit_causal_chain_without_replan():
    orch = CtiSubsystemOrchestrator(db=QueueOnlyDb(), registry=AlwaysOnRegistry())
    runtime = MissionRuntime(
        mission_id="mission-race-2861",
        plan_id="plan-race-2861",
        versions=RuntimeVersions(state_version=2, plan_version=1, policy_version="1"),
        scan_payload={},
        mission_context={},
        policy_context={"scope_allowed": True},
        status="FAILED",
    )
    orch._runtimes[runtime.mission_id] = runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("terminal revocation audit projection must not replan or reschedule")

    orch._replan = forbidden
    orch._schedule_pipeline_advance = forbidden

    ingress = {
        "event_id": "event-ingress-2861",
        "event_type": "AUTHORIZATION_REVOKED",
        "source_component": "GOV-PLANE",
        "mission_id": runtime.mission_id,
        "upstream_event_id": "gevent-race-2861",
        "payload": {
            "cti_revocation_projection": {
                "mode": "POLICY_DECISION",
                "revocation_id": "grevoke-race-2861",
                "decision_id": "gdec-race-2861",
                "verification_status": "VERIFIED_REVOKED",
                "reason": "race acceptance revoke",
                "active_affected_count": 1,
                "tasks": [
                    {
                        "task_id": "task-race-2861",
                        "prior_status": "COMMITTED",
                        "assigned_component": "cti_acquisition_freshness_agent",
                        "trace_id": "acqdec-race-2861",
                        "proposal_id": "acqdec-race-2861",
                        "policy_decision_id": "gdec-race-2861",
                        "authorization_request_id": "greq-race-2861",
                        "pre_dispatch_revalidation_id": None,
                    }
                ],
            }
        },
    }

    orch._on_reactive_trigger(ingress)
    events = _drain(orch)
    revoked = next(e for e in events if e["event_type"] == "TASK_AUTHORIZATION_REVOKED")
    blocked = next(e for e in events if e["event_type"] == "TASK_DISPATCH_BLOCKED")

    assert runtime.status == "FAILED"
    assert runtime.pending_reactive is None
    assert revoked["causation_event_id"] == "event-ingress-2861"
    assert revoked["upstream_event_id"] == "gevent-race-2861"
    assert revoked["task_id"] == "task-race-2861"
    assert revoked["policy_decision_id"] == "gdec-race-2861"
    assert blocked["causation_event_id"] == revoked["event_id"]
    assert blocked["upstream_event_id"] == "gevent-race-2861"
    assert blocked["task_id"] == "task-race-2861"



def test_terminal_fail_closed_projection_is_also_auditable():
    orch = CtiSubsystemOrchestrator(db=QueueOnlyDb(), registry=AlwaysOnRegistry())
    runtime = MissionRuntime(
        mission_id="mission-failclosed-2861",
        plan_id="plan-failclosed-2861",
        versions=RuntimeVersions(),
        scan_payload={}, mission_context={}, policy_context={}, status="FAILED",
    )
    orch._runtimes[runtime.mission_id] = runtime

    orch._on_reactive_trigger(
        {
            "event_id": "event-ingress-fc-2861",
            "event_type": "AUTHORIZATION_REVOKED",
            "source_component": "GOV-PLANE",
            "mission_id": runtime.mission_id,
            "upstream_event_id": "gevent-fc-2861",
            "payload": {
                "cti_revocation_projection": {
                    "mode": "POLICY_DECISION",
                    "revocation_id": "grevoke-fc-2861",
                    "decision_id": "gdec-fc-2861",
                    "verification_status": "FAIL_CLOSED_GOVERNANCE_UNAVAILABLE",
                    "reason": "authority unavailable",
                    "active_affected_count": 1,
                    "tasks": [
                        {
                            "task_id": "task-fc-2861",
                            "prior_status": "COMMITTED",
                            "assigned_component": "cti_acquisition_freshness_agent",
                            "trace_id": "acqdec-fc-2861",
                            "policy_decision_id": "gdec-fc-2861",
                            "authorization_request_id": "greq-fc-2861",
                        }
                    ],
                }
            },
        }
    )
    events = _drain(orch)
    assert [e["event_type"] for e in events] == [
        "TASK_AUTHORIZATION_REVOKED",
        "TASK_DISPATCH_BLOCKED",
    ]
    assert all(e["upstream_event_id"] == "gevent-fc-2861" for e in events)
