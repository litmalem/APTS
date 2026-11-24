"""Unit tests for the composed task driver (Stage 3.4 -> 3.5 -> 3.6) and the
per-mission drive loop. Pure: one fake service stands in for the authoritative
service across all stages, so these run without a Mission/DB/Governance/runtime
setup (avoids the temp-sandbox limit), matching the other driver test suites.
"""
from mission_orchestrator.mission_task_drive_automation import (
    _rt_key,
    delegation_authorization_request,
    delegation_delivery_request,
    delegation_request,
    drive_mission,
    drive_task,
    route_and_delegate,
    route_selection_request,
    routing_eligibility_request,
    routing_intent_request,
)

ACTIVE = {"plan_version_record_id": "pver-abc", "plan_version": 3, "canonical_sha256": "a" * 64}
READINESS = {"projection_id": "proj-1", "canonical_sha256": "p" * 64,
             "ready_task_keys": ["collect-cti"], "ready_task_count": 1}

# Stage 3.4 canned rows
RI = {"routing_intent_id": "ri-1", "canonical_sha256": "b1" * 32, "planned_task_id": "pt-1"}
REG = {"eligibility_gate_id": "reg-1", "canonical_sha256": "b2" * 32}
RD = {"route_decision_id": "rd-1", "canonical_sha256": "b3" * 32, "planned_task_id": "pt-1"}
DA = {"delegation_authorization_id": "da-1", "canonical_sha256": "b4" * 32}
DG = {"delegation_id": "dg-1", "canonical_sha256": "b5" * 32, "planned_task_id": "pt-1",
      "handoff_envelope_id": "he-1", "handoff_envelope_sha256": "b6" * 32,
      "handoff_envelope": {"recipient": {"subsystem_id": "CTI", "capability_id": "cti.read.context"}}}
DELIV = {"delivery_receipt_id": "drec-1", "canonical_sha256": "b7" * 32, "planned_task_id": "pt-1"}

# Stage 3.5 canned rows
DISPATCH = {"execution_dispatch_id": "disp-1", "canonical_sha256": "c1" * 32}
GATE = {"dispatch_eligibility_id": "gate-1", "canonical_sha256": "c2" * 32}
REVAL = {"pre_dispatch_revalidation_id": "reval-1", "canonical_sha256": "c3" * 32}
ATTEMPT = {"execution_attempt_id": "att-1", "canonical_sha256": "c4" * 32, "dispatch_envelope_id": "env-1"}
XDELIVERY = {"execution_delivery_id": "xdel-1", "canonical_sha256": "c5" * 32,
             "recipient_subsystem_id": "CTI", "runtime_endpoint": "ep"}
RUNNING = {"running_projection_id": "run-1", "canonical_sha256": "c6" * 32}
RESULT_OK = {"result_capture_id": "rcap-1", "canonical_sha256": "c7" * 32, "execution_state": "SUCCEEDED"}
PROP = {"outcome_propagation_id": "prop-1", "canonical_sha256": "c8" * 32}
CHK = {"checkpoint_id": "ckpt-1", "canonical_sha256": "c9" * 32}

# Stage 3.6 + finalize canned rows
OUTCOME = {"task_outcome_id": "tout-1", "canonical_sha256": "d1" * 32}
EGATE = {"eligibility_gate_id": "egate-1", "canonical_sha256": "d2" * 32}
EBIND = {"verification_id": "ebv-1", "canonical_sha256": "d3" * 32}
TCOMPLETE = {"status": "COMPLETED"}
AGG = {"aggregation_id": "agg-1", "canonical_sha256": "e1" * 32,
       "all_tasks_terminal": True, "all_tasks_verified_complete": True, "terminal_non_success_present": False}
EVAL = {"evaluation_id": "eval-1", "canonical_sha256": "e2" * 32, "overall_result": "SUCCESS_CRITERIA_SATISFIED"}
READY = {"readiness_id": "ready-1", "canonical_sha256": "e3" * 32, "readiness_result": "READY",
         "blocker_count": 0, "blockers": []}
VERIFIED = {"final_mission_state": {"state": "COMPLETED"}}


