from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.execution_revalidation import CHECKS, EVAL_DOMAIN, REQUEST_DOMAIN, digest
from app.governance_service import GovernanceError, GovernanceService
from app.models import AuthorizationRequest
from app.models import ApprovalDecisionInput
from app.approval_auth import ApprovalAccessError, ApprovalPrincipal
from app.utils import sha256_json


def seal(core, domain):
    return {**core, "integrity": {"algorithm":"SHA-256", "canonicalization":"UTF8_SORTED_JSON_V1", "hash_domain":domain,
                                 "canonical_sha256":digest({"hash_domain":domain,"core":core})}}


class Repo:
    def __init__(self, req, gov):
        now=datetime.now(timezone.utc)
        self.scope={"scope_contract_id":gov["governance_scope_contract_id"],"mission_id":req["mission_id"],"version":1,"contract_hash":"b"*64,"status":"ACTIVE","policy_set_id":"default-policy",
                    "valid_from":now-timedelta(minutes=1),"valid_until":now+timedelta(hours=1),
                    "targets":[{**req["target"],"allowed":1,"environment":"LAB"}],"sources":[]}
        self.policy={"policy_set_id":"default-policy","version":10,"status":"ACTIVE","effective_from":now-timedelta(days=1),"effective_until":now+timedelta(days=1)}
        self.constraint={"effect":"ALLOW","max_risk_level":"HIGH","requires_approval":0,"constraints":{"allowed_techniques":[req["action"]["technique"]]}}
        ref=req["authorization_requirement"]["policy_reference"]
        self.old={"decision_id":ref["policy_decision_id"],"decision_hash":ref["policy_decision_hash"],"mission_id":req["mission_id"],"decision_status":"ACTIVE"}
        self.emergency={"active":0}
        self.decisions=[];self.authorizations=[];self.risks=[];self.approvals=[];self.approval_decisions=[]
    def get_scope_contract(self,identity):return deepcopy(self.scope) if identity==self.scope["scope_contract_id"] else None
    def find_active_scope_for_mission(self,identity):return deepcopy(self.scope) if identity==self.scope["mission_id"] else None
    def get_policy_set(self,identity):return deepcopy(self.policy)
    def find_action_constraint(self,*args):return deepcopy(self.constraint)
    def get_policy_decision(self,identity):return deepcopy(self.old) if self.old and identity==self.old["decision_id"] else None
    def get_emergency_state(self):return deepcopy(self.emergency)
    def insert_authorization_request(self,row):self.authorizations.append(row)
    def insert_risk_assessment(self,row):self.risks.append(row)
    def insert_policy_decision(self,row):self.decisions.append(row)
    def insert_approval_request(self,row):self.approvals.append({**row,"status":"PENDING"})
    def update_authorization_status(self,request_id,status):
        for row in self.authorizations:
            if row["request_id"]==request_id:row["request_status"]=status
    def get_authorization_request(self,request_id):
        for row in self.authorizations:
            if row["request_id"]==request_id:
                return {**deepcopy(row),"context":json.loads(row["context_json"]),"evidence_refs":json.loads(row["evidence_refs_json"])}
    def get_approval_request(self,approval_id):
        return next((deepcopy(row) for row in self.approvals if row["approval_request_id"]==approval_id),None)
    def insert_approval_decision(self,row):
        approval=next(a for a in self.approvals if a["approval_request_id"]==row["approval_request_id"])
        if approval["status"]!="PENDING":raise ApprovalAccessError("APPROVAL_NO_LONGER_PENDING_OR_VALID",409)
        approval["status"]="APPROVED" if row["decision"]=="APPROVE" else "DENIED"
        self.approval_decisions.append(deepcopy(row))
    @contextmanager
    def approval_transaction(self):
        before=deepcopy(self.__dict__)
        try:yield
        except Exception:
            self.__dict__.update(before)
            raise


class Capture:
    def __init__(self):self.items=[]
    def record(self,*args,**kwargs):self.items.append((args,kwargs))
    def publish(self,*args,**kwargs):self.items.append((args,kwargs));return "gevt-stage64-proof"
    def obligations(self,*args):return []


def service_for(req, gov):
    repo=Repo(req,gov);service=GovernanceService(repo)
    service.audit=Capture();service.events=Capture();service.compliance=Capture()
    return service,repo


def reseal(evaluation):
    core={k:v for k,v in evaluation.items() if k!="integrity"}
    return seal(core,EVAL_DOMAIN)


