"""Run the existing real-database acceptance cases against isolated SQLite files."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest
from app.db import Db
from app.repositories import GovernanceRepository
from app.audit_service import AuditService
import test_human_approval_mariadb as approval_tests
import test_web_console_mariadb as console_tests

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def database(tmp_path):
    path=tmp_path/'governance.sqlite3'
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript((ROOT/'sql/03_governance_sqlite_schema.sql').read_text(encoding='utf-8'))
        conn.executescript((ROOT/'sql/04_seed_default_policies_sqlite.sql').read_text(encoding='utf-8'))
        conn.execute('PRAGMA journal_mode=WAL').fetchall()
    return GovernanceRepository(Db({'driver':'sqlite','path':str(path)}))

api=approval_tests.api
console_db=console_tests.console_db
# Reuse authoritative behavior tests, including parallel approval and atomic rollback.
for module in (approval_tests,console_tests):
    for name in dir(module):
        if name.startswith('test_real_'): globals()[name]=getattr(module,name)


def test_nested_transaction_rolls_back(database):
    with pytest.raises(RuntimeError):
        with database.db.connect():
            database.db.execute("UPDATE gov_policy_sets SET description=%(text)s WHERE policy_set_id=%(id)s",{'text':'changed','id':'default-policy'})
            with database.db.connect(): raise RuntimeError('rollback')
    assert database.get_policy_set('default-policy')['description']!='changed'


def test_foreign_keys_and_enum_constraints(database):
    with pytest.raises(sqlite3.IntegrityError):
        database.db.execute("INSERT INTO gov_scope_targets(scope_target_id,scope_contract_id,target_type,target_value,environment,allowed) VALUES (%(id)s,%(scope)s,'IP','127.0.0.1','LAB',1)",{'id':'target-orphan','scope':'scope-missing'})
    with pytest.raises(sqlite3.IntegrityError):
        database.db.execute("UPDATE gov_policy_sets SET status='INVALID'")


def test_datetime_decimal_and_safe_parameter_binding(database):
    values={'date':datetime(2026,11,6,12,30,tzinfo=timezone.utc),'score':Decimal('12.30'),'text':"value'); DROP TABLE gov_policy_sets; --"}
    with database.db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute('CREATE TABLE driver_test (at DATETIME,score DECIMAL_TEXT,value TEXT)')
            cur.execute('INSERT INTO driver_test VALUES (%(date)s,%(score)s,%(text)s)',values)
            cur.execute('SELECT * FROM driver_test');row=cur.fetchone()
    assert row['at']==values['date'].replace(tzinfo=None)
    assert row['score']==values['score'] and str(row['score'])=='12.30'
    assert row['value']==values['text'] and database.db.ping()


def test_concurrent_audit_writes_have_one_chain(database):
    from app.utils import sha256_json
    import json
    audit=AuditService(database)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n:audit.record('SQLITE_TEST',actor_id='test',payload={'n':n}),range(12)))
    rows=database.db.fetch_all('SELECT * FROM gov_audit_log ORDER BY id')
    prior=None
    for row in rows:
        assert row['previous_hash']==prior
        body={k:row[k] for k in ('audit_id','event_type','actor_id','mission_id','subject_type','subject_id','previous_hash')}
        body['payload']=json.loads(row['payload_json']);assert sha256_json(body)==row['record_hash']
        prior=row['record_hash']


def test_outbox_retry_backoff_uses_incremented_attempt_count(database):
    database.insert_outbox({'event_id':'event-test','mission_id':None,'event_type':'TEST','source_component':'GOV-PLANE','severity':'INFO','payload_json':'{}'})
    for attempt in range(1,5):
        before=datetime.now(timezone.utc).replace(tzinfo=None,microsecond=0)
        database.mark_outbox_failed('event-test','Synthetic')
        row=database.db.fetch_one("SELECT * FROM gov_event_outbox WHERE event_id='event-test'")
        assert row['attempt_count']==attempt
        assert abs((row['next_attempt_at']-before).total_seconds()-2**attempt)<=1


def test_missing_sqlite_file_fails_closed(tmp_path):
    db=Db({'driver':'sqlite','path':str(tmp_path/'missing.sqlite3')})
    with pytest.raises(sqlite3.OperationalError): db.ping()
    assert not (tmp_path/'missing.sqlite3').exists()


def test_control_center_sqlite_backup_and_selected_reset(database,tmp_path):
    import importlib.util
    script=ROOT.parent/'APTS_Control_Center/reset_apts.py'
    spec=importlib.util.spec_from_file_location('sqlite_reset_helper',script)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    audit=AuditService(database);audit.record('RESET_TEST',actor_id='test')
    path=Path(database.db.config['path'])
    with closing(sqlite3.connect(path)) as connection:
        helper.backup_governance(connection,'sqlite',tmp_path)
        helper.reset_governance(connection,'sqlite',helper.GOV)
        assert connection.execute('SELECT COUNT(*) FROM gov_audit_log').fetchone()[0]==0
        assert connection.execute('SELECT COUNT(*) FROM gov_policy_sets').fetchone()[0]==1
        assert connection.execute('SELECT COUNT(*) FROM gov_policy_rules').fetchone()[0]==6
        assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    with closing(sqlite3.connect(tmp_path/'governance-before.sqlite3')) as backup:
        assert backup.execute('SELECT COUNT(*) FROM gov_audit_log').fetchone()[0]==1


def test_real_query_dialect_in_migrated_copy(tmp_path):
    from app import main
    from fastapi.testclient import TestClient
    from app.governance_service import GovernanceService
    from app.approval_auth import ApprovalPrincipal,require_human_approver
    source=ROOT/'.runtime/sqlite-migration-20261106/staging3.sqlite3'
    if not source.exists():pytest.skip('Optional migration staging copy is not present')
    path=tmp_path/'migrated.sqlite3'
    with closing(sqlite3.connect(source)) as original,closing(sqlite3.connect(path)) as copied:original.backup(copied)
    service=GovernanceService(GovernanceRepository(Db({'driver':'sqlite','path':str(path)})))
    prior=main.service
    main.service=service
    main.app.dependency_overrides[require_human_approver]=lambda:ApprovalPrincipal('test-admin',frozenset({'GOVERNANCE_ADMIN','SECURITY_APPROVER'}),'HUMAN')
    try:
        client=TestClient(main.app)
        for path in ('console/overview','console/records/approvals','console/records/scopes','console/records/decisions','console/records/policies','console/records/audit','console/records/emergency-history','console/policy/default-policy'):
            response=client.get('/api/governance/'+path)
            assert response.status_code==200,(path,response.text)
    finally:
        main.service=prior;main.app.dependency_overrides.pop(require_human_approver,None)


def test_sqlite_backend_does_not_open_mysql(database,monkeypatch):
    from app import db as driver
    def forbidden(*args,**kwargs):raise AssertionError('SQLite must not connect to MySQL')
    monkeypatch.setattr(driver.pymysql,'connect',forbidden)
    assert database.db.ping()
    assert database.get_policy_set('default-policy')['status']=='ACTIVE'