class FakeService:
    def __init__(self, result_row=None):
        self.calls = []
        self._result = result_row or dict(RESULT_OK)

    # read-only projections
    def get_mission_state(self, mid):
        return {"mission_state": {"state": "RUNNING", "state_version": 7}}

    def get_mission_version_vector(self, mid):
        return {"version_sha256": "v" * 64}

    def get_active_plan_version(self, mid):
        return dict(ACTIVE)

    def get_active_task_readiness_projection(self, mid):
        return dict(READINESS)

    def get_execution_event_replay(self, mid):
        return {"replay": {"execution_event_count": 12, "execution_event_tip_sha256": "t" * 64}}

    def list_planned_tasks(self, mid):
        return {"planned_tasks": [{"task_key": "collect-cti", "planned_task_id": "pt-1"}]}

    def get_delegation_delivery_history(self, mid):
        return {"delegation_deliveries": list(getattr(self, "existing_deliveries", []))}

    # Stage 3.4
    def create_task_routing_intent(self, mid, body):
        self.calls.append(("routing-intent", body)); return dict(RI)

    def create_task_routing_eligibility_gate(self, mid, body):
        self.calls.append(("routing-eligibility", body)); return dict(REG)

    def create_task_route_selection_decision(self, mid, body):
        self.calls.append(("route-selection", body)); return dict(RD)

    def authorize_task_delegation(self, mid, body):
        self.calls.append(("delegation-authorization", body)); return dict(DA)

    def create_task_delegation(self, mid, body):
        self.calls.append(("delegation", body)); return dict(DG)

    def deliver_task_delegation(self, mid, body):
        self.calls.append(("delegation-delivery", body)); return dict(DELIV)

    # Stage 3.5
    def create_execution_dispatch_contract(self, mid, body):
        self.calls.append(("dispatch", body)); return dict(DISPATCH)

    def create_dispatch_eligibility_gate(self, mid, body):
        self.calls.append(("dispatch-gate", body)); return dict(GATE)

    def authorize_pre_dispatch_execution(self, mid, body):
        self.calls.append(("reval", body)); return dict(REVAL)

    def commit_execution_attempt(self, mid, body):
        self.calls.append(("attempt", body)); return dict(ATTEMPT)

    def deliver_execution_attempt(self, mid, body):
        self.calls.append(("exec-delivery", body)); return dict(XDELIVERY)

    def project_running_execution_state(self, mid, body):
        self.calls.append(("running", body)); return dict(RUNNING)

    def capture_execution_result(self, mid, body):
        self.calls.append(("result", body)); return dict(self._result)

    def propagate_execution_outcome(self, mid, body):
        self.calls.append(("propagation", body)); return dict(PROP)

    def create_execution_recovery_checkpoint(self, mid, body):
        self.calls.append(("checkpoint", body)); return dict(CHK)

    # Stage 3.6
    def create_task_outcome(self, mid, body):
        self.calls.append(("outcome", body)); return dict(OUTCOME)

    def evaluate_task_terminality_completion_eligibility(self, mid, body):
        self.calls.append(("eligibility", body)); return dict(EGATE)

    def verify_task_evidence_binding(self, mid, body):
        self.calls.append(("binding", body)); return dict(EBIND)

    def commit_dependency_aware_task_completion(self, mid, body):
        self.calls.append(("completion", body)); return dict(TCOMPLETE)

    # Mission finalize
    def aggregate_mission_outcome(self, mid, body):
        self.calls.append(("aggregate", body)); return dict(AGG)

    def evaluate_mission_success_criteria(self, mid, body):
        self.calls.append(("evaluate", body)); return dict(EVAL)

    def evaluate_completion_readiness(self, mid, body):
        self.calls.append(("readiness", body)); return dict(READY)

    def declare_verified_completion(self, mid, body):
        self.calls.append(("declare", body)); return dict(VERIFIED)


def _names(service):
    return [c[0] for c in service.calls]


def test_stage34_builders_bind_predecessors_and_anchors():
    s = FakeService()
    ri = routing_intent_request(s, "m1", ACTIVE, READINESS, "pt-1")
    assert ri["planned_task_id"] == "pt-1" and ri["expected_task_readiness_projection_id"] == "proj-1"
    assert ri["expected_active_plan_sha256"] == "a" * 64

    reg = routing_eligibility_request(s, "m1", ACTIVE, READINESS, RI)
    assert reg["expected_routing_intent_id"] == "ri-1"

    rt = route_selection_request(s, "m1", ACTIVE, READINESS, RI, REG)
    assert rt["expected_routing_intent_id"] == "ri-1" and rt["expected_eligibility_gate_id"] == "reg-1"

    da = delegation_authorization_request(s, "m1", ACTIVE, RD)
    assert da["expected_route_decision_id"] == "rd-1"

    dg = delegation_request(s, "m1", ACTIVE, RD, DA)
    assert dg["expected_delegation_authorization_id"] == "da-1"

    dv = delegation_delivery_request(s, "m1", ACTIVE, DG)
    assert dv["expected_delegation_id"] == "dg-1" and dv["expected_handoff_envelope_id"] == "he-1"
    assert dv["recipient_subsystem_id"] == "CTI" and dv["recipient_capability_id"] == "cti.read.context"


