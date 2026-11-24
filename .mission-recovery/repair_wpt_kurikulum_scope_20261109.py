"""Explicit operator-approved exact-IP scope revision; no target I/O."""
import json,re,sqlite3,sys
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.request import Request,build_opener,ProxyHandler,HTTPCookieProcessor
ROOT=Path('D:/APTS');sys.path.insert(0,str(ROOT/'mission_orchestrator'))
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.gss_scope_sync import fetch,synchronize
from mission_orchestrator.mission_routing_handoff_automation import _ensure_pentest_governance_binding
MID='mission-gmo-57851fd3-1f64-436f-b713-0b49e839bcc2'
BACKUP=ROOT/'backups/wpt-kurikulum-internal-20261109'
op=build_opener(ProxyHandler({}),HTTPCookieProcessor(CookieJar()))
def call(url,data=None,headers=None):
 req=Request(url,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json',**(headers or {})})
 with op.open(req,timeout=40) as response:return json.load(response)
service=CanonicalMissionService();source=fetch(service,MID)
assert source['version']==1 and source['scope_contract_id']=='scope-e639829d-21af-46b3-a925-22ed29a24d6a'
BACKUP.mkdir(exist_ok=False)
(BACKUP/'source-scope-before.json').write_text(json.dumps(source,indent=2))
html=op.open('http://127.0.0.1:8800/',timeout=10).read().decode()
token=re.search(r"window.CONTROL_TOKEN='([^']+)'",html).group(1)
def action(module,verb):
 x=call('http://127.0.0.1:8800/api/action',{'module':module,'action':verb},{'X-Control-Token':token});print(module,verb,x,flush=True)
action('mission','stop')
# Leave autonomous Mission stopped until the replacement task is fully bound.
for name in ['mission_orchestrator.db','pentest_subsystem.db','wpt_governed_intake.db','execution_subsystem.db']:
 with sqlite3.connect(ROOT/'mission_orchestrator/data'/name) as src,sqlite3.connect(BACKUP/name) as dest:src.backup(dest)
with sqlite3.connect(ROOT/'WebTechnologyProfiler/data/profiler.sqlite3') as src,sqlite3.connect(BACKUP/'profiler.sqlite3') as dest:src.backup(dest)
origin={'Origin':'http://127.0.0.1:8802'}
login=call('http://127.0.0.1:8802/api/login',{'quick_login':True},origin)
try:
 contract={k:source[k] for k in ['mission_id','name','policy_set_id','valid_from','valid_until','created_by','approved_by','metadata']}
 contract['targets']=[{k:t[k] for k in ['target_type','target_value','environment','allowed','notes']} for t in source['targets']]
 contract['targets'].append({'target_type':'IP','target_value':'172.21.2.2','environment':'LAB','allowed':True,'notes':'Exact internal DNS destination explicitly approved by user for kurikulum WPT recovery on 2026-11-09.'})
 contract['sources']=source['sources']
 contract['action_constraints']=[{k:t[k] for k in ['action_class','action_name','effect','max_risk_level','requires_approval','constraints']} for t in source['action_constraints']]
 body={'contract':contract,'previous_id':source['scope_contract_id'],'expected_version':source['version'],'apply_auto_recon_task_delegation_profile':False,'reason':'User explicitly selected internal server 172.21.2.2 and approved this exact IP in scope in Codex chat on 2026-11-09. Preserve existing six-GET read-only WPT action permissions.'}
 (BACKUP/'scope-revision-request.json').write_text(json.dumps(body,indent=2))
 result=call('http://127.0.0.1:8802/api/governance/console/scopes',body,{**origin,'X-CSRF-Token':login['csrf']})
 (BACKUP/'scope-revision-result.json').write_text(json.dumps(result,indent=2))
 print('Revised',result['scope_contract']['scope_contract_id'],result['scope_contract']['version'],flush=True)
finally:call('http://127.0.0.1:8802/api/logout',{}, {**origin,'X-CSRF-Token':login['csrf']})
scope=synchronize(service,MID)
print('Scope projected',scope['contract_version'],flush=True)
print('Binding',_ensure_pentest_governance_binding(service,MID,{}),flush=True)
