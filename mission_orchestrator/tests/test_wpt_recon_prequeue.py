import json
import sqlite3

from mission_orchestrator.canonical import sha256_hex
from mission_orchestrator.mission_wpt_preparation import prequeue_recon_targets


class PentestStore:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as conn:
            conn.execute('''CREATE TABLE pentest_recon_scope_targets(
                target_key TEXT, mission_id TEXT, record_json TEXT, record_sha256 TEXT)''')

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _migration(self, _conn):
        return 16


class PlanningMission:
    mission_id = 'mission-gmo-prequeue-test'
    target = {'target_type': 'URL', 'target_value': 'http://localhost:3000/',
              'environment': 'LAB'}
    authoritative = {'scope_snapshot': 'current'}
    source_sha = sha256_hex(authoritative)
    contract = {
        'metadata': {'gss_scope_sync': {
            'source_snapshot_sha256': source_sha,
            'source_scope_contract_id': 'scope-test', 'source_version': 2,
            'source_contract_hash': 'a' * 64}},
        'scope': {'targets': [target]},
    }

    def get_mission_state(self, _mission_id):
        return {'mission_state': {'state': 'PLANNING'}}

    def get_mission_scope_contract(self, _mission_id):
        return {'contract': self.contract}

    def list_planned_tasks(self, _mission_id):
        return {'planned_tasks': [{
            'planned_task_id': 'ptask-prequeue-test',
            'task_key': 't1-pentest-orchestration',
            'required_subsystem': 'PENTEST',
            'required_capability': 'pentest.recon',
        }]}


def test_planning_mission_prequeues_exact_recon_url_without_task_or_target_io(
        tmp_path, monkeypatch):
    from mission_orchestrator import gss_scope_sync, mission_wpt_inbox_delivery

    service = PlanningMission()
    pentest = PentestStore(tmp_path / 'pentest.db')
    record = {
        'schema_version': 'apts-recon-mission-scope-target-v1',
        'mission_id': service.mission_id,
        'scope_contract_id': 'scope-test', 'scope_version': 2,
        'scope_contract_hash': 'a' * 64,
        'source_snapshot_sha256': service.source_sha,
        'target_key': 'reconscope-prequeue-test', 'target': service.target,
        'status': 'READY_FOR_COLLECTION',
        'semantics': {'target_is_observed': False, 'execution_authorized': False,
                      'recon_run_created': False, 'external_network_io_performed': False},
    }
    record_sha = sha256_hex({'hash_domain': 'APTS_RECON_MISSION_SCOPE_TARGET_V1',
                             'record': record})
    with sqlite3.connect(pentest.path) as conn:
        conn.execute('INSERT INTO pentest_recon_scope_targets VALUES (?,?,?,?)',
                     (record['target_key'], service.mission_id,
                      json.dumps(record, sort_keys=True, separators=(',', ':')), record_sha))

    calls = []
    monkeypatch.setattr(gss_scope_sync, 'fetch', lambda *_: service.authoritative)
    monkeypatch.setattr(mission_wpt_inbox_delivery, 'deliver',
                        lambda body: calls.append(dict(body)) or {
                            'status': 'DELIVERED', 'created': True,
                            'intake_id': body['intake_id']})

    result = prequeue_recon_targets(service, service.mission_id, pentest=pentest)

    assert len(result) == len(calls) == 1
    request = calls[0]
    assert request['schema_version'] == 'apts-wpt-recon-prequeue-v1'
    assert request['task_id'] == 'ptask-prequeue-test'
    assert request['target'] == {'target_type': 'URL',
                                 'target_value': 'http://localhost:3000/'}
    assert request['recon_target_key'] == 'reconscope-prequeue-test'
    assert request['target_is_observed'] is False
    assert request['task_materialized'] is False
    assert request['waiting_reason_code'] == 'GSS_TARGET_RECON_ALLOW_REQUIRED'
    assert result[0]['execution_authorized'] is False
    assert result[0]['target_io_performed'] is False


def test_prequeue_fails_closed_when_gss_scope_hash_changed(tmp_path, monkeypatch):
    from mission_orchestrator import gss_scope_sync, mission_wpt_inbox_delivery

    service = PlanningMission()
    pentest = PentestStore(tmp_path / 'pentest.db')
    calls = []
    monkeypatch.setattr(gss_scope_sync, 'fetch', lambda *_: {'scope_snapshot': 'changed'})
    monkeypatch.setattr(mission_wpt_inbox_delivery, 'deliver',
                        lambda body: calls.append(body))

    result = prequeue_recon_targets(service, service.mission_id, pentest=pentest)
    assert result == [{'status': 'deferred', 'reason': 'GSS_SCOPE_CHANGED'}]
    assert calls == []


def test_mixed_scope_prequeues_only_url_and_rejects_undeclared_ip(tmp_path, monkeypatch):
    from copy import deepcopy
    from mission_orchestrator import gss_scope_sync, mission_wpt_inbox_delivery
    service = PlanningMission()
    service.contract = deepcopy(service.contract)
    internal = {'target_type': 'IP', 'target_value': '172.21.2.2', 'environment': 'LAB'}
    service.contract['scope']['targets'].append(internal)
    pentest = PentestStore(tmp_path / 'mixed.db')
    for i, target in enumerate([service.target, internal]):
        record = {'schema_version': 'apts-recon-mission-scope-target-v1',
            'mission_id': service.mission_id, 'scope_contract_id': 'scope-test',
            'scope_version': 2, 'scope_contract_hash': 'a' * 64,
            'source_snapshot_sha256': service.source_sha,
            'target_key': 'reconscope-mixed-' + str(i), 'target': target,
            'status': 'READY_FOR_COLLECTION',
            'semantics': {'target_is_observed': False, 'execution_authorized': False,
                'recon_run_created': False, 'external_network_io_performed': False}}
        digest = sha256_hex({'hash_domain': 'APTS_RECON_MISSION_SCOPE_TARGET_V1', 'record': record})
        with sqlite3.connect(pentest.path) as conn:
            conn.execute('INSERT INTO pentest_recon_scope_targets VALUES (?,?,?,?)',
                (record['target_key'], service.mission_id, json.dumps(record), digest))
    calls = []
    monkeypatch.setattr(gss_scope_sync, 'fetch', lambda *_: service.authoritative)
    monkeypatch.setattr(mission_wpt_inbox_delivery, 'deliver', lambda body:
        calls.append(body) or {'status': 'DELIVERED', 'created': True, 'intake_id': body['intake_id']})
    result = prequeue_recon_targets(service, service.mission_id, pentest=pentest)
    assert len(result) == len(calls) == 1
    assert calls[0]['target']['target_type'] == 'URL'
    service.contract['scope']['targets'].remove(internal)
    calls.clear()
    result = prequeue_recon_targets(service, service.mission_id, pentest=pentest)
    assert result == [{'status': 'deferred', 'reason': 'RECON_SCOPE_TARGET_INTEGRITY_OR_SCOPE_MISMATCH'}]
    assert calls == []
