"""CSRF C6-C7 acceptance — gateway wiring (state-differential verdict, §7 A1-A5).

Membuktikan jalur verifikasi KEDUA terpasang di ``ActiveExploitationGateway``:
  * A1 — ``csrf-change-username`` → EXPLOITED via ``STATE_CHANGE_CONFIRMED`` pada
    ``username`` DENGAN scoreboard dinonaktifkan (bukti target-agnostic).
  * A2 — snapshot sesudah gagal → ``INCONCLUSIVE``, outcome BUKAN EXPLOITED.
  * A3 — perubahan atribut sama oleh baseline (kontrol) ter-mask → bukan EXPLOITED.
  * A4 — determinisme: observasi sama → segel evidence identik & verify hijau.
  * A5 — opt-in: tanpa ``state_observer``, csrf tetap jalur scoreboard lama.

Semua lewat transport/observer MOCK (loopback-only, tanpa jaringan nyata).
Run: python3 tests/test_csrf_c6c7_gateway_wiring.py  (atau via pytest)
"""
import copy
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import approval_broker as ab
from pentest_subsystem import active_exploitation_execution as ae
from pentest_subsystem import impact_verification as iv
from pentest_subsystem import state_observer as sob

AEC = ae.ACTION_CLASS_ACTIVE_EXPLOITATION
SM = ae.ACTION_CLASS_STATE_MUTATION
ENABLED = [AEC, SM]
_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


class _FakeJuice:
    """Mutable victim profile + (optionally disabled) csrf scoreboard flag.

    POST /profile mengubah ``username`` profil korban (dampak state nyata). State
    fetcher mengembalikan snapshot profil; ``fail_after`` membuat snapshot KEDUA
    gagal (mensimulasikan snapshot gagal / konteks tak terbukti → A2)."""

    def __init__(self, *, scoreboard_flips=False, fail_after=False):
        self.profile = {"status": "success", "data": {
            "id": 21, "username": "bender", "email": "bender@juice-sh.op",
            "preferred_language": "en", "theme": "bluegrey", "role": "customer",
            "updatedAt": "t0"}}
        self._scoreboard_flips = scoreboard_flips
        self._csrf_solved = False
        self._fail_after = fail_after
        self._snap_calls = 0
        self.calls = []

    def tr(self, d):
        self.calls.append((d["method"], d["url"]))
        u = d["url"]
        if u.endswith("/rest/user/login"):
            return {"authentication": {"token": "LAB.JWT", "bid": 6}}
        if u.rstrip("/").endswith("/profile"):
            new = (d.get("json") or {}).get("username")
            if new:
                self.profile["data"]["username"] = new
                self.profile["data"]["updatedAt"] = "t1"  # volatil: tak mencemari S
                if self._scoreboard_flips:
                    self._csrf_solved = True
            return {"status_code": 200}
        return {"status_code": 200}

    def ch(self):
        return {"data": [{"key": "csrfChallenge", "solved": self._csrf_solved}]}

    def state_fetcher(self, session_ref):
        self._snap_calls += 1
        if self._fail_after and self._snap_calls >= 2:
            raise sob.StateObservationError("victim profile unreachable (snapshot failed)")
        return copy.deepcopy(self.profile)


def _roe():
    return {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [AEC, SM],
        "allowed_http_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [SM],
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900},
    }


def _token(broker, primitive_id="csrf-change-username"):
    card = broker.request_approval(action_class=SM, primitive_id=primitive_id, target=_TARGET,
                                   http_method="POST", orchestration_id="o")
    return broker.approve(card["approval_id"], approver="alice")


def _run(js, *, state_observer=None, baseline=None):
    b = ab.ApprovalBroker()
    tok = _token(b)
    gw = ae.ActiveExploitationGateway(
        _roe(), transport=js.tr, oracle_fetcher=js.ch, approval_broker=b,
        enable_classes=ENABLED, state_observer=state_observer, state_baseline_provider=baseline)
    return gw.run_chain("o", _TARGET, ["csrf-change-username"],
                        parameters={"csrf-change-username": {"body": {"username": "xss-attacker"}}},
                        approval_tokens={SM: tok})


def _observer(js):
    return sob.juice_shop_state_observer(js.state_fetcher)


def _csrf_step(run):
    return [s for s in run["steps"] if s["primitive_id"] == "csrf-change-username"][0]


