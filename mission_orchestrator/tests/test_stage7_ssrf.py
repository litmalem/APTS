"""Stage 7 — SSRF (profile image URL) acceptance.

`ssrf-profile-image` POSTs a form-encoded imageUrl pointing at the internal
/solve endpoint, authenticated via a `token` cookie (the server-rendered /profile
path), making the server fetch the internal resource. Hermetic: a fake shop marks
ssrfChallenge solved when the SSRF POST carries the internal URL + a token cookie.
Run: python3 tests/test_stage7_ssrf.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import approval_broker as ab
from pentest_subsystem import active_exploitation_execution as ae

AEC = ae.ACTION_CLASS_ACTIVE_EXPLOITATION
SM = ae.ACTION_CLASS_STATE_MUTATION
_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}
_BODY = "imageUrl=http%3A%2F%2Flocalhost%3A3000%2Fsolve%2Fchallenges%2Fserver-side%3Fkey%3DtRy_H4rd3r_n0thIng_iS_Imp0ssibl3"


class FakeShop:
    def __init__(self): self.solved = set(); self.calls = []
    def tr(self, d):
        self.calls.append(d)
        if d["url"].endswith("/rest/user/login"):
            return {"authentication": {"token": "T", "bid": 6}}
        if d["url"].endswith("/api/Users"):
            return {"status": "success"}
        if d["url"].endswith("/profile/image/url"):
            cookie = (d.get("headers") or {}).get("Cookie", "")
            if "server-side" in (d.get("raw_body") or "") and "token=" in cookie:
                self.solved.add("ssrfChallenge")
            return {"status_code": 200}
        return {"status_code": 200}
    def ch(self):
        return {"data": [{"key": "ssrfChallenge", "solved": "ssrfChallenge" in self.solved}]}


def _roe(**ov):
    roe = {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [AEC, SM],
        "allowed_http_methods": ["GET", "POST"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [SM],
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900},
    }
    roe.update(ov)
    return roe


def _token(broker):
    card = broker.request_approval(action_class=SM, primitive_id="ssrf-profile-image",
                                   target=_TARGET, http_method="POST", orchestration_id="o")
    return broker.approve(card["approval_id"], approver="a")


def test_ssrf_solves_with_cookie_and_internal_url():
    shop = FakeShop(); b = ab.ApprovalBroker()
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch,
                                      approval_broker=b, enable_classes=[AEC, SM])
    run = gw.run_chain("o", _TARGET, ["auth-lab-user", "ssrf-profile-image"],
                       parameters={"ssrf-profile-image": {"raw_body": _BODY,
                                                          "content_type": "application/x-www-form-urlencoded"}},
                       approval_tokens={SM: _token(b)})
    assert "ssrfChallenge" in run["solved_challenges"]
    ssrf_call = [c for c in shop.calls if c["url"].endswith("/profile/image/url")][0]
    assert ssrf_call["headers"]["Cookie"].startswith("token=")
    assert ssrf_call["content_type"] == "application/x-www-form-urlencoded"


def test_ssrf_requires_approval():
    shop = FakeShop()
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch, enable_classes=[AEC, SM])
    run = gw.run_chain("o", _TARGET, ["auth-lab-user", "ssrf-profile-image"],
                       parameters={"ssrf-profile-image": {"raw_body": _BODY, "content_type": "application/x-www-form-urlencoded"}})
    step = [s for s in run["steps"] if s["primitive_id"] == "ssrf-profile-image"][0]
    assert step["outcome"] == "REVIEW_REQUIRED"
    assert "ssrfChallenge" not in run["solved_challenges"]


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
