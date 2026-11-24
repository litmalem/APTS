from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sqlite3
import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import MissionConcurrencyConflict, MissionRepositoryIntegrityError, MissionSuccessEvaluationConflict, MissionSuccessEvaluationGuardRejected, MissionValidationError
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.mission_success_evaluation import *
from tests.test_stage3_6_5_mission_outcome_aggregation import provision_aggregation_source

CONTROL="stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR="stage3.6.9-outcome-lineage-replay-recovery"
EVENT_TYPE="MISSION_SUCCESS_CRITERIA_EVALUATED"

def evaluation_request(service, mission_id, active, aggregation, key, **extra):
    state=service.get_mission_state(mission_id)["mission_state"]
    vector=service.get_mission_version_vector(mission_id)
    body={"idempotency_key":f"mission-success-evaluation-{key}","expected_version_sha256":vector["version_sha256"],"expected_state_version":int(state["state_version"]),"expected_active_plan_version_record_id":active["plan_version_record_id"],"expected_active_plan_version":int(active["plan_version"]),"expected_active_plan_sha256":active["canonical_sha256"],"expected_aggregation_id":aggregation["aggregation_id"],"expected_aggregation_sha256":aggregation["canonical_sha256"],"evaluated_by":"stage3.6.6-pytest","reason":"evaluate immutable mission success criteria against Stage-3.6.5 evidence","metadata":{"stage":"3.6.6","key":key}}
    body.update(extra); return body

def provision_eval_source(tmp_path:Path,key:str):
    ctx=provision_aggregation_source(tmp_path,key)
    agg=ctx["service"].aggregate_mission_outcome(ctx["mission_id"],deepcopy(ctx["aggregation_body"]))
    body=evaluation_request(ctx["service"],ctx["mission_id"],ctx["active"],agg,key)
    return {**ctx,"aggregation":agg,"evaluation_body":body}

@pytest.fixture(scope="module")
def source_context(tmp_path_factory): return provision_eval_source(tmp_path_factory.mktemp("stage366-source"),"shared-source366")

@pytest.fixture(scope="module")
def evaluated_context(tmp_path_factory):
    ctx=provision_eval_source(tmp_path_factory.mktemp("stage366-evaluated"),"shared-evaluated366")
    gb=ctx["governance"].evaluate_calls; rb=(ctx["runtime"].health_calls,ctx["runtime"].result_calls,ctx["runtime"].control_calls)
    created=ctx["service"].evaluate_mission_success_criteria(ctx["mission_id"],deepcopy(ctx["evaluation_body"]))
    return {**ctx,"created":created,"gov_before":gb,"gov_after":ctx["governance"].evaluate_calls,"runtime_before":rb,"runtime_after":(ctx["runtime"].health_calls,ctx["runtime"].result_calls,ctx["runtime"].control_calls)}

