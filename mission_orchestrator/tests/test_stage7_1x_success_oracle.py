"""Stage 7.1x acceptance — generic success oracle decouples solve from scoreboard.

Proves: (1) the oracle decides CONFIRMED/REFUTED/INDETERMINATE from response
evidence under a closed grammar, fail-closed on unknown/unparseable predicates;
(2) the gateway, given a success_oracle, judges a primitive with NO challenge_key
as EXPLOITED/FAILED on evidence alone — no Juice scoreboard needed.
Run: python3 tests/test_stage7_1x_success_oracle.py  (or via pytest)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import cae_success_oracle as so
from pentest_subsystem import active_exploitation_execution as ae
from pentest_subsystem.exploit_primitive_library import PRIMITIVES, F_SESSION_AUTH

_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


# --------------------------- oracle unit tests -----------------------------
def test_idor_read_confirmed_other_owner():
    oracle = so.SuccessOracle()
    ctx = {"status_code": 200, "response": {"data": {"UserId": 2}}, "session": {"userId": 7}}
    pred = {"all": [{"path": "status_code", "op": "in_range", "value": [200, 299]},
                    {"path": "body.data.UserId", "op": "ne", "ref": "self.userId"}]}
    assert oracle.verdict(pred, ctx) == so.CONFIRMED


def test_idor_read_refuted_same_owner():
    oracle = so.SuccessOracle()
    ctx = {"status_code": 200, "response": {"data": {"UserId": 7}}, "session": {"userId": 7}}
    pred = {"all": [{"path": "status_code", "op": "in_range", "value": [200, 299]},
                    {"path": "body.data.UserId", "op": "ne", "ref": "self.userId"}]}
    assert oracle.verdict(pred, ctx) == so.REFUTED


def test_mutation_refuted_on_auth_error():
    oracle = so.SuccessOracle()
    ctx = {"status_code": 403, "response": {"error": "Unauthorized"}, "session": {}}
    assert oracle.verdict("status in 200..299", ctx) == so.REFUTED


def test_missing_evidence_is_indeterminate_not_confirmed():
    oracle = so.SuccessOracle()
    ctx = {"status_code": 200, "response": {}, "session": {"userId": 7}}
    pred = {"path": "body.data.UserId", "op": "ne", "ref": "self.userId"}
    assert oracle.verdict(pred, ctx) == so.INDETERMINATE


def test_string_predicate_parses_and_confirms():
    oracle = so.SuccessOracle()
    ctx = {"status_code": 200, "response": {"description": "see https://owasp.slack.com now"}}
    assert oracle.verdict("status==200 && description.contains('owasp.slack.com')", ctx) == so.CONFIRMED


def test_unparseable_predicate_fails_closed():
    oracle = so.SuccessOracle()
    ctx = {"status_code": 200, "response": {}}
    # free-form / scoreboard predicates are intentionally NOT confirmable here
    for bad in ("challenge.ssrfChallenge.solved==true",
                "jwt.claims.role=='admin' (payload: ' OR 1=1--)",
                "count(feedback where rating==5)==0"):
        assert oracle.verdict(bad, ctx) == so.INDETERMINATE, bad


def test_contains_on_missing_value_is_indeterminate():
    oracle = so.SuccessOracle()
    assert so.SuccessOracle().verdict("body.x.contains('y')", {"response": {}}) == so.INDETERMINATE


# --------------------------- gateway integration ---------------------------
class _FakeBackend:
    """Transport + (empty) oracle: NO scoreboard flips, so only the success
    oracle can produce EXPLOITED."""
    def __init__(self, basket_response):
        self._basket = basket_response
    def transport(self, d):
        url = d["url"]
        if url.endswith("/api/Users"):
            return {"status": "success", "data": {"id": 1}}
        if url.endswith("/rest/user/login"):
            return {"authentication": {"token": "LAB.JWT", "bid": 6, "umail": "me@lab.local"}}
        if "/rest/basket/" in url:
            return self._basket
        return {"status_code": 200}
    def challenges(self):
        return {"data": []}  # scoreboard never signals a solve


def _roe():
    return {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [ae.ACTION_CLASS_ACTIVE_EXPLOITATION],
        "allowed_http_methods": ["GET", "POST"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [],
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900},
    }


_GENERIC_PRIMITIVE = {
    "primitive_id": "t-idor-generic", "title": "Generic IDOR read (test)",
    "cwe": "CWE-639", "capec": "CAPEC-180", "attack": "T1190",
    "action_class": ae.ACTION_CLASS_ACTIVE_EXPLOITATION, "http_method": "GET",
    "endpoint_template": "/rest/basket/{id}", "non_destructive": True, "delivery": "HTTP",
    "requires": ["auth-lab-user"], "challenge_key": None, "estimated_impact": "MEDIUM",
    "planning_model": {"preconditions": [F_SESSION_AUTH], "effects": ["disclosed:x"], "cost": 1.0},
    # structured predicate: 2xx AND fetched basket id != our own basket id
    "success_predicate": {"all": [{"path": "status_code", "op": "in_range", "value": [200, 299]},
                                  {"path": "body.data.id", "op": "ne", "ref": "self.basketId"}]},
}


def _with_generic_primitive(backend_basket):
    PRIMITIVES["t-idor-generic"] = dict(_GENERIC_PRIMITIVE)
    try:
        js = _FakeBackend(backend_basket)
        gw = ae.ActiveExploitationGateway(_roe(), transport=js.transport, oracle_fetcher=js.challenges,
                                          success_oracle=so.SuccessOracle())
        run = gw.run_chain("orch", _TARGET, ["auth-lab-user", "t-idor-generic"],
                           parameters={"t-idor-generic": {"id": 2}})
    finally:
        PRIMITIVES.pop("t-idor-generic", None)
    return run


def test_gateway_exploited_via_oracle_without_scoreboard():
    run = _with_generic_primitive({"status_code": 200, "data": {"id": 2, "UserId": 2}})
    step = [s for s in run["steps"] if s["primitive_id"] == "t-idor-generic"][0]
    assert step["outcome"] == "EXPLOITED"
    assert step["oracle_verdict"] == so.CONFIRMED
    assert run["solved_challenges"] == []  # nothing on the scoreboard
    assert ae.verify_ae_run(run)


def test_gateway_failed_via_oracle_on_refuted():
    run = _with_generic_primitive({"status_code": 403, "error": "Unauthorized"})
    step = [s for s in run["steps"] if s["primitive_id"] == "t-idor-generic"][0]
    assert step["outcome"] == "FAILED"
    assert step["oracle_verdict"] == so.REFUTED


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
