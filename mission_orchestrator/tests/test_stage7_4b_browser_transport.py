"""Stage 7.4b acceptance — browser transport for SPA_NAV primitives.

A fake browser transport stands in for a real SPA navigation (the VM has no
browser): when it "navigates" a route, the shared fake shop marks the frontend-
detected challenge solved, and the gateway confirms via the oracle. Proves: Web3
Sandbox solves via browser transport; Admin needs an admin session; without a
browser transport SPA steps stay REQUIRES_BROWSER_TRANSPORT; loopback guard holds.
Run: python3 tests/test_stage7_4b_browser_transport.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import active_exploitation_execution as ae
from pentest_subsystem import exploit_primitive_library as lib

AEC = ae.ACTION_CLASS_ACTIVE_EXPLOITATION
_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


class FakeShop:
    def __init__(self): self.solved = set()
    def tr(self, d):
        if d["url"].endswith("/rest/user/login"):
            return {"authentication": {"token": "T", "bid": 6}}
        if d["url"].endswith("/api/Users"):
            return {"status": "success"}
        return {"status_code": 200}
    def ch(self):
        return {"data": [{"key": k, "solved": k in self.solved}
                         for k in ("web3SandboxChallenge", "adminSectionChallenge")]}


class FakeBrowser:
    def __init__(self, shop): self.shop = shop; self.calls = []
    def __call__(self, spa):
        self.calls.append(spa)
        if "/web3-sandbox" in spa["route"]:
            self.shop.solved.add("web3SandboxChallenge")
        if "/administration" in spa["route"]:
            self.shop.solved.add("adminSectionChallenge")
        return {"navigated": True}


def _roe(**ov):
    roe = {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [AEC],
        "allowed_http_methods": ["GET", "POST"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [],
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900},
    }
    roe.update(ov)
    return roe


def test_web3_solves_via_browser_transport():
    shop = FakeShop(); br = FakeBrowser(shop)
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch, browser_transport=br)
    run = gw.run_chain("o", _TARGET, ["forced-browse-web3-sandbox"])
    assert "web3SandboxChallenge" in run["solved_challenges"]
    step = run["steps"][0]
    assert step["outcome"] == "EXPLOITED" and step["delivery"] == "SPA_NAV"
    assert br.calls and br.calls[0]["route"] == "/#/web3-sandbox"


def test_no_browser_transport_defers():
    shop = FakeShop()
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch)
    run = gw.run_chain("o", _TARGET, ["forced-browse-web3-sandbox"])
    assert run["steps"][0]["outcome"] == "REQUIRES_BROWSER_TRANSPORT"
    assert run["solved_challenges"] == []


def test_admin_needs_admin_session():
    shop = FakeShop(); br = FakeBrowser(shop)
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch, browser_transport=br)
    run = gw.run_chain("o", _TARGET, ["auth-lab-user", "forced-browse-admin"])  # non-admin session
    step = [s for s in run["steps"] if s["primitive_id"] == "forced-browse-admin"][0]
    assert step["outcome"] == "BLOCKED" and step["reason"] == "NEEDS_ADMIN_SESSION"
    assert "adminSectionChallenge" not in run["solved_challenges"]


def test_admin_solves_with_admin_session():
    shop = FakeShop(); br = FakeBrowser(shop)
    gw = ae.ActiveExploitationGateway(_roe(), transport=shop.tr, oracle_fetcher=shop.ch, browser_transport=br)
    run = gw.run_chain("o", _TARGET, ["auth-lab-admin", "forced-browse-admin"])
    assert "adminSectionChallenge" in run["solved_challenges"]
    step = [s for s in run["steps"] if s["primitive_id"] == "forced-browse-admin"][0]
    assert step["outcome"] == "EXPLOITED"


def test_spa_non_loopback_blocked():
    shop = FakeShop(); br = FakeBrowser(shop)
    gw = ae.ActiveExploitationGateway(_roe(target_allowlist=[]), transport=shop.tr, oracle_fetcher=shop.ch, browser_transport=br)
    run = gw.run_chain("o", {"target_type": "URL", "target_value": "http://10.0.0.5:3000"},
                       ["forced-browse-web3-sandbox"])
    step = run["steps"][0]
    assert step["outcome"] == "BLOCKED" and "AE-LOOPBACK" in step["failed_rule_ids"]
    assert br.calls == []


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