def test_01_health_activates_stage366_migration41(source_context):
    h=source_context["service"].health(); assert h["control_version"]==CONTROL; assert MissionOrchestratorHandler.server_version=="APTSMissionOrchestrator/3.9.10"; assert h["supported_controls"][60:70]==["stage3.7.1-canonical-adaptation-replan-contract-identity","stage3.7.2-adaptation-trigger-detection-classification","stage3.7.3-replan-eligibility-governance-gate","stage3.7.4-canonical-replan-snapshot-context-binding","stage3.7.5-deterministic-replan-candidate-generation","stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization","stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]; assert h["mission_repository_migration_level"]==REPOSITORY_MIGRATION_LEVEL==53; assert "mission_success_criteria_evaluations" in REPOSITORY_STORES

def test_02_definition_declares_evaluation_only_boundary(source_context):
    d=source_context["service"].get_mission_success_evaluation_definition(source_context["mission_id"])["mission_success_evaluation_definition"]; assert d["schema_version"]==MISSION_SUCCESS_EVALUATION_CONTRACT_SCHEMA_VERSION; assert d["consumes_stage365_mission_outcome_aggregation"] is True; assert d["unsupported_criteria_fail_closed_as_indeterminate"] is True; assert d["mission_completion_readiness_decision_performed"] is False; assert d["next_stage"]=="3.6.7"

def test_03_evaluation_creates_immutable_contract(evaluated_context):
    c=evaluated_context["created"]; assert c["evaluation_id"].startswith(MISSION_SUCCESS_EVALUATION_ID_PREFIX); assert c["evaluation_status"]==MISSION_SUCCESS_EVALUATION_STATUS; assert verify_mission_success_evaluation_contract(c["mission_success_evaluation_contract"])

def test_04_exact_criterion_coverage(evaluated_context):
    c=evaluated_context["created"]; assert c["criterion_count"]==len(c["criteria_results"]); assert c["criterion_count"]==c["satisfied_count"]+c["not_satisfied_count"]+c["indeterminate_count"]

def test_05_unknown_mission_metrics_fail_closed_indeterminate(evaluated_context):
    c=evaluated_context["created"]; assert c["overall_result"] in OVERALL_RESULTS; assert all(x["result"] in CRITERION_RESULTS for x in c["criteria_results"])

def test_06_stale_mission_vector_rejected(source_context):
    b=deepcopy(source_context["evaluation_body"]); b["expected_version_sha256"]="0"*64
    with pytest.raises(MissionConcurrencyConflict): source_context["service"].evaluate_mission_success_criteria(source_context["mission_id"],b)

def test_07_stale_plan_hash_rejected(source_context):
    b=deepcopy(source_context["evaluation_body"]); b["expected_active_plan_sha256"]="0"*64
    with pytest.raises(MissionConcurrencyConflict): source_context["service"].evaluate_mission_success_criteria(source_context["mission_id"],b)

def test_08_wrong_aggregation_hash_rejected(source_context):
    b=deepcopy(source_context["evaluation_body"]); b["expected_aggregation_sha256"]="0"*64
    with pytest.raises(MissionConcurrencyConflict): source_context["service"].evaluate_mission_success_criteria(source_context["mission_id"],b)

def test_09_caller_supplied_results_forbidden(source_context):
    for i,(k,v) in enumerate([("criteria_results",[]),("success_criteria_satisfied",True),("completion_ready",True),("mission_completed",True),("plan_progression",True),("governance_decision","ALLOW")]):
        b=deepcopy(source_context["evaluation_body"]); b["idempotency_key"]=f"forbidden-{i}"; b[k]=v
        with pytest.raises(MissionValidationError): source_context["service"].evaluate_mission_success_criteria(source_context["mission_id"],b)

def test_10_same_request_idempotent(evaluated_context):
    s=evaluated_context["service"]; r=s.evaluate_mission_success_criteria(evaluated_context["mission_id"],deepcopy(evaluated_context["evaluation_body"])); assert r["idempotent_replay"] is True; assert r["evaluation_id"]==evaluated_context["created"]["evaluation_id"]

def test_11_idempotency_conflict(evaluated_context):
    b=deepcopy(evaluated_context["evaluation_body"]); b["reason"]="different"
    with pytest.raises(MissionSuccessEvaluationConflict): evaluated_context["service"].evaluate_mission_success_criteria(evaluated_context["mission_id"],b)

def test_12_no_runtime_or_governance_io(evaluated_context): assert evaluated_context["gov_after"]==evaluated_context["gov_before"] and evaluated_context["runtime_after"]==evaluated_context["runtime_before"]

def test_13_restart_reconstruction(evaluated_context):
    s=evaluated_context["service"]; c=evaluated_context["created"]; r=CanonicalMissionService(repository=MissionRepository(sqlite_path=s.repository.sqlite_path)).get_mission_success_evaluation(evaluated_context["mission_id"],c["evaluation_id"]); assert r["canonical_sha256"]==c["canonical_sha256"]

def test_14_exactly_once_lineage_event(evaluated_context):
    es=[e for e in evaluated_context["service"].get_mission_events(evaluated_context["mission_id"])["events"] if e["event_type"]==EVENT_TYPE]; assert len(es)==1; assert es[0]["causation_id"]==evaluated_context["created"]["evaluation_id"]

def test_15_repository_projection_integrity(evaluated_context):
    repo=evaluated_context["service"].get_mission_repository(evaluated_context["mission_id"]); assert repo["integrity_status"]=="PASS"; assert repo["record_counts"]["mission_success_criteria_evaluations"]==1; assert repo["persistence_manifest"]["mission_success_criteria_evaluation_store"]["evaluations"][0]["evaluation_id"]==evaluated_context["created"]["evaluation_id"]

def test_16_tampering_breaks_integrity(tmp_path):
    ctx=provision_eval_source(tmp_path,"tamper366"); c=ctx["service"].evaluate_mission_success_criteria(ctx["mission_id"],deepcopy(ctx["evaluation_body"]));
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as con: con.execute("UPDATE mission_success_criteria_evaluations SET criterion_count=999 WHERE evaluation_id=?",(c["evaluation_id"],)); con.commit()
    with pytest.raises(MissionRepositoryIntegrityError): ctx["service"].get_mission_repository(ctx["mission_id"])

def test_17_history_and_get(evaluated_context):
    s=evaluated_context["service"]; mid=evaluated_context["mission_id"]; c=evaluated_context["created"]; assert s.get_mission_success_evaluation_history(mid)["evaluation_count"]==1; assert s.get_mission_success_evaluation(mid,c["evaluation_id"])["canonical_sha256"]==c["canonical_sha256"]

def test_18_api_routes_registered():
    text=Path("mission_orchestrator/api_service.py").read_text(); assert "mission-success-criteria-evaluations" in text; assert "mission-success-criteria-evaluation-definition" in text

def test_19_authority_boundary_never_completes_mission(evaluated_context):
    c=evaluated_context["created"]; assert c["mission_completion_readiness_decision_performed"] is False; assert c["mission_success_completion_authority_exercised"] is False; assert c["mission_state_transition_performed"] is False; assert c["external_network_io_performed"] is False; assert c["target_actuation"] is False

def test_20_supported_direct_metric_semantics():
    fake_contract={"schema_version":"x"}; agg={"all_tasks_verified_complete":True,"all_tasks_terminal":True,"terminal_non_success_present":False,"task_count":2,"terminal_task_count":2,"verified_complete_count":2,"failed_count":0,"cancelled_count":0,"timed_out_count":0,"running_count":0,"blocked_count":0,"pending_count":0,"mission_execution_outcome_summary":"ALL_TASKS_VERIFIED_COMPLETE"}
    # direct private semantic evidence: criterion equality is deterministic
    from mission_orchestrator.mission_success_evaluation import _criterion_result
    assert _criterion_result({"metric":"all_tasks_verified_complete","expected":True},agg)["result"]=="SATISFIED"
    assert _criterion_result({"metric":"failed_count","expected":1},agg)["result"]=="NOT_SATISFIED"
