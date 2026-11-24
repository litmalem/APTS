"""Stage 7.3 acceptance — LAB session broker.

Hermetic: a fake transport stands in for the Stage 6-AE gateway's HTTP (the VM
cannot reach the user's localhost). Proves: eligibility composition with Stage
7.1, fail-closed without transport / credential permission / loopback, token
extraction + planner-legal session facts, and that raw secrets are never
persisted. No real network I/O.
Run: python3 tests/test_stage7_3_session_broker.py  (or via pytest)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import session_broker as sb
from pentest_subsystem import symbolic_planner as sp
from pentest_subsystem.exploit_primitive_library import F_SESSION_AUTH, F_SESSION_ADMIN

_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}
_TOKEN = "eyJhbGciOiJID.FAKE-LAB.JWT_TOKEN"


class FakeTransport:
    def __init__(self, token=_TOKEN):
        self.calls = []
        self.token = token
    def __call__(self, d):
        self.calls.append(d)
        if d["url"].endswith("/rest/user/login"):
            return {"authentication": {"token": self.token, "bid": 1, "umail": d["json"]["email"]}}
        return {"status": "success", "data": {"id": 1, "email": d["json"]["email"]}}


def _lab_roe(**ov):
    roe = {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [sb.ACTION_CLASS_ACTIVE_EXPLOITATION],
        "allowed_http_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "allowed_auth_modes": [sb.AUTH_MODE_SELF_REGISTERED],
        "credential_usage_allowed": True,
        "human_approval_required_for": [],
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900},
    }
    roe.update(ov)
    return roe


def test_requires_credential_permission():
    b = sb.SessionBroker(_lab_roe(credential_usage_allowed=False), transport=FakeTransport())
    cref = b.provision_lab_credential()
    try:
        b.authenticate(cref, _TARGET); assert False, "should refuse"
    except sb.SessionBrokerError as e:
        assert "AE-CREDENTIAL" in str(e)


def test_no_transport_is_fail_closed():
    b = sb.SessionBroker(_lab_roe(), transport=None)
    cref = b.provision_lab_credential()
    try:
        b.authenticate(cref, _TARGET); assert False
    except sb.SessionBrokerError as e:
        assert "no transport" in str(e)


def test_successful_user_auth():
    t = FakeTransport()
    b = sb.SessionBroker(_lab_roe(), transport=t)
    cref = b.provision_lab_credential("user")
    sref = b.authenticate(cref, _TARGET)
    assert b.get_token(sref) == _TOKEN
    assert b.session_facts(sref) == [F_SESSION_AUTH]
    paths = [c["url"] for c in t.calls]
    assert any(u.endswith("/api/Users") for u in paths)
    assert any(u.endswith("/rest/user/login") for u in paths)


def test_admin_session_facts():
    b = sb.SessionBroker(_lab_roe(), transport=FakeTransport())
    sref = b.authenticate(b.provision_lab_credential("admin"), _TARGET)
    assert set(b.session_facts(sref)) == {F_SESSION_AUTH, F_SESSION_ADMIN}


def test_raw_secret_not_persisted():
    b = sb.SessionBroker(_lab_roe(), transport=FakeTransport())
    cref = b.provision_lab_credential()
    sref = b.authenticate(cref, _TARGET)
    assert b._pending_secrets == {}
    assert "password" not in b._sessions[sref]
    ev = b.session_evidence(sref)
    assert ev["raw_secret_persisted"] is False
    assert ev["token_sha256"] != _TOKEN and len(ev["token_sha256"]) == 64
    dom = sb.SESSION_EVIDENCE_HASH_DOMAIN
    core = {k: v for k, v in ev.items() if k != "integrity"}
    assert ev["integrity"]["canonical_sha256"] == sb.sha256_hex({"hash_domain": dom, "core": core})


def test_non_loopback_refused():
    b = sb.SessionBroker(_lab_roe(target_allowlist=[]), transport=FakeTransport())
    cref = b.provision_lab_credential()
    try:
        b.authenticate(cref, {"target_type": "URL", "target_value": "http://10.0.0.5:3000"})
        assert False
    except sb.SessionBrokerError as e:
        assert "AE-LOOPBACK" in str(e)


def test_teardown_clears_sessions():
    b = sb.SessionBroker(_lab_roe(), transport=FakeTransport())
    b.authenticate(b.provision_lab_credential(), _TARGET)
    assert b.teardown() == 1
    assert b._sessions == {}


def test_facts_are_planner_legal():
    b = sb.SessionBroker(_lab_roe(), transport=FakeTransport())
    sref = b.authenticate(b.provision_lab_credential("admin"), _TARGET)
    for f in b.session_facts(sref):
        assert f in (F_SESSION_AUTH, F_SESSION_ADMIN)
        assert sp.FACT.fullmatch(f)


def test_loopback_transport_refuses_nonloopback_without_io():
    tr = sb.LoopbackHttpTransport()
    try:
        tr({"method": "POST", "url": "http://10.0.0.5/x", "json": {}}); assert False
    except sb.SessionBrokerError as e:
        assert "non-loopback" in str(e)


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
