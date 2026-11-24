from __future__ import annotations

import pytest

from pentest_subsystem.adaptive_reproposal import TARGET_CONDITION_DEGRADE_FEEDBACK_TYPE
from pentest_subsystem.cross_agent_feedback import (
    CROSS_AGENT_FEEDBACK_TYPES,
    canonical_cross_agent_feedback_contract,
    verify_cross_agent_feedback_contract,
)
from pentest_subsystem.orchestration.deliberation import deliberate
from pentest_subsystem.orchestration.perception_action import (
    PerceptionActionError,
    decide,
    new_state,
    on_evidence_sealed,
    verify_decision,
)
from pentest_subsystem.orchestration.reactive import (
    ReactiveValidationError,
    arbitrate,
    react_to_inconclusive_validation,
    react_to_target_condition,
    select_validation_strategy,
    verify_arbitration,
)
from tests.test_stage5_8_cross_agent_feedback_shared_state_replanning import (
    _feedback_and_replan,
    _full_shared_state,
)

ENUM_ALLOWED = ["SERVICE_ENUMERATION", "TECHNOLOGY_IDENTIFICATION", "VERSION_DISCOVERY",
                "ENDPOINT_DISCOVERY", "CONFIGURATION_OBSERVATION", "TCP_BANNER_READ"]
LIMITS = {"rate_window_seconds": 1.0, "timeout_seconds": 15.0, "max_network_requests": 6}


def _enum_state(**remaining):
    base = {"unprofiled_services": 0, "unversioned_services": 0, "unprobed_endpoints": 0, "unobserved_config": 0}
    base.update(remaining)
    return new_state("enumeration", {d: {"total": 10, "remaining": r} for d, r in base.items()}, budget=10)


def _signal(**observed):
    base = {"rate_limited": False, "server_overload": False, "access_forbidden": False,
            "waf_indicator": False, "retry_after_seconds": None}
    base.update(observed)
    return {"signal_id": "tcond-" + "a" * 48, "observed": base, "integrity": {"canonical_sha256": "d" * 64}}


def _event(eid, technique, new_items, **remaining):
    return {"event_id": eid, "event_type": "STAGE6_EVIDENCE_SEALED", "capability_id": "enumeration",
            "technique": technique, "new_items": new_items, "surface_remaining": remaining}


# ---- P2: action selection -------------------------------------------------------------------

def test_selection_follows_information_gain_not_a_fixed_order():
    versions = decide(_enum_state(unversioned_services=9, unobserved_config=1), allowed_techniques=ENUM_ALLOWED)
    config = decide(_enum_state(unversioned_services=1, unobserved_config=9), allowed_techniques=ENUM_ALLOWED)
    assert versions["proposal"]["technique"] == "VERSION_DISCOVERY"
    assert config["proposal"]["technique"] == "CONFIGURATION_OBSERVATION"
    assert verify_decision(versions) and versions["proposal"]["rejected_alternatives"]


def test_selection_never_leaves_server_allowlist_or_prohibited_set():
    state = _enum_state(unversioned_services=9)
    d = decide(state, allowed_techniques=["TECHNOLOGY_IDENTIFICATION", "VERSION_DISCOVERY"],
               prohibited_techniques=["VERSION_DISCOVERY"])
    assert d["proposal"] is None or d["proposal"]["technique"] == "TECHNOLOGY_IDENTIFICATION"
    d = decide(state, allowed_techniques=["PORT_SWEEP_NOT_IN_CATALOG"])
    assert d["stop_reason"] == "NO_ALLOWED_TECHNIQUE"


def test_noise_cap_models_tighten_only_degradation():
    state = _enum_state(unversioned_services=9, unprofiled_services=9)
    state["max_noise"] = 0
    d = decide(state, allowed_techniques=ENUM_ALLOWED)
    assert d["proposal"]["technique"] in {"TECHNOLOGY_IDENTIFICATION", "CONFIGURATION_OBSERVATION"}
    assert all(c["noise"] == 0 for c in d["candidates"])


# ---- P2: stopping rule ----------------------------------------------------------------------

def test_empty_surface_is_unknown_not_covered():
    state = new_state("enumeration", {d: {"total": 0, "remaining": 0} for d in (
        "unprofiled_services", "unversioned_services", "unprobed_endpoints", "unobserved_config")}, budget=5)
    d = decide(state, allowed_techniques=ENUM_ALLOWED)
    assert d["coverage"] == 0.0 and d["stop_reason"] == "NO_SURFACE_OBSERVED" and d["proposal"] is None


def test_stop_on_coverage():
    d = decide(_enum_state(), allowed_techniques=ENUM_ALLOWED)
    assert d["stop_reason"] == "COVERAGE_REACHED" and d["proposal"] is None


