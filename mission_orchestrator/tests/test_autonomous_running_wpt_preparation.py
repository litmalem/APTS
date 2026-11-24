"""Acceptance checks: no bypass of Scope Contract or Stage 6."""
from copy import deepcopy
import hashlib
import json
import sqlite3

from mission_orchestrator.mission_running_automation import activate
from mission_orchestrator.mission_wpt_preparation import propose
from mission_orchestrator.canonical import sha256_hex
from test_gss_scope_sync import gss_ready  # noqa: F401, fixture from existing acceptance suite
from test_two_phase_pip_initialization import ready  # noqa: F401, upstream fixture
from mission_orchestrator.automatic_pip import sweep as auto_pip_sweep


def test_default_running_uses_real_guarded_lifecycle(gss_ready, monkeypatch):
    service, mid, _, _ = gss_ready
    monkeypatch.delenv('APTS_AUTONOMOUS_RUNNING', raising=False)
    monkeypatch.setenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', '0')
    auto_pip_sweep(service)
    assert service.get_mission_state(mid)['mission_state']['state'] == 'RUNNING'
    result = activate(service, mid)
    assert result['status'] == 'unchanged'
    assert result['state'] == 'RUNNING'
    assert result['execution_authorized'] is False
    assert result['target_io_performed'] is False
    assert activate(service, mid)['status'] == 'unchanged'


def test_running_rechecks_changed_gss_source(gss_ready, monkeypatch):
    service, mid, gss, _ = gss_ready
    monkeypatch.setenv('APTS_AUTONOMOUS_RUNNING', '0')
    monkeypatch.setenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', '0')
    auto_pip_sweep(service)
    # Revoked scope must not promote PLANNING to RUNNING.
    gss.scope['status'] = 'REVOKED'
    try:
        activate(service, mid)
    except Exception:
        pass
    assert service.get_mission_state(mid)['mission_state']['state'] == 'PLANNING'


def test_running_activation_can_be_explicitly_paused(gss_ready, monkeypatch):
    service, mid, _, _ = gss_ready
    monkeypatch.setenv('APTS_AUTONOMOUS_RUNNING', '0')
    auto_pip_sweep(service)
    assert service.get_mission_state(mid)['mission_state']['state'] == 'PLANNING'


def test_wpt_no_intake_when_not_running(gss_ready):
    service, mid, _, _ = gss_ready
    assert propose(service, mid) == [{'status':'deferred','reason':'MISSION_NOT_RUNNING'}]


class FakePentest:
    def __init__(self, tmp_path):
        self.path = str(tmp_path / 'tasks.db')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE pentest_tasks(mission_id TEXT, upstream_task_id TEXT)')
            db.execute('''CREATE TABLE pentest_recon_scope_targets(
                target_key TEXT, mission_id TEXT, record_json TEXT, record_sha256 TEXT)''')
    def _connect(self):
        result = sqlite3.connect(self.path)
        result.row_factory = sqlite3.Row
        return result
    def _migration(self, conn):
        return 16


class FakeWPT:
    def __init__(self):
        self.calls = []
    def submit(self, body):
        self.calls.append(deepcopy(body))
        return {'created':len(self.calls)==1,'record':{
            'status':'ACCEPTED_PENDING_STAGE6',
            'authority_snapshot':{'execution_status':'REGISTERED_NOT_EXECUTABLE'}}}


def test_running_prepares_exact_scoped_wpt_intake_without_target_io(gss_ready, tmp_path, monkeypatch):
    service, mid, _, _ = gss_ready
    monkeypatch.setenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', '0')
    auto_pip_sweep(service)
    activate(service, mid)
    pentest = FakePentest(tmp_path)
    with sqlite3.connect(pentest.path) as db:
        db.execute('INSERT INTO pentest_tasks VALUES (?,?)',(mid,'ptask-test'))
        scope = service.get_mission_scope_contract(mid)['contract']
        source = scope['metadata']['gss_scope_sync']
        target = next(item for item in scope['scope']['targets'] if item['target_type']=='URL')
        record = {
            'schema_version':'apts-recon-mission-scope-target-v1', 'mission_id':mid,
            'scope_contract_id':source['source_scope_contract_id'],
            'scope_version':source['source_version'], 'scope_contract_hash':source['source_contract_hash'],
            'source_snapshot_sha256':source['source_snapshot_sha256'],
            'target_key':'reconscope-test-target',
            'target':{'target_type':target['target_type'],'target_value':target['target_value'],
                      'environment':target['environment']},
            'status':'READY_FOR_COLLECTION',
            'semantics':{'target_is_observed':False,'execution_authorized':False,
                         'recon_run_created':False,'external_network_io_performed':False},
        }
        encoded=json.dumps(record,sort_keys=True,separators=(',',':'))
        record_sha=sha256_hex({'hash_domain':'APTS_RECON_MISSION_SCOPE_TARGET_V1','record':record})
        db.execute('INSERT INTO pentest_recon_scope_targets VALUES (?,?,?,?)',
                   (record['target_key'],mid,encoded,record_sha))
    wpt = FakeWPT()
    result = propose(service, mid, pentest=pentest, wpt=wpt)
    assert len(result) == 1
    assert result[0]['status'] == 'ACCEPTED_PENDING_STAGE6'
    assert result[0]['execution_authorized'] is False
    assert result[0]['target_io_performed'] is False
    assert wpt.calls[0]['target'] == {'target_type':'URL','target_value':'http://localhost:3000/'}
    assert wpt.calls[0]['schema_version'] == 'apts-wpt-governed-intake-v2'
    assert wpt.calls[0]['recon_target_key'] == 'reconscope-test-target'
    assert wpt.calls[0]['target_is_observed'] is False
    assert wpt.calls[0]['profile'] == 'fingerprinting'
    assert wpt.calls[0]['mission_id'] == mid


