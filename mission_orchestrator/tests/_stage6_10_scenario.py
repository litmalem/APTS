"""Isolated native trajectory. No deployed database or user target is used."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import sys
from threading import Thread, RLock
import time

from execution_subsystem.apts_acceptance_service import APTSAcceptanceService
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.cti_feedback_repository import ExecutionCTIFeedbackRepository
from execution_subsystem.cti_knowledge_repository import CTIKnowledgeRepository
from execution_subsystem.execution_contract import canonical_json
from execution_subsystem.governance_client import ExecutionGovernanceClient
from execution_subsystem.runtime_contract import START_SCHEMA
from pentest_subsystem.governance_bound_e2e import GovernanceBoundE2ERepository
from pentest_subsystem.pip_contract import seal_pip_artifact
from pentest_subsystem.task_contract import build_pentest_task_binding
from tests.test_stage3_7_3_replan_eligibility_governance_gate import make_governed_service, PolicyGovernanceClient, scope_payload, binding_payload
from tests.test_stage3_3_4_task_dependency_graph_structural_validation import (
    mission_payload, activate_planning, plan_request, snapshot_request, decomposition_request, graph_request)
from tests.test_stage3_3_5_planner_invocation_plan_generation import planner_request
from tests.test_stage3_3_6_plan_validation_feasibility_gate import validation_request
from tests.test_stage3_3_7_plan_versioning_replanning_supersession import activate_v1
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage4_3_pentest_mission_task_contract import sample_boundary, sample_pip, sample_task, FIXED_NOW
from tests.test_stage5_1_full_agentic_pentest_workflow_orchestrator import start_payload
from tests.test_stage5_2_reconnaissance_agent import recon_request
from tests.test_stage5_3_enumeration_agent import enumeration_request
from tests.test_stage5_4_vulnerability_hypothesis_agent import hypothesis_request
from tests.test_stage5_5_attack_path_planning_agent import attack_path_request
from tests.test_stage5_6_exploitation_agent import exploitation_request
from tests.test_stage5_7_post_exploitation_impact_agent import impact_request
from tests.test_stage6_1_canonical_execution_request_contract import intake_for
from tests._stage6_10_cti import assemble_native_pip


def provision(root, target):
    key = "stage610-connected"
    mission, authority = make_governed_service(root / "mission.db", PolicyGovernanceClient())
    objective = mission_payload(key)
    objective.update(source_system="STAGE610_ISOLATED_OPERATOR", created_by="acceptance-operator",
        required_subsystems=["CTI", "PENTEST"],
        pip_version="1",
        objective={"type": "SECURITY_VALIDATION", "target_ref": target,
                   "description": "Observe the authorized loopback service and retain validation evidence."})
    mid = mission.create_mission(objective)["canonical_identity"]["mission_id"]
    scope_body = scope_payload(key)
    scope_body["scope"]["targets"] = [{"target_type": "URL", "target_value": target}]
    scope_body["roe"]["allowed_action_classes"].append("INTERNAL_REASONING")
    scope_body["roe"]["human_approval_required_for"] = []
    scope_body["constraints"]["data_handling_policy"] = {"retain_sensitive_output": False}
    scope = mission.put_mission_scope_contract(mid, scope_body)
    binding = mission.put_mission_governance_binding(mid, binding_payload(key))
    reference = mission.repository.get_by_mission_id(mid).envelope["bindings"]["pip"]
    native_pip = assemble_native_pip(mid, reference, target, scope, binding)
    activate_planning(mission, mid, key)
    mission.create_mission_plan_contract(mid, plan_request(mission, mid, key))
    mission.create_planner_input_snapshot(mid, snapshot_request(mission, mid, key))
    body = decomposition_request(mission, mid, key)
    body["tasks"] = [{**body["tasks"][0], "task_key": "validate-pentest", "task_type": "SECURITY_VALIDATION",
        "required_capability": "pentest.validate", "required_subsystem": "PENTEST",
        "objective": {"goal": "Observe authorized loopback service; retain evidence for further validation"}}]
    mission.create_task_decomposition(mid, body)
    mission.create_task_dependency_graph(mid, graph_request(mission, mid, key, edges=[]))
    mission.invoke_planner_and_generate_plan(mid, planner_request(mission, mid, key))
    feasible = mission.validate_generated_plan_feasibility(mid, validation_request(mission, mid, key))
    active = activate_v1(mission, mid, feasible, key)
    execute(mission, mid, "START", key)
    boundary = sample_boundary()
    boundary.update(mission_id=mid, task_id=active["plan_version_contract"]["candidate_plan"]["plan_steps"][0]["planned_task_id"])
    boundary["scope"]["targets"][0] = {"target_type": "URL", "target_value": target}
    intake_now = datetime.now(timezone.utc)
    pip = sample_pip(boundary, now=intake_now)
    core = {k: v for k, v in pip.items() if k != "integrity"}
    core.update(pip_id=reference["pip_id"], pip_version=reference["pip_version"])
    core["source_cti"].update(artifact_id=native_pip["pip_id"], artifact_version=str(native_pip["revision"]),
        artifact_sha256=native_pip["canonical_sha256"])
    core["confidence"] = native_pip["artifact"]["intelligence"]["normalized_objects"][0]["confidence"]
    core["intelligence"] = deepcopy(native_pip["artifact"]["intelligence"])
    core["provenance"]["source_refs"] = [native_pip["pip_id"], "fixture:stage610:synthetic-cti-feed"]
    pip = seal_pip_artifact(core)
    task = sample_task(boundary, pip, now=intake_now)
    bound = build_pentest_task_binding(boundary_payload=boundary, pip_payload=pip, task_payload=task, now=intake_now)
    pentest = GovernanceBoundE2ERepository(root / "pentest.db")
    pentest.create_task(task, bound)
    orch, _, _, _ = pentest.start_orchestration(task["pentest_task_id"], start_payload(key))
    oid = orch["orchestration_id"]
    runs = {}
    runs["5.2"], _ = pentest.run_reconnaissance(oid, recon_request(boundary, task, key))
    runs["5.3"], _ = pentest.run_enumeration(oid, enumeration_request(boundary, task, runs["5.2"], key, proposals=False))
    hypothesis_body = hypothesis_request(boundary, runs["5.3"], key, match=True)
    cti_knowledge = deepcopy(pip["intelligence"]["normalized_objects"][0])
    cti_knowledge["content_sha256"] = native_pip["canonical_sha256"]
    cti_knowledge["source"].update(source_id=native_pip["pip_id"], source_ref="cti:"+native_pip["pip_id"])
    hypothesis_body["knowledge_items"] = [cti_knowledge]
    runs["5.4"], _ = pentest.run_vulnerability_hypothesis(oid, hypothesis_body)
    runs["5.5"], _ = pentest.run_attack_path_planning(oid, attack_path_request(boundary, runs["5.4"], key))
    runs["5.6"], _ = pentest.run_exploitation(oid, exploitation_request(boundary, runs["5.5"], key))
    return {"mission": mission, "mission_governance": authority, "mission_id": mid, "active": active,
        "scope": scope, "binding": binding, "boundary": boundary, "pip": pip, "task": task,
        "pentest": pentest, "orchestration_id": oid, "runs": runs, "root": root, "native_pip": native_pip}


def gss_root():
    explicit = os.getenv("APTS_ACCEPTANCE_GSS_ROOT")
    candidates = [Path(explicit)] if explicit else [Path(__file__).resolve().parents[2] / name for name in ("gss", "aptsGSS")]
    for path in candidates:
        if (path / "app" / "execution_revalidation.py").is_file():
            return path.resolve()
    raise RuntimeError("Stage 6.10 requires APTS_ACCEPTANCE_GSS_ROOT pointing to the supplied aptsGSS source")


class Capture:
    def __init__(self): self.items = []
    def record(self, *args, **kwargs): self.items.append((args, kwargs))
    def publish(self, *args, **kwargs): self.items.append((args, kwargs)); return "gevt-stage610"
    def obligations(self, *args): return []


class AuthorityRepository:
    """Repository fixture only. Decisions and checks use the supplied production GSS code."""
    def __init__(self, request, context):
        now = datetime.now(timezone.utc)
        self.lock = RLock()
        self.mode = "ALLOW"
        gov = context["governance_authority"]
        self.scope = {"scope_contract_id": gov["governance_scope_contract_id"], "mission_id": request["mission_id"],
            "version": gov["governance_scope_version"], "contract_hash": gov["governance_scope_contract_hash"],
            "status": "ACTIVE", "policy_set_id": gov["policy_set_id"],
            "valid_from": now-timedelta(minutes=1), "valid_until": now+timedelta(hours=1),
            "targets": [{**request["target"], "allowed": 1, "environment": "LAB"}], "sources": []}
        reference = request["authorization_requirement"]["policy_reference"]
        self.policy = {"policy_set_id": gov["policy_set_id"], "version": max(10, reference["policy_version"]),
            "status": "ACTIVE", "effective_from": now-timedelta(days=1), "effective_until": now+timedelta(days=1)}
        self.old = {"decision_id": reference["policy_decision_id"], "decision_hash": reference["policy_decision_hash"],
            "mission_id": request["mission_id"], "decision_status": "ACTIVE"}
        self.technique = request["action"]["technique"]
        self.decisions, self.requests, self.risks, self.approvals = [], [], [], []
    def get_scope_contract(self, identity): return deepcopy(self.scope) if identity == self.scope["scope_contract_id"] else None
    def find_active_scope_for_mission(self, identity): return deepcopy(self.scope) if identity == self.scope["mission_id"] else None
    def get_policy_set(self, identity): return deepcopy(self.policy)
    def find_action_constraint(self, *args):
        return {"effect": "DENY" if self.mode == "DENY" else "ALLOW", "max_risk_level": "HIGH",
            "requires_approval": int(self.mode == "REVIEW"), "constraints": {"allowed_techniques": [self.technique]}}
    def get_policy_decision(self, identity):
        if identity == self.old["decision_id"]: return deepcopy(self.old)
        return next((deepcopy(d) for d in self.decisions if d["decision_id"] == identity), None)
    def get_emergency_state(self): return {"active": int(self.mode == "EMERGENCY")}
    def insert_authorization_request(self, row): self.requests.append(deepcopy(row))
    def insert_risk_assessment(self, row): self.risks.append(deepcopy(row))
    def insert_policy_decision(self, row): self.decisions.append(deepcopy(row))
    def insert_approval_request(self, row): self.approvals.append(deepcopy(row))
    def update_authorization_status(self, *args): pass


@contextmanager
def native_authority(request, context):
    root = gss_root()
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("app.governance_service")
        models = importlib.import_module("app.models")
    finally:
        sys.path.remove(str(root))
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise RuntimeError("GSS authority module does not belong to the configured source")
    repo = AuthorityRepository(request, context)
    native = module.GovernanceService(repo)
    native.audit, native.events, native.compliance = Capture(), Capture(), Capture()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/api/governance/authorization/evaluate":
                self.send_error(404); return
            if repo.mode == "TIMEOUT": time.sleep(0.25)
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with repo.lock:
                    result = native.evaluate_authorization(models.AuthorizationRequest(**body))
                raw = canonical_json({"status": "completed", "policy_decision": result}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError): pass
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", repo, native
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def runtime_for(ctx, authority_url, *, timeout=2.0):
    root = ctx["root"]
    runtime = APTSAcceptanceService(ExecutionCTIFeedbackRepository(root / "execution.db"),
        ExecutionAuthorizationProposalSource(ctx["pentest"].sqlite_path),
        MissionAuthorizationSource(ctx["mission"].repository.sqlite_path),
        ExecutionGovernanceClient(authority_url, timeout),
        knowledge_repository=CTIKnowledgeRepository(root / "knowledge.db"))
    request = runtime.create_request(intake_for(ctx["runs"]["5.6"], "stage610-connected"))
    start = {"schema_version": START_SCHEMA, "invocation_request_id": "toolreq-stage610",
        "idempotency_key": "idem-tool-stage610", "execution_id": request["execution_id"],
        "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"], "requested_by": "acceptance-operator"}
    ctx.update(runtime=runtime, execution_request=request, start=start)
    ctx["mission"].cti_feedback_source = CTIKnowledgeRepository(root / "knowledge.db", read_only=True)
    return runtime


def post_impact(ctx):
    item, _ = ctx["pentest"].run_post_exploitation_impact(ctx["orchestration_id"],
        impact_request(ctx["boundary"], ctx["runs"]["5.6"], "stage610-connected"))
    ctx["runs"]["5.7"] = item
    return item
