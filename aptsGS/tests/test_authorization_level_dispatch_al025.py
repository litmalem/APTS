"""AL-025 wiring to GSS dispatch (A1): level gate guard + repo persistence.

Two layers:
  * fake in-memory repo — exercises the `GovernanceService` level guard and the
    issue/downgrade/reauthorize lifecycle without SQL plumbing;
  * real sqlite — exercises the actual repository SQL (DDL portability, supersede).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.authorization_level import build_authorization_level_grant, verify_authorization_level_grant
from app.governance_service import GovernanceError, GovernanceService
from app.repositories import GovernanceRepository
from app.db import Db

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
YEAR = timedelta(days=365)
MISSION, SCOPE = "mission-al025", "scope-al025"


class _Capture:
    def record(self, *a, **k): pass
    def publish(self, *a, **k): return "evt"
    def obligations(self, *a, **k): return []


class FakeRepo:
    """Minimal in-memory grant store matching the repo's level-grant interface."""
    def __init__(self):
        self.grants: list[dict] = []
        self.transitions: list[dict] = []
    def ensure_authorization_level_schema(self): pass
    def save_level_grant(self, grant):
        for g in self.grants:
            if g["mission_id"] == grant["mission_id"] and g["scope_contract_id"] == grant["scope_contract_id"] and g["status"] == "ACTIVE":
                g["status"] = "SUPERSEDED"
        self.grants.append(dict(grant))
        return grant
    def get_active_level_grant(self, *, mission_id, scope_contract_id):
        for g in reversed(self.grants):
            if g["mission_id"] == mission_id and g["scope_contract_id"] == scope_contract_id and g["status"] == "ACTIVE":
                return dict(g)
        return None
    def save_level_transition(self, transition, *, transition_id, mission_id, scope_contract_id):
        self.transitions.append({"transition_id": transition_id, **transition})
        return transition


def _service(repo):
    svc = GovernanceService(repo)
    svc.audit = _Capture(); svc.events = _Capture(); svc.compliance = _Capture()
    return svc


def _req(level=None):
    ctx = {} if level is None else {"autonomy_level_required": level}
    return SimpleNamespace(mission_id=MISSION, scope_contract_id=SCOPE, context=ctx)


def _scope():
    return {"scope_contract_id": SCOPE, "mission_id": MISSION}


def _grant(level, **kw):
    return build_authorization_level_grant(
        grant_id="g1", mission_id=MISSION, scope_contract_id=SCOPE, authorized_level=level,
        approver="human:ciso", authorization_reference="dec-1",
        valid_from=kw.get("valid_from", NOW - timedelta(days=1)),
        valid_until=kw.get("valid_until", NOW + YEAR),
        status=kw.get("status", "ACTIVE"),
        requires_reauthorization=kw.get("requires_reauthorization", False),
    )


# --- guard behavior -----------------------------------------------------------

def test_guard_noop_when_request_declares_no_level():
    repo = FakeRepo(); repo.save_level_grant(_grant(2))
    assert _service(repo)._level_gate_denials(_req(None), _scope(), {"active": 0}) == []


def test_guard_noop_when_repo_has_no_grant_store():
    class Bare: pass
    assert _service(Bare())._level_gate_denials(_req(4), _scope(), {"active": 0}) == []


def test_guard_allows_in_ceiling_level():
    repo = FakeRepo(); repo.save_level_grant(_grant(3))
    assert _service(repo)._level_gate_denials(_req(3), _scope(), {"active": 0}) == []


def test_guard_denies_above_ceiling():
    repo = FakeRepo(); repo.save_level_grant(_grant(2))
    codes = _service(repo)._level_gate_denials(_req(4), _scope(), {"active": 0})
    assert codes == ["LEVEL_AUTHORIZATION_FAILED:LEVEL-CEILING"]


def test_guard_denies_when_no_grant_present():
    codes = _service(FakeRepo())._level_gate_denials(_req(1), _scope(), {"active": 0})
    assert "LEVEL_AUTHORIZATION_FAILED:GRANT-INTEGRITY" in codes


def test_guard_denies_expired_grant():
    repo = FakeRepo(); repo.save_level_grant(_grant(4, valid_until=NOW - timedelta(days=1), valid_from=NOW - 2 * YEAR))
    codes = _service(repo)._level_gate_denials(_req(1), _scope(), {"active": 0})
    assert "LEVEL_AUTHORIZATION_FAILED:GRANT-WINDOW" in codes