def test_route_and_delegate_drives_six_calls_in_order():
    s = FakeService()
    rows = route_and_delegate(s, "m1", ACTIVE, READINESS, "pt-1")
    assert _names(s) == ["routing-intent", "routing-eligibility", "route-selection",
                         "delegation-authorization", "delegation", "delegation-delivery"]
    assert rows["delivery"]["delivery_receipt_id"] == "drec-1"


def test_drive_task_success_runs_full_34_35_36_chain():
    s = FakeService()
    out = drive_task(s, "m1", ACTIVE, READINESS, "pt-1")
    assert out["status"] == "COMPLETED"
    assert out["completion"]["completion"] == TCOMPLETE
    # the composed chain spans routing -> execution -> completion
    names = _names(s)
    assert names[:6] == ["routing-intent", "routing-eligibility", "route-selection",
                         "delegation-authorization", "delegation", "delegation-delivery"]
    assert names[6:15] == ["dispatch", "dispatch-gate", "reval", "attempt", "exec-delivery",
                           "running", "result", "propagation", "checkpoint"]
    assert names[15:] == ["outcome", "eligibility", "binding", "completion"]


def test_drive_task_is_fail_closed_on_non_success_execution():
    s = FakeService(result_row={"result_capture_id": "rcap-1", "canonical_sha256": "c7" * 32,
                                "execution_state": "FAILED"})
    out = drive_task(s, "m1", ACTIVE, READINESS, "pt-1")
    assert out["status"] == "TERMINAL_NON_SUCCESS" and out["execution_state"] == "FAILED"
    # evidence sealed (propagation+checkpoint) but NO completion commit ever attempted
    names = _names(s)
    assert "propagation" in names and "checkpoint" in names
    assert "outcome" not in names and "completion" not in names


def test_drive_mission_drives_ready_tasks_then_finalizes_to_completed():
    s = FakeService()
    out = drive_mission(s, "m1")
    assert out["driven_task_count"] == 1
    assert out["tasks"]["collect-cti"]["status"] == "COMPLETED"
    assert out["finalization"]["status"] == "COMPLETED"
    # finalization ran after task completion
    names = _names(s)
    assert names.index("completion") < names.index("aggregate") < names.index("declare")


def test_drive_mission_withholds_finalization_when_task_fails():
    s = FakeService(result_row={"result_capture_id": "rcap-1", "canonical_sha256": "c7" * 32,
                                "execution_state": "FAILED"})
    # aggregation reports not-all-complete so finalize stops NOT_READY (fail-closed)
    s_agg = {"aggregation_id": "agg-1", "canonical_sha256": "e1" * 32,
             "all_tasks_terminal": False, "all_tasks_verified_complete": False,
             "terminal_non_success_present": True}

    def _agg(mid, body):
        s.calls.append(("aggregate", body)); return dict(s_agg)
    s.aggregate_mission_outcome = _agg

    out = drive_mission(s, "m1")
    assert out["tasks"]["collect-cti"]["status"] == "TERMINAL_NON_SUCCESS"
    assert out["finalization"]["status"] == "NOT_READY"
    assert "declare" not in _names(s)  # never forces completion


def test_idempotency_keys_are_deterministic_and_stage_distinct():
    assert _rt_key("pt-1", "routing-intent") == _rt_key("pt-1", "routing-intent")
    assert _rt_key("pt-1", "routing-intent") != _rt_key("pt-1", "delegation")
    assert _rt_key("pt-1", "routing-intent") != _rt_key("pt-2", "routing-intent")


def test_drive_task_reuses_delivery_routed_during_planning():
    svc = FakeService()
    svc.existing_deliveries = [{**DELIV, "planned_task_id": "pt-1",
                                "plan_version_record_id": ACTIVE["plan_version_record_id"]}]
    out = drive_task(svc, "m-1", dict(ACTIVE), dict(READINESS), "pt-1")
    stages = [c[0] for c in svc.calls]
    assert out["status"] == "COMPLETED"
    assert "routing-intent" not in stages and "delegation-delivery" not in stages
    assert "dispatch" in stages
