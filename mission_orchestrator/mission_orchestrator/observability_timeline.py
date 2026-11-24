"""Stage 3.8.6: reconstruct a Mission timeline from verified read-only projections.

Ledger order is authoritative for the sequence. Event timestamps are observations:
equal or decreasing timestamps are reported, never used to reorder the ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .observability_causal_graph import verify_global_causal_lineage_graph
from .observability_decision_trace import verify_decision_governance_evidence_trace
from .observability_ingestion import HASH_DOMAIN as EVENT_HASH_DOMAIN
from .observability_ingestion import SCHEMA_VERSION as EVENT_SCHEMA_VERSION
from .observability_trace import sha256_hex

SCHEMA_VERSION = "apts-deterministic-mission-timeline-v1"
HASH_DOMAIN = "MISSION_DETERMINISTIC_TIMELINE_V1"
ENTRY_HASH_DOMAIN = "MISSION_DETERMINISTIC_TIMELINE_ENTRY_V1"
IDENTITY_PREFIX = "mtimeline-"
ENTRY_IDENTITY_PREFIX = "mtentry-"


def _identity(prefix: str, domain: str, material: Mapping[str, Any]) -> str:
    return prefix + sha256_hex({"hash_domain": domain, "material": dict(material)})[:32]


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("normalized event timestamp must be a UTC string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid normalized event timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("normalized event timestamp must be UTC")
    return parsed


def _microseconds(start: datetime, end: datetime) -> int:
    delta = end - start
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _verified_normalized_event(event: Mapping[str, Any], mission_id: str, trace_id: str) -> bool:
    try:
        core = dict(event)
        integrity = core.pop("integrity")
        return (
            core["schema_version"] == EVENT_SCHEMA_VERSION
            and core["mission_id"] == mission_id
            and core["trace_id"] == trace_id
            and isinstance(core["source_event_id"], str)
            and bool(core["source_event_id"])
            and isinstance(core["source_event_sha256"], str)
            and len(core["source_event_sha256"]) == 64
            and integrity["hash_domain"] == EVENT_HASH_DOMAIN
            and integrity["canonical_sha256"]
            == sha256_hex({"hash_domain": EVENT_HASH_DOMAIN, "core": core})
        )
    except (KeyError, TypeError, ValueError):
        return False


def build_deterministic_mission_timeline(
    *,
    mission_id: str,
    trace_id: str,
    normalized_events: list[Mapping[str, Any]],
    causal_graph: Mapping[str, Any],
    decision_trace: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind each ledger event to its causal node and Stage 3.8.5 annotations."""
    if not verify_global_causal_lineage_graph(causal_graph):
        raise ValueError("causal graph integrity verification failed")
    if not verify_decision_governance_evidence_trace(decision_trace):
        raise ValueError("decision trace integrity verification failed")
    if (causal_graph.get("mission_id"), causal_graph.get("trace_id")) != (mission_id, trace_id):
        raise ValueError("cross-mission or cross-trace causal graph rejected")
    if (decision_trace.get("mission_id"), decision_trace.get("trace_id")) != (mission_id, trace_id):
        raise ValueError("cross-mission or cross-trace decision trace rejected")
    if (decision_trace.get("causal_graph_id"), decision_trace.get("causal_graph_sha256")) != (
        causal_graph["graph_id"], causal_graph["integrity"]["canonical_sha256"]
    ):
        raise ValueError("decision trace and causal graph disagree")

    events_by_id: dict[str, Mapping[str, Any]] = {}
    for event in normalized_events:
        if not _verified_normalized_event(event, mission_id, trace_id):
            raise ValueError("normalized event integrity or scope verification failed")
        event_id = event["source_event_id"]
        if event_id in events_by_id:
            raise ValueError("duplicate normalized source event rejected")
        events_by_id[event_id] = event

    nodes = {n["source_event_id"]: n for n in causal_graph["nodes"] if n["node_type"] == "MISSION_EVENT"}
    if len(nodes) != len(normalized_events) or set(nodes) != set(events_by_id):
        raise ValueError("causal graph and normalized ledger disagree")
    if sum(n["node_type"] == "MISSION_ROOT" for n in causal_graph["nodes"]) != 1:
        raise ValueError("causal graph must have exactly one Mission root")
    edges = {(e["source_node_id"], e["target_node_id"], e["relation_type"]) for e in causal_graph["edges"]}
    annotations: dict[str, Mapping[str, Any]] = {}
    for annotation in decision_trace["entries"]:
        event_id = annotation["source_event_id"]
        event = events_by_id.get(event_id)
        if event_id in annotations or event is None or (
            annotation["source_event_sha256"] != event["source_event_sha256"]
            or annotation["causal_node_id"] != nodes[event_id]["node_id"]
            or annotation["event_type"] != event["event_type"]
            or annotation["occurred_at_utc"] != event["occurred_at_utc"]
        ):
            raise ValueError("decision trace entry disagrees with normalized ledger")
        annotations[event_id] = annotation

    timeline_id = _identity(IDENTITY_PREFIX, HASH_DOMAIN, {"mission_id": mission_id, "trace_id": trace_id})
    entries = []
    anomalies = []
    previous_at: datetime | None = None
    first_at: datetime | None = None
    seen_ids: set[str] = set()
    for index, event in enumerate(normalized_events):
        event_id = event["source_event_id"]
        node = nodes[event_id]
        if any(node[field] != event[source] for field, source in (
            ("source_event_sha256", "source_event_sha256"), ("event_type", "event_type"),
            ("source_component", "source_component"), ("occurred_at_utc", "occurred_at_utc"),
            ("parent_event_id", "parent_event_id"), ("causation_id", "causation_id"),
        )):
            raise ValueError("causal node and normalized event disagree")
        parent = event.get("parent_event_id")
        if parent and parent not in seen_ids:
            raise ValueError("non-causal timeline parent ordering rejected")
        parent_node_id = nodes[parent]["node_id"] if parent else causal_graph["root_node_id"]
        expected_edge = (parent_node_id, node["node_id"], "PARENT_EVENT" if parent else "MISSION_ROOT")
        if expected_edge not in edges:
            raise ValueError("causal parent edge missing from graph")
        causation = event.get("causation_id")
        causation_node_id = nodes[causation]["node_id"] if causation in seen_ids else None
        if causation in events_by_id and causation not in seen_ids and causation != parent:
            raise ValueError("non-causal timeline causation ordering rejected")
        if causation_node_id and causation != parent and (
            causation_node_id, node["node_id"], "CAUSATION_EVENT"
        ) not in edges:
            raise ValueError("causation edge missing from graph")
        if causation is None:
            causation_resolution = "NONE"
        elif causation_node_id:
            causation_resolution = "RESOLVED_EVENT"
        else:
            causation_resolution = "UNRESOLVED_EXTERNAL"

        at = _timestamp(event["occurred_at_utc"])
        if first_at is None:
            first_at = at
        delta_us = None if previous_at is None else _microseconds(previous_at, at)
        relation = ("FIRST" if delta_us is None else
                    "FORWARD" if delta_us > 0 else "SAME" if delta_us == 0 else "BACKWARD")
        if relation == "BACKWARD":
            anomalies.append({"sequence": index + 1, "source_event_id": event_id,
                              "type": "OBSERVED_TIMESTAMP_BACKWARD", "delta_us": delta_us})
        entry_core = {
            "schema_version": SCHEMA_VERSION,
            "sequence": index + 1,
            "entry_id": _identity(ENTRY_IDENTITY_PREFIX, ENTRY_HASH_DOMAIN, {
                "mission_id": mission_id, "trace_id": trace_id,
                "source_event_id": event_id, "source_event_sha256": event["source_event_sha256"]}),
            "source_event_id": event_id,
            "source_event_sha256": event["source_event_sha256"],
            "causal_node_id": node["node_id"],
            "parent_event_id": parent,
            "parent_node_id": parent_node_id,
            "causation_id": causation,
            "causation_node_id": causation_node_id,
            "causation_resolution": causation_resolution,
            "source_component": event["source_component"],
            "event_type": event["event_type"],
            "occurred_at_utc": event["occurred_at_utc"],
            "timestamp_relation_to_previous": relation,
            "observed_delta_from_previous_us": delta_us,
            "observed_elapsed_from_first_us": _microseconds(first_at, at),
            "state_version": event.get("state_version"),
            "plan_version": event.get("plan_version"),
            "policy_version": event.get("policy_version"),
            "decision_trace_categories": list(annotations[event_id]["categories"]) if event_id in annotations else [],
        }
        entries.append({**entry_core, "integrity": {"hash_domain": ENTRY_HASH_DOMAIN,
            "canonical_sha256": sha256_hex({"hash_domain": ENTRY_HASH_DOMAIN, "core": entry_core})}})
        seen_ids.add(event_id)
        previous_at = at

    core = {
        "schema_version": SCHEMA_VERSION,
        "timeline_id": timeline_id,
        "mission_id": mission_id, "trace_id": trace_id,
        "causal_graph_id": causal_graph["graph_id"],
        "causal_graph_sha256": causal_graph["integrity"]["canonical_sha256"],
        "decision_trace_id": decision_trace["trace_projection_id"],
        "decision_trace_sha256": decision_trace["integrity"]["canonical_sha256"],
        "ordering": "VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER",
        "event_count": len(entries),
        "first_event_at_utc": entries[0]["occurred_at_utc"] if entries else None,
        "last_event_at_utc": entries[-1]["occurred_at_utc"] if entries else None,
        "timestamp_anomalies": anomalies,
        "entries": entries,
        "semantics": {
            "read_only": True, "deterministic": True, "restart_stable": True,
            "timestamp_is_ordering_authority": False, "causal_order_preserved": True,
            "event_classification_is_authorization": False,
            "authorization_performed": False, "governance_query_performed": False,
            "runtime_probe_performed": False, "external_network_io_performed": False,
            "telemetry_export_performed": False, "mission_state_transition_performed": False,
            "routing_performed": False, "delegation_performed": False,
            "dispatch_performed": False, "execution_attempt_created": False,
            "target_action_dispatch_performed": False, "target_actuation": False,
            "database_migration_added": False, "durable_store_added": False,
        },
    }
    return {**core, "integrity": {"hash_domain": HASH_DOMAIN,
        "canonical_sha256": sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})}}


