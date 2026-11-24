"""Read-only decision, governance and evidence trace derived from verified sources."""
from __future__ import annotations

from typing import Any, Mapping

from .observability_trace import sha256_hex

SCHEMA_VERSION = "apts-decision-governance-evidence-trace-v1"
HASH_DOMAIN = "MISSION_DECISION_GOVERNANCE_EVIDENCE_TRACE_V1"
IDENTITY_PREFIX = "dgetrace-"


def build_decision_governance_evidence_trace(*, mission_id: str, trace_id: str,
    normalized_events: list[Mapping[str, Any]], causal_graph: Mapping[str, Any],
    sources: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, Any]:
    if causal_graph.get("mission_id") != mission_id or causal_graph.get("trace_id") != trace_id:
        raise ValueError("cross-mission causal graph rejected")
    if any(e.get("mission_id") != mission_id or e.get("trace_id") != trace_id for e in normalized_events):
        raise ValueError("cross-mission normalized event rejected")
    nodes = {n["source_event_id"]: n["node_id"] for n in causal_graph["nodes"] if n.get("source_event_id")}
    if set(nodes) != {e["source_event_id"] for e in normalized_events}:
        raise ValueError("causal graph and normalized ledger disagree")
    entries = []
    for event in normalized_events:
        event_type = str(event["event_type"]).upper()
        categories = [name for name, markers in (
            ("DECISION", ("DECISION", "ROUTE", "REPLAN")),
            ("GOVERNANCE", ("GOVERNANCE", "AUTHORIZ", "POLICY", "REVALIDAT")),
            ("EVIDENCE", ("EVIDENCE", "ARTIFACT", "RESULT_CAPTURE")),
        ) if any(marker in event_type for marker in markers)]
        if categories:
            entries.append({"source_event_id": event["source_event_id"],
                "source_event_sha256": event["source_event_sha256"],
                "causal_node_id": nodes[event["source_event_id"]],
                "event_type": event["event_type"], "categories": categories,
                "occurred_at_utc": event["occurred_at_utc"]})
    bindings = []
    for kind, records in sorted(sources.items()):
        for ordinal, record in enumerate(records):
            bindings.append({"source_kind": kind, "source_ordinal": ordinal,
                "record_sha256": sha256_hex(record)})
    core = {"schema_version": SCHEMA_VERSION,
        "trace_projection_id": IDENTITY_PREFIX + sha256_hex({"hash_domain": HASH_DOMAIN, "mission_id": mission_id, "trace_id": trace_id})[:32],
        "mission_id": mission_id, "trace_id": trace_id, "causal_graph_id": causal_graph["graph_id"],
        "causal_graph_sha256": causal_graph["integrity"]["canonical_sha256"],
        "entries": entries, "source_bindings": bindings,
        "source_counts": {kind: len(records) for kind, records in sorted(sources.items())},
        "semantics": {"read_only": True, "deterministic": True, "restart_stable": True,
            "event_classification_is_authorization": False, "governance_query_performed": False,
            "dispatch_performed": False, "target_actuation": False,
            "durable_store_added": False, "database_migration_added": False}}
    return {**core, "integrity": {"hash_domain": HASH_DOMAIN,
        "canonical_sha256": sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})}}


def verify_decision_governance_evidence_trace(projection: Mapping[str, Any]) -> bool:
    try:
        core = dict(projection)
        integrity = core.pop("integrity")
        return (core["schema_version"] == SCHEMA_VERSION
            and core["trace_projection_id"].startswith(IDENTITY_PREFIX)
            and core["semantics"]["read_only"] is True
            and core["semantics"]["dispatch_performed"] is False
            and integrity["hash_domain"] == HASH_DOMAIN
            and integrity["canonical_sha256"] == sha256_hex({"hash_domain": HASH_DOMAIN, "core": core}))
    except (KeyError, TypeError, ValueError):
        return False


def canonical_decision_governance_evidence_trace_definition() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "identity_prefix": IDENTITY_PREFIX,
        "mode": "DETERMINISTIC_READ_ONLY_DECISION_GOVERNANCE_EVIDENCE_TRACE",
        "persistence_mode": "DERIVED_NO_NEW_DURABLE_STORE",
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION", "runtime_side_effects": False}
