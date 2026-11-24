exec((__import__('pathlib').Path('D:/APTS/.mission-recovery/repair_wpt_kurikulum_scope_20261109b.py').read_text().split('service=CanonicalMissionService();source=fetch(service,MID)')[0]))
from mission_orchestrator.mission_routing_handoff_automation import _start_local_orchestration
old='pentest-task-747de339d002f7189e7766d893590870'
state=call('http://127.0.0.1:8790/api/pentest/tasks/'+old+'/lifecycle')['lifecycle']
print('Old state',state,flush=True)
if state['state']!='ABORTED':
 result=call('http://127.0.0.1:8790/api/pentest/tasks/'+old+'/lifecycle/transitions',{'transition_id':'ptrans-wpt-kurikulum-scope-superseded-20261109b','idempotency_key':'idem-wpt-kurikulum-scope-superseded-20261109b','expected_state_version':state['state_version'],'to_state':'ABORTED','actor':'operator-wpt-recovery','reason_code':'SCOPE_SUPERSEDED','reason':'Operator-approved exact internal IP scope requires a new immutable task. Old attempt proved no target I/O; preserve original task history.','evidence_refs':['operator-approval:codex-chat-20261109-internal-172.21.2.2'],'metadata':{'replacement_task_id':'pentest-task-wpt-kurikulum-internal-20261109b'}})
 print('Old task',result['status'],flush=True)
new=call('http://127.0.0.1:8790/api/pentest/tasks/pentest-task-wpt-kurikulum-internal-20261109b')
print('Orchestration',_start_local_orchestration(MID,'ptask-wpt-kurikulum-internal-20261109b','operator-approved-scope-recovery-20261109',new),flush=True)
html=op.open('http://127.0.0.1:8800/',timeout=10).read().decode();token=re.search(r"window.CONTROL_TOKEN='([^']+)'",html).group(1)
print('Mission start',call('http://127.0.0.1:8800/api/action',{'module':'mission','action':'start'},{'X-Control-Token':token}),flush=True)
