"""Stage 3.8.8: source-bound observability metrics and operator health.

The report describes the quality of a Mission's observability sources. It does
not report runtime liveness, Mission success, or permission to perform actions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping
from urllib.parse import quote

from .observability_diagnostics import (
    SOURCES, build_integrity_gap_consistency_diagnostics,
    verify_integrity_gap_consistency_diagnostics,
)
from .observability_trace import sha256_hex

SCHEMA_VERSION = "apts-observability-metrics-health-operator-diagnostics-v1"
HASH_DOMAIN = "MISSION_OBSERVABILITY_METRICS_HEALTH_OPERATOR_V1"
IDENTITY_PREFIX = "omhealth-"


def _identity(mission_id: str, trace_id: str) -> str:
    return IDENTITY_PREFIX + sha256_hex({
        "hash_domain": HASH_DOMAIN, "mission_id": mission_id, "trace_id": trace_id,
    })[:32]


def _counts(values: Any) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def build_observability_metrics_health(
    *, mission_id: str, trace_id: str, diagnostics: Mapping[str, Any],
    normalized_events: list[Mapping[str, Any]] | None,
    causal_graph: Mapping[str, Any] | None,
    decision_trace: Mapping[str, Any] | None,
    timeline: Mapping[str, Any] | None,
    live_projection: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Publish metrics only when the same verified sources pass Stage 3.8.7."""
    if not mission_id or not trace_id or not verify_integrity_gap_consistency_diagnostics(diagnostics):
        raise ValueError("invalid diagnostic report")
    if (diagnostics["mission_id"], diagnostics["trace_id"]) != (mission_id, trace_id):
        raise ValueError("cross-Mission diagnostic report rejected")
    source_bundle = dict(zip(SOURCES, (
        normalized_events, causal_graph, decision_trace, timeline, live_projection,
    )))
    expected = build_integrity_gap_consistency_diagnostics(
        mission_id=mission_id, trace_id=trace_id,
        source_errors=diagnostics["source_errors"], **source_bundle,
    )
    if expected != diagnostics:
        raise ValueError("diagnostics do not bind the supplied source snapshot")

    diag_status = diagnostics["status"]
    health_status = {"PASS": "HEALTHY", "FINDINGS": "DEGRADED",
                     "INDETERMINATE": "UNKNOWN"}[diag_status]
    health = {
        "status": health_status,
        "scope": "OBSERVABILITY_DATA_QUALITY_ONLY",
        "reason_code": {"PASS": "SOURCES_CONSISTENT",
                        "FINDINGS": "BLOCKING_DIAGNOSTIC_FINDINGS",
                        "INDETERMINATE": "REQUIRED_SOURCE_UNAVAILABLE"}[diag_status],
        "mission_success_asserted": False, "runtime_liveness_asserted": False,
        "authorization_granted": False,
    }
    findings = diagnostics["findings"]
    operator = {
        "status": "REVIEW_REQUIRED" if diag_status != "PASS" else "INFORMATIONAL",
        "source_status": dict(diagnostics["source_status"]),
        "unavailable_sources": [s for s in SOURCES if diagnostics["source_status"][s] == "UNAVAILABLE"],
        "failed_sources": [s for s in SOURCES if diagnostics["source_status"][s] == "FAIL"],
        "finding_count": len(findings),
        "blocking_finding_count": diagnostics["blocking_finding_count"],
        "finding_counts_by_category": _counts(f["category"] for f in findings),
        "finding_counts_by_code": _counts(f["code"] for f in findings),
        "items": [{
            "finding_id": f["finding_id"], "category": f["category"],
            "code": f["code"], "source": f["source"], "reference": f["reference"],
            "impact": "INFORMATIONAL" if f["category"] == "OBSERVATION" else "REVIEW_REQUIRED",
        } for f in findings],
        "diagnostics_path": "/api/missions/" + quote(mission_id, safe="") + "/observability-diagnostics",
        "automatic_repair_performed": False,
    }

    if diag_status == "PASS":
        # The diagnostics bind all five projections to this ledger. Counts of
        # overlapping decision categories are intentionally not additive.
        event_types = _counts(e["event_type"] for e in normalized_events)
        components = _counts(e["source_component"] for e in normalized_events)
        categories = _counts(category for entry in decision_trace["entries"]
                             for category in entry["categories"])
        live = {
            "mission_state": live_projection["mission"]["state"],
            "state_version": live_projection["mission"]["state_version"],
            "plan_version_count": live_projection["plan"]["version_count"],
            "planned_task_count": live_projection["tasks"]["total"],
            "completed_task_count": live_projection["tasks"]["completed"],
            "execution_dispatch_count": live_projection["execution"]["dispatch_count"],
            "execution_attempt_count": live_projection["execution"]["attempt_count"],
            "active_execution_attempt_count": live_projection["execution"]["active_attempt_count"],
            "adaptation_episode_count": live_projection["adaptation"]["episode_count"],
            "replan_commit_count": live_projection["adaptation"]["replan_commit_count"],
        }
        metrics = {
            "status": "AVAILABLE", "withheld_reason": None,
            "event_count": len(normalized_events),
            "event_counts_by_type": event_types,
            "event_counts_by_component": components,
            "decision_event_count": len(decision_trace["entries"]),
            "decision_category_counts": categories,
            "causal_node_count": causal_graph["node_count"],
            "causal_edge_count": causal_graph["edge_count"],
            "unresolved_external_causation_count": len(causal_graph["unresolved_external_causation_refs"]),
            "backward_timestamp_count": len(timeline["timestamp_anomalies"]),
            "first_event_at_utc": timeline["first_event_at_utc"],
            "last_event_at_utc": timeline["last_event_at_utc"],
            "live_snapshot": live,
        }
    else:
        # Null is distinct from a measured zero. A stale or broken projection
        # must not appear as an empty, healthy Mission to an operator.
        metrics = {
            "status": "WITHHELD", "withheld_reason": diag_status,
            "event_count": None, "event_counts_by_type": None,
            "event_counts_by_component": None, "decision_event_count": None,
            "decision_category_counts": None, "causal_node_count": None,
            "causal_edge_count": None, "unresolved_external_causation_count": None,
            "backward_timestamp_count": None, "first_event_at_utc": None,
            "last_event_at_utc": None, "live_snapshot": None,
        }

    core = {
        "schema_version": SCHEMA_VERSION, "report_id": _identity(mission_id, trace_id),
        "mission_id": mission_id, "trace_id": trace_id,
        "diagnostics_id": diagnostics["diagnostics_id"],
        "diagnostics_sha256": diagnostics["integrity"]["canonical_sha256"],
        "diagnostics_status": diag_status,
        "metrics": metrics, "observability_health": health,
        "operator_diagnostics": operator,
        "semantics": {
            "read_only": True, "deterministic": True, "restart_stable": True,
            "metric_scope": "CURRENT_MISSION_VERIFIED_SOURCE_PROJECTIONS",
            "source_timestamps_are_ordering_authority": False,
            "time_based_rates_inferred": False,
            "diagnostics_are_authorization": False, "authorization_performed": False,
            "governance_query_performed": False, "runtime_probe_performed": False,
            "external_network_io_performed": False, "telemetry_export_performed": False,
            "mission_state_transition_performed": False, "routing_performed": False,
            "delegation_performed": False, "dispatch_performed": False,
            "execution_attempt_created": False, "target_action_dispatch_performed": False,
            "target_actuation": False, "automatic_repair_performed": False,
            "database_migration_added": False, "durable_store_added": False,
        },
    }
    return {**core, "integrity": {"hash_domain": HASH_DOMAIN,
        "canonical_sha256": sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})}}


