"""P3 acceptance tests: AL-025 activation via a per-mission autonomy envelope.

Every capability now declares an autonomy_level_required, and a sealed per-mission
envelope (an AL-025-shaped grant, approved once) gates dispatch fail-closed: a
capability auto-proceeds only inside the envelope, else it is routed to review (or
denied on emergency/tamper). Wired into the Deliberative Dispatcher so level-gating
actually affects what runs.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from pentest_subsystem.orchestration import autonomy_envelope as ae
from pentest_subsystem.orchestration import deliberative_dispatcher as dd
from pentest_subsystem.orchestration.deliberation import CAPABILITY_SEQUENCE

PAST = "2020-01-01T00:00:00Z"
FUTURE = "2030-01-01T00:00:00Z"
NOW = "2026-01-01T00:00:00Z"


def _envelope(level=2, *, status=ae.GRANT_ACTIVE, valid_from=PAST, valid_until=FUTURE):
    return ae.build_autonomy_envelope(
        envelope_id="env-1", mission_id="m1", orchestration_id="paorch-1",
        scope_contract_id="scope-1", authorized_level=level, approver="human:ciso",
        authorization_reference="auth-ref-1", valid_from=valid_from, valid_until=valid_until,
        status=status)


# ---------------------------------------------------------------------------
# 1. Every capability declares autonomy_level_required (the missing input).
# ---------------------------------------------------------------------------
def test_every_capability_has_required_level():
    for cap in CAPABILITY_SEQUENCE:
        assert ae.required_level_for(cap) in ae.LEVELS
    with pytest.raises(ae.AutonomyEnvelopeError):
        ae.required_level_for("not_a_capability")


# ---------------------------------------------------------------------------
# 2. Envelope build/verify and in-envelope capability derivation.
# ---------------------------------------------------------------------------
def test_envelope_build_and_verify():
    env = _envelope(level=2)
    assert ae.verify_autonomy_envelope(env)
    assert "enumeration" in env["in_envelope_capabilities"]  # L2 required <= L2
    assert "exploitation" not in env["in_envelope_capabilities"]  # L3 required > L2
    env["authorized_level"] = 4  # tamper
    assert not ae.verify_autonomy_envelope(env)


# ---------------------------------------------------------------------------
# 3. Fail-closed evaluation: in-envelope / review / denied.
# ---------------------------------------------------------------------------
def test_in_envelope_when_level_sufficient():
    d = ae.evaluate_dispatch_envelope(_envelope(level=2), capability_id="enumeration", now=NOW)
    assert d["disposition"] == ae.DISPOSITION_IN_ENVELOPE
    assert d["in_envelope"] is True
    assert ae.verify_envelope_decision(d)


def test_review_required_when_level_exceeds_envelope():
    d = ae.evaluate_dispatch_envelope(_envelope(level=2), capability_id="exploitation", now=NOW)
    assert d["disposition"] == ae.DISPOSITION_REVIEW_REQUIRED
    assert "LEVEL-CEILING" in d["failed_rule_ids"]


def test_denied_on_emergency_stop():
    d = ae.evaluate_dispatch_envelope(_envelope(level=3), capability_id="exploitation",
                                      now=NOW, emergency_active=True)
    assert d["disposition"] == ae.DISPOSITION_DENIED
    assert "EMERGENCY-STOP" in d["failed_rule_ids"]


def test_missing_or_expired_envelope_is_fail_closed():
    denied = ae.evaluate_dispatch_envelope(None, capability_id="enumeration", now=NOW)
    assert denied["disposition"] == ae.DISPOSITION_DENIED  # no trustworthy envelope
    expired = ae.evaluate_dispatch_envelope(
        _envelope(level=2, valid_from="2020-01-01T00:00:00Z", valid_until="2021-01-01T00:00:00Z"),
        capability_id="enumeration", now=NOW)
    assert expired["disposition"] == ae.DISPOSITION_REVIEW_REQUIRED
    assert "ENVELOPE-WINDOW" in expired["failed_rule_ids"]


# ---------------------------------------------------------------------------
# 4. Dispatcher integration: the envelope gates driver invocation.
# ---------------------------------------------------------------------------
class _FakeRepo:
    def __init__(self, db):
        self.sqlite_path = str(db)

    def initialize(self):
        pass

    def _connect(self):
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


class _StubRuntime:
    def __init__(self, repo, deliberation):
        self.repo = repo
        self.service = SimpleNamespace(repository=repo)
        self._deliberation = deliberation

    def deliberate(self, oid, **kwargs):
        return {"deliberation": self._deliberation}


def _delib(cap):
    return {"cycle": 1, "status": "INTENTION_SELECTED", "record_sha256": "d" * 64,
            "options": [{"capability_id": cap, "sequence_index": CAPABILITY_SEQUENCE.index(cap),
                         "utility": 0.9}],
            "intention": {"capability_id": cap}}


@pytest.fixture(autouse=True)
def _no_bdi_migration(monkeypatch):
    monkeypatch.setattr(dd, "ensure_bdi_store", lambda repo: None)


def test_dispatch_proceeds_inside_envelope(tmp_path):
    repo = _FakeRepo(tmp_path / "d.db")
    runtime = _StubRuntime(repo, _delib("enumeration"))
    calls = []
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"enumeration": lambda s, o: calls.append(o) or {"status": "ok"}},
                           envelope=_envelope(level=2), now=NOW)["dispatch"]
    assert calls == ["paorch-1"]
    assert rec["dispatched"] is True
    assert rec["enacted"] is True
    assert rec["autonomy_envelope_decision"]["disposition"] == ae.DISPOSITION_IN_ENVELOPE
    assert rec["autonomy_level_required"] == 2
    assert dd.verify_dispatch_decision(rec)


def test_dispatch_blocked_by_envelope_routes_to_review(tmp_path):
    repo = _FakeRepo(tmp_path / "d.db")
    runtime = _StubRuntime(repo, _delib("exploitation"))
    calls = []
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"exploitation": lambda s, o: calls.append(o) or {"status": "ok"}},
                           envelope=_envelope(level=2), now=NOW)["dispatch"]  # L2 < required L3
    assert calls == []  # driver never invoked
    assert rec["dispatched"] is False
    assert rec["enacted"] is False
    assert rec["outcome"]["status"] == ae.DISPOSITION_REVIEW_REQUIRED
    assert rec["autonomy_envelope_decision"]["disposition"] == ae.DISPOSITION_REVIEW_REQUIRED
    assert dd.verify_dispatch_decision(rec)


def test_dispatch_without_envelope_is_unchanged(tmp_path):
    repo = _FakeRepo(tmp_path / "d.db")
    runtime = _StubRuntime(repo, _delib("exploitation"))
    calls = []
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"exploitation": lambda s, o: calls.append(o) or {"status": "ok"}})["dispatch"]
    assert calls == ["paorch-1"]  # no envelope -> prior behaviour
    assert rec["dispatched"] is True
    assert rec["autonomy_envelope_decision"] is None
