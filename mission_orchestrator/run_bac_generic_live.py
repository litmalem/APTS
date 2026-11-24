#!/usr/bin/env python3
r"""Stage 7 Fase 5 — GENERIC BAC pipeline, LIVE host runner.

Unlike run_cae_live.py (which is handed a hardcoded Juice challenge list), this
runner drives the *general* pipeline end-to-end:

    authorized surface import  ->  BAC hypothesis synthesis (Stage 7.3x)
      ->  symbolic plan (real planner)  ->  CAE gateway + evidence oracle (7.1x/7.4x)
      ->  cross-validate against the Juice scoreboard (corroborator, not mechanism)

No challenge keys drive execution; solves are judged by response evidence. The
Juice scoreboard is only read to CONFIRM the generic oracle agrees with ground
truth. Run ON THE WINDOWS HOST with Juice Shop up on http://127.0.0.1:3000 :

    python run_bac_generic_live.py                 # read-active-safe surface only
    python run_bac_generic_live.py --include-mutations   # + approval-gated mutations

Reset Juice Shop before a mutation run. Every actuation is RoE-guarded, loopback-only.
"""
from __future__ import annotations

import argparse
import json
import urllib.request

from pentest_subsystem import bac_hypothesis_synthesis as syn
from pentest_subsystem import symbolic_planner as sp
from pentest_subsystem import cae_service_runner as csr
from pentest_subsystem.session_broker import LoopbackHttpTransport
from pentest_subsystem.knowledge_packs import owasp_juice_shop as pack

BASE = "http://127.0.0.1:3000"
TARGET = {"target_type": "URL", "target_value": BASE}


def _req(method, path):
    r = urllib.request.Request(BASE + path, method=method,
                               headers={"Accept": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def scoreboard():
    return {c["key"]: bool(c.get("solved"))
            for c in _req("GET", "/api/Challenges/").get("data", []) if c.get("key")}


def main():
    ap = argparse.ArgumentParser(description="Generic BAC pipeline live runner (loopback Juice Shop)")
    ap.add_argument("--include-mutations", action="store_true",
                    help="also attempt approval-gated mutation hypotheses (reset Juice first)")
    args = ap.parse_args()

    # 1) Authorized surface import (stands in for a bounded enumeration run).
    enumeration = pack.bac_surface_enumeration()
    if not args.include_mutations:
        enumeration["endpoint_discoveries"] = [
            e for e in enumeration["endpoint_discoveries"]
            if e["attributes"]["endpoint"] in pack.READ_ACTIVE_SAFE]

    # 2) Synthesise BAC hypotheses from the surface (no challenge keys).
    hypotheses = syn.synthesize_bac_hypotheses(enumeration, target=TARGET)
    print(f"Target: {BASE}")
    print(f"Synthesised {len(hypotheses)} BAC hypotheses from imported surface:")
    for h in hypotheses:
        print(f"  - {h['hypothesis_id']}  [{h['cae']['template']}]  {h['cae']['endpoint_template']}")

    # 3) Symbolic plan (prove causal chains form).
    run_in = syn.make_bac_hypothesis_run("bac-live", "juice-bac", TARGET, enumeration)
    plan = sp.plan(sp.compile_problem({"task": {"objective": {}}}, run_in))
    print(f"\nPlanner: {plan['status']}  ({len(plan.get('paths', []))} candidate path(s))")

    # 4) Execute through the generic gateway + evidence oracle (no scoreboard).
    before = scoreboard()
    out = csr.execute_bac_generic(BASE, hypotheses=hypotheses, transport=LoopbackHttpTransport(),
                                  identity_probe=pack.SELF_IDENTITY_PROBE)
    after = scoreboard()

    print("\nGateway results (judged by evidence oracle):")
    for r in out["results"]:
        print(f"  - {r['hypothesis_id']}: {r.get('outcome')} "
              f"(verdict={r.get('oracle_verdict')}, stop={r.get('stop_reason')})")

    # 5) Cross-validate against the Juice scoreboard (corroborator only).
    xval = csr.cross_validate_with_scoreboard(out, before, after, pack.BAC_SURFACE_CHALLENGE_MAP)
    print(f"\nScoreboard cross-validation: agreed={xval['agreed']}")
    for a in xval["agreements"]:
        print(f"  AGREE  {a['challenge']}: oracle={a['oracle_exploited']} scoreboard={a['scoreboard_solved']}")
    for d in xval["disagreements"]:
        print(f"  DISAGREE  {d['challenge']}: oracle={d['oracle_exploited']} scoreboard={d['scoreboard_solved']}")
    print(f"\nExploited (by oracle): {out['exploited']}")


if __name__ == "__main__":
    main()