def verify_observability_metrics_health(report: Mapping[str, Any]) -> bool:
    try:
        core = dict(report)
        integrity = core.pop("integrity")
        status = core["diagnostics_status"]
        metrics, health, operator = core["metrics"], core["observability_health"], core["operator_diagnostics"]
        source_status = operator["source_status"]
        items = operator["items"]
        blocking = sum(item["impact"] == "REVIEW_REQUIRED" for item in items)
        return (
            core["schema_version"] == SCHEMA_VERSION
            and core["report_id"] == _identity(core["mission_id"], core["trace_id"])
            and status in ("PASS", "FINDINGS", "INDETERMINATE")
            and health["status"] == {"PASS": "HEALTHY", "FINDINGS": "DEGRADED",
                                     "INDETERMINATE": "UNKNOWN"}[status]
            and health["reason_code"] == {"PASS": "SOURCES_CONSISTENT",
                "FINDINGS": "BLOCKING_DIAGNOSTIC_FINDINGS",
                "INDETERMINATE": "REQUIRED_SOURCE_UNAVAILABLE"}[status]
            and health["scope"] == "OBSERVABILITY_DATA_QUALITY_ONLY"
            and health["mission_success_asserted"] is False
            and health["runtime_liveness_asserted"] is False
            and health["authorization_granted"] is False
            and metrics["status"] == ("AVAILABLE" if status == "PASS" else "WITHHELD")
            and metrics["withheld_reason"] == (None if status == "PASS" else status)
            and (status == "PASS" or all(metrics[field] is None for field in (
                "event_count", "event_counts_by_type", "event_counts_by_component",
                "decision_event_count", "decision_category_counts", "causal_node_count",
                "causal_edge_count", "unresolved_external_causation_count",
                "backward_timestamp_count", "first_event_at_utc", "last_event_at_utc", "live_snapshot")))
            and (status != "PASS" or (metrics["event_count"] == sum(metrics["event_counts_by_type"].values())
                == sum(metrics["event_counts_by_component"].values())
                and metrics["decision_event_count"] >= 0))
            and set(source_status) == set(SOURCES)
            and all(value in ("PASS", "FAIL", "UNAVAILABLE") for value in source_status.values())
            and (status != "PASS" or (all(value == "PASS" for value in source_status.values())
                                      and blocking == 0))
            and (status != "FINDINGS" or (blocking > 0 and "UNAVAILABLE" not in source_status.values()))
            and (status != "INDETERMINATE" or "UNAVAILABLE" in source_status.values())
            and operator["status"] == ("INFORMATIONAL" if status == "PASS" else "REVIEW_REQUIRED")
            and operator["unavailable_sources"] == [s for s in SOURCES if source_status[s] == "UNAVAILABLE"]
            and operator["failed_sources"] == [s for s in SOURCES if source_status[s] == "FAIL"]
            and operator["finding_count"] == len(items)
            and operator["blocking_finding_count"] == blocking
            and operator["finding_counts_by_category"] == _counts(i["category"] for i in items)
            and operator["finding_counts_by_code"] == _counts(i["code"] for i in items)
            and all(i["impact"] == ("INFORMATIONAL" if i["category"] == "OBSERVATION" else "REVIEW_REQUIRED")
                    for i in items)
            and operator["diagnostics_path"] == (
                "/api/missions/" + quote(core["mission_id"], safe="") + "/observability-diagnostics")
            and operator["automatic_repair_performed"] is False
            and all(core["semantics"][key] is expected for key, expected in (
                ("read_only", True), ("deterministic", True), ("time_based_rates_inferred", False),
                ("authorization_performed", False), ("dispatch_performed", False),
                ("target_actuation", False), ("automatic_repair_performed", False),
                ("database_migration_added", False), ("durable_store_added", False)))
            and integrity["hash_domain"] == HASH_DOMAIN
            and integrity["canonical_sha256"] == sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})
        )
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def canonical_observability_metrics_health_definition() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "identity_prefix": IDENTITY_PREFIX,
        "mode": "DETERMINISTIC_READ_ONLY_OBSERVABILITY_METRICS_HEALTH_OPERATOR_DIAGNOSTICS",
        "source": "VERIFIED_STAGE3_8_7_INTEGRITY_GAP_CONSISTENCY_DIAGNOSTICS_AND_BOUND_SOURCES",
        "health_scope": "OBSERVABILITY_DATA_QUALITY_ONLY",
        "health_status_values": ["HEALTHY", "DEGRADED", "UNKNOWN"],
        "untrusted_metrics_mode": "WITHHELD_NULL_NOT_ZERO",
        "timestamp_rate_inference": False,
        "persistence_mode": "DERIVED_NO_NEW_DURABLE_STORE",
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "runtime_side_effects": False,
    }
