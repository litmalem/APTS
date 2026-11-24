"""First verified WPT observation, durable replay and receipt binding."""
from copy import deepcopy
import pytest
from execution_subsystem.wpt_intake_repository import WPTIntakeRepository, _seal_handoff
from execution_subsystem.wpt_intake_service import WPTIntakeService
from pentest_subsystem.reconnaissance import ReconnaissanceAgentService, ReconnaissanceAgentIntegrityError
from tests.test_stage5_2_reconnaissance_agent import _start_repo
from tests.test_wpt_to_recon_cross_module_acceptance import AuthorizedTaskSnapshot, SealedStage6Ledger


def test_first_observation_replay_and_tamper_rejection(tmp_path):
    repo, boundary, task, orch, *_ = _start_repo(tmp_path, 'wpt-first')
    class Authority(AuthorizedTaskSnapshot):
        def resolve(self, intake):
            snapshot = super().resolve(intake)
            snapshot['task_binding_sha256'] = repo.get_task(task['pentest_task_id'])['task_binding_sha256']
            snapshot['current_boundary'] = deepcopy(boundary)
            return snapshot
    source = WPTIntakeRepository(tmp_path / 'intake.db')
    receiver = ReconnaissanceAgentService(repo)
    deliveries = []
    def receive(event):
        ack = receiver.run_wpt_initial_observation(event, source_repository=source)
        deliveries.append(ack)
        if len(deliveries) == 1:
            raise ConnectionError('lost acknowledgement after commit')
        return ack
    service = WPTIntakeService(source, Authority(task, orch), SealedStage6Ledger(task), recon_handoff_provider=receive)
    intake = {'schema_version':'apts-wpt-governed-intake-v1', 'intake_id':'wptreq-first',
              'idempotency_key':'idem-wpt-first', 'mission_id':task['mission_id'],
              'task_id':task['upstream_task_id'], 'target':deepcopy(task['target']), 'profile':'fingerprinting'}
    service.submit(intake)
    service.submit_stage6_result({'intake_id':'wptreq-first', 'schema_version':'apts-wpt-stage6-result-reference-v1',
        'execution_id':'exec-first', 'attempt_id':'xattempt-first'})
    request = {'schema_version':'apts-wpt-recon-initial-request-v1'}
    first = service.handoff_to_recon('wptreq-first', request)
    assert first['delivery_status'] == 'PENDING'
    second = service.handoff_to_recon('wptreq-first', request)
    assert second['delivery_status'] == 'DELIVERED'
    assert deliveries[1]['replayed'] is True
    runs = receiver.list_recon_runs(mission_id=task['mission_id'])
    assert len(runs) == 1
    assert runs[0]['parent_recon_run_id'] is None
    assert runs[0]['source_action_id'] is None
    assert runs[0]['request']['observations'][0]['source']['source_kind'] == 'WPT_STAGE6_RESULT'
    assert service.handoff_to_recon('wptreq-first', request)['acknowledgement'] == second['acknowledgement']
    bad = deepcopy(second['record'])
    bad['mission_id'] = 'mission-gmo-other'
    bad = _seal_handoff({k:v for k,v in bad.items() if k != 'integrity'})
    with pytest.raises(ReconnaissanceAgentIntegrityError):
        receiver.run_wpt_initial_observation(bad, source_repository=source)


def test_governed_wpt_receipt_binding_and_replay(tmp_path, monkeypatch):
    import importlib.util
    import json
    from pathlib import Path
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from execution_subsystem import wpt_job_callback as callback
    path = Path(__file__).resolve().parents[2] / 'WebTechnologyProfiler' / 'app.py'
    spec = importlib.util.spec_from_file_location('wpt_receipt_test', path)
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    app.DB_PATH = tmp_path / 'wpt.db'
    app.CLIENT_TOKEN = 'receipt-test-' + 'x' * 40
    with app.connection() as db:
        db.execute("INSERT INTO jobs(job_id,created_at,updated_at,mission_id,task_id,target,requested_by,mode,status,intake_id,execution_id,result_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (callback.job_id_for_intake('wptreq-receipt'),'now','now','mission-gmo-receipt','ptask-receipt',
             'http://localhost','test','fingerprinting','COMPLETED','wptreq-receipt','exec-receipt',
             json.dumps({'evidence':{'manifest_sha256':'a'*64}})))
    server = ThreadingHTTPServer(('127.0.0.1',0), app.Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('APTS_WPT_INBOX_URL', 'http://127.0.0.1:' + str(server.server_port))
    monkeypatch.setenv('APTS_WPT_INBOX_TOKEN', app.CLIENT_TOKEN)
    intake = {'intake_id':'wptreq-receipt','mission_id':'mission-gmo-receipt','task_id':'ptask-receipt'}
    result = {'execution_id':'exec-receipt','integrity':{'canonical_sha256':'b'*64},'evidence':{'manifest_sha256':'a'*64}}
    handoff = {'delivery_status':'DELIVERED','acknowledgement':{'accepted':True,'intake_id':'wptreq-receipt',
        'source_result_sha256':'b'*64,'recon_run_id':'reconrun-receipt'}}
    try:
        for _ in range(2):
            assert callback.publish_recon_receipt(intake,result,handoff)['status'] == 'DELIVERED'
        bad = deepcopy(result)
        bad['execution_id'] = 'exec-wrong'
        with pytest.raises(RuntimeError):
            callback.publish_recon_receipt(intake,bad,handoff)
        with app.connection() as db:
            row = db.execute('SELECT * FROM jobs').fetchone()
        assert row['recon_status'] == 'DELIVERED'
        assert row['recon_delivery_id'] == 'reconrun-receipt'
        assert row['enum_status'] == 'NOT_SENT'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_iteration_schema_repair_preserves_newer_metadata(tmp_path):
    import sqlite3
    from pathlib import Path
    repo, *_ = _start_repo(tmp_path, 'wpt-schema-repair')
    with sqlite3.connect(repo.sqlite_path) as db:
        db.execute('DROP TABLE pentest_recon_runs')
        db.executescript((Path(__file__).resolve().parents[1] / 'pentest_migrations/009_stage5_2_reconnaissance_agent.sql').read_text())
        db.execute('UPDATE pentest_repository_meta SET migration_level=16')
    repo._ensure_iteration_store()
    repo._ensure_iteration_store()
    with sqlite3.connect(repo.sqlite_path) as db:
        columns = {r[1] for r in db.execute('PRAGMA table_info(pentest_recon_runs)')}
        assert 'iteration_index' in columns
        assert db.execute('SELECT migration_level FROM pentest_repository_meta').fetchone()[0] == 16


def test_task_target_metadata_is_not_an_observation_field():
    from pentest_subsystem.reconnaissance import derive_recon_observation_needs
    target = {'target_type':'URL','target_value':'http://localhost/','environment':'LAB','metadata':{}}
    task = {'target':target,'scope':{'targets':[target],'excluded_targets':[]}}
    assert derive_recon_observation_needs(observations=[], task=task, as_of='2026-11-07T00:00:00Z')
