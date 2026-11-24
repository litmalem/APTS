"""Stage 7.4x acceptance — generic BAC bridge: hypotheses -> gateway, no scoreboard.

Proves the pipeline seam: synthesised BAC hypotheses (Stage 7.3x) drive the CAE
gateway (Stage 7.4) and are judged EXPLOITED by the evidence oracle (Stage 7.1x)
with NO Juice scoreboard; the CAE-authorized scope profile actually authorizes
execution; and RoE (loopback) still blocks a non-loopback target in generic mode.
Hermetic: fake transport + empty scoreboard, no network.
Run: python3 tests/test_stage7_4x_bac_generic_bridge.py  (or via pytest)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import cae_service_runner as csr
from pentest_subsystem import cae_success_oracle as so
from pentest_subsystem.active_exploit_contract import ACTION_CLASS_ACTIVE_EXPLOITATION
from pentest_subsystem.bac_primitive_templates import F_SESSION_AUTH

_LOOPBACK = "http://127.0.0.1:3000"


class _FakeBackend:
    """Transport for a loopback app: supports lab register/login and returns a
    foreign-owned object for IDOR, 200 for forced-browse. No scoreboard."""
    def __call__(self, d):  # SessionBroker/gateway transport protocol
        url = d["url"]
        if url.endswith("/api/Users"):
            return {"status": "success", "data": {"id": 1}}
        if url.endswith("/rest/user/login"):
            return {"authentication": {"token": "LAB.JWT", "bid": 6, "umail": "me@lab.local"}}
        if "/rest/basket/" in url:
            return {"status_code": 200, "data": {"id": 2}}   # someone else's basket (id 2 != own 6)
        if "/administration" in url:
            return {"status_code": 200, "data": {"ok": True}}
        return {"status_code": 200}


def _empty_oracle():
    return {"data": []}


# --------------------------- scope profile ---------------------------------
def test_scope_profile_authorizes_execution():
    prof = csr.bac_controlled_scope_profile("127.0.0.1:3000")
    assert prof["workflow_profile"] == csr.WPT_BAC_CONTROLLED_PROFILE
    assert prof["data_handling_policy"]["execution_authorized"] is True
    assert prof["read_only"] is False and prof["loopback_only"] is True
    assert ACTION_CLASS_ACTIVE_EXPLOITATION in prof["allowed_action_classes"]


# --------------------------- forced-browse from enumeration ----------------
def test_forced_browse_exploited_from_enumeration_no_scoreboard():
    enumeration = {"endpoint_discoveries": [
        {"attributes": {"endpoint": "/administration", "method": "GET"},
         "confidence": 0.7, "evidence_ref": "evi-1"}]}
    out = csr.execute_bac_generic(_LOOPBACK, enumeration_output=enumeration,
                                  transport=_FakeBackend(), oracle_fetch=_empty_oracle)
    assert out["mode"] == "GENERIC_BAC_EVIDENCE_ORACLE_NO_SCOREBOARD"
    assert len(out["results"]) == 1
    r = out["results"][0]
    assert r["template"] == "forced-browse"
    assert r["outcome"] == "EXPLOITED" and r["oracle_verdict"] == so.CONFIRMED
    assert out["exploited"] == [r["hypothesis_id"]]


# --------------------------- idor via auth chain ---------------------------
def _idor_hypothesis():
    return {
        "hypothesis_id": "bac-idor-basket",
        "knowledge": {"title": "IDOR basket", "cwe": "CWE-639", "capec": "CAPEC-180", "attack": "T1190"},
        "planning_model": {"preconditions": [F_SESSION_AUTH], "effects": ["disclosed:x"], "cost": 1.0},
        "required_validation": {"http_method": "GET", "estimated_impact": "MEDIUM",
                                "action_class": ACTION_CLASS_ACTIVE_EXPLOITATION},
        "cae": {"primitive_id": "bac-idor-basket", "action_class": ACTION_CLASS_ACTIVE_EXPLOITATION,
                "template": "idor-read", "endpoint_template": "/rest/basket/{id}", "challenge_key": None,
                "success_predicate": {"all": [{"path": "status_code", "op": "in_range", "value": [200, 299]},
                                              {"path": "body.data.id", "op": "ne", "ref": "self.basketId"}]}},
    }


def test_idor_bridge_auth_chain_exploits_via_oracle():
    out = csr.execute_bac_generic(_LOOPBACK, hypotheses=[_idor_hypothesis()],
                                  transport=_FakeBackend(), oracle_fetch=_empty_oracle)
    r = out["results"][0]
    assert r["outcome"] == "EXPLOITED" and r["oracle_verdict"] == so.CONFIRMED
    assert r["action_class"] == ACTION_CLASS_ACTIVE_EXPLOITATION


# --------------------------- RoE still enforced in generic mode ------------
def test_non_loopback_blocked_in_generic_mode():
    enumeration = {"endpoint_discoveries": [
        {"attributes": {"endpoint": "/administration", "method": "GET"}, "evidence_ref": "e"}]}
    out = csr.execute_bac_generic("http://10.0.0.5:3000", enumeration_output=enumeration,
                                  transport=_FakeBackend(), oracle_fetch=_empty_oracle)
    r = out["results"][0]
    assert r["outcome"] == "BLOCKED"
    assert out["exploited"] == []


def test_run_record_sealed():
    out = csr.execute_bac_generic(_LOOPBACK, hypotheses=[_idor_hypothesis()],
                                  transport=_FakeBackend(), oracle_fetch=_empty_oracle)
    core = {k: v for k, v in out.items() if k != "integrity"}
    assert out["integrity"]["canonical_sha256"] == csr.sha256_hex(
        {"hash_domain": csr.BAC_GENERIC_HASH_DOMAIN, "core": core})


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
