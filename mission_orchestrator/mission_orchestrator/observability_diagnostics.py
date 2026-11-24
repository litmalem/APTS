"""Stage 3.8.7: read-only, source-bound Mission observability diagnostics.

An unresolved *external* causation reference is an observation, not proof of a
missing Mission event. Findings never confer authorization or repair a source.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .observability_causal_graph import (build_global_causal_lineage_graph,
                                         verify_global_causal_lineage_graph)
from .observability_decision_trace import (build_decision_governance_evidence_trace,
                                           verify_decision_governance_evidence_trace)
from .observability_live_projection import verify_live_mission_state_execution_projection
from .observability_timeline import (_verified_normalized_event,
                                     build_deterministic_mission_timeline,
                                     verify_deterministic_mission_timeline)
from .observability_trace import sha256_hex

SCHEMA_VERSION = "apts-integrity-gap-consistency-diagnostics-v1"
HASH_DOMAIN = "MISSION_OBSERVABILITY_DIAGNOSTICS_V1"
FINDING_HASH_DOMAIN = "MISSION_OBSERVABILITY_DIAGNOSTIC_FINDING_V1"
IDENTITY_PREFIX = "mdiag-"
FINDING_IDENTITY_PREFIX = "mdfinding-"
SOURCES = ("normalized_events", "causal_graph", "decision_trace", "timeline", "live_projection")


def _identity(prefix: str, domain: str, material: Mapping[str, Any]) -> str:
    return prefix + sha256_hex({"hash_domain": domain, "material": dict(material)})[:32]


def _finding(category: str, code: str, source: str, reference: str | None = None) -> dict[str, Any]:
    core = {"category": category, "code": code, "source": source, "reference": reference}
    return {"finding_id": _identity(FINDING_IDENTITY_PREFIX, FINDING_HASH_DOMAIN, core), **core}


def _required_shape(name: str, source: Mapping[str, Any]) -> bool:
    """A recomputed digest does not make an incomplete projection usable."""
    if name == "causal_graph":
        return (isinstance(source.get("nodes"), list)
                and all(n.get("node_type") in ("MISSION_ROOT", "MISSION_EVENT")
                        and (n.get("source_event_id") is None if n["node_type"] == "MISSION_ROOT"
                             else isinstance(n.get("source_event_id"), str) and bool(n["source_event_id"]))
                        for n in source["nodes"])
                and isinstance(source.get("unresolved_external_causation_refs"), list)
                and all(isinstance(ref.get("source_event_id"), str)
                        and isinstance(ref.get("causation_id"), str)
                        for ref in source["unresolved_external_causation_refs"]))
    if name == "decision_trace":
        return (isinstance(source.get("entries"), list)
                and all(isinstance(entry.get("source_event_id"), str)
                        and all(key in entry for key in (
                    "source_event_id", "source_event_sha256", "causal_node_id",
                    "event_type", "categories", "occurred_at_utc")) for entry in source["entries"])
                and isinstance(source.get("source_counts"), Mapping)
                and isinstance(source.get("source_bindings"), list)
                and all(isinstance(binding.get("source_kind"), str)
                        and isinstance(binding.get("source_ordinal"), int)
                        for binding in source["source_bindings"])
                and all(isinstance(value, int) and value >= 0 for value in source["source_counts"].values()))
    if name == "timeline":
        return (all(key in source for key in (
            "causal_graph_id", "causal_graph_sha256", "decision_trace_id", "decision_trace_sha256"))
            and all(all(key in entry for key in (
                "source_event_id", "source_event_sha256", "event_type", "source_component",
                "occurred_at_utc", "parent_event_id", "causation_id", "state_version",
                "plan_version", "policy_version")) for entry in source["entries"])
            and all("source_event_id" in anomaly for anomaly in source["timestamp_anomalies"]))
    if name == "live_projection":
        counts, head = source.get("source_counts"), source.get("causal_head")
        return (isinstance(counts, Mapping)
                and all(key in counts for key in (
                    "normalized_event_count", "causal_graph_node_count", "causal_graph_edge_count"))
                and (head is None or isinstance(head, Mapping) and all(key in head for key in (
                    "source_event_id", "source_event_sha256", "event_type", "graph_id", "graph_sha256"))))
    return False


def build_integrity_gap_consistency_diagnostics(
    *, mission_id: str, trace_id: str,
    normalized_events: list[Mapping[str, Any]] | None,
    causal_graph: Mapping[str, Any] | None,
    decision_trace: Mapping[str, Any] | None,
    timeline: Mapping[str, Any] | None,
    live_projection: Mapping[str, Any] | None,
    source_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Diagnose independently verified sources without treating failed inputs as facts."""
    if not mission_id or not trace_id:
        raise ValueError("Mission and trace identity are required")
    errors = dict(source_errors or {})
    if set(errors) - set(SOURCES) or any(not isinstance(value, str) or not value for value in errors.values()):
        raise ValueError("invalid source error inventory")
    sources: dict[str, Any] = dict(zip(SOURCES, (
        normalized_events, causal_graph, decision_trace, timeline, live_projection,
    )))
    findings: list[dict[str, Any]] = []
    source_status: dict[str, str] = {}
    for name, source in sources.items():
        if name in errors or source is None:
            source_status[name] = "UNAVAILABLE"
            findings.append(_finding("INTEGRITY", "SOURCE_UNAVAILABLE", name))
        elif name == "normalized_events":
            valid = isinstance(source, list) and all(
                isinstance(e, Mapping) and _verified_normalized_event(e, mission_id, trace_id)
                for e in source
            )
            source_status[name] = "PASS" if valid else "FAIL"
        else:
            verifier = {
                "causal_graph": verify_global_causal_lineage_graph,
                "decision_trace": verify_decision_governance_evidence_trace,
                "timeline": verify_deterministic_mission_timeline,
                "live_projection": verify_live_mission_state_execution_projection,
            }[name]
            try:
                valid = isinstance(source, Mapping) and verifier(source) and _required_shape(name, source) and (
                    source.get("mission_id"), source.get("trace_id")
                ) == (mission_id, trace_id)
            except (TypeError, ValueError, KeyError, AttributeError):
                valid = False
            source_status[name] = "PASS" if valid else "FAIL"
        if source_status[name] == "FAIL":
            findings.append(_finding("INTEGRITY", "SOURCE_INTEGRITY_FAILED", name))

    if source_status["normalized_events"] == "PASS":
        if not normalized_events or normalized_events[0]["event_type"] != "MISSION_REGISTERED":
            findings.append(_finding("GAP", "MISSING_REGISTRATION_EVENT", "normalized_events"))
        event_ids = [event["source_event_id"] for event in normalized_events]
        counts = Counter(event_ids)
        for eid in sorted((eid for eid, count in counts.items() if count > 1), key=str):
            findings.append(_finding("INTEGRITY", "DUPLICATE_LEDGER_EVENT", "normalized_events", str(eid)))
        if any(not isinstance(eid, str) or not eid for eid in event_ids):
            findings.append(_finding("INTEGRITY", "INVALID_LEDGER_EVENT_ID", "normalized_events"))
        event_map = {event["source_event_id"]: event for event in normalized_events}
        for event in normalized_events:
            parent = event.get("parent_event_id")
            if parent and parent not in event_map:
                findings.append(_finding("GAP", "MISSING_PARENT_EVENT", "normalized_events", str(event["source_event_id"])))
        if len(event_map) == len(event_ids) and source_status["causal_graph"] == "PASS":
            graph_nodes = {node["source_event_id"]: node for node in causal_graph["nodes"]
                           if node["node_type"] == "MISSION_EVENT"}
            for eid in event_ids:
                if eid not in graph_nodes:
                    findings.append(_finding("GAP", "MISSING_CAUSAL_NODE", "causal_graph", eid))
            for eid in sorted(set(graph_nodes) - set(event_map)):
                findings.append(_finding("CONSISTENCY", "ORPHAN_CAUSAL_NODE", "causal_graph", eid))
            try:
                expected_graph = build_global_causal_lineage_graph(
                    mission_id=mission_id, trace_id=trace_id, normalized_events=normalized_events)
            except (ValueError, KeyError, TypeError):
                expected_graph = None  # Missing parents and invalid causal order are recorded separately.
            if expected_graph is not None and expected_graph != causal_graph:
                findings.append(_finding("CONSISTENCY", "GRAPH_LEDGER_DIVERGENCE", "causal_graph"))
        if len(event_map) == len(event_ids) and source_status["timeline"] == "PASS":
            entries = timeline["entries"]
            entry_ids = [e["source_event_id"] for e in entries]
            for eid in event_ids:
                if eid not in entry_ids:
                    findings.append(_finding("GAP", "MISSING_TIMELINE_EVENT", "timeline", eid))
            comparison_fields = ("source_event_sha256", "event_type", "source_component",
                                 "occurred_at_utc", "parent_event_id", "causation_id",
                                 "state_version", "plan_version", "policy_version")
            if entry_ids != event_ids or any(
                any(entry[field] != event.get(field) for field in comparison_fields)
                for entry, event in zip(entries, normalized_events)
            ):
                findings.append(_finding("CONSISTENCY", "TIMELINE_LEDGER_DIVERGENCE", "timeline"))
            if source_status["causal_graph"] == "PASS" and (
                timeline["causal_graph_id"] != causal_graph["graph_id"] or
                timeline["causal_graph_sha256"] != causal_graph["integrity"]["canonical_sha256"]
            ):
                findings.append(_finding("CONSISTENCY", "TIMELINE_GRAPH_BINDING_MISMATCH", "timeline"))
            if source_status["decision_trace"] == "PASS" and (
                timeline["decision_trace_id"] != decision_trace["trace_projection_id"] or
                timeline["decision_trace_sha256"] != decision_trace["integrity"]["canonical_sha256"]
            ):
                findings.append(_finding("CONSISTENCY", "TIMELINE_DECISION_BINDING_MISMATCH", "timeline"))
            if source_status["causal_graph"] == "PASS" and source_status["decision_trace"] == "PASS":
                try:
                    expected_timeline = build_deterministic_mission_timeline(
                        mission_id=mission_id, trace_id=trace_id, normalized_events=normalized_events,
                        causal_graph=causal_graph, decision_trace=decision_trace)
                except (ValueError, KeyError, TypeError):
                    expected_timeline = None  # Other findings retain the specific source failure.
                if expected_timeline is not None and expected_timeline != timeline:
                    findings.append(_finding("CONSISTENCY", "TIMELINE_SOURCE_DIVERGENCE", "timeline"))
        if source_status["decision_trace"] == "PASS" and source_status["causal_graph"] == "PASS":
            if (decision_trace["causal_graph_id"], decision_trace["causal_graph_sha256"]) != (
                causal_graph["graph_id"], causal_graph["integrity"]["canonical_sha256"]
            ):
                findings.append(_finding("CONSISTENCY", "DECISION_GRAPH_BINDING_MISMATCH", "decision_trace"))
            elif len(event_map) == len(event_ids) and set(event_map) == {
                node["source_event_id"] for node in causal_graph["nodes"] if node["node_type"] == "MISSION_EVENT"
            }:
                expected_entries = build_decision_governance_evidence_trace(
                    mission_id=mission_id, trace_id=trace_id, normalized_events=normalized_events,
                    causal_graph=causal_graph, sources={},
                )["entries"]
                actual_entries = decision_trace["entries"]
                expected_ids = {entry["source_event_id"] for entry in expected_entries}
                actual_ids = {entry["source_event_id"] for entry in actual_entries}
                for eid in sorted(expected_ids - actual_ids):
                    findings.append(_finding("GAP", "MISSING_DECISION_ANNOTATION", "decision_trace", eid))
                if actual_entries != expected_entries:
                    findings.append(_finding("CONSISTENCY", "DECISION_LEDGER_DIVERGENCE", "decision_trace"))
            binding_counts = Counter(b["source_kind"] for b in decision_trace["source_bindings"])
            if any(binding_counts.get(kind, 0) != count for kind, count in decision_trace["source_counts"].items()) or (
                set(binding_counts) - set(decision_trace["source_counts"])
            ) or any(
                b["source_ordinal"] != ordinal
                for kind in binding_counts
                for ordinal, b in enumerate(b for b in decision_trace["source_bindings"] if b["source_kind"] == kind)
            ):
                findings.append(_finding("CONSISTENCY", "DECISION_BINDING_COUNT_MISMATCH", "decision_trace"))
        if source_status["live_projection"] == "PASS":
            counts = live_projection["source_counts"]
            head = live_projection["causal_head"]
            expected_head = normalized_events[-1] if normalized_events else None
            if counts["normalized_event_count"] != len(normalized_events) or (
                (head is None) != (expected_head is None)
            ) or (head is not None and expected_head is not None and any(
                head[key] != expected_head[source] for key, source in (
                    ("source_event_id", "source_event_id"), ("source_event_sha256", "source_event_sha256"),
                    ("event_type", "event_type"),
                )
            )):
                findings.append(_finding("CONSISTENCY", "LIVE_LEDGER_DIVERGENCE", "live_projection"))
            if source_status["causal_graph"] == "PASS" and (
                counts["causal_graph_node_count"] != causal_graph["node_count"] or
                counts["causal_graph_edge_count"] != causal_graph["edge_count"] or
                (head is not None and (head["graph_id"] != causal_graph["graph_id"] or
                                       head["graph_sha256"] != causal_graph["integrity"]["canonical_sha256"]))
            ):
                findings.append(_finding("CONSISTENCY", "LIVE_GRAPH_DIVERGENCE", "live_projection"))

    if source_status["causal_graph"] == "PASS":
        for ref in causal_graph["unresolved_external_causation_refs"]:
            findings.append(_finding("OBSERVATION", "UNRESOLVED_EXTERNAL_CAUSATION", "causal_graph",
                                     str(ref["source_event_id"])))
    if source_status["timeline"] == "PASS":
        for anomaly in timeline["timestamp_anomalies"]:
            findings.append(_finding("OBSERVATION", "OBSERVED_TIMESTAMP_BACKWARD", "timeline",
                                     str(anomaly["source_event_id"])))

    # Each finding has a stable identity. Repeated external refs from the same event are one finding.
    findings = list({f["finding_id"]: f for f in findings}.values())
    blocking = [f for f in findings if f["category"] != "OBSERVATION"]
    status = "INDETERMINATE" if "UNAVAILABLE" in source_status.values() else (
        "FINDINGS" if blocking else "PASS")
    core = {
        "schema_version": SCHEMA_VERSION,
        "diagnostics_id": _identity(IDENTITY_PREFIX, HASH_DOMAIN, {"mission_id": mission_id, "trace_id": trace_id}),
        "mission_id": mission_id, "trace_id": trace_id,
        "status": status, "source_status": source_status,
        "source_errors": errors, "finding_count": len(findings),
        "blocking_finding_count": len(blocking), "findings": findings,
        "semantics": {"read_only": True, "deterministic": True, "restart_stable": True,
                      "external_causation_is_gap": False, "observed_timestamp_is_ordering_authority": False,
                      "diagnostics_are_authorization": False, "authorization_performed": False,
                      "governance_query_performed": False, "runtime_probe_performed": False,
                      "external_network_io_performed": False, "telemetry_export_performed": False,
                      "mission_state_transition_performed": False, "routing_performed": False,
                      "delegation_performed": False, "dispatch_performed": False,
                      "execution_attempt_created": False, "target_action_dispatch_performed": False,
                      "target_actuation": False, "database_migration_added": False,
                      "durable_store_added": False},
    }
    return {**core, "integrity": {"hash_domain": HASH_DOMAIN,
        "canonical_sha256": sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})}}


