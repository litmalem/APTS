"""CSRF C7 acceptance — Impact Verification diff/compare (+ INCONCLUSIVE).

Proves (fungsi murni, tanpa I/O), memetakan acceptance §7 desain:
  * ``diff`` = delta before→after, hanya atribut berubah, deterministik.
  * ``compare`` = STATE_CHANGE_CONFIRMED (A1), NO_STATE_CHANGE ter-mask baseline
    (A3), INCONCLUSIVE fail-closed (A2: snapshot kurang / atribut tak teramati /
    tak ada atribut-uji).
  * Segel delta+verdict (§6) domain ``APTS_CSRF_STATE_VERIFICATION_V1``, replay
    deterministik (A4) & tamper-evident.
  * ``verify_impact`` end-to-end atas state φ (snapshot gagal → INCONCLUSIVE).

Run: python3 tests/test_csrf_c7_impact_verification.py  (atau via pytest)
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import impact_verification as iv
from pentest_subsystem.boundary_contract import sha256_hex


# -------------------------------- diff -------------------------------------
def test_diff_reports_only_changed_attributes():
    s0 = {"username": "bender", "email": "a@b", "theme": "x"}
    s1 = {"username": "mallory", "email": "a@b", "theme": "x"}
    assert iv.diff(s0, s1) == {"username": {"before": "bender", "after": "mallory"}}


def test_diff_no_change_is_empty():
    s = {"username": "bender", "email": "a@b"}
    assert iv.diff(s, dict(s)) == {}


def test_diff_handles_appearing_and_disappearing_attribute():
    assert iv.diff({}, {"username": "x"}) == {"username": {"before": None, "after": "x"}}
    assert iv.diff({"username": "x"}, {}) == {"username": {"before": "x", "after": None}}


def test_diff_is_deterministic_regardless_of_key_order():
    a = iv.diff({"a": 1, "b": 2}, {"b": 2, "a": 9})
    b = iv.diff({"b": 2, "a": 1}, {"a": 9, "b": 2})
    assert a == b == {"a": {"before": 1, "after": 9}}


# ------------------------------ compare ------------------------------------
def test_compare_confirmed_exploit_only_change():
    # A1: username berubah di eksploit, tidak di baseline → CONFIRMED
    delta_b = {}
    delta_e = {"username": {"before": "bender", "after": "xss"}}
    v = iv.compare(delta_b, delta_e, attributes_under_test=["username"])
    assert v["verdict"] == iv.STATE_CHANGE_CONFIRMED
    assert v["confirmed_attributes"] == ["username"]


def test_compare_masked_by_baseline_is_no_change():
    # A3: perubahan username juga muncul pada baseline (same-origin terotorisasi)
    delta_b = {"username": {"before": "bender", "after": "newname"}}
    delta_e = {"username": {"before": "bender", "after": "xss"}}
    v = iv.compare(delta_b, delta_e, attributes_under_test=["username"])
    assert v["verdict"] == iv.NO_STATE_CHANGE
    assert v["reason"] == "MASKED_BY_BASELINE"


def test_compare_no_relevant_change():
    v = iv.compare({}, {}, attributes_under_test=["username"])
    assert v["verdict"] == iv.NO_STATE_CHANGE
    assert v["reason"] == "NO_RELEVANT_CHANGE"


def test_compare_ignores_changes_outside_attributes_under_test():
    # email berubah di eksploit tapi BUKAN atribut-uji → tak memicu CONFIRMED
    delta_e = {"email": {"before": "a@b", "after": "c@d"}}
    v = iv.compare({}, delta_e, attributes_under_test=["username"])
    assert v["verdict"] == iv.NO_STATE_CHANGE


def test_compare_empty_attributes_under_test_is_inconclusive():
    v = iv.compare({}, {"username": {"before": "x", "after": "y"}}, attributes_under_test=[])
    assert v["verdict"] == iv.INCONCLUSIVE
    assert v["reason"] == "NO_ATTRIBUTES_UNDER_TEST"


def test_compare_unobserved_attribute_is_inconclusive():
    # A2: atribut-uji tak teramati di snapshot → INCONCLUSIVE (bukan CONFIRMED)
    delta_e = {"username": {"before": "x", "after": "y"}}
    v = iv.compare(
        {}, delta_e, attributes_under_test=["username"], observed_attributes=["email", "theme"]
    )
    assert v["verdict"] == iv.INCONCLUSIVE
    assert v["reason"] == "ATTRIBUTE_NOT_OBSERVED"
    assert v["unobserved"] == ["username"]


def test_compare_confirmed_when_observed():
    delta_e = {"username": {"before": "x", "after": "y"}}
    v = iv.compare(
        {}, delta_e, attributes_under_test=["username"], observed_attributes=["username", "email"]
    )
    assert v["verdict"] == iv.STATE_CHANGE_CONFIRMED


# ------------------------------ sealing ------------------------------------
def test_seal_shape_domain_and_verification():
    delta_b, delta_e = {}, {"username": {"before": "x", "after": "y"}}
    verdict = iv.compare(delta_b, delta_e, attributes_under_test=["username"])
    sealed = iv.seal_state_verification(delta_b, delta_e, verdict)
    assert sealed["domain"] == iv.STATE_VERIFICATION_HASH_DOMAIN == "APTS_CSRF_STATE_VERIFICATION_V1"
    assert sealed["verdict"]["verdict"] == iv.STATE_CHANGE_CONFIRMED
    assert iv.verify_state_verification(sealed)
    expected = sha256_hex({"hash_domain": iv.STATE_VERIFICATION_HASH_DOMAIN, "core": {
        "schema_version": sealed["schema_version"],
        "delta_baseline": sealed["delta_baseline"],
        "delta_exploit": sealed["delta_exploit"],
        "verdict": sealed["verdict"],
    }})
    assert sealed["sha256"] == expected


def test_seal_replay_determinism():
    delta_b, delta_e = {}, {"username": {"before": "x", "after": "y"}}
    v = iv.compare(delta_b, delta_e, attributes_under_test=["username"])
    a = iv.seal_state_verification(delta_b, delta_e, v)
    b = iv.seal_state_verification(dict(delta_b), dict(delta_e), dict(v))
    assert a == b


def test_tampered_verdict_fails_verification():
    delta_b, delta_e = {}, {"username": {"before": "x", "after": "y"}}
    v = iv.compare(delta_b, delta_e, attributes_under_test=["username"])
    sealed = iv.seal_state_verification(delta_b, delta_e, v)
    tampered = dict(sealed, verdict=dict(sealed["verdict"], verdict=iv.NO_STATE_CHANGE))
    assert not iv.verify_state_verification(tampered)


# --------------------------- verify_impact e2e -----------------------------
_BEFORE = {"username": "bender", "email": "bender@juice-sh.op", "theme": "bluegrey"}


def test_verify_impact_confirmed_csrf_username_change():
    # A1 end-to-end: baseline inert, eksploit ubah username
    after = dict(_BEFORE, username="xss-attacker")
    sealed = iv.verify_impact(_BEFORE, dict(_BEFORE), _BEFORE, after,
                              attributes_under_test=["username"])
    assert sealed["verdict"]["verdict"] == iv.STATE_CHANGE_CONFIRMED
    assert iv.verify_state_verification(sealed)


def test_verify_impact_masked_by_baseline():
    # A3: baseline same-origin juga mengubah username → tidak CONFIRMED
    base_after = dict(_BEFORE, username="legit-rename")
    exp_after = dict(_BEFORE, username="xss")
    sealed = iv.verify_impact(_BEFORE, base_after, _BEFORE, exp_after,
                              attributes_under_test=["username"])
    assert sealed["verdict"]["verdict"] == iv.NO_STATE_CHANGE


def test_verify_impact_snapshot_failure_is_inconclusive():
    # A2: snapshot sesudah gagal → state kosong → atribut-uji tak teramati
    sealed = iv.verify_impact(_BEFORE, dict(_BEFORE), _BEFORE, {},
                              attributes_under_test=["username"])
    assert sealed["verdict"]["verdict"] == iv.INCONCLUSIVE
    assert sealed["verdict"]["reason"] == "ATTRIBUTE_NOT_OBSERVED"


def test_verify_impact_no_change_is_not_exploited():
    sealed = iv.verify_impact(_BEFORE, dict(_BEFORE), _BEFORE, dict(_BEFORE),
                              attributes_under_test=["username"])
    assert sealed["verdict"]["verdict"] == iv.NO_STATE_CHANGE


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
