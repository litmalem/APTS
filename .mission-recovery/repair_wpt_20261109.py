from pathlib import Path
import sys,json,re,sqlite3,time
from urllib.request import Request,build_opener,ProxyHandler
ROOT=Path('D:/APTS');sys.path.insert(0,str(ROOT/'mission_orchestrator'))
OP=build_opener(ProxyHandler({}))
BASE='http://127.0.0.1:8800'
html=OP.open(BASE+'/',timeout=10).read().decode()
token=re.search(r"window.CONTROL_TOKEN='([^']+)'",html).group(1)
def action(module,verb):
    req=Request(BASE+'/api/action',data=json.dumps({'module':module,'action':verb}).encode(),
        headers={'Content-Type':'application/json','X-Control-Token':token},method='POST')
    with OP.open(req,timeout=30) as response: result=json.load(response)
    print(module,verb,json.dumps(result),flush=True)
    return result
for module in ['mission','stage6_runtime','wpt']: action(module,'stop')
backup=ROOT/'backups'/'wpt-repair-20261109'
backup.mkdir(exist_ok=True)
paths=['mission_orchestrator/data/wpt_governed_intake.db','mission_orchestrator/data/execution_subsystem.db',
       'mission_orchestrator/data/mission_orchestrator.db','mission_orchestrator/data/pentest_subsystem.db',
       'WebTechnologyProfiler/data/profiler.sqlite3']
for name in paths:
    output=backup/Path(name).name
    if output.exists(): raise RuntimeError('Backup already exists; refusing overwrite')
    with sqlite3.connect(ROOT/name) as source,sqlite3.connect(output) as dest: source.backup(dest)
print('Backup',backup,flush=True)
from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
from execution_subsystem.wpt_intake_repository import WPTIntakeRepository
runtime=ExecutionRuntimeRepository(ROOT/'mission_orchestrator/data/execution_subsystem.db')
repo=WPTIntakeRepository(ROOT/'mission_orchestrator/data/wpt_governed_intake.db')
mid='mission-gmo-31538bcf-92cc-46be-8a94-a9179c496f4a'
with sqlite3.connect(repo.sqlite_path) as c:
    ids=[r[0] for r in c.execute('SELECT intake_id FROM wpt_governed_intakes WHERE mission_id=? ORDER BY stored_at',(mid,))]
assert len(ids)==4
proofs=[repo.retire_unused(identity,ids[0],runtime) for identity in ids[1:]]
# WPT is a status projection; the authoritative retirement proofs stay append-only.
import importlib.util
spec=importlib.util.spec_from_file_location('repair_wpt_app',ROOT/'WebTechnologyProfiler/app.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
app.DB_PATH=ROOT/'WebTechnologyProfiler/data/profiler.sqlite3'
with app.connection() as c:
    jobs=c.execute('SELECT * FROM jobs WHERE mission_id=?',(mid,)).fetchall()
    for job in jobs:
        latest=runtime.list_attempts(job['execution_id'])[-1]
        assert latest['state']=='FAILED' and runtime.retryable(latest)
        reason=latest['events'][-1]['data']['reason_code']
        c.execute('UPDATE jobs SET status=?,error=?,runtime_attempt_number=?,runtime_attempt_id=?,superseded_by_intake_id=?,updated_at=? WHERE job_id=?',
            ('FAILED',reason,latest['record']['attempt_number'],latest['attempt_id'],ids[0] if job['intake_id']!=ids[0] else None,app.now(),job['job_id']))
        c.execute('UPDATE governed_intakes SET status=? WHERE intake_id=?',('FAILED',job['intake_id']))
(backup/'retirement-proofs.json').write_text(json.dumps(proofs,indent=2))
print('Retired duplicates',len(proofs),'released request reservations',sum(p['released_requests'] for p in proofs),flush=True)
for module in ['wpt','stage6_runtime']: action(module,'start')
# Wait for fresh runtime initialization before submitting an explicit retry.
for _ in range(40):
    try:
        if json.load(OP.open('http://127.0.0.1:8792/health',timeout=2)): break
    except Exception: time.sleep(.5)
else: raise RuntimeError('Runtime did not become healthy')
request=runtime.get(runtime.list_attempts()[0]['record']['execution_id'])
execution_id=request['envelope']['execution_request']['execution_id']
latest=runtime.list_attempts(execution_id)[-1]
assert latest['invocation']['record']['authorization_record']['evaluation']['execution_request']['parameters']['source_wpt_intake_id']==ids[0]
payload={'schema_version':'apts-execution-runtime-retry-v1',
    'invocation_request_id':'toolreq-wpt-repair-20261109','idempotency_key':'idem-wpt-repair-20261109',
    'execution_id':execution_id,'envelope_sha256':request['envelope']['integrity']['canonical_sha256'],
    'requested_by':'MISSION_AUTONOMOUS_WPT_WORKER','retry_of_attempt_id':latest['attempt_id'],
    'expected_head_sha256':latest['head_sha256']}
req=Request('http://127.0.0.1:8792/api/execution/runtime/retries',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
try:
    with OP.open(req,timeout=25) as response: result=json.load(response)
    print('Explicit retry',result.get('attempt_id'),result.get('state'),flush=True)
finally:
    action('mission','start')
