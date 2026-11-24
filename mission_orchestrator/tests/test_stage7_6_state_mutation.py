"""Stage 7.6 acceptance — CONTROLLED_STATE_MUTATION with approval + auto-rollback.

STATE_MUTATION is opt-in (enable_classes); gated by a single-use approval token
(Stage 7.5); reversible mutations auto-roll-back after the solve is recorded;
non-reversible ones are flagged for manual review. No real network I/O.
Run: python3 tests/test_stage7_6_state_mutation.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import approval_broker as ab
from pentest_subsystem import active_exploitation_execution as ae

AEC = ae.ACTION_CLASS_ACTIVE_EXPLOITATION
SM = ae.ACTION_CLASS_STATE_MUTATION
ENABLED = [AEC, SM]
_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}
_SOLVE = [("/api/BasketItems", "basketManipulateChallenge"),
          ("/api/Feedbacks", "forgedFeedbackChallenge"),
          ("/profile/image/url", "ssrfChallenge"),
          ("/profile", "csrfChallenge")]
_KEYS = [k for _, k in _SOLVE]


class FakeJuiceShop:
    def __init__(self):
        self.solved = set()
        self.calls = []
    def tr(self, d):
        self.calls.append((d["method"], d["url"]))
        u = d["url"]
        if u.endswith("/rest/user/login"):
            return {"authentication": {"token": "LAB.JWT", "bid": 6}}
        if u.endswith("/api/Users"):
            return {"status": "success"}
        if d["method"] == "DELETE":
            return {"status_code": 200}
        if u.rstrip("/").endswith("/api/BasketItems"):
            self.solved.add("basketManipulateChallenge")
            return {"status_code": 200, "data": {"id": 99, "BasketId": 2}}
        if u.rstrip("/").endswith("/api/Feedbacks"):
            self.solved.add("forgedFeedbackChallenge")
            return {"status_code": 201, "data": {"id": 42}}
        if "/profile/image/url" in u:
            self.solved.add("ssrfChallenge")
            return {"status_code": 200}
        if u.rstrip("/").endswith("/profile"):
            self.solved.add("csrfChallenge")
            return {"status_code": 200}
        return {"status_code": 200}
    def ch(self):
        return {"data": [{"key": k, "solved": k in self.solved} for k in _KEYS]}


def _roe(**ov):
    roe = {
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
    roe.update(ov)
    return roe


def _token(broker, primitive_id):
    card = broker.request_approval(action_class=SM, primitive_id=primitive_id, target=_TARGET,
                                   http_method="POST", orchestration_id="o")
    return broker.approve(card["approval_id"], approver="alice")


def test_mutation_deferred_when_not_enabled():
    js = FakeJuiceShop()
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch)  # default: SM not enabled
    run = gw.run_chain("o", _TARGET, ["auth-lab-user", "idor-write-basket"],
                       parameters={"idor-write-basket": {"body": {"ProductId": 1, "BasketId": 2, "quantity": 1}}})
    step = [s for s in run["steps"] if s["primitive_id"] == "idor-write-basket"][0]
    assert step["outcome"] == "DEFERRED" and step["deferred_to"] == "7.6"


def test_mutation_requires_approval():
    js = FakeJuiceShop()
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, ["auth-lab-user", "idor-write-basket"],
                       parameters={"idor-write-basket": {"body": {"ProductId": 1, "BasketId": 2}}})
    step = [s for s in run["steps"] if s["primitive_id"] == "idor-write-basket"][0]
    assert step["outcome"] == "REVIEW_REQUIRED"
    assert "basketManipulateChallenge" not in run["solved_challenges"]


def test_reversible_mutation_solves_and_rolls_back():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    tok = _token(b, "idor-write-basket")
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch,
                                      approval_broker=b, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, ["auth-lab-user", "idor-write-basket"],
                       parameters={"idor-write-basket": {"body": {"ProductId": 1, "BasketId": 2, "quantity": 1}}},
                       approval_tokens={SM: tok})
    assert "basketManipulateChallenge" in run["solved_challenges"]
    step = [s for s in run["steps"] if s["primitive_id"] == "idor-write-basket"][0]
    assert step["rollback"]["status"] == "ROLLED_BACK"
    assert ("DELETE", "http://127.0.0.1:3000/api/BasketItems/99") in js.calls


def test_feedback_mutation_rolls_back():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    tok = _token(b, "param-tamper-feedback")
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch,
                                      approval_broker=b, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, ["auth-lab-user", "param-tamper-feedback"],
                       parameters={"param-tamper-feedback": {"body": {"comment": "x", "rating": 1, "UserId": 1}}},
                       approval_tokens={SM: tok})
    assert "forgedFeedbackChallenge" in run["solved_challenges"]
    step = [s for s in run["steps"] if s["primitive_id"] == "param-tamper-feedback"][0]
    assert step["rollback"]["status"] == "ROLLED_BACK"
    assert ("DELETE", "http://127.0.0.1:3000/api/Feedbacks/42") in js.calls


def test_non_reversible_flagged_for_manual_review():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    tok = _token(b, "csrf-change-username")
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch,
                                      approval_broker=b, enable_classes=ENABLED)
    run = gw.run_chain("o", _TARGET, ["csrf-change-username"],
                       parameters={"csrf-change-username": {"body": {"username": "pwned"}}},
                       approval_tokens={SM: tok})
    assert "csrfChallenge" in run["solved_challenges"]
    step = run["steps"][0]
    assert step["rollback"]["status"] == "NOT_REVERSIBLE_MANUAL_REVIEW"
    assert not any(m == "DELETE" for m, _ in js.calls)


def test_reused_token_rejected_for_mutation():
    b = ab.ApprovalBroker(); tok = _token(b, "idor-write-basket")
    p = {"idor-write-basket": {"body": {"ProductId": 1, "BasketId": 2}}}
    js1 = FakeJuiceShop()
    ae.ActiveExploitationGateway(_roe(), transport=js1.tr, oracle_fetcher=js1.ch, approval_broker=b,
                                 enable_classes=ENABLED).run_chain("o", _TARGET, ["auth-lab-user", "idor-write-basket"],
                                 parameters=p, approval_tokens={SM: tok})
    js2 = FakeJuiceShop()
    run2 = ae.ActiveExploitationGateway(_roe(), transport=js2.tr, oracle_fetcher=js2.ch, approval_broker=b,
                                        enable_classes=ENABLED).run_chain("o", _TARGET, ["auth-lab-user", "idor-write-basket"],
                                        parameters=p, approval_tokens={SM: tok})
    step = [s for s in run2["steps"] if s["primitive_id"] == "idor-write-basket"][0]
    assert step["outcome"] == "BLOCKED" and "APPROVAL_INVALID" in step["reason"]


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
