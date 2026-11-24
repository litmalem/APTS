from copy import deepcopy
from pathlib import Path
import pytest
from mission_orchestrator.observability_live_projection import SCHEMA_VERSION, IDENTITY_PREFIX, canonical_live_mission_state_execution_projection_definition, verify_live_mission_state_execution_projection
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService, MissionNotFound
from tests.test_stage3_1_1_identity_envelope import payload

def _svc(tmp_path: Path, key='stage384'):
    db=tmp_path/'mission.db'; svc=CanonicalMissionService(MissionRepository(driver='sqlite',sqlite_path=str(db)))
    mid=svc.create_mission(payload(key))['canonical_identity']['mission_id']; return db,svc,mid

def test_live_projection_is_deterministic_restart_stable_and_read_only(tmp_path):
    db,svc,mid=_svc(tmp_path); before=svc.repository.list_mission_events(mid)
    a=svc.get_live_mission_state_execution_projection(mid); b=CanonicalMissionService(MissionRepository(driver='sqlite',sqlite_path=str(db))).get_live_mission_state_execution_projection(mid)
    assert a==b; assert svc.repository.list_mission_events(mid)==before; assert a['projection']['projection_id'].startswith(IDENTITY_PREFIX)

def test_live_projection_binds_current_mission_and_causal_head(tmp_path):
    _,svc,mid=_svc(tmp_path,'bind'); p=svc.get_live_mission_state_execution_projection(mid)['projection']; events=svc.get_normalized_observability_events(mid)
    assert p['mission']['state']==svc.repository.get_state(mid)['state']; assert p['causal_head']['source_event_id']==events['events'][-1]['source_event_id']; assert p['source_counts']['normalized_event_count']==events['event_count']

def test_empty_execution_is_explicit_not_invented(tmp_path):
    _,svc,mid=_svc(tmp_path,'empty'); p=svc.get_live_mission_state_execution_projection(mid)['projection']
    assert p['execution']['attempt_count']==0; assert p['execution']['active_attempt_count']==0; assert p['execution']['latest_attempt'] is None

def test_projection_integrity_tamper_rejected(tmp_path):
    _,svc,mid=_svc(tmp_path,'tamper'); p=deepcopy(svc.get_live_mission_state_execution_projection(mid)['projection']); p['mission']['state']='TAMPERED'; assert not verify_live_mission_state_execution_projection(p)

def test_contract_no_store_no_migration_no_side_effects():
    d=canonical_live_mission_state_execution_projection_definition(); assert d['schema_version']==SCHEMA_VERSION; assert d['persistence_mode']=='DERIVED_NO_NEW_DURABLE_STORE'; assert d['database_change_mode']=='NO_NEW_DATABASE_MIGRATION'; assert d['runtime_side_effects'] is False

def test_unknown_mission_fails_closed(tmp_path):
    svc=CanonicalMissionService(MissionRepository(driver='sqlite',sqlite_path=str(tmp_path/'x.db')))
    with pytest.raises(MissionNotFound): svc.get_live_mission_state_execution_projection('mis-missing')

def test_health_activates_stage384_without_migration(tmp_path):
    _,svc,_=_svc(tmp_path,'health'); h=svc.health(); assert h['control_version']=='stage3.9.10-global-mission-orchestrator-acceptance-regression-gate'; assert h['mission_repository_migration_level']==53; assert h['live_mission_state_execution_projection_schema_version']==SCHEMA_VERSION; assert h['live_mission_state_execution_projection_read_only'] is True; assert h['live_mission_state_execution_projection_new_durable_store_added'] is False
