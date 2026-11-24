"""Coverage for the autonomous SEALED-CTI -> Enumeration delivery sweep.

Unit-level: `deliver()` takes an injected `pentest` service and a lightweight
`service` double, so no SQLite/orchestration fixtures are needed. The two
externally-imported collaborators (GSS scope fetch and the CTI context builder)
are patched at their source modules, matching how `deliver` imports them lazily.
"""
from unittest.mock import patch

from mission_orchestrator.canonical import sha256_hex
from mission_orchestrator.mission_cti_enumeration_delivery import deliver, enabled, sweep

SCOPE_SRC = {"scope": "committed"}
SNAPSHOT = sha256_hex(SCOPE_SRC)

DRAFT = {
    "orchestration_id": "paorch-1",
    "enumeration_request_draft": {
        "request_id": "enumreq-cti-abc",
        "schema_version": "apts-stage5.3-enumeration-run-request-v1",
    },
}


class FakeMission:
    """Minimal stand-in for the Mission orchestrator service."""

    def __init__(self, state="RUNNING", snapshot=SNAPSHOT, missions=None):
        self._state = state
        self._snapshot = snapshot
        self._missions = list(missions or [])
        self.listed = 0

    def get_mission_state(self, mission_id):
        return {"mission_state": {"state": self._state}}

    def get_mission_scope_contract(self, mission_id):
        return {"contract": {"metadata": {"gss_scope_sync": {"source_snapshot_sha256": self._snapshot}}}}

    def list_missions(self, state, limit, offset):
        self.listed += 1
        rows = [{"mission_id": m} for m in self._missions]
        return {"missions": rows if offset == 0 else [], "mission_count": len(rows)}


class FakePentest:
    """Minimal stand-in for EnumerationAgentService."""

    def __init__(self, runs, existing=None, run_result=None):
        self._runs = runs
        self._existing = existing
        self._run_result = run_result or {
            "status": "completed", "created": True,
            "run": {"enumeration_run_id": "enumrun-x"},
        }
        self.run_calls = []

    def list_recon_runs(self, mission_id, limit):
        return self._runs

    def get_orchestration_enumeration_run(self, orchestration_id):
        return self._existing

    def run_enumeration(self, orchestration_id, payload):
        self.run_calls.append((orchestration_id, payload))
        return self._run_result


def _run(status="COMPLETED", parent=None, rid="reconrun-1"):
    return {"recon_run_id": rid, "run_status": status, "parent_recon_run_id": parent}


def _patches(*, ctx_side_effect=None, ctx_return=DRAFT):
    fetch_patch = patch("mission_orchestrator.gss_scope_sync.fetch", lambda service, mid: SCOPE_SRC)
    if ctx_side_effect is not None:
        ctx_patch = patch(
            "pentest_subsystem.web_ui.cti_enumeration_context_for_recon_run",
            side_effect=ctx_side_effect,
        )
    else:
        ctx_patch = patch(
            "pentest_subsystem.web_ui.cti_enumeration_context_for_recon_run",
            return_value=ctx_return,
        )
    return fetch_patch, ctx_patch


def test_eligible_recon_run_is_submitted():
    pentest = FakePentest([_run()])
    fetch_patch, ctx_patch = _patches()
    with fetch_patch, ctx_patch:
        out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert len(pentest.run_calls) == 1
    assert pentest.run_calls[0][0] == "paorch-1"
    assert out[0]["status"] == "completed"
    assert out[0]["enumeration_run_id"] == "enumrun-x"
    assert out[0]["target_actuation"] is False
    assert out[0]["authorization_minted"] is False


def test_scope_change_defers_without_submit():
    pentest = FakePentest([_run()])
    fetch_patch, ctx_patch = _patches()
    with fetch_patch, ctx_patch:
        out = deliver(FakeMission(snapshot="deadbeef"), "mission-1", pentest=pentest)
    assert out == [{"status": "deferred", "reason": "GSS_SCOPE_CHANGED"}]
    assert pentest.run_calls == []