@pytest.fixture
def ctx():
    now=datetime.now(timezone.utc)
    target={"target_type":"IP","target_value":"127.0.0.1"}
    gov={"governance_scope_contract_id":"scope-stage64","governance_scope_version":1,"governance_scope_contract_hash":"b"*64,"policy_set_id":"default-policy",
         "authorization_authority":"aptsGSS","authorization_authority_component":"GOV-PLANE"}
    source={"scope":{"targets":[target],"excluded_targets":[]},"roe":{"allowed_action_classes":["VULNERABILITY_VALIDATION"],"prohibited_action_classes":[],"human_approval_required_for":[],"credential_usage_allowed":False},
            "constraints":{"max_actions":10,"max_duration":30,"risk_threshold":"MODERATE","resource_budget":{},"data_handling_policy":{"retain_sensitive_output":False}}}
    req=seal({"schema_version":"apts-execution-request-v1","execution_id":"exec-stage64","mission_id":"mission-gmo-stage64","task_id":"ptask-stage64","pentest_id":"pentest-stage64",
        "proposing_agent":{"agent_id":"agent-stage64","role":"exploitation","orchestration_id":"orch-stage64","subtask_id":"subtask-stage64"},
        "action":{"action_class":"VULNERABILITY_VALIDATION","capability_id":"exploitation","technique":"SAFE_VERSION_CONFIGURATION_CONFIRMATION"},"target":target,
        "parameters":{"validation_task_id":"valtask-stage64","expected_evidence":["version"],"estimated_impact":"LOW"},"evidence_basis":[{"evidence_id":"evi-stage64","canonical_sha256":"c"*64}],
        "authorization_requirement":{"authority":"EXTERNAL_APTS_GSS","revalidation_required":True,"required_checks":list(CHECKS),"human_review_required":False,
            "policy_reference":{"policy_decision_id":"gdec-old","policy_decision_hash":"a"*64,"policy_version":10,"reference_sha256":"d"*64}}},REQUEST_DOMAIN)
    evaluation=seal({"schema_version":"apts-execution-authorization-evaluation-v1","revalidation_id":"eauthreq-stage64","nonce":"f"*32,"submitted_at":now.isoformat(),
        "intake":{"schema_version":"apts-execution-authorization-intake-v1","revalidation_id":"eauthreq-stage64","idempotency_key":"idem-stage64","execution_id":req["execution_id"],"envelope_sha256":"e"*64,"requested_by":"test"},
        "execution_request":req,"envelope_sha256":"e"*64,"source_binding":{},
        "current_context":{"mission_id":req["mission_id"],"mission_state":"RUNNING","mission_scope":deepcopy(source),"governance_authority":gov,"pentest_context":{"boundary":deepcopy(source),"task":deepcopy(source)}},
        "local_checks":{k:"PASS" for k in ("SCOPE","ROE","TARGET","RISK","TECHNIQUE")},"required_checks":list(CHECKS)},EVAL_DOMAIN)
    service,repo=service_for(req,gov)
    return service,repo,evaluation


def request(evaluation, **extra):
    req=evaluation["execution_request"]
    body={"mission_id":req["mission_id"],"scope_contract_id":"scope-stage64","subject_component":"EXECUTION_SUBSYSTEM","action_class":req["action"]["action_class"],
          "action_name":"AUTHORIZE_TARGET_EXECUTION","resource_type":req["target"]["target_type"],"resource_value":req["target"]["target_value"],"requested_by":"test",
          "context":{"authorization_purpose":"STAGE6_2_EXECUTION_REVALIDATION","execution_authorization_evaluation":evaluation},"evidence_refs":["evi-stage64"]}
    body.update(extra)
    return AuthorizationRequest(**body)


def test_authoritative_proof_is_bound_before_decision_hash_and_audit(ctx):
    service,repo,evaluation=ctx;result=service.evaluate_authorization(request(evaluation))
    assert result["decision"]=="ALLOW" and result["execution_revalidation"]["checks"]=={k:"PASS" for k in CHECKS}
    proof=result["execution_revalidation"]
    assert proof["evaluation_sha256"]==evaluation["integrity"]["canonical_sha256"] and proof["context_sha256"]==digest(evaluation["current_context"])
    assert proof["human_approval_verified"] is False and proof["revoked"] is False
    core={k:v for k,v in result.items() if k not in {"decision_hash","governance_event_id"}}
    assert result["decision_hash"]==sha256_json(core)==repo.decisions[-1]["decision_hash"]
    assert service.audit.items[-1][1]["payload"]["execution_revalidation"]==proof


@pytest.mark.parametrize("field,value",[("resource_value","outside.example"),("mission_id","mission-gmo-other"),("scope_contract_id","scope-other"),("action_name","RUN_TOOL"),("subject_component","SPECIALIST"),("requested_by","other"),("evidence_refs",[])])
def test_unbound_caller_context_is_rejected_before_persistence(ctx,field,value):
    service,repo,evaluation=ctx
    with pytest.raises(GovernanceError):service.evaluate_authorization(request(evaluation,**{field:value}))
    assert not repo.decisions and not repo.authorizations


