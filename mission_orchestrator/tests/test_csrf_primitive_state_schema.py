"""CSRF C6-C7 — primitive schema extension (verification: "state").

Proves langkah 3 §9: ``csrf-change-username`` kini membawa field opsional
``verification/state_attributes/state_scope`` yang mengaktifkan jalur state
(C6-C7), SEMENTARA ``challenge_key``/``success_predicate`` dipertahankan sebagai
korroborator LAB (bukan satu-satunya oracle). Perubahan bersifat aditif: katalog
tetap valid & hash library tetap konsisten, primitive lain tak tersentuh.

Run: python3 tests/test_csrf_primitive_state_schema.py  (atau via pytest)
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import exploit_primitive_library as lib
from pentest_subsystem.knowledge_packs import owasp_juice_shop as pack


def test_csrf_primitive_carries_state_verification_fields():
    p = lib.get_primitive("csrf-change-username")
    assert p["verification"] == "state"
    assert p["state_attributes"] == ["username"]
    assert p["state_scope"] == "session_principal"


def test_csrf_primitive_preserves_scoreboard_corroborator():
    p = lib.get_primitive("csrf-change-username")
    # scoreboard tetap ada sebagai korroborator LAB, bukan dihapus
    assert p["challenge_key"] == "csrfChallenge"
    assert p["success_predicate"] == "challenge.csrfChallenge.solved==true"
    assert "csrfChallenge" in lib.BROKEN_ACCESS_CONTROL_CHALLENGES


def test_state_fields_are_opt_in_only_for_csrf():
    # primitive lain TIDAK mendapat field state (aditif & opt-in)
    for pid in ("auth-lab-user", "idor-read-basket", "param-tamper-feedback"):
        p = lib.get_primitive(pid)
        assert "verification" not in p
        assert "state_attributes" not in p


def test_state_attributes_match_observer_projection_attribute():
    # atribut-uji CSRF ("username") termasuk dalam projection Juice Shop yang
    # diamati StateObserver -> teramati -> bisa menghasilkan verdict konklusif.
    from pentest_subsystem.state_observer import JUICE_SHOP_USER_PROJECTION
    p = lib.get_primitive("csrf-change-username")
    for attr in p["state_attributes"]:
        assert attr in JUICE_SHOP_USER_PROJECTION["attributes"], attr


def test_catalog_still_loads_and_hash_is_consistent():
    cat = lib.canonical_exploit_primitive_library()
    dom = lib.EXPLOIT_PRIMITIVE_LIBRARY_HASH_DOMAIN
    core = {k: v for k, v in cat.items() if k != "integrity"}
    assert cat["integrity"]["canonical_sha256"] == lib.sha256_hex({"hash_domain": dom, "core": core})


def test_schema_fields_constant_exported():
    assert pack.STATE_VERIFICATION_FIELDS == ("verification", "state_attributes", "state_scope")


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
