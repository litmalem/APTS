"""CSRF C6 acceptance — State Observer φ + snapshot (mock fetcher).

Proves, dengan fetcher MOCK (tanpa jaringan I/O nyata):
  * φ (``abstract``) = whitelist atribut projection, buang field volatil,
    kanonikalisasi; atribut tak teramati tidak dikarang (fail-closed).
  * ``snapshot`` hanya memanggil fetcher terinjeksi & meneruskan ``session_ref``.
  * Determinisme: observasi terekam yang sama -> ``S`` & segel identik (replay).
  * Segel snapshot (§6) ber-domain ``APTS_CSRF_STATE_SNAPSHOT_V1`` & verifiable.
  * Target Juice Shop (CSRF change-username): perubahan ``username`` tampak di ``S``.

Run: python3 tests/test_csrf_c6_state_observer.py  (atau via pytest)
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import state_observer as sob
from pentest_subsystem.boundary_contract import sha256_hex


# --------------------------- mock fetcher ----------------------------------
class _MockFetcher:
    """Mock state_fetcher: memetakan session_ref -> observasi mentah terekam.
    Mencatat tiap panggilan agar bisa diassert snapshot meneruskan session_ref."""

    def __init__(self, by_ref):
        self._by_ref = dict(by_ref)
        self.calls = []

    def __call__(self, session_ref):
        self.calls.append(session_ref)
        if session_ref not in self._by_ref:
            raise KeyError(f"no recorded observation for {session_ref!r}")
        return self._by_ref[session_ref]


_JUICE_VICTIM = {
    "status": "success",
    "data": {
        "id": 21,
        "username": "bender",
        "email": "bender@juice-sh.op",
        "preferred_language": "en",
        "theme": "bluegrey",
        "role": "customer",
        "updatedAt": "2026-11-24T10:00:00.000Z",  # volatil
        "createdAt": "2026-01-01T00:00:00.000Z",  # volatil
        "token": "eyJhbGciOi...",                 # volatil
        "deluxeToken": "nope",                     # bukan whitelist -> dibuang
    },
}


def _observer(by_ref):
    fetcher = _MockFetcher(by_ref)
    return sob.StateObserver(fetcher, projection=sob.JUICE_SHOP_USER_PROJECTION), fetcher


# ------------------------------- φ tests -----------------------------------
def test_phi_whitelists_and_drops_volatile():
    obs, _ = _observer({"victim": _JUICE_VICTIM})
    s = obs.abstract(_JUICE_VICTIM)
    assert s == {
        "username": "bender",
        "email": "bender@juice-sh.op",
        "preferred_language": "en",
        "theme": "bluegrey",
        "role": "customer",
    }
    # id/updatedAt/createdAt/token (volatil) + deluxeToken (non-whitelist) dibuang
    for dropped in ("id", "updatedAt", "createdAt", "token", "deluxeToken"):
        assert dropped not in s


def test_phi_unobserved_attribute_is_not_fabricated():
    obs, _ = _observer({"x": {}})
    partial = {"data": {"username": "only-this"}}
    s = obs.abstract(partial)
    assert s == {"username": "only-this"}  # email/theme/... tak dikarang


def test_phi_missing_root_yields_empty_state():
    obs, _ = _observer({"x": {}})
    assert obs.abstract({"status": "error"}) == {}   # root "data" absen
    assert obs.abstract(None) == {}                  # observasi kosong
    assert obs.abstract({"data": []}) == {}          # root bukan mapping


def test_phi_strips_volatile_recursively_in_nested_values():
    proj = {"observation_root": "data", "attributes": ["profile"]}
    obs = sob.StateObserver(lambda r: None, projection=proj)
    nested = {"data": {"profile": {"name": "x", "updatedAt": "t", "token": "k", "lang": "en"}}}
    assert obs.abstract(nested) == {"profile": {"lang": "en", "name": "x"}}


def test_phi_is_deterministic_regardless_of_key_order():
    obs, _ = _observer({"x": {}})
    a = {"data": {"username": "u", "email": "e", "theme": "t"}}
    b = {"data": {"theme": "t", "email": "e", "username": "u"}}
    assert obs.abstract(a) == obs.abstract(b)


# ---------------------------- snapshot tests -------------------------------
def test_snapshot_uses_injected_fetcher_and_passes_session_ref():
    obs, fetcher = _observer({"victim": _JUICE_VICTIM})
    raw = obs.snapshot("victim")
    assert raw is _JUICE_VICTIM
    assert fetcher.calls == ["victim"]  # session_ref diteruskan apa adanya


def test_snapshot_failure_raises_state_observation_error():
    obs, _ = _observer({"victim": _JUICE_VICTIM})
    try:
        obs.snapshot("absent")
    except sob.StateObservationError:
        pass
    else:
        raise AssertionError("expected StateObservationError on fetch failure")


def test_observe_combines_snapshot_and_phi():
    obs, fetcher = _observer({"victim": _JUICE_VICTIM})
    s = obs.observe("victim")
    assert s["username"] == "bender"
    assert fetcher.calls == ["victim"]


# ------------------------- sealing / determinism ---------------------------
def test_sealed_snapshot_shape_and_domain():
    obs, _ = _observer({"victim": _JUICE_VICTIM})
    sealed = obs.observe_sealed("victim")
    assert sealed["domain"] == sob.STATE_SNAPSHOT_HASH_DOMAIN == "APTS_CSRF_STATE_SNAPSHOT_V1"
    assert set(sealed) >= {"domain", "state", "sha256"}
    assert sob.verify_state_snapshot(sealed)
    # sha256 = segel deterministik atas state abstrak
    expected = sha256_hex({"hash_domain": sob.STATE_SNAPSHOT_HASH_DOMAIN, "state": sealed["state"]})
    assert sealed["sha256"] == expected


def test_replay_determinism_same_observation_same_seal():
    obs1, _ = _observer({"victim": _JUICE_VICTIM})
    obs2, _ = _observer({"victim": dict(_JUICE_VICTIM)})
    assert obs1.observe_sealed("victim") == obs2.observe_sealed("victim")


def test_tampered_seal_fails_verification():
    obs, _ = _observer({"victim": _JUICE_VICTIM})
    sealed = obs.observe_sealed("victim")
    tampered = dict(sealed, state=dict(sealed["state"], username="mallory"))
    assert not sob.verify_state_snapshot(tampered)  # sha256 tak lagi cocok


# ------------------- CSRF change-username state delta ----------------------
def test_csrf_username_change_is_visible_in_abstract_state():
    before = _JUICE_VICTIM
    after = {"status": "success", "data": dict(_JUICE_VICTIM["data"], username="xss-attacker")}
    obs, _ = _observer({"before": before, "after": after})
    s0 = obs.observe("before")
    s1 = obs.observe("after")
    assert s0["username"] == "bender"
    assert s1["username"] == "xss-attacker"
    assert s0 != s1  # perubahan state teramati (bukti target-agnostic untuk C7)
    # atribut non-target tak berubah (kontrol untuk compare di C7)
    assert s0["email"] == s1["email"]


def test_volatile_only_change_does_not_alter_state():
    before = _JUICE_VICTIM
    after = {"status": "success", "data": dict(_JUICE_VICTIM["data"], updatedAt="2026-12-31T00:00:00Z")}
    obs, _ = _observer({"before": before, "after": after})
    assert obs.observe("before") == obs.observe("after")  # volatil tak mencemari S


# -------------------------- projection guards ------------------------------
def test_projection_requires_non_empty_attributes():
    for bad in ({}, {"attributes": []}, {"attributes": ["ok", 3]}):
        try:
            sob.StateObserver(lambda r: None, projection=bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for projection={bad!r}")


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
