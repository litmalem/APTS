"""Unit tests for the autonomous Mission completion driver's payload builders and
fail-closed control flow. Pure: a fake service stands in for the real one, so these
run without a Mission/DB setup (avoids the temp-sandbox permission limit)."""
from mission_orchestrator.mission_completion_automation import (
    aggregation_request, evaluation_request, readiness_request,
    verified_completion_request, finalize_mission, _key,
    outcome_request, eligibility_request, binding_request, completion_request,
    complete_task, _task_key)


ACTIVE = {"plan_version_record_id": "pver-abc", "plan_version": 3, "canonical_sha256": "a" * 64}


class FakeService:
    """Minimal service double. The finalization-call methods return queued results."""
    def __init__(self, **queued):
        self.q = queued
        self.calls = []

    def get_mission_state(self, mid):
        return {"mission_state": {"state": "RUNNING", "state_version": 7}}

    def get_mission_version_vector(self, mid):
        return {"version_sha256": "v" * 64}

    def get_active_plan_version(self, mid):
        return dict(ACTIVE)

    def aggregate_mission_outcome(self, mid, body):
        self.calls.append(("aggregate", body)); return self.q["aggregation"]

    def evaluate_mission_success_criteria(self, mid, body):
        self.calls.append(("evaluate", body)); return self.q["evaluation"]

    def evaluate_completion_readiness(self, mid, body):
        self.calls.append(("readiness", body)); return self.q["readiness"]

    def declare_verified_completion(self, mid, body):
        self.calls.append(("declare", body)); return self.q["completion"]


def test_builders_carry_concurrency_anchors_and_prior_step_bindings():
    s = FakeService()
    agg = aggregation_request(s, "m1", ACTIVE)
    assert agg["expected_version_sha256"] == "v" * 64 and agg["expected_state_version"] == 7
    assert agg["expected_active_plan_version_record_id"] == "pver-abc"
    assert agg["expected_active_plan_version"] == 3 and agg["expected_active_plan_sha256"] == "a" * 64

    ev = evaluation_request(s, "m1", ACTIVE, {"aggregation_id": "magg-1", "canonical_sha256": "b" * 64})
    assert ev["expected_aggregation_id"] == "magg-1" and ev["expected_aggregation_sha256"] == "b" * 64

    rd = readiness_request(s, "m1", ACTIVE, {"evaluation_id": "msceval-1", "canonical_sha256": "c" * 64})
    assert rd["expected_evaluation_id"] == "msceval-1" and rd["expected_evaluation_sha256"] == "c" * 64

    vc = verified_completion_request(s, "m1", ACTIVE, {"readiness_id": "mready-1", "canonical_sha256": "d" * 64})
    assert vc["expected_readiness_id"] == "mready-1" and vc["expected_readiness_sha256"] == "d" * 64


def test_idempotency_keys_are_deterministic_and_stage_distinct():
    k1 = _key("m1", "a" * 64, "agg")
    assert k1 == _key("m1", "a" * 64, "agg")  # replay-stable
    assert k1 != _key("m1", "a" * 64, "eval")  # distinct per stage
    assert k1 != _key("m2", "a" * 64, "agg")  # distinct per mission


def test_finalize_stops_when_tasks_not_all_complete():
    s = FakeService(aggregation={"all_tasks_terminal": False, "all_tasks_verified_complete": False,
                                 "terminal_non_success_present": False})
    out = finalize_mission(s, "m1")
    assert out["status"] == "NOT_READY" and out["stage"] == "aggregation"
    assert [c[0] for c in s.calls] == ["aggregate"]  # never evaluated/declared


_AGG_OK = {"aggregation_id": "magg-1", "canonical_sha256": "b" * 64,
           "all_tasks_terminal": True, "all_tasks_verified_complete": True, "terminal_non_success_present": False}
_EVAL_OK = {"evaluation_id": "msceval-1", "canonical_sha256": "c" * 64, "overall_result": "SUCCESS_CRITERIA_SATISFIED"}


def test_finalize_stops_when_success_criteria_not_satisfied():
    s = FakeService(
        aggregation=_AGG_OK,
        evaluation={"evaluation_id": "msceval-1", "canonical_sha256": "c" * 64,
                    "overall_result": "SUCCESS_CRITERIA_NOT_SATISFIED"})
    out = finalize_mission(s, "m1")
    assert out["status"] == "NOT_READY" and out["stage"] == "evaluation"
    assert [c[0] for c in s.calls] == ["aggregate", "evaluate"]