def test_stop_on_marginal_gain():
    # coverage < 0.95 overall, but the only allowed technique yields 0.5 * 1/20 = 0.025 < 0.05
    state = _enum_state()
    state["surface"]["unversioned_services"] = {"total": 20, "remaining": 1}
    state["surface"]["unprofiled_services"] = {"total": 100, "remaining": 20}  # keeps coverage below threshold
    d = decide(state, allowed_techniques=["TCP_BANNER_READ"])
    assert d["coverage"] < 0.95
    assert d["stop_reason"] == "MARGINAL_GAIN_BELOW_THRESHOLD"


def test_stop_on_budget():
    state = _enum_state(unversioned_services=9)
    state["budget_remaining"] = 0
    assert decide(state, allowed_techniques=ENUM_ALLOWED)["stop_reason"] == "BUDGET_EXHAUSTED"


def test_stalled_technique_is_excluded_after_two_empty_attempts():
    state = _enum_state(unversioned_services=9)
    state["history"] = [{"event_id": "a", "technique": "VERSION_DISCOVERY", "new_items": 0},
                        {"event_id": "b", "technique": "VERSION_DISCOVERY", "new_items": 0}]
    d = decide(state, allowed_techniques=["VERSION_DISCOVERY", "TCP_BANNER_READ"])
    assert d["proposal"]["technique"] == "TCP_BANNER_READ"


# ---- P2: event-driven loop ------------------------------------------------------------------

def test_sealed_evidence_events_drive_iterations_without_manual_calls():
    state = _enum_state(unprofiled_services=8, unversioned_services=8)
    seen = []
    events = [_event("e1", "SERVICE_ENUMERATION", 6, unprofiled_services=2),
              _event("e2", "VERSION_DISCOVERY", 7, unversioned_services=1),
              _event("e3", "SERVICE_ENUMERATION", 1, unprofiled_services=0)]
    for ev in events:
        state, decision = on_evidence_sealed(state, ev, allowed_techniques=ENUM_ALLOWED)
        seen.append(decision)
        assert verify_decision(decision)
    assert seen[0]["proposal"] is not None
    assert seen[-1]["stop_reason"] == "COVERAGE_REACHED"
    assert state["budget_remaining"] == 7


def test_event_replay_is_a_noop_and_bad_events_fail_closed():
    state = _enum_state(unprofiled_services=8)
    ev = _event("e1", "SERVICE_ENUMERATION", 3, unprofiled_services=5)
    s1, d1 = on_evidence_sealed(state, ev, allowed_techniques=ENUM_ALLOWED)
    s2, d2 = on_evidence_sealed(s1, ev, allowed_techniques=ENUM_ALLOWED)
    assert d1 is not None and d2 is None and s2 == s1
    for bad in (dict(ev, event_type="OTHER"), dict(ev, event_id="e9", capability_id="reconnaissance"),
                dict(ev, event_id="e9", technique="NOT_A_TECHNIQUE"),
                dict(ev, event_id="e9", surface_remaining={"unprofiled_services": 99})):
        with pytest.raises(PerceptionActionError):
            on_evidence_sealed(s1, bad, allowed_techniques=ENUM_ALLOWED)


def test_evidence_cannot_increase_unknown_surface():
    state = _enum_state(unprofiled_services=3)
    s, _ = on_evidence_sealed(state, _event("e1", "SERVICE_ENUMERATION", 0, unprofiled_services=9),
                              allowed_techniques=ENUM_ALLOWED)
    assert s["surface"]["unprofiled_services"]["remaining"] == 3


# ---- P5: reactive layer ---------------------------------------------------------------------

def test_target_condition_degrade_is_now_an_official_feedback_type():
    assert TARGET_CONDITION_DEGRADE_FEEDBACK_TYPE in CROSS_AGENT_FEEDBACK_TYPES
    assert verify_cross_agent_feedback_contract(canonical_cross_agent_feedback_contract())


def test_degrade_feedback_flows_through_local_replan_for_probing_subject(tmp_path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "deg2a")
    d = _feedback_and_replan(repo, oid, state, "deg2a", feedback_type="TARGET_CONDITION_DEGRADE",
                             subject="enumeration")
    assert d["decision_class"] == "REPLAN_LOCAL"
    assert d["restart_capability_id"] == "enumeration"
    assert d["semantics"]["automatic_execution"] is False
    assert d["obligations"]["active_stage5_1_plan_mutated"] is False


def test_degrade_feedback_on_non_probing_subject_changes_nothing(tmp_path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "deg2b")
    d = _feedback_and_replan(repo, oid, state, "deg2b", feedback_type="TARGET_CONDITION_DEGRADE",
                             subject="exploitation")
    assert d["decision_class"] == "NO_CHANGE"


