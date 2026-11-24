from copy import deepcopy

import pytest

from mission_orchestrator.observability_decision_trace import (
    build_decision_governance_evidence_trace, verify_decision_governance_evidence_trace,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService, MissionNotFound
from tests.test_stage3_1_1_identity_envelope import payload


def test_projection_restart_stable_and_no_ledger_writes(tmp_path):
    db = tmp_path / 'mission.db'
    svc = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(db)))
    mid = svc.create_mission(payload('stage385'))['canonical_identity']['mission_id']
    before = svc.repository.list_mission_events(mid)
    first = svc.get_decision_governance_evidence_trace(mid)
    second = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(db))).get_decision_governance_evidence_trace(mid)
    assert first == second
    assert before == svc.repository.list_mission_events(mid)
    assert verify_decision_governance_evidence_trace(first['projection'])
    assert first['projection']['causal_graph_id'] == svc.get_global_causal_lineage_graph(mid)['graph']['graph_id']


def test_tampering_and_cross_mission_sources_rejected(tmp_path):
    svc = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(tmp_path / 'm.db')))
    mid = svc.create_mission(payload('stage385-tamper'))['canonical_identity']['mission_id']
    projection = deepcopy(svc.get_decision_governance_evidence_trace(mid)['projection'])
    projection['source_counts']['route_decisions'] = 99
    assert not verify_decision_governance_evidence_trace(projection)
    normalized = svc.get_normalized_observability_events(mid)
    graph = svc.get_global_causal_lineage_graph(mid)['graph']
    with pytest.raises(ValueError):
        build_decision_governance_evidence_trace(mission_id='another', trace_id=normalized['trace_id'],
            normalized_events=normalized['events'], causal_graph=graph, sources={})
    with pytest.raises(MissionNotFound):
        svc.get_decision_governance_evidence_trace('missing')


def test_health_contract(tmp_path):
    svc = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(tmp_path / 'm.db')))
    health = svc.health()
    assert health['control_version'] == 'stage3.9.10-global-mission-orchestrator-acceptance-regression-gate'
    assert health['mission_repository_migration_level'] == 53
    assert health['decision_governance_evidence_trace_read_only'] is True
    assert health['decision_governance_evidence_trace_new_durable_store_added'] is False