@pytest.mark.parametrize("field,value",[("nonce","bad"),("required_checks",["SCOPE"]),("schema_version","fake"),("envelope_sha256","changed")])
def test_resealed_malformed_evaluation_is_rejected(ctx,field,value):
    service,repo,evaluation=ctx;evaluation[field]=value;evaluation=reseal(evaluation)
    with pytest.raises(GovernanceError):service.evaluate_authorization(request(evaluation))
    assert not repo.decisions


def test_tampered_evaluation_digest_is_rejected(ctx):
    service,repo,evaluation=ctx;evaluation["nonce"]="a"*32
    with pytest.raises(GovernanceError):service.evaluate_authorization(request(evaluation))


@pytest.mark.parametrize("change,check",[("scope_version","SCOPE"),("scope_hash","SCOPE"),("out_of_scope","TARGET"),("excluded","TARGET"),("policy_inactive","POLICY"),
    ("policy_downgrade","POLICY"),("technique_denied","TECHNIQUE"),("empty_techniques","TECHNIQUE"),("expired_scope","EXPIRY"),("revoked","REVOCATION"),("missing_old","REVOCATION"),("old_hash","REVOCATION")])
def test_server_owned_restrictions_override_caller_pass_and_allow(ctx,change,check):
    service,repo,evaluation=ctx
    if change=="scope_version":repo.scope["version"]=2
    elif change=="scope_hash":repo.scope["contract_hash"]="f"*64
    elif change=="out_of_scope":repo.scope["targets"]=[]
    elif change=="excluded":repo.scope["targets"].append({"target_type":"IP","target_value":"127.0.0.1","allowed":0})
    elif change=="policy_inactive":repo.policy["status"]="DISABLED"
    elif change=="policy_downgrade":repo.policy["version"]=1
    elif change=="technique_denied":repo.constraint["constraints"]["allowed_techniques"]=["DIFFERENT"]
    elif change=="empty_techniques":repo.constraint["constraints"]["allowed_techniques"]=[]
    elif change=="expired_scope":repo.scope["valid_until"]=datetime.now(timezone.utc)-timedelta(seconds=1)
    elif change=="revoked":repo.old["decision_status"]="REVOKED"
    elif change=="missing_old":repo.old=None
    elif change=="old_hash":repo.old["decision_hash"]="f"*64
    result=service.evaluate_authorization(request(evaluation))
    assert result["decision"]=="DENY" and result["execution_revalidation"]["checks"][check]=="FAIL"


def test_emergency_stop_remains_authoritative(ctx):
    service,repo,evaluation=ctx;repo.emergency["active"]=1
    result=service.evaluate_authorization(request(evaluation))
    assert result["decision"]=="DENY" and result["execution_revalidation"]["emergency_stop"] is True


@pytest.mark.parametrize("source_name",["mission","pentest","task"])
def test_source_roe_restrictions_are_recomputed_not_echoed(ctx,source_name):
    service,repo,evaluation=ctx
    context=evaluation["current_context"]
    source=context["mission_scope"] if source_name=="mission" else context["pentest_context"]["boundary" if source_name=="pentest" else "task"]
    source["roe"]["allowed_action_classes"]=[];evaluation=reseal(evaluation)
    result=service.evaluate_authorization(request(evaluation))
    assert result["decision"]=="DENY" and result["execution_revalidation"]["checks"]["ROE"]=="FAIL"


def test_expired_evaluation_fails_freshness(ctx):
    service,repo,evaluation=ctx;evaluation["submitted_at"]=(datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat();evaluation=reseal(evaluation)
    result=service.evaluate_authorization(request(evaluation))
    assert result["decision"]=="DENY" and result["execution_revalidation"]["checks"]["EXPIRY"]=="FAIL"


def test_human_review_cannot_be_supplied_by_caller(ctx):
    service,repo,evaluation=ctx;repo.constraint["requires_approval"]=1
    payload=request(evaluation);payload.context["human_approval_granted"]=True
    result=service.evaluate_authorization(payload)
    assert result["decision"]=="REVIEW" and result["execution_revalidation"]["human_approval_verified"] is False


def test_approved_server_path_marks_proof_without_overriding_hard_deny(ctx):
    service,repo,evaluation=ctx;repo.constraint["requires_approval"]=1
    review=service.evaluate_authorization(request(evaluation))
    principal=ApprovalPrincipal("operator-stage64",frozenset({"SECURITY_APPROVER"}),"HUMAN")
    result=service.decide_approval(review["approval_request_id"],ApprovalDecisionInput(decision="APPROVE",reason="Authorized lab review"),principal=principal)["policy_decision"]
    assert result["decision"]=="ALLOW" and result["execution_revalidation"]["human_approval_verified"] is True
    review=service.evaluate_authorization(request(evaluation))
    repo.emergency["active"]=1
    assert service.decide_approval(review["approval_request_id"],ApprovalDecisionInput(decision="APPROVE",reason="Authorized lab review"),principal=principal)["policy_decision"]["decision"]=="DENY"
