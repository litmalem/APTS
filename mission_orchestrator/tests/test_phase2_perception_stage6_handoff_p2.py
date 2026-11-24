"""P2 acceptance tests: the perception loop is closed to Stage 6.

A sealed perception decision that carries a proposal must be handed to the Stage-6
intake queue as a governed, non-executing, idempotent submission — instead of dying
in the perception store. Stop decisions and tampered decisions are refused
(fail-closed), and the submission executes nothing and mints no authorization.
"""
import sqlite3

import pytest

from pentest_subsystem.orchestration import perception_stage6_handoff as ho
from pentest_subsystem.orchestration.perception_action import decide, new_state

RECON_SURFACE = {"unprofiled_hosts": {"total": 4, "remaining": 4},
                 "unprofiled_ports": {"total": 4, "remaining": 4}}
RECON_ALLOWED = ["PASSIVE_DISCOVERY", "TCP_CONNECT_SCAN"]


class _FakeRepo:
    def __init__(self, db):
        self.sqlite_path = str(db)

    def initialize(self):
        pass

    def _connect(self):
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


def _proposal_decision():
    state = new_state("reconnaissance", RECON_SURFACE, budget=5)
    decision = decide(state, allowed_techniques=RECON_ALLOWED)
    assert decision["proposal"] is not None  # guard the fixture
    return decision


def _stop_decision():
    state = new_state("reconnaissance", RECON_SURFACE, budget=0)  # BUDGET_EXHAUSTED
    decision = decide(state, allowed_techniques=RECON_ALLOWED)
    assert decision["proposal"] is None
    return decision


# ---------------------------------------------------------------------------
# 1. A proposal decision builds a verifiable, non-executing submission.
# ---------------------------------------------------------------------------
def test_build_submission_is_governed_and_non_executing():
    decision = _proposal_decision()
    rec = ho.build_submission(decision=decision, orchestration_id="paorch-1",
                              run_ref="recon-1", event_id="sealed-abc")
    assert ho.verify_submission(rec)
    assert rec["stage6_intake"]["status"] == ho.STATUS_SUBMITTED
    assert rec["stage6_intake"]["proposal_target"] == "STAGE6"
    assert rec["proposal"]["technique"] == decision["proposal"]["technique"]
    assert rec["perception_decision_sha256"] == decision["record_sha256"]
    assert rec["run_ref"] == {"recon_run_id": "recon-1"}
    for key in ("execution_started", "authorization_minted", "target_actuation",
                "external_network_io_performed"):
        assert rec["semantics"][key] is False
    assert rec["authority"]["executes"] is False


# ---------------------------------------------------------------------------
# 2. Fail-closed: stop decisions and tampered decisions are refused.
# ---------------------------------------------------------------------------
def test_stop_decision_is_refused():
    with pytest.raises(ho.PerceptionHandoffError, match="no proposal"):
        ho.build_submission(decision=_stop_decision(), orchestration_id="paorch-1")


def test_tampered_decision_is_refused():
    decision = _proposal_decision()
    tampered = dict(decision)
    tampered["coverage"] = 0.123456  # breaks the sealed hash
    with pytest.raises(ho.PerceptionHandoffError, match="integrity"):
        ho.build_submission(decision=tampered, orchestration_id="paorch-1")


# ---------------------------------------------------------------------------
# 3. Queuing is idempotent per sealed decision; the queue is readable.
# ---------------------------------------------------------------------------
def test_submission_is_idempotent_and_readable(tmp_path):
    repo = _FakeRepo(tmp_path / "handoff.db")
    decision = _proposal_decision()

    first = ho.submit_perception_decision(repo, "paorch-1", decision, run_ref="recon-1")
    assert first["created"] is True
    second = ho.submit_perception_decision(repo, "paorch-1", decision, run_ref="recon-1")
    assert second["created"] is False  # same sealed decision => queued once

    pending = ho.pending_submissions(repo, "paorch-1")
    assert len(pending) == 1
    assert pending[0]["proposal"]["technique"] == decision["proposal"]["technique"]
    assert all(ho.verify_submission(p) for p in pending)


def test_persist_refuses_unverifiable_submission(tmp_path):
    repo = _FakeRepo(tmp_path / "handoff.db")
    rec = ho.build_submission(decision=_proposal_decision(), orchestration_id="paorch-1")
    rec["proposal"]["technique"] = "SOMETHING_ELSE"  # breaks the seal
    with pytest.raises(ho.PerceptionHandoffError):
        ho.persist_submission(repo, rec)


def test_verify_submission_detects_semantic_tampering():
    rec = ho.build_submission(decision=_proposal_decision(), orchestration_id="paorch-1")
    assert ho.verify_submission(rec)
    rec["semantics"]["execution_started"] = True
    assert not ho.verify_submission(rec)
