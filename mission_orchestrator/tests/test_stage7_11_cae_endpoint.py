"""Stage 7.11 acceptance — CAE wired into the pentest service (:8790 via Control Center :8800).

Proves the fail-closed RoE gate and the endpoint dispatch WITHOUT touching a target:
master-switch off -> blocked & executor never called; missing arm token / non-loopback /
SPA / unknown challenge -> blocked with the right reason; fully armed -> executor invoked
with the resolved target+challenges and its sealed result surfaced. Network is never hit:
the executor is injected as a fake.
Run: python3 tests/test_stage7_11_cae_endpoint.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import cae_service_runner as C

ARMED = {"APTS_CAE_ROE_MASTER": "ARM"}


def test_gate_master_off_blocks():
    d = C.evaluate_cae_request({}, {"arm": C.CAE_ARM_TOKEN})
    assert d["allowed"] is False and d["reason"] == "CAE_ROE_MASTER_OFF"


def test_gate_requires_arm_token():
    d = C.evaluate_cae_request(ARMED, {})
    assert d["allowed"] is False and d["reason"] == "ARM_TOKEN_REQUIRED"


def test_gate_rejects_non_loopback():
    d = C.evaluate_cae_request(ARMED, {"arm": C.CAE_ARM_TOKEN, "target": "http://10.0.0.5:3000"})
    assert d["allowed"] is False and d["reason"] == "NON_LOOPBACK_TARGET"


def test_gate_rejects_spa_and_unknown():
    spa = C.evaluate_cae_request(ARMED, {"arm": C.CAE_ARM_TOKEN, "challenges": ["web3SandboxChallenge"]})
    assert spa["reason"] == "SPA_REQUIRES_HOST_RUNNER"
    unk = C.evaluate_cae_request(ARMED, {"arm": C.CAE_ARM_TOKEN, "challenges": ["nopeChallenge"]})
    assert unk["reason"] == "UNKNOWN_CHALLENGES"


def test_gate_allows_when_armed():
    d = C.evaluate_cae_request(ARMED, {"arm": C.CAE_ARM_TOKEN, "challenges": ["basketAccessChallenge"]})
    assert d["allowed"] is True and d["target"] == C.BASE and d["challenges"] == ["basketAccessChallenge"]


def test_handle_blocks_without_executing():
    calls = []
    code, payload = C.handle_cae_execute({}, {"arm": C.CAE_ARM_TOKEN}, executor=lambda *a, **k: calls.append(a))
    assert code == 403 and payload["executed"] is False and payload["cae"] == "FAIL_CLOSED"
    assert calls == []  # executor must NOT run when fail-closed


def test_handle_executes_when_armed():
    seen = {}
    def fake(target, challenges):
        seen["target"], seen["challenges"] = target, challenges
        return {"target": target, "solved_before": 0, "solved_after": 2,
                "newly_solved": ["basketAccessChallenge", "ssrfChallenge"], "results": [], "integrity": {"x": 1}}
    code, payload = C.handle_cae_execute(ARMED, {"arm": C.CAE_ARM_TOKEN, "challenges": ["basketAccessChallenge"]}, executor=fake)
    assert code == 200 and payload["executed"] is True and payload["cae"] == "EXECUTED"
    assert payload["solved_after"] == 2 and payload["newly_solved"][0] == "basketAccessChallenge"
    assert seen["target"] == C.BASE and seen["challenges"] == ["basketAccessChallenge"]


def test_default_challenges_exclude_spa():
    assert set(C.DEFAULT_CHALLENGES).isdisjoint(set(C.SPA))
    assert "ssrfChallenge" in C.DEFAULT_CHALLENGES and "web3SandboxChallenge" not in C.DEFAULT_CHALLENGES


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
