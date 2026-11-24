"""Stage 7.4c acceptance — admin escalation via SQLi login.

`escalate-admin-sqli` injects `' OR 1=1--` at the login endpoint to obtain an
admin session (solving Login Admin), which then unlocks Admin Section (SPA via the
Stage 7.4b browser transport) and Five-Star Feedback (DESTRUCTIVE, double-approval).
Hermetic: a fake shop recognises the SQLi payload. No real network I/O.
Run: python3 tests/test_stage7_4c_admin_escalation.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import approval_broker as ab
from pentest_subsystem import active_exploitation_execution as ae
from pentest_subsystem import exploit_primitive_library as lib

AEC = ae.ACTION_CLASS_ACTIVE_EXPLOITATION
DESTR = ae.ACTION_CLASS_DESTRUCTIVE
ALL = [AEC, ae.ACTION_CLASS_STATE_MUTATION, DESTR]
_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


class FakeShop:
    def __init__(self): self.solved = set()
    def tr(self, d):
        if d["url"].endswith("/rest/user/login"):
            email = (d.get("json") or {}).get("email", "")
            if "1=1" in email or "'" in email:
                self.solved.add("loginAdminChallenge")
                return {"authentication": {"token": "ADMIN.JWT", "umail": "admin@juice-sh.op", "bid": 1}}
            return {"authentication": {"token": "T", "bid": 6}}
        if d["url"].endswith("/api/Users"):
            return {"status": "success"}
        if d["method"] == "DELETE" and "/api/Feedbacks/" in d["url"]:
            self.solved.add("feedbackChallenge")
            return {"status_code": 200}
        return {"status_code": 200}
    def ch(self):
        keys = ("loginAdminChallenge", "adminSectionChallenge", "feedbackChallenge")
        return {"data": [{"key": k, "solved": k in self.solved} for k in keys]}


class FakeBrowser:
    def __init__(self, shop): self.shop = shop
    def __call__(self, spa):
        if "/administration" in spa["route"]:
            self.shop.solved.add("adminSectionChallenge")
        return {"navigated": True}


def _roe(**ov):
    roe = {
        "active_exploitation_allowed": True,
        "allowed_action_classes": ALL,
        "allowed_http_methods": ["GET", "POST", "DELETE"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT", "SQLI_LOGIN_LAB_ONLY"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [DESTR],
        "destructive_actions_allowed": True,
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 50, "max_requests": 500, "max_duration_s": 900},
    }
    roe.update(ov)
    return roe


def test_sqli_escalation_solves_login_admin():
    shop = FakeShop()
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch, enable_classes=ALL)
    run = gw.run_chain("o", _TARGET, ["escalate-admin-sqli"])
    assert "loginAdminChallenge" in run["solved_challenges"]
    assert run["steps"][0]["outcome"] == "SESSION_ESTABLISHED" and run["steps"][0]["via"] == "SQLI"


def test_admin_section_via_sqli_and_browser():
    shop = FakeShop(); br = FakeBrowser(shop)
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch,
                                      browser_transport=br, enable_classes=ALL)
    run = gw.run_chain("o", _TARGET, lib.primitives_for_challenge("adminSectionChallenge"))
    assert "adminSectionChallenge" in run["solved_challenges"]


def test_five_star_via_sqli_destructive():
    shop = FakeShop(); b = ab.ApprovalBroker()
    c1 = b.request_approval(action_class=DESTR, primitive_id="destroy-5star-feedback", target=_TARGET, http_method="DELETE", orchestration_id="o")
    c2 = b.request_approval(action_class=DESTR, primitive_id="destroy-5star-feedback", target=_TARGET, http_method="DELETE", orchestration_id="o")
    toks = [b.approve(c1["approval_id"], approver="a"), b.approve(c2["approval_id"], approver="z")]
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch,
                                      approval_broker=b, enable_classes=ALL)
    run = gw.run_chain("o", _TARGET, lib.primitives_for_challenge("feedbackChallenge"),
                       parameters={"destroy-5star-feedback": {"id": 5}}, approval_tokens={DESTR: toks})
    assert "feedbackChallenge" in run["solved_challenges"]


def test_sqli_blocked_without_auth_mode():
    shop = FakeShop()
    gw = ae.ActiveExploitationGateway(_roe(allowed_auth_modes=["SELF_REGISTERED_LAB_ACCOUNT"]),
                                      transport=shop.tr, oracle_fetcher=shop.ch, enable_classes=ALL)
    run = gw.run_chain("o", _TARGET, ["escalate-admin-sqli"])
    assert run["steps"][0]["outcome"] == "BLOCKED"
    assert "loginAdminChallenge" not in run["solved_challenges"]


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
