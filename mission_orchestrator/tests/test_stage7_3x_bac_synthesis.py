"""Stage 7.3x acceptance — BAC hypotheses synthesised from enumeration surface.

Proves the recon->Stage7 bridge: a fixture enumeration output (endpoints only,
no challenge keys) yields the right BAC hypotheses (IDOR read/write,
forced-browse, missing-function-level-ac, SSRF, CSRF), each plan-legal and
challenge-key-free; an empty/irrelevant surface yields NOTHING (no false
positives); and a synthesised run compiles through the real symbolic_planner.
Run: python3 tests/test_stage7_3x_bac_synthesis.py  (or via pytest)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import bac_hypothesis_synthesis as syn
from pentest_subsystem import symbolic_planner as sp

_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


def _disc(endpoint, method="GET", params=None, ev="evi-1", conf=0.6):
    return {"observation_id": "obs-" + endpoint, "target": dict(_TARGET),
            "attributes": {"endpoint": endpoint, "scheme": "http", "method": method,
                           "status": 200, "params": params or []},
            "confidence": conf, "evidence_ref": ev}


_SURFACE = {
    "mission_id": "mission-fixture",
    "endpoint_discoveries": [
        _disc("/rest/basket/4", "GET"),               # -> idor-read
        _disc("/api/Products/9", "PUT"),              # -> idor-write
        _disc("/administration", "GET"),              # -> forced-browse (page)
        _disc("/api/admin/users", "GET"),             # -> missing-function-level-ac (api)
        _disc("/api/fetch", "POST", params=["url"]),  # -> ssrf
        _disc("/profile", "POST", params=["username"]),  # -> csrf
        _disc("/status", "GET"),                      # -> nothing (no boundary)
        _disc("/rest/products/search", "GET"),        # -> nothing (no id)
    ],
}


def _templates_of(records):
    return sorted(r["cae"]["template"] for r in records)


def test_synthesises_expected_bac_classes():
    recs = syn.synthesize_bac_hypotheses(_SURFACE, target=_TARGET)
    got = _templates_of(recs)
    assert got == sorted(["idor-read", "idor-write", "forced-browse",
                          "missing-function-level-ac", "ssrf", "csrf"]), got
    # all generic: no challenge_key leaks in
    assert all(r["cae"]["challenge_key"] is None for r in recs)


def test_idor_path_is_templatised():
    recs = syn.synthesize_bac_hypotheses(_SURFACE, target=_TARGET)
    idor = next(r for r in recs if r["cae"]["template"] == "idor-read")
    assert idor["cae"]["endpoint_template"] == "/rest/basket/{id}"
    assert isinstance(idor["cae"]["success_predicate"], dict)  # evidence-based, not scoreboard


def test_empty_surface_yields_nothing():
    assert syn.synthesize_bac_hypotheses({"endpoint_discoveries": []}, target=_TARGET) == []
    assert syn.synthesize_bac_hypotheses({}, target=_TARGET) == []


def test_benign_surface_yields_no_false_positives():
    benign = {"endpoint_discoveries": [_disc("/status", "GET"), _disc("/health", "GET"),
                                       _disc("/rest/products/search", "GET")]}
    assert syn.synthesize_bac_hypotheses(benign, target=_TARGET) == []


def test_records_are_plan_legal():
    recs = syn.synthesize_bac_hypotheses(_SURFACE, target=_TARGET)
    for r in recs:
        m = sp.normalize_model(r["planning_model"])  # raises if illegal
        assert m["effects"], r["hypothesis_id"]
        assert "integrity" in r and len(r["integrity"]["canonical_sha256"]) == 64


def test_synthesised_run_compiles_through_planner():
    run = syn.make_bac_hypothesis_run("orch-bac", "asset-bac", _TARGET, _SURFACE)
    assert run["synthesis"]["hypothesis_count"] == 6
    problem = sp.compile_problem({"task": {"objective": {}}}, run)
    result = sp.plan(problem)
    assert result["status"] in ("CANDIDATE_PLANS", "NO_CANDIDATE_PLANS")
    # every synthesised exploit hypothesis appears as a validation goal
    validates = {p.get("validates") for p in result.get("paths", [])}
    assert any(v and v.startswith("validated:bac-") for v in validates)


def test_accepts_bare_endpoint_list():
    recs = syn.synthesize_bac_hypotheses(
        [{"attributes": {"endpoint": "/rest/basket/4", "method": "GET"}}], target=_TARGET)
    assert len(recs) == 1 and recs[0]["cae"]["template"] == "idor-read"


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
