from copy import deepcopy
import sqlite3
import pytest
from execution_subsystem.execution_contract import ExecutionRequestConflict, ExecutionSourceRejected
from execution_subsystem.wpt_intake_repository import WPTIntakeRepository, _seal
from execution_subsystem.wpt_intake_source import WPTIntakeAuthoritySource
from execution_subsystem.runtime_repository import ExecutionRuntimeRepository


def record(identity):
    return _seal({'intake':{'intake_id':identity,'idempotency_key':'idem-'+identity,
        'mission_id':'mission-gmo-retire','task_id':'ptask-retire',
        'target':{'target_type':'URL','target_value':'http://localhost:8080/WebGoat'},'profile':'fingerprinting'},
        'authority_snapshot':{'mission_id':'mission-gmo-retire','task_id':'ptask-retire',
            'mission_network_request_budget':12,'limits':{'max_requests':6}}})


class Runtime:
    retryable=staticmethod(ExecutionRuntimeRepository.retryable)
    def __init__(self,path,io=False):
        self.path=path
        request={'parameters':{'source_wpt_intake_id':'wptreq-duplicate'}}
        self.item={'attempt_id':'xattempt-proof','head_sha256':'a'*64,'state':'FAILED',
            'target_io_uncertain':False,'events':[{'data':{'resources_closed':True}}],
            'invocation':{'result':{'semantics':{'target_network_io_performed':io}},
                'record':{'authorization_record':{'evaluation':{'execution_request':request}}}}}
        with self._connect() as c:
            c.execute('CREATE TABLE execution_runtime_attempts(mission_id TEXT)')
            c.execute('INSERT INTO execution_runtime_attempts VALUES (?)',('mission-gmo-retire',))
    def initialize(self): pass
    def _connect(self): return sqlite3.connect(self.path)
    def _runtime_item(self,row,conn): return deepcopy(self.item)


def test_retire_releases_budget_preserves_history_and_blocks_dispatch(tmp_path,monkeypatch):
    repo=WPTIntakeRepository(tmp_path/'wpt.db')
    monkeypatch.setenv('APTS_WPT_INTAKE_DB',str(repo.sqlite_path))
    repo.append(record('wptreq-original')); original=repo.append(record('wptreq-duplicate'))[0]
    with pytest.raises(ExecutionRequestConflict): repo.append(record('wptreq-third'))
    runtime=Runtime(tmp_path/'runtime.db')
    proof=repo.retire_unused('wptreq-duplicate','wptreq-original',runtime)
    assert proof['released_requests']==6
    assert repo.get('wptreq-duplicate')==original
    assert repo.retire_unused('wptreq-duplicate','wptreq-original',runtime)==proof
    assert repo.append(record('wptreq-third'))[1]
    with pytest.raises(ExecutionSourceRejected,match='WPT_INTAKE_RETIRED'):
        WPTIntakeAuthoritySource().resolve(original['record']['intake'])
    with repo._connect() as c:
        with pytest.raises(sqlite3.IntegrityError): c.execute('DELETE FROM wpt_intake_retirements')


def test_retire_refuses_possible_io_and_same_identity(tmp_path):
    repo=WPTIntakeRepository(tmp_path/'wpt.db')
    repo.append(record('wptreq-original'));repo.append(record('wptreq-duplicate'))
    runtime=Runtime(tmp_path/'runtime.db',io=True)
    with pytest.raises(ExecutionRequestConflict,match='without target I/O'):
        repo.retire_unused('wptreq-duplicate','wptreq-original',runtime)
    with pytest.raises(ExecutionRequestConflict,match='same logical measurement'):
        repo.retire_unused('wptreq-original','wptreq-original',runtime)


def test_retire_unadmitted_releases_only_verified_denials(tmp_path):
    repo = WPTIntakeRepository(tmp_path/'wpt.db')
    repo.append(record('wptreq-duplicate'))
    replacement = {**record('wptreq-replacement')['intake'],
                   'schema_version': 'apts-wpt-governed-intake-v1'}
    class DeniedRuntime:
        def initialize(self): pass
        def _connect(self):
            c = sqlite3.connect(tmp_path/'denied.db'); c.row_factory = sqlite3.Row
            return c
        def _item(self, row, conn): return deepcopy(self.item)
    runtime = DeniedRuntime()
    runtime.item = {'result': None, 'record': {
        'status': 'BLOCKED', 'invocation_id': 'toolinv-denied', 'execution_id': 'exec-denied',
        'integrity': {'canonical_sha256': 'a'*64},
        'authorization_record': {'decision': 'DENY', 'evaluation': {'execution_request': {
            'parameters': {'source_wpt_intake_id': 'wptreq-duplicate'}}}}}}
    with runtime._connect() as c:
        c.execute('CREATE TABLE execution_adapter_invocations(mission_id TEXT)')
        c.execute('INSERT INTO execution_adapter_invocations VALUES (?)', ('mission-gmo-retire',))
        c.execute('CREATE TABLE execution_runtime_attempts(execution_id TEXT)')
        c.execute('INSERT INTO execution_runtime_attempts VALUES (?)', ('exec-denied',))
    with pytest.raises(ExecutionRequestConflict, match='without reservation or runtime'):
        repo.retire_unadmitted('wptreq-duplicate', replacement, runtime)
    with runtime._connect() as c:
        c.execute('DELETE FROM execution_runtime_attempts')
    runtime.item['record']['status'] = 'RESERVED'
    with pytest.raises(ExecutionRequestConflict, match='without reservation or runtime'):
        repo.retire_unadmitted('wptreq-duplicate', replacement, runtime)
    runtime.item['record']['status'] = 'BLOCKED'
    proof = repo.retire_unadmitted('wptreq-duplicate', replacement, runtime)
    assert proof['released_requests'] == 6
    assert proof['target_network_io_performed'] is False
    assert repo.retire_unadmitted('wptreq-duplicate', replacement, runtime) == proof
    assert repo.get('wptreq-duplicate') is not None
