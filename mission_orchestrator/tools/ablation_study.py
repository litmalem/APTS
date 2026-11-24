"""Deterministic SIMULATION ablation: fixed-order pipeline vs agentic controller (Phase 1+2+4 logic).

This is NOT empirical evidence about real targets. It runs the real decision code (`deliberate`, `decide`, learned
reliability) against a toy world with fixed yields, so that structural claims (fewer target-touching actions, stop on
coverage, no noisy actions after an adverse condition) are checkable and reproducible. Run from mission_orchestrator/:

    python tools/ablation_study.py            # prints a markdown table and JSON
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pentest_subsystem.orchestration.deliberation import deliberate  # noqa: E402
from pentest_subsystem.orchestration.perception_action import (  # noqa: E402
    STOPPING_RULE, TECHNIQUE_CATALOG, coverage, decide, new_state)
from pentest_subsystem.orchestration.task_graph import CAPABILITY_SEQUENCE  # noqa: E402

SCENARIOS = {
    "clean_target":      {"assets": 2, "surface": 10, "hypotheses": 0, "adverse_if_noisy": False},
    "vulnerable_target": {"assets": 2, "surface": 10, "hypotheses": 4, "adverse_if_noisy": False},
    "rate_limited":      {"assets": 2, "surface": 10, "hypotheses": 4, "adverse_if_noisy": True},
    "large_surface":     {"assets": 5, "surface": 40, "hypotheses": 6, "adverse_if_noisy": False},
}
ENUM = sorted(TECHNIQUE_CATALOG["enumeration"])


def _surface(n):
    return {d: {"total": n, "remaining": n} for d in ("unprofiled_services", "unversioned_services",
                                                      "unprobed_endpoints", "unobserved_config")}


def _apply(surface, technique, noisy_block):
    dim, yld, _cost, noise = TECHNIQUE_CATALOG["enumeration"][technique]
    if noisy_block and noise > 0:       # a rate-limited target rejects noisy techniques: nothing learned
        return 0
    found = min(surface[dim]["remaining"], math.ceil(yld * surface[dim]["remaining"]))
    surface[dim]["remaining"] -= found
    return found


def _cov(surface):
    t = sum(v["total"] for v in surface.values())
    return 1.0 if t == 0 else 1 - sum(v["remaining"] for v in surface.values()) / t


def run_fixed(sc):
    """Baseline: all 7 capabilities in canonical order; enumeration runs EVERY technique once, no feedback."""
    surface = _surface(sc["surface"])
    probes = noise = adverse = 0
    first_validation = None
    steps = 0
    for cap in CAPABILITY_SEQUENCE:
        steps += 1
        if cap == "enumeration":
            for tech in ENUM:
                probes += 1
                n = TECHNIQUE_CATALOG["enumeration"][tech][3]
                noise += n
                adverse += int(sc["adverse_if_noisy"] and n > 0)
                _apply(surface, tech, sc["adverse_if_noisy"])
        if cap == "validation" and sc["hypotheses"]:
            first_validation = steps
    return {"controller": "fixed_pipeline", "capabilities_run": len(CAPABILITY_SEQUENCE), "probing_actions": probes,
            "noise_units": noise, "adverse_noisy_actions": adverse, "final_coverage": round(_cov(surface), 3),
            "steps_to_first_validation": first_validation}


def run_agentic(sc, *, budget=30):
    """Agentic: deliberation picks capabilities; information-gain loop picks enumeration techniques and stops."""
    surface = _surface(sc["surface"])
    graph = {"orchestration_id": "sim", "plan_version": 1,
             "nodes": [{"capability_id": c, "subtask_id": "s-" + c, "status": "PENDING"} for c in CAPABILITY_SEQUENCE]}
    world = dict(in_scope_assets=0, enumerated_assets=0, open_hypotheses=0, candidate_paths=0, validated_paths=0,
                 rejected_paths=0, proposed_paths=0, impact_assessed_paths=0)
    probes = noise = adverse = caps = 0
    first_validation = None
    max_noise = None
    for cycle in range(1, 40):
        rec = deliberate(graph, {**world, "budget_remaining": budget}, cycle=cycle)
        if rec["intention"] is None:
            break
        cap = rec["intention"]["capability_id"]
        caps += 1
        next(n for n in graph["nodes"] if n["capability_id"] == cap)["status"] = "SUCCEEDED"
        if cap == "reconnaissance":
            world["in_scope_assets"] = sc["assets"]
        elif cap == "enumeration":
            state = new_state("enumeration", surface, budget=budget)
            state["max_noise"] = max_noise
            while True:
                d = decide(state, allowed_techniques=ENUM)
                if d["proposal"] is None:
                    break
                tech = d["proposal"]["technique"]
                n = TECHNIQUE_CATALOG["enumeration"][tech][3]
                probes += 1
                noise += n
                blocked = sc["adverse_if_noisy"] and n > 0
                adverse += int(blocked)
                if blocked:
                    max_noise = 0                       # reactive layer: tighten-only after the adverse observation
                    state["max_noise"] = 0
                found = _apply(surface, tech, blocked)
                state["surface"] = {k: dict(v) for k, v in surface.items()}
                state["history"].append({"event_id": f"e{probes}", "technique": tech, "new_items": found})
                state["budget_remaining"] -= 1
            world["enumerated_assets"] = world["in_scope_assets"]
        elif cap == "vulnerability_analysis":
            world["open_hypotheses"] = sc["hypotheses"]
        elif cap == "attack_path_analysis":
            world["candidate_paths"] = world["open_hypotheses"]
        elif cap == "validation":
            world["validated_paths"], world["open_hypotheses"] = world["candidate_paths"], 0
            first_validation = caps
        elif cap == "exploitation":
            world["proposed_paths"] = world["validated_paths"]
        elif cap == "impact_analysis":
            world["impact_assessed_paths"] = world["proposed_paths"]
    return {"controller": "agentic", "capabilities_run": caps, "probing_actions": probes, "noise_units": noise,
            "adverse_noisy_actions": adverse, "final_coverage": round(_cov(surface), 3),
            "steps_to_first_validation": first_validation}


def main() -> dict:
    out = {"disclaimer": "deterministic simulation of decision logic on a toy world; not empirical evidence",
           "coverage_threshold": STOPPING_RULE["coverage_threshold"], "scenarios": {}}
    for name, sc in SCENARIOS.items():
        out["scenarios"][name] = {"fixed": run_fixed(sc), "agentic": run_agentic(sc)}
    return out


if __name__ == "__main__":
    result = main()
    keys = ["capabilities_run", "probing_actions", "noise_units", "adverse_noisy_actions", "final_coverage",
            "steps_to_first_validation"]
    print("| scenario | controller | " + " | ".join(keys) + " |")
    print("|---|---|" + "---|" * len(keys))
    for name, pair in result["scenarios"].items():
        for ctl in ("fixed", "agentic"):
            r = pair[ctl]
            print(f"| {name} | {r['controller']} | " + " | ".join(str(r[k]) for k in keys) + " |")
    print()
    print(json.dumps(result, indent=2, sort_keys=True))