def test_mission_not_running_defers():
    pentest = FakePentest([_run()])
    out = deliver(FakeMission(state="CREATED"), "mission-1", pentest=pentest)
    assert out == [{"status": "deferred", "reason": "MISSION_NOT_RUNNING"}]
    assert pentest.run_calls == []


def test_missing_scope_source_defers():
    pentest = FakePentest([_run()])
    out = deliver(FakeMission(snapshot=None), "mission-1", pentest=pentest)
    assert out == [{"status": "deferred", "reason": "GSS_SCOPE_SOURCE_REQUIRED"}]
    assert pentest.run_calls == []


def test_existing_run_is_replayed_not_resubmitted():
    pentest = FakePentest([_run()], existing={"enumeration_run_id": "enumrun-x"})
    fetch_patch, ctx_patch = _patches()
    with fetch_patch, ctx_patch:
        out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert out[0]["status"] == "replayed"
    assert pentest.run_calls == []


def test_unsealed_or_unready_cti_waits():
    pentest = FakePentest([_run()])
    fetch_patch, ctx_patch = _patches(ctx_side_effect=ValueError("CTI evidence has no matching WPT handoff"))
    with fetch_patch, ctx_patch:
        out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert out[0]["status"] == "waiting"
    assert pentest.run_calls == []


def test_recon_iteration_is_not_a_candidate():
    pentest = FakePentest([_run(parent="reconrun-parent")])
    fetch_patch, ctx_patch = _patches()
    with fetch_patch, ctx_patch:
        out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert out == []
    assert pentest.run_calls == []


def test_incomplete_recon_run_is_skipped():
    pentest = FakePentest([_run(status="RUNNING")])
    fetch_patch, ctx_patch = _patches()
    with fetch_patch, ctx_patch:
        out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert out == []
    assert pentest.run_calls == []


def test_draft_mode_prepares_without_submit():
    pentest = FakePentest([_run()])
    fetch_patch, ctx_patch = _patches()
    with patch.dict("os.environ", {"APTS_CTI_ENUMERATION_DELIVERY_MODE": "draft"}):
        with fetch_patch, ctx_patch:
            out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert out[0]["status"] == "drafted"
    assert out[0]["request_id"] == "enumreq-cti-abc"
    assert pentest.run_calls == []


def test_sweep_is_noop_unless_enabled():
    mission = FakeMission(missions=["mission-1"])
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY", None)
        sweep(mission)
    assert mission.listed == 0
    assert enabled() is False


def test_sweep_enabled_calls_deliver_per_running_mission():
    mission = FakeMission(missions=["m1", "m2"])
    seen = []
    with patch.dict("os.environ", {"APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY": "1"}):
        with patch(
            "mission_orchestrator.mission_cti_enumeration_delivery.deliver",
            side_effect=lambda service, mid: seen.append(mid) or [],
        ):
            sweep(mission)
    assert seen == ["m1", "m2"]


def test_one_unavailable_context_does_not_starve_next_candidate():
    from urllib.error import URLError
    pentest = FakePentest([_run(rid="reconrun-1"), _run(rid="reconrun-2")])
    fetch_patch, ctx_patch = _patches(ctx_side_effect=[URLError("CTI unavailable"), DRAFT])
    with fetch_patch, ctx_patch:
        out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert [row["status"] for row in out] == ["waiting", "completed"]
    assert "CTI unavailable" in out[0]["reason"]
    assert len(pentest.run_calls) == 1


def test_conflicting_submission_does_not_starve_next_candidate():
    pentest = FakePentest([_run(rid="reconrun-1"), _run(rid="reconrun-2")])
    fetch_patch, ctx_patch = _patches()
    from pentest_subsystem.enumeration import EnumerationAgentConflict
    with fetch_patch, ctx_patch, patch.object(pentest, "run_enumeration", side_effect=[
        EnumerationAgentConflict("subtask blocked"), pentest._run_result
    ]):
        out = deliver(FakeMission(), "mission-1", pentest=pentest)
    assert [row["status"] for row in out] == ["deferred", "completed"]
