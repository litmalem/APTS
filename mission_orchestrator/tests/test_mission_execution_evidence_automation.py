"""Unit tests for the Stage-3.5 execution-evidence driver's payload builders and
orchestration. Pure: a fake service stands in for the real one, so these run
without a Mission/DB/Governance/runtime setup (avoids the temp-sandbox permission
limit and the live-governance coupling), matching the completion-driver tests.
"""
from mission_orchestrator.mission_execution_evidence_automation import (
    _ev_key,
    attempt_request,
    dispatch_request,
    eligibility_request,
    execution_delivery_request,
    produce_execution_evidence,
    propagation_request,
    recovery_request,
    result_request,
    revalidation_request,
    running_request,
)

ACTIVE = {"plan_version_record_id": "pver-abc", "plan_version": 3, "canonical_sha256": "a" * 64}

DELIVERY = {"delivery_receipt_id": "drec-1", "canonical_sha256": "d" * 64, "planned_task_id": "ptask-1"}
DISPATCH = {"execution_dispatch_id": "disp-1", "canonical_sha256": "01" * 32}
GATE = {"dispatch_eligibility_id": "gate-1", "canonical_sha256": "02" * 32}
REVAL = {"pre_dispatch_revalidation_id": "reval-1", "canonical_sha256": "03" * 32}
ATTEMPT = {"execution_attempt_id": "att-1", "canonical_sha256": "04" * 32, "dispatch_envelope_id": "env-1"}
XDELIVERY = {"execution_delivery_id": "xdel-1", "canonical_sha256": "05" * 32,
             "recipient_subsystem_id": "sub-1", "runtime_endpoint": "ep"}
RUNNING = {"running_projection_id": "run-1", "canonical_sha256": "06" * 32}
RESULT = {"result_capture_id": "rcap-1", "canonical_sha256": "07" * 32, "execution_state": "SUCCEEDED"}
PROP = {"outcome_propagation_id": "prop-1", "canonical_sha256": "08" * 32}
CHK = {"checkpoint_id": "ckpt-1", "canonical_sha256": "09" * 32}


class FakeExecService:
    """Minimal service double returning queued canonical rows for each Stage-3.5 call."""

    def __init__(self, result_row=None):
        self.calls = []
        self._result = result_row or dict(RESULT)

    # read-only projections the builders consult
    def get_mission_state(self, mid):
        return {"mission_state": {"state": "RUNNING", "state_version": 7}}

    def get_mission_version_vector(self, mid):
        return {"version_sha256": "v" * 64}

    def get_active_task_readiness_projection(self, mid):
        return {"projection_id": "proj-1", "canonical_sha256": "p" * 64}

    def get_execution_event_replay(self, mid):
        return {"replay": {"execution_event_count": 12, "execution_event_tip_sha256": "t" * 64}}

    # mutating chain calls
    def create_execution_dispatch_contract(self, mid, body):
        self.calls.append(("dispatch", body)); return dict(DISPATCH)

    def create_dispatch_eligibility_gate(self, mid, body):
        self.calls.append(("gate", body)); return dict(GATE)

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


def _anchor_fields_present(body):
    return (body["expected_version_sha256"] == "v" * 64
            and body["expected_state_version"] == 7
            and body["expected_active_plan_version_record_id"] == "pver-abc"
            and body["expected_active_plan_version"] == 3
            and body["expected_active_plan_sha256"] == "a" * 64)


def test_every_builder_carries_concurrency_anchors():
    s = FakeExecService()
    anchor = DELIVERY["delivery_receipt_id"]
    bodies = [
        dispatch_request(s, "m1", ACTIVE, DELIVERY),
        eligibility_request(s, "m1", ACTIVE, anchor, DISPATCH),
        revalidation_request(s, "m1", ACTIVE, anchor, DISPATCH, GATE),
        attempt_request(s, "m1", ACTIVE, anchor, DISPATCH, GATE, REVAL),
        execution_delivery_request(s, "m1", ACTIVE, anchor, ATTEMPT),
        running_request(s, "m1", ACTIVE, anchor, ATTEMPT, XDELIVERY),
        result_request(s, "m1", ACTIVE, anchor, ATTEMPT, XDELIVERY, RUNNING),
        propagation_request(s, "m1", ACTIVE, anchor, ATTEMPT, RESULT),
        recovery_request(s, "m1", ACTIVE, anchor, ATTEMPT, XDELIVERY, RUNNING, RESULT, PROP),
    ]
    assert all(_anchor_fields_present(b) for b in bodies)