def test_running_waits_for_materialized_orchestration_task(monkeypatch):
    from mission_orchestrator import gss_scope_sync, mission_running_automation as running
    from mission_orchestrator.canonical import sha256_hex

    authoritative = {'scope': 'authoritative-test-snapshot'}
    scope_sha = sha256_hex(authoritative)
    class Service:
        def get_mission_state(self, _mid):
            return {'mission_state': {'state': 'PLANNING', 'state_version': 2}}
        def get_plan_validation(self, _mid):
            return {'validation_status': 'VALIDATED_FEASIBLE', 'feasible': True}
        def get_generated_plan(self, _mid):
            return {'generated_plan_id': 'mplan-test', 'canonical_sha256': 'a' * 64}
        def get_mission_scope_contract(self, _mid):
            return {'contract': {'metadata': {'gss_scope_sync': {
                'source_snapshot_sha256': scope_sha}}}}

    monkeypatch.delenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', raising=False)
    monkeypatch.setattr(gss_scope_sync, 'fetch', lambda _service, _mid: authoritative)
    monkeypatch.setattr(running, '_missing_pentest_orchestration_task_ids',
                        lambda _service, _mid: ['ptask-orchestration-pending'])
    result = running.activate(Service(), 'mission-gmo-test')
    assert result['status'] == 'deferred'
    assert result['reason'] == 'PENTEST_ORCHESTRATION_NOT_MATERIALIZED'
    assert result['pending_planned_task_ids'] == ['ptask-orchestration-pending']
    assert result['execution_authorized'] is False
    assert result['target_io_performed'] is False



def test_orchestration_readiness_uses_exact_planned_task_id(monkeypatch):
    import sqlite3
    import execution_subsystem.proposal_source as source_module
    from mission_orchestrator.mission_running_automation import _missing_pentest_orchestration_task_ids

    class FakeProposalSource:
        def _connect(self):
            conn = sqlite3.connect(':memory:')
            conn.row_factory = sqlite3.Row
            conn.execute('CREATE TABLE pentest_tasks(mission_id TEXT, upstream_task_id TEXT, pentest_task_id TEXT)')
            conn.execute('INSERT INTO pentest_tasks VALUES (?,?,?)',
                         ('mission-gmo-check', 'ptask-orchestration-present', 'pentest-task-present'))
            conn.execute('CREATE TABLE pentest_agentic_orchestrations(mission_id TEXT, upstream_task_id TEXT, pentest_task_id TEXT, orchestration_status TEXT)')
            conn.execute('INSERT INTO pentest_agentic_orchestrations VALUES (?,?,?,?)',
                         ('mission-gmo-check', 'ptask-orchestration-present', 'pentest-task-present', 'ACTIVE'))
            return conn
        def _migration(self, _conn):
            return 16

    monkeypatch.setattr(source_module, 'PentestProposalSource', FakeProposalSource)
    class Service:
        def list_planned_tasks(self, _mission_id):
            return {'planned_tasks': [
                {'planned_task_id':'ptask-orchestration-present','task_key':'t1-pentest-orchestration',
                 'required_subsystem':'PENTEST'},
                {'planned_task_id':'ptask-recon','task_key':'t1-recon','required_subsystem':'PENTEST'},
            ]}

    service = Service()
    assert _missing_pentest_orchestration_task_ids(service, 'mission-gmo-check') == []
    service.list_planned_tasks = lambda _mid: {'planned_tasks': [
        {'planned_task_id':'ptask-orchestration-pending','task_key':'t1-pentest-orchestration',
         'required_subsystem':'PENTEST'},
    ]}
    assert _missing_pentest_orchestration_task_ids(service, 'mission-gmo-check') == [
        'ptask-orchestration-pending']