def test_inconclusive_validation_only_descends_in_risk():
    r = react_to_inconclusive_validation(tried=["NON_DESTRUCTIVE"], roe_max_strategy="CONTROLLED")
    assert r["decision_class"] == "REPLAN_LOCAL" and r["strategy"] == "PASSIVE"
    r = react_to_inconclusive_validation(tried=["NON_DESTRUCTIVE", "PASSIVE"], roe_max_strategy="CONTROLLED")
    assert r["decision_class"] == "DEFER_TO_STAGE6"
    r = react_to_inconclusive_validation(tried=["PASSIVE"], roe_max_strategy="CONTROLLED")
    assert r["decision_class"] == "DEFER_TO_STAGE6"  # never escalates upward reactively


def test_deliberative_strategy_respects_criticality_and_roe_cap():
    assert select_validation_strategy(path_confidence=0.9, asset_criticality="LOW",
                                      roe_max_strategy="CONTROLLED")["strategy"] == "CONTROLLED"
    capped = select_validation_strategy(path_confidence=0.9, asset_criticality="LOW", roe_max_strategy="PASSIVE")
    assert capped["strategy"] == "PASSIVE" and capped["capped_by_roe"] is True
    assert select_validation_strategy(path_confidence=0.9, asset_criticality="CRITICAL",
                                      roe_max_strategy="CONTROLLED")["strategy"] == "PASSIVE"
    with pytest.raises(ReactiveValidationError):
        select_validation_strategy(path_confidence=2, asset_criticality="LOW", roe_max_strategy="PASSIVE")


# ---- P5: arbitration ------------------------------------------------------------------------

def _delib():
    graph = {"orchestration_id": "paorch-t", "plan_version": 1,
             "nodes": [{"capability_id": c, "subtask_id": f"s-{c}", "status": "PENDING"} for c in (
                 "reconnaissance", "enumeration", "vulnerability_analysis", "attack_path_analysis",
                 "validation", "exploitation", "impact_analysis")]}
    return deliberate(graph, {"in_scope_assets": 2, "budget_remaining": 5}, cycle=1)


def test_reactive_degrade_preempts_deliberative_intention_with_gentler_proposal():
    delib = _delib()
    assert delib["intention"]["capability_id"] == "enumeration"
    reactive = react_to_target_condition(
        signal=_signal(rate_limited=True), subject_capability="enumeration",
        current_proposal={"technique": "SERVICE_ENUMERATION", "rate_cost": 1, "active_concurrency": 1},
        current_limits=LIMITS)
    arb = arbitrate(delib, reactive)
    assert verify_arbitration(arb)
    assert arb["rule"] == "R2_DEGRADE_PREEMPTS" and arb["winner"] == "REACTIVE"
    assert arb["preemption"] == {"occurred": True, "kind": "DEGRADE", "suppressed_intention": "enumeration"}
    assert arb["effective_action"]["pacing_hint"]["rate_window_seconds"] == 4.0
    assert arb["effective_action"]["degraded_proposal"]["rate_cost"] == 1


def test_safety_halt_beats_everything_and_suppresses_intention():
    reactive = react_to_target_condition(
        signal=_signal(server_overload=True), subject_capability="enumeration",
        current_proposal={"technique": "SERVICE_ENUMERATION"}, current_limits=LIMITS, prior_degradation_count=2)
    arb = arbitrate(_delib(), reactive)
    assert arb["rule"] == "R1_SAFETY_HALT" and arb["effective_action"] is None
    assert arb["preemption"]["kind"] == "HALT"


def test_no_adverse_condition_leaves_deliberative_intention_untouched():
    reactive = react_to_target_condition(
        signal=_signal(), subject_capability="enumeration",
        current_proposal={"technique": "SERVICE_ENUMERATION"}, current_limits=LIMITS)
    arb = arbitrate(_delib(), reactive)
    assert arb["rule"] == "R3_DELIBERATIVE_STANDS" and arb["preemption"]["occurred"] is False
    assert arb["effective_action"]["capability_id"] == "enumeration"


def test_arbitration_rejects_intensity_raising_reactive_proposals():
    bad = {"decision_class": "REPLAN_LOCAL", "restart_capability": "enumeration",
           "degraded_proposal": {"rate_cost": 3, "active_concurrency": 1}}
    with pytest.raises(ReactiveValidationError):
        arbitrate(_delib(), bad)
    with pytest.raises(ReactiveValidationError):
        arbitrate(_delib(), {"decision_class": "EXECUTE_NOW"})


def test_governance_invariance_no_execution_authority_anywhere():
    d = decide(_enum_state(unversioned_services=9), allowed_techniques=ENUM_ALLOWED)
    assert d["authority"] == {"executes": False, "mints_authorization": False, "widens_allowlist": False,
                              "proposal_target": "STAGE6"}
    arb = arbitrate(_delib(), None)
    assert arb["invariants"] == {"intensity_never_raised": True, "scope_never_widened": True, "executes": False}