def test_builders_bind_each_predecessor_id_and_sha():
    s = FakeExecService()
    anchor = DELIVERY["delivery_receipt_id"]

    d = dispatch_request(s, "m1", ACTIVE, DELIVERY)
    assert d["expected_delivery_receipt_id"] == "drec-1" and d["expected_delivery_receipt_sha256"] == "d" * 64
    assert d["planned_task_id"] == "ptask-1"

    g = eligibility_request(s, "m1", ACTIVE, anchor, DISPATCH)
    assert g["expected_execution_dispatch_id"] == "disp-1" and g["expected_execution_dispatch_sha256"] == "01" * 32
    assert g["expected_task_readiness_projection_id"] == "proj-1"

    r = revalidation_request(s, "m1", ACTIVE, anchor, DISPATCH, GATE)
    assert r["expected_dispatch_eligibility_id"] == "gate-1"

    a = attempt_request(s, "m1", ACTIVE, anchor, DISPATCH, GATE, REVAL)
    assert a["expected_pre_dispatch_revalidation_id"] == "reval-1"
    assert a["expected_dispatch_eligibility_id"] == "gate-1"

    xd = execution_delivery_request(s, "m1", ACTIVE, anchor, ATTEMPT)
    assert xd["expected_execution_attempt_id"] == "att-1" and xd["expected_dispatch_envelope_id"] == "env-1"

    run = running_request(s, "m1", ACTIVE, anchor, ATTEMPT, XDELIVERY)
    assert run["expected_execution_delivery_id"] == "xdel-1" and run["expected_execution_attempt_id"] == "att-1"

    res = result_request(s, "m1", ACTIVE, anchor, ATTEMPT, XDELIVERY, RUNNING)
    assert res["expected_running_projection_id"] == "run-1" and res["expected_execution_delivery_id"] == "xdel-1"

    prop = propagation_request(s, "m1", ACTIVE, anchor, ATTEMPT, RESULT)
    assert prop["expected_result_capture_id"] == "rcap-1" and prop["expected_execution_attempt_id"] == "att-1"

    chk = recovery_request(s, "m1", ACTIVE, anchor, ATTEMPT, XDELIVERY, RUNNING, RESULT, PROP)
    assert chk["expected_outcome_propagation_id"] == "prop-1" and chk["expected_result_capture_id"] == "rcap-1"
    # recovery folds in the durable replay tip and a (default) zero termination count
    assert chk["expected_execution_event_count"] == 12 and chk["expected_execution_event_tip_sha256"] == "t" * 64
    assert chk["expected_termination_control_count"] == 0


def test_idempotency_keys_are_deterministic_and_stage_distinct():
    assert _ev_key("drec-1", "dispatch") == _ev_key("drec-1", "dispatch")       # replay-stable
    assert _ev_key("drec-1", "dispatch") != _ev_key("drec-1", "attempt")        # distinct per stage
    assert _ev_key("drec-1", "dispatch") != _ev_key("drec-2", "dispatch")       # distinct per task lineage


def test_produce_drives_the_full_chain_in_canonical_order():
    s = FakeExecService()
    rows = produce_execution_evidence(s, "m1", ACTIVE, DELIVERY)
    assert [c[0] for c in s.calls] == [
        "dispatch", "gate", "reval", "attempt", "exec-delivery",
        "running", "result", "propagation", "checkpoint",
    ]
    assert rows["succeeded"] is True and rows["execution_state"] == "SUCCEEDED"
    # the four Stage-3.6 inputs are surfaced under stable keys
    assert rows["attempt"]["execution_attempt_id"] == "att-1"
    assert rows["result"]["result_capture_id"] == "rcap-1"
    assert rows["propagation"]["outcome_propagation_id"] == "prop-1"
    assert rows["checkpoint"]["checkpoint_id"] == "ckpt-1"


def test_produce_seals_evidence_even_on_terminal_non_success():
    """A FAILED terminal result is still propagated and checkpointed; completion is
    deferred to the fail-closed Stage-3.6 chain, which the driver does not short-circuit."""
    s = FakeExecService(result_row={"result_capture_id": "rcap-1", "canonical_sha256": "07" * 32,
                                    "execution_state": "FAILED"})
    rows = produce_execution_evidence(s, "m1", ACTIVE, DELIVERY)
    assert rows["succeeded"] is False and rows["execution_state"] == "FAILED"
    # full evidence lineage still sealed (propagation + checkpoint recorded)
    assert [c[0] for c in s.calls][-2:] == ["propagation", "checkpoint"]


def test_chain_propagates_live_predecessor_rows_not_stale_fixtures():
    """The attempt body must bind the dispatch/gate/reval rows the service actually
    returned during this run, proving the orchestration threads live outputs through."""
    s = FakeExecService()
    produce_execution_evidence(s, "m1", ACTIVE, DELIVERY)
    attempt_body = dict(next(b for name, b in s.calls if name == "attempt"))
    assert attempt_body["expected_execution_dispatch_id"] == "disp-1"
    assert attempt_body["expected_dispatch_eligibility_id"] == "gate-1"
    assert attempt_body["expected_pre_dispatch_revalidation_id"] == "reval-1"
    checkpoint_body = dict(next(b for name, b in s.calls if name == "checkpoint"))
    assert checkpoint_body["expected_outcome_propagation_id"] == "prop-1"
