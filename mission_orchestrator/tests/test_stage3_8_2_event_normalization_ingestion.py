from pathlib import Path

import pytest

from mission_orchestrator.observability_ingestion import normalize_events
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_1_1_identity_envelope import payload


def test_verified_ledger_projection_is_stable_and_read_only(tmp_path: Path):
    db = tmp_path / 'mission.db'
    svc = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(db)))
    mission_id = svc.create_mission(payload('stage382-projection'))['canonical_identity']['mission_id']
    before = svc.repository.list_mission_events(mission_id)
    first = svc.get_normalized_observability_events(mission_id)
    second = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(db))).get_normalized_observability_events(mission_id)
    assert first == second
    assert first['event_count'] == len(before)
    assert svc.repository.list_mission_events(mission_id) == before
    assert {e['trace_id'] for e in first['events']} == {first['trace_id']}
    assert all(e['integrity']['canonical_sha256'] for e in first['events'])


def test_cross_mission_and_duplicate_source_events_fail_closed():
    event = {'mission_id': 'm1', 'event_id': 'e1'}
    with pytest.raises(ValueError, match='cross-mission'):
        normalize_events([event], 'm2', 'a' * 32)
    with pytest.raises(ValueError, match='duplicate'):
        normalize_events([event, event], 'm1', 'a' * 32)
