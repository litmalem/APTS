"""P0 regression: recover from DENIED after an explicitly advanced Governance binding."""
import sqlite3
from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionDelegationAuthorizationConflict
from mission_orchestrator.pentest_handoff import handoff_to_pentest
from mission_orchestrator.delegation_authorization_migration import upgrade_sqlite
from tests.test_mission_pentest_handoff import ready
from tests.test_stage3_1_4_governance_authorization_binding import binding_payload


def rebind(service, mission, key):
    return service.put_mission_governance_binding(mission, binding_payload(key, expected=1))


def test_denied_is_preserved_and_fresh_binding_can_authorize(ready):
    service, gov, mission, inbox, payload = ready
    gov.emergency_stop = True
    old = handoff_to_pentest(service, mission, payload, inbox)
    assert old['status'] == 'blocked'
    denied = old['authorization']
    assert denied['authorization_status'] == 'DENIED'
    calls = gov.evaluate_calls
    assert handoff_to_pentest(service, mission, payload, inbox)['status'] == 'blocked'
    assert gov.evaluate_calls == calls
    gov.emergency_stop = False
    assert handoff_to_pentest(service, mission, payload, inbox)['status'] == 'blocked'
    assert gov.evaluate_calls == calls
    binding = rebind(service, mission, 'retry-binding-2')
    assert binding['binding_version'] == 2
    result = handoff_to_pentest(service, mission, payload, inbox)
    assert result['status'] == 'completed' and result['handoff_received']
    history = service.repository.list_delegation_authorizations(mission)
    assert len(history) == 2
    assert history[0]['authorization_status'] == 'DENIED'
    assert history[0]['canonical_sha256'] == denied['canonical_sha256']
    assert history[1]['authorization_status'] == 'AUTHORIZED'
    assert history[1]['governance_binding_version'] == 2
    assert history[0]['policy_decision_id'] != history[1]['policy_decision_id']
    calls = gov.evaluate_calls
    again = handoff_to_pentest(service, mission, payload, inbox)
    assert again['handoff_id'] == result['handoff_id']
    assert len(inbox.list()) == 1 and gov.evaluate_calls == calls


def test_direct_api_rejects_retry_without_rebinding(ready):
    service, gov, mission, inbox, payload = ready
    gov.emergency_stop = True
    first = handoff_to_pentest(service, mission, payload, inbox)
    from tests.test_stage3_4_5_governance_bound_delegation_authorization import auth_request
    route = service.get_task_route_selection_decision(mission,payload['route_decision_id'])
    plan = service.repository.get_active_plan_version(mission)
    with pytest.raises(MissionDelegationAuthorizationConflict, match='already has an immutable'):
        service.authorize_task_delegation(mission,auth_request(service,mission,plan,route,'same-binding'))
    assert len(service.repository.list_delegation_authorizations(mission)) == 1


def test_original_schema_is_upgraded_without_losing_history(ready):
    service, gov, mission, inbox, payload = ready
    # Force one existing DENIED under a legacy table layout; then migrate it.
    gov.emergency_stop=True
    first=handoff_to_pentest(service,mission,payload,inbox)
    db=Path(service.repository.sqlite_path)
    # The repository migration is idempotent.
    assert upgrade_sqlite(db) is False
    con=sqlite3.connect(db)
    try:
        sql=con.execute("select sql from sqlite_master where name='mission_delegation_authorizations'").fetchone()[0]
        assert 'UNIQUE(mission_id, route_decision_id, governance_binding_version)' in sql
        assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
    finally:con.close()
    assert service.repository.list_delegation_authorizations(mission)[0]['canonical_sha256']==first['authorization']['canonical_sha256']


def test_rebound_but_still_denied_cannot_retry_same_binding(ready):
    service, gov, mission, inbox, payload = ready
    gov.emergency_stop = True
    first = handoff_to_pentest(service, mission, payload, inbox)
    rebind(service, mission, 'retry-binding-denied')
    second = handoff_to_pentest(service, mission, payload, inbox)
    assert second['status'] == 'blocked'
    assert first['authorization']['delegation_authorization_id'] != second['authorization']['delegation_authorization_id']
    calls = gov.evaluate_calls
    assert handoff_to_pentest(service, mission, payload, inbox)['status'] == 'blocked'
    assert gov.evaluate_calls == calls
    assert len(service.repository.list_delegation_authorizations(mission)) == 2
    assert inbox.list() == []


def test_migration_of_legacy_table_preserves_rows_and_allows_one_per_binding(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE mission_delegation_authorizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            delegation_authorization_id TEXT UNIQUE NOT NULL,
            mission_id TEXT NOT NULL, route_decision_id TEXT NOT NULL,
            governance_binding_version INTEGER NOT NULL,
            canonical_sha256 TEXT NOT NULL,
            UNIQUE(mission_id, route_decision_id)
        )''')
        conn.execute('''CREATE INDEX idx_auth_test ON mission_delegation_authorizations(mission_id)''')
        conn.execute("INSERT INTO mission_delegation_authorizations (delegation_authorization_id, mission_id,route_decision_id,governance_binding_version,canonical_sha256) VALUES ('old','mission','route',1,'old-hash')")
    assert upgrade_sqlite(path) is True
    assert upgrade_sqlite(path) is False
    with sqlite3.connect(path) as conn:
        row=conn.execute('SELECT delegation_authorization_id,canonical_sha256 FROM mission_delegation_authorizations').fetchone()
        assert row==('old','old-hash')
        conn.execute("INSERT INTO mission_delegation_authorizations (delegation_authorization_id, mission_id,route_decision_id,governance_binding_version,canonical_sha256) VALUES ('new','mission','route',2,'new-hash')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO mission_delegation_authorizations (delegation_authorization_id, mission_id,route_decision_id,governance_binding_version,canonical_sha256) VALUES ('repeat','mission','route',2,'duplicate')")
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_auth_test'").fetchone() is not None
