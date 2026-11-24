from __future__ import annotations

from types import SimpleNamespace

from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator
from cti_services.governance_correlation import (
    GOVERNANCE_CORRELATION_SCHEMA_V1,
    CrossSubsystemGovernanceCorrelator,
)
from cti_services.governance_client import GovernanceUnavailableError


class SnapshotClient:
    def __init__(self, snapshot=None, error=None):
        self.snapshot = snapshot
        self.error = error
        self.requested = []

    def get_mission_correlation_snapshot(self, mission_id: str):
        self.requested.append(mission_id)
        if self.error:
            raise self.error
        return self.snapshot


def _task_lineage():
    return {
        "projection_schema_version": "cti-lineage-projection-v1",
        "projection_scope": "TASK",
        "identity": {
            "mission_id": "mission-294",
            "task_id": "task-294",
            "trace_id": "trace-294",
            "proposal_id": "trace-294",
        },
        "task_contract": {
            "task_id": "task-294",
            "mission_id": "mission-294",
            "governance_subject_component": "CTI-A02",
            "governance_action_class": "CTI_SOURCE_READ",
            "governance_action_name": "INCREMENTAL_FETCH",
            "governance_resource_type": "CTI_SOURCE",
            "governance_resource_value": "nvd-cve",
        },
        "governance_binding": {
            "authorization_mode": "REQUIRED",
            "required_authority": True,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "policy_decision_id": "gdec-294",
            "authorization_request_id": "greq-294",
            "scope_contract_id": "scope-294",
            "scope_version": 3,
            "policy_set_id": "default-policy",
            "policy_version": "7",
            "policy_decision_hash": "a" * 64,
            "authorization_decision": "ALLOW",
            "authorization_governance_event_id": "gevent-294-1",
            "pre_dispatch_revalidation_id": "greval-294",
            "pre_dispatch_governance_event_id": "gevent-294-2",
            "revocation_id": "grevoke-294",
            "revocation_event_id": "gevent-294-3",
            "correlation_status": "NOT_EVALUATED_STAGE_2_9_4",
        },
        "lifecycle": {"canonical_state": "BLOCKED_REVOKED"},
        "events": [
            {
                "event_id": "cti-event-1",
                "event_type": "TASK_COMMITTED",
                "upstream_event_id": "gevent-294-1",
            },
            {
                "event_id": "cti-event-2",
                "event_type": "TASK_REVALIDATED",
                "upstream_event_id": "gevent-294-2",
            },
            {
                "event_id": "cti-event-3",
                "event_type": "TASK_AUTHORIZATION_REVOKED",
                "upstream_event_id": "gevent-294-3",
            },
        ],
        "causal_edges": [],
        "upstream_edges": [],
        "decision_traces": [],
        "audit_records": [],
        "projection_metadata": {"quality": "CANONICAL_V2"},
    }


def _snapshot():
    return {
        "schema_version": "governance-correlation-snapshot-v1",
        "mission_id": "mission-294",
        "authority": "aptsGSS",
        "authority_component": "GOV-PLANE",
        "scope_contracts": [
            {
                "scope_contract_id": "scope-294",
                "mission_id": "mission-294",
                "version": 3,
                "status": "ACTIVE",
            }
        ],
        "authorization_requests": [
            {
                "request_id": "greq-294",
                "mission_id": "mission-294",
                "scope_contract_id": "scope-294",
                "subject_component": "CTI-A02",
                "action_class": "CTI_SOURCE_READ",
                "action_name": "INCREMENTAL_FETCH",
                "resource_type": "CTI_SOURCE",
                "resource_value": "nvd-cve",
                "request_status": "ALLOW",
            }
        ],
        "policy_decisions": [
            {
                "decision_id": "gdec-294",
                "request_id": "greq-294",
                "mission_id": "mission-294",
                "scope_contract_id": "scope-294",
                "scope_version": 3,
                "policy_set_id": "default-policy",
                "policy_version": 7,
                "decision": "ALLOW",
                "decision_hash": "a" * 64,
                "decision_status": "REVOKED",
            }
        ],
        "events": [
            {
                "event_id": "gevent-294-1",
                "mission_id": "mission-294",
                "event_type": "POLICY_DECISION_ISSUED",
                "delivery_status": "DELIVERED",
                "payload": {
                    "decision_id": "gdec-294",
                    "request_id": "greq-294",
                    "mission_id": "mission-294",
                },
            },
            {
                "event_id": "gevent-294-2",
                "mission_id": "mission-294",
                "event_type": "POLICY_DECISION_REVALIDATED",
                "delivery_status": "DELIVERED",
                "payload": {
                    "decision_id": "gdec-294",
                    "request_id": "greq-294",
                    "mission_id": "mission-294",
                    "task_id": "task-294",
                    "revalidation_id": "greval-294",
                },
            },
            {
                "event_id": "gevent-294-3",
                "mission_id": "mission-294",
                "event_type": "AUTHORIZATION_REVOKED",
                "delivery_status": "DELIVERED",
                "payload": {
                    "decision_id": "gdec-294",
                    "request_id": "greq-294",
                    "mission_id": "mission-294",
                    "revocation_id": "grevoke-294",
                },
            },
        ],
        "audit_records": [],
    }