def verify_deterministic_mission_timeline(timeline: Mapping[str, Any]) -> bool:
    try:
        core = dict(timeline)
        integrity = core.pop("integrity")
        mission_id, trace_id = core["mission_id"], core["trace_id"]
        if core["schema_version"] != SCHEMA_VERSION or core["timeline_id"] != _identity(
            IDENTITY_PREFIX, HASH_DOMAIN, {"mission_id": mission_id, "trace_id": trace_id}
        ) or core["ordering"] != "VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER":
            return False
        entries = core["entries"]
        if core["event_count"] != len(entries) or len({e["source_event_id"] for e in entries}) != len(entries):
            return False
        if core["first_event_at_utc"] != (entries[0]["occurred_at_utc"] if entries else None):
            return False
        if core["last_event_at_utc"] != (entries[-1]["occurred_at_utc"] if entries else None):
            return False
        first_at = previous_at = None
        anomalies = []
        for index, entry in enumerate(entries):
            if entry["sequence"] != index + 1 or entry["schema_version"] != SCHEMA_VERSION:
                return False
            if entry["entry_id"] != _identity(ENTRY_IDENTITY_PREFIX, ENTRY_HASH_DOMAIN, {
                "mission_id": mission_id, "trace_id": trace_id,
                "source_event_id": entry["source_event_id"],
                "source_event_sha256": entry["source_event_sha256"]}):
                return False
            entry_core = dict(entry)
            entry_integrity = entry_core.pop("integrity")
            if entry_integrity["hash_domain"] != ENTRY_HASH_DOMAIN or entry_integrity["canonical_sha256"] != sha256_hex(
                {"hash_domain": ENTRY_HASH_DOMAIN, "core": entry_core}
            ):
                return False
            at = _timestamp(entry["occurred_at_utc"])
            if first_at is None:
                first_at = at
            delta_us = None if previous_at is None else _microseconds(previous_at, at)
            relation = ("FIRST" if delta_us is None else
                        "FORWARD" if delta_us > 0 else "SAME" if delta_us == 0 else "BACKWARD")
            if entry["observed_delta_from_previous_us"] != delta_us or entry["timestamp_relation_to_previous"] != relation:
                return False
            if entry["observed_elapsed_from_first_us"] != _microseconds(first_at, at):
                return False
            if relation == "BACKWARD":
                anomalies.append({"sequence": index + 1, "source_event_id": entry["source_event_id"],
                                  "type": "OBSERVED_TIMESTAMP_BACKWARD", "delta_us": delta_us})
            previous_at = at
        semantics = core["semantics"]
        if core["timestamp_anomalies"] != anomalies or any(semantics[key] is not expected for key, expected in (
            ("read_only", True), ("deterministic", True), ("causal_order_preserved", True),
            ("timestamp_is_ordering_authority", False), ("dispatch_performed", False),
            ("target_actuation", False), ("durable_store_added", False), ("database_migration_added", False),
        )):
            return False
        return integrity["hash_domain"] == HASH_DOMAIN and integrity["canonical_sha256"] == sha256_hex(
            {"hash_domain": HASH_DOMAIN, "core": core}
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def canonical_deterministic_mission_timeline_definition() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "identity_prefix": IDENTITY_PREFIX,
        "entry_identity_prefix": ENTRY_IDENTITY_PREFIX,
        "mode": "DETERMINISTIC_READ_ONLY_MISSION_TIMELINE_RECONSTRUCTION",
        "source": "VERIFIED_STAGE3_8_2_NORMALIZED_MISSION_EVENT_LEDGER",
        "causal_source": "VERIFIED_STAGE3_8_3_GLOBAL_CAUSAL_LINEAGE_GRAPH",
        "annotation_source": "VERIFIED_STAGE3_8_5_DECISION_GOVERNANCE_EVIDENCE_TRACE",
        "ordering": "VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER",
        "timestamp_mode": "OBSERVED_UTC_WITH_BACKWARD_TIMESTAMP_ANOMALIES",
        "persistence_mode": "DERIVED_NO_NEW_DURABLE_STORE",
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "runtime_side_effects": False,
    }