def test_guard_denies_under_emergency_stop():
    repo = FakeRepo(); repo.save_level_grant(_grant(4))
    codes = _service(repo)._level_gate_denials(_req(1), _scope(), {"active": 1})
    assert "LEVEL_AUTHORIZATION_FAILED:EMERGENCY-STOP" in codes


def test_guard_fail_closed_on_bad_level_value():
    repo = FakeRepo(); repo.save_level_grant(_grant(3))
    codes = _service(repo)._level_gate_denials(_req("not-an-int"), _scope(), {"active": 0})
    assert codes == ["LEVEL_AUTHORIZATION_FAILED:GRANT-INTEGRITY"]


# --- lifecycle via service ----------------------------------------------------

def test_issue_then_downgrade_then_reauthorize_flow():
    repo = FakeRepo(); svc = _service(repo)
    issued = svc.issue_authorization_level_grant(
        mission_id=MISSION, scope_contract_id=SCOPE, authorized_level=4,
        approver="human:ciso", authorization_reference="dec-1")
    assert verify_authorization_level_grant(issued) and issued["authorized_level"] == 4
    assert svc._level_gate_denials(_req(4), _scope(), {"active": 0}) == []

    downgraded = svc.downgrade_authorization_level(
        mission_id=MISSION, scope_contract_id=SCOPE, signal="DEGRADE", to_level=2)
    assert downgraded["authorized_level"] == 2 and downgraded["requires_reauthorization"] is True
    assert svc._level_gate_denials(_req(3), _scope(), {"active": 0}) == ["LEVEL_AUTHORIZATION_FAILED:LEVEL-CEILING"]
    assert svc._level_gate_denials(_req(2), _scope(), {"active": 0}) == []
    assert repo.transitions and repo.transitions[-1]["transition_type"] == "DOWNGRADE"

    reauth = svc.reauthorize_authorization_level(
        mission_id=MISSION, scope_contract_id=SCOPE, approver="human:ciso",
        authorized_level=3, authorization_reference="dec-2")
    assert reauth["authorized_level"] == 3 and reauth["requires_reauthorization"] is False
    assert svc._level_gate_denials(_req(3), _scope(), {"active": 0}) == []


def test_downgrade_without_grant_raises():
    with pytest.raises(GovernanceError):
        _service(FakeRepo()).downgrade_authorization_level(
            mission_id=MISSION, scope_contract_id=SCOPE, signal="HALT", to_level=1)


# --- real sqlite persistence (DDL portability + supersede) --------------------

@pytest.fixture
def sqlite_repo(tmp_path):
    path = tmp_path / "gov_level.sqlite3"
    sqlite3.connect(str(path)).close()  # bootstrap empty DB (connect uses mode=rw)
    repo = GovernanceRepository(Db({"driver": "sqlite", "path": str(path)}))
    repo.ensure_authorization_level_schema()
    return repo


def test_sqlite_save_and_get_active_grant(sqlite_repo):
    repo = sqlite_repo
    repo.save_level_grant(_grant(3))
    got = repo.get_active_level_grant(mission_id=MISSION, scope_contract_id=SCOPE)
    assert got is not None
    assert got["authorized_level"] == 3
    assert verify_authorization_level_grant(got) is True  # survives JSON round-trip, hash intact


def test_sqlite_save_supersedes_prior_active(sqlite_repo):
    repo = sqlite_repo
    repo.save_level_grant(build_authorization_level_grant(
        grant_id="g-old", mission_id=MISSION, scope_contract_id=SCOPE, authorized_level=4,
        approver="h", authorization_reference="d", valid_from=NOW - timedelta(days=1), valid_until=NOW + YEAR))
    repo.save_level_grant(build_authorization_level_grant(
        grant_id="g-new", mission_id=MISSION, scope_contract_id=SCOPE, authorized_level=2,
        approver="h", authorization_reference="d", valid_from=NOW - timedelta(days=1), valid_until=NOW + YEAR))
    got = repo.get_active_level_grant(mission_id=MISSION, scope_contract_id=SCOPE)
    assert got["grant_id"] == "g-new" and got["authorized_level"] == 2


def test_sqlite_get_returns_none_for_unknown_mission(sqlite_repo):
    assert sqlite_repo.get_active_level_grant(mission_id="nope", scope_contract_id=SCOPE) is None
