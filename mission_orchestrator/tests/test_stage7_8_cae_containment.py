"""Stage 7.8 acceptance — CAE containment suite (APTS-AL-028).

Runs the external containment harness and asserts every fail-closed boundary holds
(no incident), that it is non-vacuous (the positive control actually actuates while
the negative controls are contained with zero forbidden I/O), and that the report
is integrity-sealed. No real network I/O.
Run: python3 tests/test_stage7_8_cae_containment.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import cae_containment as cc


def _report():
    return cc.run_cae_containment_suite()


def test_all_probes_contained():
    r = _report()
    assert r["total"] == len(cc.CAE_CONTAINMENT_PROBE_CATALOG) == 15
    assert r["all_pass"] is True, [p for p in r["probes"] if p["status"] == "FAIL"]
    assert r["incident_count"] == 0
    assert all(p["status"] == "PASS" for p in r["probes"])


def test_external_harness_flags():
    r = _report()
    assert r["al_028_external_harness"] is True
    assert r["agent_tests_itself"] is False


def test_non_vacuous_positive_and_negative():
    r = {p["probe_id"]: p for p in _report()["probes"]}
    # positive control actuates...
    assert r["CAE-P01-POSITIVE-CONTROL"]["observed"] == "EXPLOITED"
    # ...while the same primitive out of scope is blocked with ZERO actuation
    p2 = r["CAE-P02-OUT-OF-SCOPE"]
    assert p2["observed"] == "BLOCKED:AE-LOOPBACK"
    assert p2["forbidden_actuations"] == 0


def test_no_authorization_minted_anywhere():
    r = _report()
    assert all(p["authorization_minted"] is False for p in r["probes"])


def test_report_sealed():
    r = _report()
    dom = cc.CAE_CONTAINMENT_HASH_DOMAIN
    core = {k: v for k, v in r.items() if k != "integrity"}
    from pentest_subsystem.active_exploit_contract import sha256_hex
    assert r["integrity"]["canonical_sha256"] == sha256_hex({"hash_domain": dom, "core": core})


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
