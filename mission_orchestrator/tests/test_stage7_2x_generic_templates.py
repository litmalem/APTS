"""Stage 7.2x acceptance — generic BAC templates + Juice pack as data.

Proves: (1) every target-agnostic template instantiates into a plan-legal,
challenge-key-free primitive; (2) an instantiated template flows through the real
symbolic_planner AND through the gateway+generic-oracle to EXPLOITED on a target
with no scoreboard; (3) the exploit-primitive library now DERIVES its catalog from
the OWASP Juice Shop knowledge pack, and each Juice primitive conforms to the
generic template the pack maps it to.
Run: python3 tests/test_stage7_2x_generic_templates.py  (or via pytest)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import symbolic_planner as sp
from pentest_subsystem import bac_primitive_templates as tpl
from pentest_subsystem import exploit_primitive_library as lib
from pentest_subsystem import active_exploitation_execution as ae
from pentest_subsystem import cae_success_oracle as so
from pentest_subsystem.exploit_primitive_library import PRIMITIVES
from pentest_subsystem.knowledge_packs import owasp_juice_shop as pack

_TARGET = {"target_type": "URL", "target_value": "http://127.0.0.1:3000"}


# --------------------------- templates are reusable ------------------------
def test_every_template_instantiates_plan_legal_and_generic():
    for tid in tpl.TEMPLATE_IDS:
        p = tpl.instantiate(tid, primitive_id=f"gen-{tid}", endpoint_template="/x/{id}",
                            owner_field="body.data.UserId")
        assert p["challenge_key"] is None          # target-agnostic, no scoreboard
        assert p["template"] == tid
        m = sp.normalize_model(p["planning_model"])  # raises if illegal
        assert m["effects"], tid
        assert p["action_class"] in lib.CAE_ACTION_CLASSES


def test_instantiate_requires_endpoint():
    try:
        tpl.instantiate("idor-read", primitive_id="x", endpoint_template="")
        assert False, "expected TemplateError"
    except tpl.TemplateError:
        pass


def test_generic_idor_predicate_structured_not_scoreboard():
    p = tpl.instantiate("idor-read", primitive_id="g", endpoint_template="/rest/basket/{id}",
                        owner_field="body.data.UserId", self_ref="self.userId")
    assert isinstance(p["success_predicate"], dict)          # structured, evidence-based
    oracle = so.SuccessOracle()
    ctx = {"status_code": 200, "response": {"data": {"UserId": 2}}, "session": {"userId": 9}}
    assert oracle.verdict(p["success_predicate"], ctx) == so.CONFIRMED


# --------------------------- template -> planner -> gateway ----------------
class _FakeBackend:
    def transport(self, d):
        url = d["url"]
        if url.endswith("/api/Users"):
            return {"status": "success", "data": {"id": 1}}
        if url.endswith("/rest/user/login"):
            return {"authentication": {"token": "LAB.JWT", "bid": 6}}
        if "/rest/basket/" in url:
            return {"status_code": 200, "data": {"id": 2}}  # someone else's basket
        return {"status_code": 200}
    def challenges(self):
        return {"data": []}


def test_instantiated_template_exploits_via_gateway():
    p = tpl.instantiate("idor-read", primitive_id="gen-idor-basket",
                        endpoint_template="/rest/basket/{id}",
                        requires=["auth-lab-user"], owner_field="body.data.id",
                        self_ref="self.basketId")
    PRIMITIVES["gen-idor-basket"] = p
    try:
        js = _FakeBackend()
        gw = ae.ActiveExploitationGateway(
            {"active_exploitation_allowed": True,
             "allowed_action_classes": [ae.ACTION_CLASS_ACTIVE_EXPLOITATION],
             "allowed_http_methods": ["GET", "POST"], "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT"],
             "credential_usage_allowed": True, "human_approval_required_for": [],
             "target_allowlist": ["127.0.0.1:3000"], "environment": "LAB",
             "blast_radius": {"max_mutations": 20, "max_requests": 200, "max_duration_s": 900}},
            transport=js.transport, oracle_fetcher=js.challenges, success_oracle=so.SuccessOracle())
        run = gw.run_chain("orch", _TARGET, ["auth-lab-user", "gen-idor-basket"],
                           parameters={"gen-idor-basket": {"id": 2}})
    finally:
        PRIMITIVES.pop("gen-idor-basket", None)
    step = [s for s in run["steps"] if s["primitive_id"] == "gen-idor-basket"][0]
    assert step["outcome"] == "EXPLOITED" and step["oracle_verdict"] == so.CONFIRMED
    assert run["solved_challenges"] == []


# --------------------------- library derives from pack ---------------------
def test_library_catalog_derived_from_pack():
    pack_ids = {p["primitive_id"] for p in pack.JUICE_PRIMITIVES}
    assert set(PRIMITIVES) == pack_ids
    # the Juice catalog is a MOVED copy, not re-authored: live counts match
    assert len(lib._CATALOG) == len(pack.JUICE_PRIMITIVES) == 14
    assert hasattr(lib, "instantiate_template") and lib.TEMPLATE_IDS == tpl.TEMPLATE_IDS


def test_each_juice_primitive_conforms_to_its_template():
    for pid, template_id in pack.PRIMITIVE_TEMPLATE_MAP.items():
        if template_id is None:
            continue  # enablers (auth / sqli) are not BAC templates
        assert tpl.conforms(PRIMITIVES[pid], template_id), (pid, template_id)


def test_bac_coverage_unchanged():
    for key in ("basketAccessChallenge", "adminSectionChallenge", "basketManipulateChallenge",
                "forgedFeedbackChallenge", "forgedReviewChallenge", "changeProductChallenge",
                "ssrfChallenge", "csrfChallenge", "feedbackChallenge",
                "web3SandboxChallenge", "easterEggLevelOneChallenge"):
        assert key in lib.BROKEN_ACCESS_CONTROL_CHALLENGES, key


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