def _mission_projection():
    task = _task_lineage()
    return {
        "projection_schema_version": "cti-lineage-projection-v1",
        "projection_scope": "MISSION",
        "identity": {"mission_id": "mission-294"},
        "mission": {"mission_id": "mission-294", "status": "COMPLETED"},
        "lifecycle": {"mission_status": "COMPLETED"},
        "task_lineages": [task],
        "events": list(task["events"]),
        "causal_edges": [],
        "causal_order_event_ids": [],
        "root_event_ids": [],
        "decision_traces": [],
        "audit_records": [],
        "structural_facts": {},
        "projection_metadata": {
            "quality": "CANONICAL_V2",
            "governance_correlation_status": "NOT_EVALUATED_STAGE_2_9_4",
            "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
        },
    }


def test_task_correlation_matches_request_decision_scope_and_all_governance_events():
    client = SnapshotClient(snapshot=_snapshot())
    result = CrossSubsystemGovernanceCorrelator(client).correlate_task(_task_lineage())

    assert client.requested == ["mission-294"]
    assert result["governance_correlation"]["schema_version"] == GOVERNANCE_CORRELATION_SCHEMA_V1
    assert result["governance_correlation"]["status"] == "CORRELATED"
    assert result["governance_binding"]["correlation_status"] == "CORRELATED"
    task_corr = result["governance_correlation"]["task_correlation"]
    assert task_corr["coverage_complete"] is True
    assert task_corr["missing_required_reference_count"] == 0
    assert task_corr["mismatch_count"] == 0
    assert all(row["status"] in {"MATCH", "NOT_ASSERTED_OPTIONAL"} for row in task_corr["field_comparisons"])


def test_mission_correlation_reuses_one_authoritative_snapshot_and_correlates_external_event_edges():
    client = SnapshotClient(snapshot=_snapshot())
    result = CrossSubsystemGovernanceCorrelator(client).correlate_mission(_mission_projection())

    assert client.requested == ["mission-294"]
    corr = result["governance_correlation"]
    assert corr["status"] == "CORRELATED"
    assert corr["correlation_facts"]["governed_task_count"] == 1
    assert corr["correlation_facts"]["correlated_governed_task_count"] == 1
    assert corr["correlation_facts"]["external_event_reference_count"] == 3
    assert corr["correlation_facts"]["missing_external_event_count"] == 0
    assert result["projection_metadata"]["governance_correlation_status"] == "CORRELATED"
    assert result["projection_metadata"]["integrity_classification_status"] == "NOT_EVALUATED_STAGE_2_9_5"


def test_mismatch_is_reported_as_stage_2_9_4_correlation_fact_not_integrity_violation():
    snapshot = _snapshot()
    snapshot["policy_decisions"][0]["decision_hash"] = "b" * 64
    result = CrossSubsystemGovernanceCorrelator(SnapshotClient(snapshot=snapshot)).correlate_mission(_mission_projection())

    corr = result["governance_correlation"]
    assert corr["status"] == "PARTIAL"
    assert corr["correlation_facts"]["field_mismatch_count"] == 1
    assert corr["classification"] == "CORRELATION_FACTS_ONLY_STAGE_2_9_4"
    assert corr["integrity_classification_status"] == "NOT_EVALUATED_STAGE_2_9_5"
    assert "violation" not in corr


def test_governance_outage_preserves_local_lineage_and_reports_unavailable_without_inventing_authority():
    client = SnapshotClient(error=GovernanceUnavailableError("offline"))
    local = _mission_projection()
    result = CrossSubsystemGovernanceCorrelator(client).correlate_mission(local)

    assert result["identity"] == local["identity"]
    assert result["task_lineages"] == local["task_lineages"]
    assert result["governance_correlation"]["status"] == "UNAVAILABLE"
    assert result["projection_metadata"]["governance_correlation_status"] == "UNAVAILABLE"
    assert result["governance_correlation"]["integrity_classification_status"] == "NOT_EVALUATED_STAGE_2_9_5"


def test_internal_task_does_not_require_governance_records():
    task = _task_lineage()
    task["governance_binding"] = {
        "authorization_mode": "NOT_REQUIRED_INTERNAL",
        "required_authority": False,
        "correlation_status": "NOT_EVALUATED_STAGE_2_9_4",
    }
    snapshot = _snapshot()
    snapshot["authorization_requests"] = []
    snapshot["policy_decisions"] = []
    snapshot["scope_contracts"] = []
    snapshot["events"] = []
    result = CrossSubsystemGovernanceCorrelator(SnapshotClient(snapshot=snapshot)).correlate_task(task)
    assert result["governance_correlation"]["status"] == "NOT_REQUIRED_INTERNAL"


def test_orchestrator_control_version_is_stage_2_9_4():
    assert CtiSubsystemOrchestrator.CONTROL_VERSION == "hybrid-event-driven-2.17-health-diagnostics"
