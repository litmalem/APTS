"""A3 — operational 24/7 monitoring pipeline wiring.

Two layers:
  * FakeRepo — service `monitoring_snapshot` wiring: heartbeat/liveness, alert
    propagation, sealed snapshot;
  * real sqlite — the repo aggregation SQL (window counts, audit chain-break
    detection, heartbeat upsert) on the sqlite dialect.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.db import Db
from app.governance_service import GovernanceService
from app.oversight_attestation import verify_monitoring_snapshot
from app.repositories import GovernanceRepository


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class _Capture:
    def __init__(self): self.items = []
    def record(self, *a, **k): self.items.append((a, k))
    def publish(self, *a, **k): return "evt"
    def obligations(self, *a, **k): return []


class FakeMonitorRepo:
    def __init__(self, window):
        self._window = window
        self.heartbeat = None
        self.touched = []
    def monitoring_window(self, *, since):
        return dict(self._window)
    def read_monitoring_heartbeat(self):
        return dict(self.heartbeat) if self.heartbeat else None
    def touch_monitoring_heartbeat(self, *, sampled_at):
        self.touched.append(sampled_at)
        self.heartbeat = {"last_sample_at": sampled_at, "sample_count": len(self.touched)}


def _svc(repo):
    svc = GovernanceService(repo)
    svc.audit = _Capture(); svc.events = _Capture(); svc.compliance = _Capture()
    return svc


_CLEAN = {"total_decisions": 100, "ineligible": 10, "emergency_stops": 0,
          "integrity_failures": 0, "downgrades": 0}


# --- service wiring -----------------------------------------------------------

def test_first_sample_has_no_heartbeat_and_flags_stale():
    repo = FakeMonitorRepo(_CLEAN)
    snap = _svc(repo).monitoring_snapshot()
    assert snap["healthy"] is False
    assert "MONITORING_STALE" in snap["critical_alert_codes"]
    assert repo.touched  # heartbeat written for next tick
    assert verify_monitoring_snapshot(snap) is True


def test_recent_heartbeat_is_healthy():
    repo = FakeMonitorRepo(_CLEAN)
    repo.heartbeat = {"last_sample_at": _fmt(datetime.now(timezone.utc) - timedelta(seconds=30)),
                      "sample_count": 1}
    snap = _svc(repo).monitoring_snapshot()
    assert snap["healthy"] is True
    assert snap["alerts"] == []
    assert snap["window"]["heartbeat_gap_seconds"] is not None


def test_stale_heartbeat_gap_flags_critical():
    repo = FakeMonitorRepo(_CLEAN)
    repo.heartbeat = {"last_sample_at": _fmt(datetime.now(timezone.utc) - timedelta(hours=3)),
                      "sample_count": 1}
    snap = _svc(repo).monitoring_snapshot()
    assert "MONITORING_STALE" in snap["critical_alert_codes"]


def test_emergency_and_downgrade_propagate_to_snapshot():
    repo = FakeMonitorRepo({**_CLEAN, "emergency_stops": 1, "downgrades": 2})
    repo.heartbeat = {"last_sample_at": _fmt(datetime.now(timezone.utc) - timedelta(seconds=10)),
                      "sample_count": 1}
    snap = _svc(repo).monitoring_snapshot()
    codes = {a["code"] for a in snap["alerts"]}
    assert "EMERGENCY_STOP_ACTIVE" in codes and "AUTONOMY_DOWNGRADE" in codes
    assert snap["healthy"] is False


def test_snapshot_records_audit_entry():
    repo = FakeMonitorRepo(_CLEAN)
    svc = _svc(repo)
    svc.monitoring_snapshot()
    assert any(a[0] == ("MONITORING_SNAPSHOT",) for a in svc.audit.items)


# --- real sqlite aggregation --------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "mon.sqlite3"
    sqlite3.connect(str(path)).close()
    db = Db({"driver": "sqlite", "path": str(path)})
    db.execute("CREATE TABLE gov_policy_decisions (decision VARCHAR(16), created_at VARCHAR(40))")
    db.execute("CREATE TABLE gov_emergency_actions (action_type VARCHAR(16), created_at VARCHAR(40))")
    db.execute("CREATE TABLE gov_authorization_level_transition (transition_type VARCHAR(32), created_at VARCHAR(40))")
    db.execute("CREATE TABLE gov_audit_log (id INTEGER PRIMARY KEY, previous_hash VARCHAR(64), record_hash VARCHAR(64), created_at VARCHAR(40))")
    return GovernanceRepository(db)


def test_window_counts_only_rows_in_window(repo):
    now = datetime.now(timezone.utc)
    recent, old = _fmt(now), _fmt(now - timedelta(days=2))
    db = repo.db
    for dec, ts in [("ALLOW", recent), ("DENY", recent), ("DENY", recent), ("ALLOW", old)]:
        db.execute("INSERT INTO gov_policy_decisions (decision, created_at) VALUES (%(d)s, %(t)s)", {"d": dec, "t": ts})
    db.execute("INSERT INTO gov_emergency_actions (action_type, created_at) VALUES ('ACTIVATE', %(t)s)", {"t": recent})
    db.execute("INSERT INTO gov_emergency_actions (action_type, created_at) VALUES ('RELEASE', %(t)s)", {"t": recent})
    db.execute("INSERT INTO gov_authorization_level_transition (transition_type, created_at) VALUES ('DOWNGRADE', %(t)s)", {"t": recent})
    since = _fmt(now - timedelta(hours=1))
    w = repo.monitoring_window(since=since)
    assert w["total_decisions"] == 3   # old ALLOW excluded
    assert w["ineligible"] == 2
    assert w["emergency_stops"] == 1   # RELEASE not counted
    assert w["downgrades"] == 1
    assert w["integrity_failures"] == 0


def test_audit_chain_break_is_detected(repo):
    db = repo.db
    rows = [(1, None, "h1"), (2, "h1", "h2"), (3, "WRONG", "h3")]  # row 3 breaks linkage
    for i, prev, rec in rows:
        db.execute("INSERT INTO gov_audit_log (id, previous_hash, record_hash, created_at) VALUES (%(i)s,%(p)s,%(r)s,%(t)s)",
                   {"i": i, "p": prev, "r": rec, "t": _fmt(datetime.now(timezone.utc))})
    assert repo.audit_chain_breaks() == 1


def test_heartbeat_upsert_increments_count(repo):
    assert repo.read_monitoring_heartbeat() is None
    repo.touch_monitoring_heartbeat(sampled_at="2026-11-19 12:00:00")
    repo.touch_monitoring_heartbeat(sampled_at="2026-11-19 12:05:00")
    hb = repo.read_monitoring_heartbeat()
    assert hb["sample_count"] == 2
    assert hb["last_sample_at"] == "2026-11-19 12:05:00"
