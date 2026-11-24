"""Stage 7.5x acceptance — generic BAC pipeline end-to-end (hermetic).

Drives the WHOLE pipeline the way a mission would, with no challenge list:
authorized surface import -> BAC hypothesis synthesis -> real symbolic planner ->
CAE gateway + evidence oracle -> cross-validate against a (fake) Juice scoreboard.
Proves solves are decided by evidence and that the generic oracle AGREES with the
scoreboard ground truth. Fake transport+scoreboard; no network.
Run: python3 tests/test_stage7_5x_bac_mission_e2e.py  (or via pytest)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import bac_hypothesis_synthesis as syn
from pentest_subsystem import symbolic_planner as sp
from pentest_subsystem import cae_service_runner as csr
from pentest_subsystem.knowledge_packs import owasp_juice_shop as pack

BASE = "http://127.0.0.1:3000"
_TARGET = {"target_type": "URL", "target_value": BASE}


class FakeJuice:
    """Fake loopback Juice: lab register/login (with uid), forced-browse + IDOR
    read, and a scoreboard that flips when the matching endpoint is hit."""
    def __init__(self):
        self.solved = set()
    def __call__(self, d):
        url = d["url"]
        if url.endswith("/api/Users"):
            return {"status": "success", "data": {"id": 7}}
        if url.endswith("/rest/user/login"):
            return {"authentication": {"token": "LAB.JWT", "bid": 6, "uid": 7, "umail": "me@lab.local"}}
        if "/ftp/eastere.gg%2500.md" in url:
            self.solved.add("easterEggLevelOneChallenge")
            return {"status_code": 200, "data": "egg"}
        if "/rest/basket/" in url:
            self.solved.add("basketAccessChallenge")
            return {"status_code": 200, "data": {"id": 1, "UserId": 2}}  # UserId 2 != our uid 7
        return {"status_code": 200}
    def snapshot(self):
        keys = ["easterEggLevelOneChallenge", "basketAccessChallenge"]
        return {k: (k in self.solved) for k in keys}


def _read_active_surface():
    enum = pack.bac_surface_enumeration()
    enum["endpoint_discoveries"] = [e for e in enum["endpoint_discoveries"]
                                    if e["attributes"]["endpoint"] in pack.READ_ACTIVE_SAFE]
    return enum


def test_pipeline_synthesises_and_plans():
    enum = _read_active_surface()
    hyps = syn.synthesize_bac_hypotheses(enum, target=_TARGET)
    tmpls = sorted(h["cae"]["template"] for h in hyps)
    assert tmpls == ["forced-browse", "idor-read"]
    result = sp.plan(sp.compile_problem({"task": {"objective": {}}},
                                        syn.make_bac_hypothesis_run("o", "juice-bac", _TARGET, enum)))
    assert result["status"] in ("CANDIDATE_PLANS", "NO_CANDIDATE_PLANS")


def test_pipeline_exploits_via_evidence_oracle():
    enum = _read_active_surface()
    hyps = syn.synthesize_bac_hypotheses(enum, target=_TARGET)
    out = csr.execute_bac_generic(BASE, hypotheses=hyps, transport=FakeJuice(),
                                  oracle_fetch=lambda: {"data": []})
    outcomes = {r["template"]: r["outcome"] for r in out["results"]}
    assert outcomes["forced-browse"] == "EXPLOITED"
    assert outcomes["idor-read"] == "EXPLOITED"      # needs session uid -> owner check
    assert len(out["exploited"]) == 2


def test_oracle_agrees_with_scoreboard_ground_truth():
    enum = _read_active_surface()
    hyps = syn.synthesize_bac_hypotheses(enum, target=_TARGET)
    backend = FakeJuice()
    before = backend.snapshot()
    out = csr.execute_bac_generic(BASE, hypotheses=hyps, transport=backend,
                                  oracle_fetch=lambda: {"data": []})
    after = backend.snapshot()
    xval = csr.cross_validate_with_scoreboard(out, before, after, pack.BAC_SURFACE_CHALLENGE_MAP)
    assert xval["agreed"] is True
    assert len(xval["agreements"]) == 2
    assert xval["disagreements"] == []
    solved_challenges = sorted(a["challenge"] for a in xval["agreements"])
    assert solved_challenges == ["basketAccessChallenge", "easterEggLevelOneChallenge"]


def test_no_challenge_key_anywhere_in_pipeline():
    enum = _read_active_surface()
    hyps = syn.synthesize_bac_hypotheses(enum, target=_TARGET)
    assert all(h["cae"]["challenge_key"] is None for h in hyps)  # driven by evidence, not scoreboard


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