def verify_integrity_gap_consistency_diagnostics(report: Mapping[str, Any]) -> bool:
    try:
        core = dict(report)
        integrity = core.pop("integrity")
        findings = core["findings"]
        statuses = core["source_status"]
        blocking = sum(f["category"] != "OBSERVATION" for f in findings)
        expected = "INDETERMINATE" if "UNAVAILABLE" in statuses.values() else (
            "FINDINGS" if blocking else "PASS")
        return (
            core["schema_version"] == SCHEMA_VERSION
            and core["diagnostics_id"] == _identity(IDENTITY_PREFIX, HASH_DOMAIN, {
                "mission_id": core["mission_id"], "trace_id": core["trace_id"]})
            and set(statuses) == set(SOURCES)
            and set(core["source_errors"]) <= set(SOURCES)
            and all(value in ("PASS", "FAIL", "UNAVAILABLE") for value in statuses.values())
            and core["status"] == expected
            and core["finding_count"] == len(findings)
            and core["blocking_finding_count"] == blocking
            and len({f["finding_id"] for f in findings}) == len(findings)
            and all(f["finding_id"] == _identity(FINDING_IDENTITY_PREFIX, FINDING_HASH_DOMAIN, {
                k: f[k] for k in ("category", "code", "source", "reference")}) for f in findings)
            and all(core["semantics"][key] is expected for key, expected in (
                ("read_only", True), ("deterministic", True), ("diagnostics_are_authorization", False),
                ("dispatch_performed", False), ("target_actuation", False),
                ("durable_store_added", False), ("database_migration_added", False)))
            and integrity["hash_domain"] == HASH_DOMAIN
            and integrity["canonical_sha256"] == sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def canonical_integrity_gap_consistency_diagnostics_definition() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "identity_prefix": IDENTITY_PREFIX,
            "mode": "DETERMINISTIC_READ_ONLY_INTEGRITY_GAP_CONSISTENCY_DIAGNOSTICS",
            "sources": list(SOURCES), "status_values": ["PASS", "FINDINGS", "INDETERMINATE"],
            "finding_categories": ["INTEGRITY", "GAP", "CONSISTENCY", "OBSERVATION"],
            "external_causation_is_gap": False,
            "persistence_mode": "DERIVED_NO_NEW_DURABLE_STORE",
            "database_change_mode": "NO_NEW_DATABASE_MIGRATION", "runtime_side_effects": False}