# ------------------------------- A1 ----------------------------------------
def test_a1_exploited_via_state_change_without_scoreboard():
    js = _FakeJuice(scoreboard_flips=False)  # scoreboard DISABLED
    run = _run(js, state_observer=_observer(js))
    step = _csrf_step(run)
    assert step["outcome"] == "EXPLOITED"
    assert step["state_verdict"] == iv.STATE_CHANGE_CONFIRMED
    assert run["solved_challenges"] == []          # nothing on the scoreboard
    assert step["scoreboard_solved"] is False      # corroborator absent, not required
    assert ae.verify_ae_run(run)


def test_a1_state_evidence_sealed_and_verifiable():
    js = _FakeJuice(scoreboard_flips=False)
    run = _run(js, state_observer=_observer(js))
    step = _csrf_step(run)
    ev = step["state_evidence"]
    assert ev["domain"] == iv.STATE_VERIFICATION_HASH_DOMAIN
    assert iv.verify_state_verification(ev)
    assert step["state_evidence_ref"] == ev["sha256"]
    # dampak nyata: username berubah di delta eksploit
    assert ev["delta_exploit"]["username"] == {"before": "bender", "after": "xss-attacker"}


def test_a1_scoreboard_corroborates_but_is_not_required():
    # Bila scoreboard JUGA menyala, verdict tetap dari state; korroborator dicatat.
    js = _FakeJuice(scoreboard_flips=True)
    run = _run(js, state_observer=_observer(js))
    step = _csrf_step(run)
    assert step["outcome"] == "EXPLOITED"
    assert step["state_verdict"] == iv.STATE_CHANGE_CONFIRMED
    assert step["scoreboard_solved"] is True       # corroborator present now


# ------------------------------- A2 ----------------------------------------
def test_a2_snapshot_failure_is_inconclusive_not_exploited():
    js = _FakeJuice(scoreboard_flips=False, fail_after=True)  # snapshot sesudah gagal
    run = _run(js, state_observer=_observer(js))
    step = _csrf_step(run)
    assert step["state_verdict"] == iv.INCONCLUSIVE
    assert step["outcome"] == "INCONCLUSIVE"
    assert step["outcome"] != "EXPLOITED"
    assert ae.verify_ae_run(run)


# ------------------------------- A3 ----------------------------------------
def test_a3_baseline_masks_change_not_exploited():
    js = _FakeJuice(scoreboard_flips=False)
    # baseline (kontrol same-origin terotorisasi) juga mengubah username
    baseline = lambda pid, ref: {"username": {"before": "bender", "after": "legit-rename"}}
    run = _run(js, state_observer=_observer(js), baseline=baseline)
    step = _csrf_step(run)
    assert step["state_verdict"] == iv.NO_STATE_CHANGE
    assert step["state_reason"] == "MASKED_BY_BASELINE"
    assert step["outcome"] != "EXPLOITED"


# ------------------------------- A4 ----------------------------------------
def test_a4_replay_determinism_of_state_evidence():
    ev1 = _csrf_step(_run(_FakeJuice(), state_observer=_observer(_FakeJuice())))["state_evidence"]
    ev2 = _csrf_step(_run(_FakeJuice(), state_observer=_observer(_FakeJuice())))["state_evidence"]
    assert ev1 == ev2
    assert iv.verify_state_verification(ev1)


# ------------------------------- A5 ----------------------------------------
def test_a5_opt_in_without_observer_uses_legacy_scoreboard_path():
    # Tanpa state_observer: perilaku lama (scoreboard) tak berubah, aditif.
    js = _FakeJuice(scoreboard_flips=True)
    run = _run(js, state_observer=None)
    step = _csrf_step(run)
    assert step["outcome"] == "EXPLOITED"          # via scoreboard (jalur lama)
    assert "csrfChallenge" in run["solved_challenges"]
    assert "state_verdict" not in step             # jalur state tak aktif


def test_a5_no_state_change_without_mutation_is_not_exploited():
    # Observer aktif tapi POST tak mengubah username (body kosong) -> NO_STATE_CHANGE.
    js = _FakeJuice(scoreboard_flips=False)
    b = ab.ApprovalBroker(); tok = _token(b)
    gw = ae.ActiveExploitationGateway(
        _roe(), transport=js.tr, oracle_fetcher=js.ch, approval_broker=b,
        enable_classes=ENABLED, state_observer=_observer(js))
    run = gw.run_chain("o", _TARGET, ["csrf-change-username"],
                       parameters={"csrf-change-username": {"body": {"nothing": "x"}}},
                       approval_tokens={SM: tok})
    step = _csrf_step(run)
    assert step["state_verdict"] == iv.NO_STATE_CHANGE
    assert step["outcome"] != "EXPLOITED"


def _run_all():
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); ok += 1
        except Exception:
            print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
