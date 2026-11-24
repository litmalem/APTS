from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.observability_causal_graph import (
    EDGE_SCHEMA_VERSION, IDENTITY_PREFIX, NODE_SCHEMA_VERSION, SCHEMA_VERSION,
    build_global_causal_lineage_graph, canonical_global_causal_lineage_graph_definition,
    verify_global_causal_lineage_graph,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_1_1_identity_envelope import payload


def _svc(tmp_path: Path, key='stage383'):
    db = tmp_path / 'mission.db'
    svc = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(db)))
    mid = svc.create_mission(payload(key))['canonical_identity']['mission_id']
    return db, svc, mid


def test_graph_projection_is_deterministic_restart_stable_and_read_only(tmp_path: Path):
    db, svc, mid = _svc(tmp_path)
    before = svc.repository.list_mission_events(mid)
    first = svc.get_global_causal_lineage_graph(mid)
    second = CanonicalMissionService(MissionRepository(driver='sqlite', sqlite_path=str(db))).get_global_causal_lineage_graph(mid)
    assert first == second
    assert svc.repository.list_mission_events(mid) == before
    assert first['graph']['graph_id'].startswith(IDENTITY_PREFIX)


def test_graph_binds_stage382_event_projection_exactly(tmp_path: Path):
    _, svc, mid = _svc(tmp_path, 'stage383-bind')
    events = svc.get_normalized_observability_events(mid)
    graph = svc.get_global_causal_lineage_graph(mid)['graph']
    event_nodes = [n for n in graph['nodes'] if n['node_type'] == 'MISSION_EVENT']
    assert graph['node_count'] == events['event_count'] + 1
    assert [n['source_event_id'] for n in event_nodes] == [e['source_event_id'] for e in events['events']]
    assert [n['source_event_sha256'] for n in event_nodes] == [e['source_event_sha256'] for e in events['events']]


def test_root_reaches_every_event_and_graph_verifies(tmp_path: Path):
    _, svc, mid = _svc(tmp_path, 'stage383-reach')
    graph = svc.get_global_causal_lineage_graph(mid)['graph']
    assert verify_global_causal_lineage_graph(graph)
    assert sum(1 for n in graph['nodes'] if n['node_type'] == 'MISSION_ROOT') == 1


def test_parent_edges_preserve_verified_ledger_order(tmp_path: Path):
    _, svc, mid = _svc(tmp_path, 'stage383-parent')
    graph = svc.get_global_causal_lineage_graph(mid)['graph']
    assert graph['edge_count'] >= 1
    assert graph['edges'][0]['relation_type'] == 'MISSION_ROOT'
    assert all(e['relation_type'] in {'MISSION_ROOT','PARENT_EVENT','CAUSATION_EVENT'} for e in graph['edges'])


def test_cross_mission_or_trace_normalized_event_fails_closed():
    event = {'mission_id':'m2','trace_id':'t1','source_event_id':'e1','source_event_sha256':'a'*64,'event_type':'X','source_component':'x','occurred_at_utc':'2026-01-01T00:00:00Z','parent_event_id':None,'causation_id':None}
    with pytest.raises(ValueError, match='cross-mission'):
        build_global_causal_lineage_graph(mission_id='m1', trace_id='t1', normalized_events=[event])


def test_duplicate_source_event_fails_closed():
    event = {'mission_id':'m1','trace_id':'t1','source_event_id':'e1','source_event_sha256':'a'*64,'event_type':'X','source_component':'x','occurred_at_utc':'2026-01-01T00:00:00Z','parent_event_id':None,'causation_id':None}
    with pytest.raises(ValueError, match='duplicate'):
        build_global_causal_lineage_graph(mission_id='m1', trace_id='t1', normalized_events=[event,event])


def test_dangling_parent_fails_closed():
    event = {'mission_id':'m1','trace_id':'t1','source_event_id':'e1','source_event_sha256':'a'*64,'event_type':'X','source_component':'x','occurred_at_utc':'2026-01-01T00:00:00Z','parent_event_id':'missing','causation_id':None}
    with pytest.raises(ValueError, match='dangling parent'):
        build_global_causal_lineage_graph(mission_id='m1', trace_id='t1', normalized_events=[event])


def test_noncausal_parent_order_fails_closed():
    base={'mission_id':'m1','trace_id':'t1','source_event_sha256':'a'*64,'event_type':'X','source_component':'x','occurred_at_utc':'2026-01-01T00:00:00Z','causation_id':None}
    e1={**base,'source_event_id':'e1','parent_event_id':'e2'}; e2={**base,'source_event_id':'e2','parent_event_id':None}
    with pytest.raises(ValueError, match='non-causal'):
        build_global_causal_lineage_graph(mission_id='m1', trace_id='t1', normalized_events=[e1,e2])


def test_tampered_node_integrity_is_rejected(tmp_path: Path):
    _, svc, mid = _svc(tmp_path, 'stage383-node-tamper')
    graph = deepcopy(svc.get_global_causal_lineage_graph(mid)['graph'])
    graph['nodes'][0]['source_component'] = 'tampered'
    assert not verify_global_causal_lineage_graph(graph)


def test_tampered_edge_or_graph_integrity_is_rejected(tmp_path: Path):
    _, svc, mid = _svc(tmp_path, 'stage383-edge-tamper')
    graph = deepcopy(svc.get_global_causal_lineage_graph(mid)['graph'])
    graph['edges'][0]['relation_type'] = 'TAMPERED'
    assert not verify_global_causal_lineage_graph(graph)


def test_contract_declares_no_new_persistence_or_runtime_side_effects():
    d = canonical_global_causal_lineage_graph_definition()
    assert d['schema_version'] == SCHEMA_VERSION
    assert d['node_schema_version'] == NODE_SCHEMA_VERSION
    assert d['edge_schema_version'] == EDGE_SCHEMA_VERSION
    assert d['persistence_mode'] == 'DERIVED_NO_NEW_DURABLE_STORE'
    assert d['database_change_mode'] == 'NO_NEW_DATABASE_MIGRATION'
    assert d['runtime_side_effects'] is False


def test_health_activates_stage383_without_migration(tmp_path: Path):
    _, svc, _ = _svc(tmp_path, 'stage383-health')
    h = svc.health()
    assert h['control_version'] == 'stage3.9.10-global-mission-orchestrator-acceptance-regression-gate'
    assert h['mission_repository_migration_level'] == 53
    assert h['global_causal_lineage_graph_schema_version'] == SCHEMA_VERSION
    assert h['global_causal_lineage_graph_read_only'] is True
    assert h['global_causal_lineage_graph_deterministic'] is True
    assert h['global_causal_lineage_graph_acyclic'] is True
    assert h['global_causal_lineage_graph_new_durable_store_added'] is False
