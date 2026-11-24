"""Stage 7.5 acceptance — human approval queue + single-use action-bound tokens.

Proves the approval broker lifecycle (request -> approve/deny -> single-use,
action-bound, time-bound consume, emergency stop) and its integration with the
Stage 6-AE gateway: a class in `human_approval_required_for` is REVIEW_REQUIRED
without a valid token and actuates only after a matching token is consumed; a
reused token is rejected; emergency stop halts the run and revokes tokens.
No network I/O. Run: python3 tests/test_stage7_5_approval_broker.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import approval_broker as ab
from pentest_subsystem import active_exploitation_execution as ae

AEC = ae.ACTION_CLASS_ACTIVE_EXPLOITATION
_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


class FakeJuiceShop:
    def __init__(self): self.solved = set()
    def tr(self, d):
        if d["url"].endswith("/rest/user/login"):
            return {"authentication": {"token": "LAB.JWT"}}
        if "/ftp" in d["url"]:
            self.solved.add("easterEggLevelOneChallenge")
        return {"status_code": 200}
    def ch(self):
        return {"data": [{"key": "easterEggLevelOneChallenge", "solved": "easterEggLevelOneChallenge" in self.solved}]}


def _roe(**ov):
    roe = {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [AEC],
        "allowed_http_methods": ["GET", "POST"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [AEC],
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900},
    }
    roe.update(ov)
    return roe


def _approved_token(broker, primitive_id="forced-browse-easter-egg"):
    card = broker.request_approval(action_class=AEC, primitive_id=primitive_id, target=_TARGET,
                                   http_method="GET", orchestration_id="o")
    return broker.approve(card["approval_id"], approver="alice"), card["approval_id"]


# -- broker lifecycle -------------------------------------------------------
def test_approve_mint_consume():
    b = ab.ApprovalBroker()
    tok, aid = _approved_token(b)
    binding = b.validate_and_consume(tok, action_class=AEC, primitive_id="forced-browse-easter-egg", target=_TARGET)
    assert binding["primitive_id"] == "forced-browse-easter-egg"
    assert b.status(aid) == ab.S_CONSUMED


def test_single_use():
    b = ab.ApprovalBroker()
    tok, _ = _approved_token(b)
    b.validate_and_consume(tok, action_class=AEC, primitive_id="forced-browse-easter-egg", target=_TARGET)
    try:
        b.validate_and_consume(tok, action_class=AEC, primitive_id="forced-browse-easter-egg", target=_TARGET)
        assert False
    except ab.ApprovalError as e:
        assert "consumed" in str(e)


def test_binding_mismatch():
    b = ab.ApprovalBroker()
    tok, _ = _approved_token(b)
    try:
        b.validate_and_consume(tok, action_class=AEC, primitive_id="idor-read-basket", target=_TARGET)
        assert False
    except ab.ApprovalError as e:
        assert "binding mismatch" in str(e)


def test_expired_token():
    clk = Clock()
    b = ab.ApprovalBroker(clock=clk, ttl_seconds=60)
    tok, _ = _approved_token(b)
    clk.t += 120  # past TTL
    try:
        b.validate_and_consume(tok, action_class=AEC, primitive_id="forced-browse-easter-egg", target=_TARGET)
        assert False
    except ab.ApprovalError as e:
        assert "expired" in str(e)


def test_deny_blocks():
    b = ab.ApprovalBroker()
    card = b.request_approval(action_class=AEC, primitive_id="forced-browse-easter-egg", target=_TARGET,
                              http_method="GET", orchestration_id="o")
    b.deny(card["approval_id"], approver="alice", reason="not in scope")
    assert b.status(card["approval_id"]) == ab.S_DENIED


def test_emergency_stop_revokes():
    b = ab.ApprovalBroker()
    _approved_token(b); _approved_token(b)
    n = b.emergency_stop()
    assert n == 2 and b.halted is True
    try:
        b.request_approval(action_class=AEC, primitive_id="x", target=_TARGET, http_method="GET", orchestration_id="o")
        assert False
    except ab.ApprovalError:
        pass


def test_record_sealed_no_raw_token():
    b = ab.ApprovalBroker()
    tok, aid = _approved_token(b)
    rec = b.record(aid)
    dom = ab.APPROVAL_RECORD_HASH_DOMAIN
    core = {k: v for k, v in rec.items() if k != "integrity"}
    assert rec["integrity"]["canonical_sha256"] == ab.sha256_hex({"hash_domain": dom, "core": core})
    assert rec["token_sha256"] and rec["token_sha256"] != tok


# -- gateway integration ----------------------------------------------------
def test_gateway_blocks_without_token():
    js = FakeJuiceShop()
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch)
    run = gw.run_chain("o", _TARGET, ["forced-browse-easter-egg"])
    assert run["steps"][0]["outcome"] == "REVIEW_REQUIRED"
    assert run["solved_challenges"] == []


def test_gateway_proceeds_with_valid_token():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    tok, _ = _approved_token(b)
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch, approval_broker=b)
    run = gw.run_chain("o", _TARGET, ["forced-browse-easter-egg"], approval_tokens={AEC: tok})
    assert "easterEggLevelOneChallenge" in run["solved_challenges"]
    assert run["steps"][0]["outcome"] == "EXPLOITED"


def test_gateway_rejects_reused_token():
    b = ab.ApprovalBroker()
    tok, _ = _approved_token(b)
    js1 = FakeJuiceShop()
    ae.ActiveExploitationGateway(_roe(), transport=js1.tr, oracle_fetcher=js1.ch, approval_broker=b)\
        .run_chain("o", _TARGET, ["forced-browse-easter-egg"], approval_tokens={AEC: tok})
    js2 = FakeJuiceShop()
    run2 = ae.ActiveExploitationGateway(_roe(), transport=js2.tr, oracle_fetcher=js2.ch, approval_broker=b)\
        .run_chain("o", _TARGET, ["forced-browse-easter-egg"], approval_tokens={AEC: tok})
    assert run2["steps"][0]["outcome"] == "BLOCKED"
    assert "APPROVAL_INVALID" in run2["steps"][0]["reason"]
    assert run2["solved_challenges"] == []


def test_emergency_stop_halts_gateway():
    js = FakeJuiceShop(); b = ab.ApprovalBroker()
    _approved_token(b)
    gw = ae.ActiveExploitationGateway(_roe(), transport=js.tr, oracle_fetcher=js.ch, approval_broker=b)
    revoked = gw.emergency_stop()
    assert revoked == 1 and b.halted is True
    run = gw.run_chain("o", _TARGET, ["forced-browse-easter-egg"])
    assert run["stop_reason"] == "KILL_SWITCH" and run["solved_challenges"] == []


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
