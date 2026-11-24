from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sqlite3
import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import MissionConcurrencyConflict, MissionCompletionReadinessConflict, MissionRepositoryIntegrityError, MissionValidationError
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.completion_readiness import *
from tests.test_stage3_6_6_mission_success_criteria_evaluation import provision_eval_source

CONTROL="stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR="stage3.6.9-outcome-lineage-replay-recovery"
EVENT_TYPE="MISSION_COMPLETION_READINESS_EVALUATED"

def readiness_request(service, mission_id, active, evaluation, key, **extra):
    state=service.get_mission_state(mission_id)["mission_state"]
    vector=service.get_mission_version_vector(mission_id)
    body={"idempotency_key":f"completion-readiness-{key}","expected_version_sha256":vector["version_sha256"],"expected_state_version":int(state["state_version"]),"expected_active_plan_version_record_id":active["plan_version_record_id"],"expected_active_plan_version":int(active["plan_version"]),"expected_active_plan_sha256":active["canonical_sha256"],"expected_evaluation_id":evaluation["evaluation_id"],"expected_evaluation_sha256":evaluation["canonical_sha256"],"decided_by":"stage3.6.7-pytest","reason":"derive fail-closed completion readiness and blockers","metadata":{"stage":"3.6.7","key":key}}
    body.update(extra); return body

def provision_readiness_source(tmp_path:Path,key:str):
    ctx=provision_eval_source(tmp_path,key)
    ev=ctx["service"].evaluate_mission_success_criteria(ctx["mission_id"],deepcopy(ctx["evaluation_body"]))
    body=readiness_request(ctx["service"],ctx["mission_id"],ctx["active"],ev,key)
    return {**ctx,"evaluation":ev,"readiness_body":body}

@pytest.fixture(scope="module")
def source_context(tmp_path_factory): return provision_readiness_source(tmp_path_factory.mktemp("stage367-source"),"shared-source367")

@pytest.fixture(scope="module")
def decided_context(tmp_path_factory):
    ctx=provision_readiness_source(tmp_path_factory.mktemp("stage367-decided"),"shared-decided367")
    gb=ctx["governance"].evaluate_calls; rb=(ctx["runtime"].health_calls,ctx["runtime"].result_calls,ctx["runtime"].control_calls)
    created=ctx["service"].evaluate_completion_readiness(ctx["mission_id"],deepcopy(ctx["readiness_body"]))
    return {**ctx,"created":created,"gov_before":gb,"gov_after":ctx["governance"].evaluate_calls,"runtime_before":rb,"runtime_after":(ctx["runtime"].health_calls,ctx["runtime"].result_calls,ctx["runtime"].control_calls)}

