"""Stage 7.7 acceptance — CONTROLLED_DESTRUCTIVE with double-approval.

DESTRUCTIVE (DELETE) is opt-in, requires `destructive_actions_allowed`, and needs
TWO distinct approvers (segregation of duties) before it actuates. Solves Five-Star
Feedback via the admin chain. No real network I/O.
Run: python3 tests/test_stage7_7_destructive.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import approval_broker as ab
from pentest_subsystem import active_exploitation_execution as ae

AEC = ae.ACTION_CLASS_ACTIVE_EXPLOITATION
DESTR = ae.ACTION_CLASS_DESTRUCTIVE
ENABLED = [AEC, DESTR]
_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


class FakeJuiceShop:
    def __init__(self): self.solved = set(); self.calls = []
    def tr(self, d):
        self.calls.append((d["method"], d["url"]))
        if d["url"].endswith("/rest/user/login"):
            return {"authentication": {"token": "ADMIN.JWT"}}
        if d["url"].endswith("/api/Users"):
            return {"status": "success"}
        if d["method"] == "DELETE" and "/api/Feedbacks/" in d["url"]:
            self.solved.add("feedbackChallenge")
            return {"status_code": 200}
        return {"status_code": 200}
    def ch(self):
        return {"data": [{"key": "feedbackChallenge", "solved": "feedbackChallenge" in self.solved}]}


def _roe(**ov):
    roe = {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [AEC, DESTR],
        "allowed_http_methods": ["GET", "POST", "DELETE"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [DESTR],
        "destructive_actions_allowed": True,
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900},
    }
    roe.update(ov)
    return roe


def _dtoken(broker, approver):
    card = broker.request_approval(action_class=DESTR, primitive_id="destroy-5star-feedback",
                                   target=_TARGET, http_method="DELETE", orchestration_id="o")
    return broker.approve(card["approval_id"], approver=approver)


_CHAIN = ["auth-lab-admin", "destroy-5star-feedback"]
_PARAMS = {"destroy-5star-feedback": {"id": 5}}


def test_destructive_deferred_when_not_enabled():
    js = FakeJuiceShop()
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch)  # DESTR not enabled
    run = gw.run_chain("o", _TARGET, _CHAIN, parameters=_PARAMS)
    step = [s for s in run["steps"] if s["primitive_id"] == "destroy-5star-feedback"][0]
    assert step["outcome"] == "DEFERRED" and step["deferred_to"] == "7.7"


def test_blocked_without_destructive_allowed():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    toks = [_dtoken(b, "alice"), _dtoken(b, "bob")]
    gw = ae.ActiveExploitationGateway(_roe(destructive_actions_allowed=False),
                                      transport=js.tr, oracle_fetcher=js.ch, approval_broker=b, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, _CHAIN, parameters=_PARAMS, approval_tokens={DESTR: toks})
    step = [s for s in run["steps"] if s["primitive_id"] == "destroy-5star-feedback"][0]
    assert step["outcome"] == "BLOCKED" and "AE-DESTRUCTIVE" in step["failed_rule_ids"]


def test_requires_two_approvals():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch,
                                      approval_broker=b, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, _CHAIN, parameters=_PARAMS,
                       approval_tokens={DESTR: [_dtoken(b, "alice")]})  # only one
    step = [s for s in run["steps"] if s["primitive_id"] == "destroy-5star-feedback"][0]
    assert step["outcome"] == "REVIEW_REQUIRED" and step["required_approvals"] == 2
    assert "feedbackChallenge" not in run["solved_challenges"]


def test_same_approver_rejected():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch,
                                      approval_broker=b, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, _CHAIN, parameters=_PARAMS,
                       approval_tokens={DESTR: [_dtoken(b, "alice"), _dtoken(b, "alice")]})
    step = [s for s in run["steps"] if s["primitive_id"] == "destroy-5star-feedback"][0]
    assert step["outcome"] == "BLOCKED" and "SEGREGATION_OF_DUTIES" in step["reason"]
    assert "feedbackChallenge" not in run["solved_challenges"]


def test_two_distinct_approvals_solves():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    toks = [_dtoken(b, "alice"), _dtoken(b, "bob")]
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch,
                                      approval_broker=b, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, _CHAIN, parameters=_PARAMS, approval_tokens={DESTR: toks})
    assert "feedbackChallenge" in run["solved_challenges"]
    step = [s for s in run["steps"] if s["primitive_id"] == "destroy-5star-feedback"][0]
    assert step["outcome"] == "EXPLOITED"
    assert ("DELETE", "http://127.0.0.1:3000/api/Feedbacks/5") in js.calls


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