def test_finalize_is_fail_closed_on_blocked_readiness():
    s = FakeService(
        aggregation=_AGG_OK, evaluation=_EVAL_OK,
        readiness={"readiness_id": "mready-1", "canonical_sha256": "d" * 64,
                   "readiness_result": "BLOCKED", "blocker_count": 1,
                   "blockers": [{"code": "TASKS_NOT_ALL_VERIFIED_COMPLETE"}]})
    out = finalize_mission(s, "m1")
    assert out["status"] == "BLOCKED" and out["blocker_count"] == 1
    assert "declare" not in [c[0] for c in s.calls]  # never forces completion


def test_finalize_declares_completion_when_ready():
    s = FakeService(
        aggregation=_AGG_OK, evaluation=_EVAL_OK,
        readiness={"readiness_id": "mready-1", "canonical_sha256": "d" * 64,
                   "readiness_result": "READY", "blocker_count": 0, "blockers": []},
        completion={"final_mission_state": {"state": "COMPLETED"}})
    out = finalize_mission(s, "m1")
    assert out["status"] == "COMPLETED" and out["final_state"] == "COMPLETED"
    assert [c[0] for c in s.calls] == ["aggregate", "evaluate", "readiness", "declare"]


# --- Per-task Stage-3.6 completion chain ---

class FakeTaskService(FakeService):
    def __init__(self, **queued):
        super().__init__(**queued)
    def create_task_outcome(self, mid, body):
        self.calls.append(("outcome", body)); return self.q["task_outcome"]
    def evaluate_task_terminality_completion_eligibility(self, mid, body):
        self.calls.append(("eligibility", body)); return self.q["gate"]
    def verify_task_evidence_binding(self, mid, body):
        self.calls.append(("binding", body)); return self.q["ebind"]
    def commit_dependency_aware_task_completion(self, mid, body):
        self.calls.append(("completion", body)); return self.q["task_completion"]


_ATTEMPT = {"execution_attempt_id": "xatt-1", "canonical_sha256": "1" * 64}
_RESULT = {"result_capture_id": "rcap-1", "canonical_sha256": "2" * 64}
_PROP = {"outcome_propagation_id": "oprop-1", "canonical_sha256": "3" * 64}
_CHK = {"checkpoint_id": "ckpt-1", "canonical_sha256": "4" * 64}
_OUTCOME = {"task_outcome_id": "tout-1", "canonical_sha256": "5" * 64}
_GATE = {"eligibility_gate_id": "egate-1", "canonical_sha256": "6" * 64}
_EBIND = {"verification_id": "ebv-1", "canonical_sha256": "7" * 64}


def test_outcome_request_binds_all_four_stage35_evidence_refs():
    s = FakeTaskService()
    body = outcome_request(s, "m1", ACTIVE, _ATTEMPT, _RESULT, _PROP, _CHK)
    assert body["expected_execution_attempt_id"] == "xatt-1" and body["expected_execution_attempt_sha256"] == "1" * 64
    assert body["expected_result_capture_id"] == "rcap-1"
    assert body["expected_outcome_propagation_id"] == "oprop-1"
    assert body["expected_execution_recovery_checkpoint_id"] == "ckpt-1"
    # concurrency anchors present too
    assert body["expected_active_plan_sha256"] == "a" * 64


def test_eligibility_binding_completion_carry_prior_step_bindings():
    s = FakeTaskService()
    el = eligibility_request(s, "m1", ACTIVE, _OUTCOME)
    assert el["expected_task_outcome_id"] == "tout-1" and el["expected_task_outcome_sha256"] == "5" * 64
    bd = binding_request(s, "m1", ACTIVE, _OUTCOME, _GATE, _RESULT)
    assert bd["expected_eligibility_gate_id"] == "egate-1" and bd["expected_result_capture_id"] == "rcap-1"
    cp = completion_request(s, "m1", ACTIVE, _EBIND)
    assert cp["expected_evidence_binding_verification_id"] == "ebv-1"


def test_task_keys_are_deterministic_and_stage_distinct():
    assert _task_key("xatt-1", "outcome") == _task_key("xatt-1", "outcome")
    assert _task_key("xatt-1", "outcome") != _task_key("xatt-1", "binding")


def test_complete_task_drives_full_chain_in_order():
    s = FakeTaskService(task_outcome=_OUTCOME, gate=_GATE, ebind=_EBIND,
                        task_completion={"status": "COMPLETED"})
    out = complete_task(s, "m1", ACTIVE, {"attempt": _ATTEMPT, "result": _RESULT,
                                          "propagation": _PROP, "checkpoint": _CHK})
    assert [c[0] for c in s.calls] == ["outcome", "eligibility", "binding", "completion"]
    assert out["task_outcome"] == _OUTCOME and out["completion"] == {"status": "COMPLETED"}
    # binding must reference the gate produced by the eligibility step
    binding_body = dict(s.calls[2][1])
    assert binding_body["expected_eligibility_gate_id"] == "egate-1"