def test_01_health_activates_stage367_migration42(source_context):
    h=source_context["service"].health(); assert h["control_version"]==CONTROL; assert MissionOrchestratorHandler.server_version=="APTSMissionOrchestrator/3.9.10"; assert h["supported_controls"][60:70]==["stage3.7.1-canonical-adaptation-replan-contract-identity","stage3.7.2-adaptation-trigger-detection-classification","stage3.7.3-replan-eligibility-governance-gate","stage3.7.4-canonical-replan-snapshot-context-binding","stage3.7.5-deterministic-replan-candidate-generation","stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization","stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]; assert h["mission_repository_migration_level"]==REPOSITORY_MIGRATION_LEVEL==53; assert "mission_completion_readiness_decisions" in REPOSITORY_STORES

def test_02_definition_declares_fail_closed_readiness_only_boundary(source_context):
    d=source_context["service"].get_completion_readiness_definition(source_context["mission_id"])["completion_readiness_definition"]; assert d["schema_version"]==COMPLETION_READINESS_CONTRACT_SCHEMA_VERSION; assert d["consumes_stage366_success_criteria_evaluation"] is True; assert d["fail_closed"] is True; assert d["mission_success_completion_authority_exercised"] is False; assert d["next_stage"]=="3.6.8"

def test_03_decision_creates_immutable_contract(decided_context):
    c=decided_context["created"]; assert c["readiness_id"].startswith(COMPLETION_READINESS_ID_PREFIX); assert c["readiness_status"]==COMPLETION_READINESS_STATUS; assert verify_completion_readiness_contract(c["completion_readiness_contract"])

def test_04_blockers_are_deterministic_and_exact(decided_context):
    c=decided_context["created"]; assert c["readiness_result"] in READINESS_RESULTS; assert c["completion_ready"] == (c["readiness_result"]=="READY"); assert c["blocker_count"]==len(c["blockers"]); assert all(x["code"] in BLOCKER_CODES for x in c["blockers"])

def test_05_indeterminate_success_criteria_fail_closed(decided_context):
    ev=decided_context["evaluation"]; c=decided_context["created"]
    if ev["overall_result"]=="SUCCESS_CRITERIA_INDETERMINATE": assert any(x["code"]=="SUCCESS_CRITERIA_INDETERMINATE" for x in c["blockers"]) and c["completion_ready"] is False

def test_06_stale_mission_vector_rejected(source_context):
    b=deepcopy(source_context["readiness_body"]); b["expected_version_sha256"]="0"*64
    with pytest.raises(MissionConcurrencyConflict): source_context["service"].evaluate_completion_readiness(source_context["mission_id"],b)

def test_07_stale_plan_hash_rejected(source_context):
    b=deepcopy(source_context["readiness_body"]); b["expected_active_plan_sha256"]="0"*64
    with pytest.raises(MissionConcurrencyConflict): source_context["service"].evaluate_completion_readiness(source_context["mission_id"],b)

def test_08_wrong_evaluation_hash_rejected(source_context):
    b=deepcopy(source_context["readiness_body"]); b["expected_evaluation_sha256"]="0"*64
    with pytest.raises(MissionConcurrencyConflict): source_context["service"].evaluate_completion_readiness(source_context["mission_id"],b)

def test_09_caller_supplied_readiness_or_authority_fields_forbidden(source_context):
    for i,(k,v) in enumerate([("completion_ready",True),("readiness_result","READY"),("blockers",[]),("mission_completed",True),("mission_state_transition",True),("plan_progression",True),("governance_decision","ALLOW")]):
        b=deepcopy(source_context["readiness_body"]); b["idempotency_key"]=f"forbidden367-{i}"; b[k]=v
        with pytest.raises(MissionValidationError): source_context["service"].evaluate_completion_readiness(source_context["mission_id"],b)

def test_10_same_request_idempotent(decided_context):
    s=decided_context["service"]; r=s.evaluate_completion_readiness(decided_context["mission_id"],deepcopy(decided_context["readiness_body"])); assert r["idempotent_replay"] is True; assert r["readiness_id"]==decided_context["created"]["readiness_id"]

def test_11_idempotency_conflict(decided_context):
    b=deepcopy(decided_context["readiness_body"]); b["reason"]="different"
    with pytest.raises(MissionCompletionReadinessConflict): decided_context["service"].evaluate_completion_readiness(decided_context["mission_id"],b)

def test_12_no_runtime_or_governance_io(decided_context): assert decided_context["gov_after"]==decided_context["gov_before"] and decided_context["runtime_after"]==decided_context["runtime_before"]

def test_13_restart_reconstruction(decided_context):
    s=decided_context["service"]; c=decided_context["created"]; r=CanonicalMissionService(repository=MissionRepository(sqlite_path=s.repository.sqlite_path)).get_completion_readiness(decided_context["mission_id"],c["readiness_id"]); assert r["canonical_sha256"]==c["canonical_sha256"]

def test_14_exactly_once_lineage_event(decided_context):
    es=[e for e in decided_context["service"].get_mission_events(decided_context["mission_id"])["events"] if e["event_type"]==EVENT_TYPE]; assert len(es)==1; assert es[0]["causation_id"]==decided_context["created"]["readiness_id"]

def test_15_repository_projection_integrity(decided_context):
    repo=decided_context["service"].get_mission_repository(decided_context["mission_id"]); assert repo["integrity_status"]=="PASS"; assert repo["record_counts"]["mission_completion_readiness_decisions"]==1; assert repo["persistence_manifest"]["mission_completion_readiness_store"]["decisions"][0]["readiness_id"]==decided_context["created"]["readiness_id"]

def test_16_tampering_breaks_integrity(tmp_path):
    ctx=provision_readiness_source(tmp_path,"tamper367"); c=ctx["service"].evaluate_completion_readiness(ctx["mission_id"],deepcopy(ctx["readiness_body"]));
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as con: con.execute("UPDATE mission_completion_readiness_decisions SET blocker_count=999 WHERE readiness_id=?",(c["readiness_id"],)); con.commit()
    with pytest.raises(MissionRepositoryIntegrityError): ctx["service"].get_mission_repository(ctx["mission_id"])

def test_17_history_and_get(decided_context):
    s=decided_context["service"]; mid=decided_context["mission_id"]; c=decided_context["created"]; assert s.get_completion_readiness_history(mid)["decision_count"]==1; assert s.get_completion_readiness(mid,c["readiness_id"])["canonical_sha256"]==c["canonical_sha256"]

def test_18_api_routes_registered():
    text=Path("mission_orchestrator/api_service.py").read_text(); assert "completion-readiness-decisions" in text; assert "completion-readiness-definition" in text

def test_19_authority_boundary_never_completes_mission(decided_context):
    c=decided_context["created"]; assert c["completion_readiness_decision_performed"] is True; assert c["mission_success_completion_authority_exercised"] is False; assert c["mission_state_transition_performed"] is False; assert c["external_network_io_performed"] is False; assert c["target_actuation"] is False

def test_20_failed_or_aborted_lifecycle_is_always_blocked(decided_context):
    ev=decided_context["evaluation"]
    for state in ("FAILED","ABORTED"):
        d=derive_completion_readiness(mission_state=state,evaluation=ev); assert d["completion_ready"] is False; assert d["readiness_result"]=="BLOCKED"; assert d["blockers"][0]["code"]=="MISSION_STATE_NOT_RUNNING"
