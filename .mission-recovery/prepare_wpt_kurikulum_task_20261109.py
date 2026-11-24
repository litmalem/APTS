"""Operator-authored recovery task using actual CTI source and fresh GSS authorization."""
exec((__import__('pathlib').Path('D:/APTS/.mission-recovery/repair_wpt_kurikulum_scope_20261109.py').read_text().split('service=CanonicalMissionService();source=fetch(service,MID)')[0]))
from copy import deepcopy
from datetime import datetime,timezone
from mission_orchestrator.cti_stage43_bridge import _verify_cti_pip,_z
from mission_orchestrator.task_routing import CtiSubsystemClient
from pentest_subsystem.pip_contract import seal_pip_artifact,build_pip_ingestion_binding
from pentest_subsystem.task_contract import seal_pentest_task_artifact
from mission_orchestrator.mission_planning_automation import _publish_scope_targets
service=CanonicalMissionService()
route=service.get_task_route_selection_decision(MID,'rdec-be6ec64e-b71d-4c1f-b0f0-e7e6cfaacd2d')
print('Binding',_ensure_pentest_governance_binding(service,MID,route),flush=True)
scope=service.get_mission_scope_contract(MID)['contract']
assert {(t['target_type'],t['target_value']) for t in scope['scope']['targets']}=={('URL','https://kurikulum.del.ac.id:443'),('IP','172.21.2.2')}
print('Recon declarations',_publish_scope_targets(service,MID,service.get_mission_scope_contract(MID)),flush=True)
old=call('http://127.0.0.1:8790/api/pentest/tasks/pentest-task-a1e5e7545ad16a3e40a0161ebf9cc5b9')['record']
task=deepcopy(old['task']);oldpip={'pip_id':task['pip_reference']['pip_id']}
upstream='ptask-wpt-kurikulum-internal-20261109'
pentest='pentest-wpt-kurikulum-internal-20261109'
taskid='pentest-task-wpt-kurikulum-internal-20261109'
binding=service.repository.get_current_governance_binding(MID)
authorized=service.authorize_mission_capability(MID,{'idempotency_key':'wpt-kurikulum-internal-task-auth-20261109','capability_id':'web_technology_fingerprinting','resource_type':'URL','resource_value':task['target']['target_value'],'context':{'task_id':upstream,'execution_profile':'wpt.fingerprinting.v1','max_requests':6,'allowed_methods':['GET'],'state_changing_requests':False,'authorization_purpose':'USER_APPROVED_INTERNAL_WPT_RECOVERY','governance_scope_contract_id':binding['governance_scope_contract_id'],'governance_scope_version':binding['governance_scope_version']},'evidence_refs':['operator-approval:codex-chat-20261109-internal-172.21.2.2'],'requested_by':'operator-wpt-recovery','metadata':{'target_io_performed':False}})
(BACKUP/'recovery-task-authorization.json').write_text(json.dumps(authorized,indent=2))
decision=authorized['authorization_binding']['decision_provenance']
assert decision['decision']=='ALLOW'
auth={'policy_decision_id':decision['policy_decision_id'],'policy_decision_hash':decision['policy_decision_hash'],'policy_version':decision['policy_version'],'execution_authorized':True}
source=CtiSubsystemClient().get_pip(oldpip['pip_id'])
now=datetime.now(timezone.utc)
artifact,issued,expiry,confidence,bootstrap=_verify_cti_pip(source,pip_id=oldpip['pip_id'],mission_id=MID,target=task['target'],now=now)
pipcore={'schema_version':__import__('pentest_subsystem.pip_contract',fromlist=['PIP_SCHEMA_VERSION']).PIP_SCHEMA_VERSION,'pip_id':source['pip_id'],'pip_version':str(source['revision']),'mission_id':MID,'source_cti':{'source_type':'CTI','source_system':'VULNDESK_CTI','artifact_id':source['pip_id'],'artifact_version':str(source['revision']),'artifact_sha256':source['canonical_sha256']},'provenance':{'producer':'VULNDESK_CTI','source_refs':[source['pip_id']],'collection_method':'CTI_PIP_VERIFIED_BRIDGE'}}
pipcore.update(pentest_id=pentest,task_id=upstream,scope=deepcopy(scope['scope']),issued_at=_z(issued),expires_at=_z(expiry),confidence=confidence)
# Preserve genuine CTI intelligence and its source hash; only consumer scope/identity and TTL are rebound.
pipcore['intelligence']={'cti_intelligence':deepcopy(artifact['intelligence']),'validation_objectives':deepcopy(artifact.get('validation_objectives') or []),'assumptions_and_gaps':deepcopy(artifact.get('assumptions_and_gaps') or []),'source_integrity_sha256':source['canonical_sha256'],'consumer_eligibility':bootstrap}
pip=seal_pip_artifact(pipcore)
objective=deepcopy(task['objective']);objective.update(scope_snapshot_sha256=scope['integrity']['canonical_sha256'],source_gss_scope_contract_id=binding['governance_scope_contract_id'],source_gss_scope_version=binding['governance_scope_version'],goal='Recover bounded WPT for the explicitly approved internal DNS destination 172.21.2.2')
boundary={'mission_id':MID,'task_id':upstream,'pentest_id':pentest,'scope':deepcopy(scope['scope']),'objective':objective,'constraints':deepcopy(scope['constraints']),'roe':deepcopy(scope['roe']),'authorization_reference':auth}
pb=build_pip_ingestion_binding(boundary_payload=boundary,pip_payload=pip)
core={k:deepcopy(v) for k,v in task.items() if k!='integrity'}
core.update(pentest_task_id=taskid,pentest_id=pentest,upstream_task_id=upstream,scope=deepcopy(scope['scope']),objective=objective,constraints=deepcopy(scope['constraints']),authorization_reference=auth,created_at=_z(now),pip_reference={'pip_id':pip['pip_id'],'pip_version':pip['pip_version'],'pip_artifact_sha256':pip['integrity']['canonical_sha256'],'pip_binding_sha256':pb['integrity']['canonical_sha256']})
newtask=seal_pentest_task_artifact(core)
payload={'boundary':boundary,'pip':pip,'task':newtask}
(BACKUP/'recovery-task-request.json').write_text(json.dumps(payload,indent=2))
result=call('http://127.0.0.1:8790/api/pentest/tasks',payload)
(BACKUP/'recovery-task-result.json').write_text(json.dumps(result,indent=2))
print('Recovery task',result['status'],taskid,flush=True)

