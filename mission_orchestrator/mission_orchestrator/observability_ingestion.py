"""Read-only normalization of verified Mission ledger events for observability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .observability_trace import sha256_hex

SCHEMA_VERSION = "apts-cross-subsystem-event-normalization-v1"
HASH_DOMAIN = "MISSION_OBSERVABILITY_NORMALIZED_EVENT_V1"


def normalize_event(event: Mapping[str, Any], trace_id: str) -> dict[str, Any]:
    """Normalize a verified event; never promote payload claims to source identity."""
    occurred = event["occurred_at"]
    parsed = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("event timestamp must carry a timezone")
    timestamp = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    source = str(event["source_component"]).strip()
    if not source:
        raise ValueError("event source component is required")
    core = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": event["mission_id"],
        "trace_id": trace_id,
        "source_component": source,
        "source_event_id": event["event_id"],
        "source_event_sha256": event["canonical_sha256"],
        "event_type": event["event_type"],
        "occurred_at_utc": timestamp,
        "correlation_id": event["correlation_id"],
        "causation_id": event.get("causation_id"),
        "parent_event_id": event.get("parent_event_id"),
        "state_version": event.get("state_version"),
        "plan_version": event.get("plan_version"),
        "policy_version": event.get("policy_version"),
    }
    return {**core, "integrity": {"hash_domain": HASH_DOMAIN, "canonical_sha256": sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})}}


def normalize_events(events: list[Mapping[str, Any]], mission_id: str, trace_id: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for event in events:
        if event["mission_id"] != mission_id:
            raise ValueError("cross-mission event rejected")
        if event["event_id"] in seen:
            raise ValueError("duplicate source event rejected")
        seen.add(event["event_id"])
    return [normalize_event(event, trace_id) for event in events]
