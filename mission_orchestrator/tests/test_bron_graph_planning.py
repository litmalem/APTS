"""Offline BRON acceptance: evidence binding, replay, masking and Stage 5.6 handoff."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from pentest_subsystem.attack_path_planning import (
    ATTACK_PATH_MODEL_HASH_DOMAIN, ATTACK_PATH_PLANNING_OUTPUT_HASH_DOMAIN,
    verify_candidate_attack_path, verify_attack_path_planning_output,
)
from pentest_subsystem.bron_graph_contract import LIMITS, seal, verify_snapshot
from pentest_subsystem.bron_graph_repository import BronGraphRepository
from pentest_subsystem.bron_graph_service import enrichment, traverse
from pentest_subsystem.cti_attack_chain import normalize_attack_chain
from pentest_subsystem.exploitation import _required_validation, ExploitationAgentIntegrityError
from pentest_subsystem.symbolic_planner import compile_problem, plan, action_mask
from pentest_subsystem.vulnerability_hypothesis import _with_integrity
from tests.test_cti_attack_chain_normalize import _raw_full
from tests.test_stage5_4_vulnerability_hypothesis_agent import knowledge_item
from tests.test_stage5_5_attack_path_planning_agent import _start_repo, attack_path_request


def start(tmp_path, raw=None, *, planning_model=None, max_paths=25):
    item = knowledge_item()
    item["vulnerability_id"] = "CVE-2021-1234"
    item["attack_chain"] = normalize_attack_chain(raw or _raw_full(), entry="CPE")
    if planning_model:
        item["planning_model"] = planning_model
    repo, boundary, task, orch, _, _, hyp, *_ = _start_repo(tmp_path, knowledge_items=[item])
    with patch("socket.socket.connect", side_effect=AssertionError("Stage 5.5 network access")):
        run, _ = repo.run_attack_path_planning(orch["orchestration_id"],
            attack_path_request(boundary, hyp, max_paths=max_paths))
    return repo, task, orch, hyp, run


def test_graph_candidates_replace_templates_and_round_trip_storage(tmp_path):
    repo, _, _, hyp, run = start(tmp_path)
    output = run["output"]
    assert verify_attack_path_planning_output(output)
    assert repo.get_attack_path_planning_run(run["attack_path_planning_run_id"])["output"] == output
    assert output["graph_enrichment_status"] == "COMPLETE"
    path = output["candidate_paths"][0]
    assert path["stage_sequence"] == []
    assert [n["node_type"] for n in path["nodes"]] == ["CPE", "CVE", "CWE", "CAPEC", "TECHNIQUE", "TACTIC"]
    assert {e["mapping_level"] for e in path["edges"]} == {"AUTHORITATIVE", "RELATED", "PARTIAL"}
    assert all(e["is_causal"] is False for e in path["edges"])
    assert path["applicability"]["status"] == "UNKNOWN"
    assert path["applicability"]["endpoint_binding"] == "UNKNOWN"
    assert _required_validation(path) == hyp["output"]["vulnerability_hypotheses"][0]["required_validation"]
    action = path["action_model"]
    assert action["capability_ref"]["capability_id"] == "validation"
    assert action["source_path_refs"] and action["belief"] == "UNKNOWN"
    assert not set(action) & {"command", "payload", "tool_parameters", "execution_request"}
    assert path["semantics"]["authorization_minted"] is False
    snapshot = path["graph_context"]["snapshot"]
    assert not any(e["relation"] == "RUNS_CPE" for e in snapshot["edges"])
    assert {e["evidence_refs"][0] for e in snapshot["edges"] if e["relation"] == "SUPPORTED_BY"} == set(action["evidence_refs"])


def test_deterministic_replay_and_source_order(tmp_path):
    _, task, _, hyp, run = start(tmp_path)
    h = hyp["output"]["vulnerability_hypotheses"][0]
    assert enrichment(h) == enrichment(h)
    assert compile_problem(task, hyp) == compile_problem(task, hyp)
    assert plan(compile_problem(task, hyp)) == plan(compile_problem(task, hyp))
    raw = _raw_full()
    raw["links"].reverse()
    assert normalize_attack_chain(raw, entry="CPE") == h["knowledge"]["attack_chain"]
    assert verify_attack_path_planning_output(run["output"])


def test_missing_graph_keeps_explicit_legacy_fallback(tmp_path):
    repo, boundary, _, orch, _, _, hyp, *_ = _start_repo(tmp_path)
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp))
    assert run["output"]["graph_enrichment_status"] == "UNAVAILABLE"
    path = run["output"]["candidate_paths"][0]
    assert len(path["nodes"]) == 4
    assert path["graph_context"]["fallback_reason"] == "NO_REACHABLE_CATALOG_RELATIONS"
    assert verify_candidate_attack_path(path)


def test_partial_graph_never_fabricates_tail_or_endpoint(tmp_path):
    raw = _raw_full()
    raw["links"] = raw["links"][:2]
    _, _, _, _, run = start(tmp_path, raw)
    assert run["output"]["graph_enrichment_status"] == "PARTIAL"
    path = run["output"]["candidate_paths"][0]
    assert [n["node_type"] for n in path["nodes"]] == ["CPE", "CVE", "CWE"]
    assert path["applicability"]["endpoint_binding"] == "UNKNOWN"


def test_catalog_never_satisfies_symbolic_preconditions(tmp_path):
    _, task, orch, hyp, run = start(tmp_path, planning_model={
        "preconditions": ["access:unknown"], "effects": ["goal:assessment"], "cost": 2})
    problem = compile_problem(task, hyp)
    assert action_mask(problem["actions"], problem["initial_facts"]) == [False]
    assert not run["output"]["symbolic_plan"]["paths"]
    feedback = {"feedback_id": "feedback-bron-conflict", "orchestration_id": orch["orchestration_id"],
        "subject_capability_id": "validation", "feedback_type": "CONFLICTING_EVIDENCE",
        "evidence_refs": ["evidence-conflict"], "integrity": {"canonical_sha256": "a" * 64}}
    conflict = compile_problem(task, hyp, [feedback])
    assert conflict["actions"][0]["belief"] == "CONFLICTING"
    assert action_mask(conflict["actions"], conflict["initial_facts"]) == [False]


@pytest.mark.parametrize("mutation", ["type", "edge", "evidence", "limit", "snapshot", "provenance"])
def test_resealed_snapshot_malformations_fail_closed(tmp_path, mutation):
    _, _, _, _, run = start(tmp_path)
    snapshot = deepcopy(run["output"]["knowledge_graph_snapshots"][0]["snapshot"])
    if mutation == "type":
        snapshot["nodes"][0]["node_type"] = "SHELL"
    elif mutation == "edge":
        snapshot["edges"][0]["to"] = "missing-node"
    elif mutation == "evidence":
        snapshot["edges"][0]["evidence_refs"] = ["fabricated"]
    elif mutation == "limit":
        snapshot["limits"]["depth"] = 999
    elif mutation == "snapshot":
        snapshot["knowledge_graph_snapshot_id"] = "brongs-forged"
    else:
        snapshot["nodes"][0]["provenance"]["snapshot"] = "forged"
    snapshot = seal({k: v for k, v in snapshot.items() if k != "integrity"})
    assert not verify_snapshot(snapshot)
    with pytest.raises(ValueError, match="Malformed"):
        BronGraphRepository([snapshot])


@pytest.mark.parametrize("field,value", [("capability_ref", {"capability_id": "exploitation"}),
    ("preconditions", []), ("effects", ["access:root"]), ("tool_parameters", {"shell": "x"})])
def test_resealed_injected_action_is_rejected(tmp_path, field, value):
    _, _, _, _, run = start(tmp_path)
    path = deepcopy(run["output"]["candidate_paths"][0])
    path["action_model"][field] = value
    path = _with_integrity({k: v for k, v in path.items() if k != "integrity"}, domain=ATTACK_PATH_MODEL_HASH_DOMAIN)
    assert not verify_candidate_attack_path(path)
    with pytest.raises(ExploitationAgentIntegrityError):
        _required_validation(path)


def test_resealed_symbolic_effect_tampering_is_rejected(tmp_path):
    from pentest_subsystem.symbolic_planner import seal as seal_plan
    _, _, _, _, run = start(tmp_path)
    output = deepcopy(run["output"])
    output["symbolic_plan"]["problem"]["actions"][0]["effects"].append("access:root")
    output["symbolic_plan"] = seal_plan({k: v for k, v in output["symbolic_plan"].items() if k != "integrity"})
    output = _with_integrity({k: v for k, v in output.items() if k != "integrity"}, domain=ATTACK_PATH_PLANNING_OUTPUT_HASH_DOMAIN)
    assert not verify_attack_path_planning_output(output)


def test_snapshot_repository_returns_isolated_copies(tmp_path):
    _, _, _, _, run = start(tmp_path)
    snapshot = run["output"]["knowledge_graph_snapshots"][0]["snapshot"]
    repo = BronGraphRepository([snapshot])
    retrieved = repo.get(snapshot["knowledge_graph_snapshot_id"])
    retrieved["nodes"].clear()
    assert repo.get(snapshot["knowledge_graph_snapshot_id"]) == snapshot


def test_observations_are_exactly_bound_to_predecessor_asset(tmp_path):
    _, _, _, _, run = start(tmp_path)
    graph = run["output"]["knowledge_graph_snapshots"][0]
    snapshot = graph["snapshot"]
    observed = snapshot["source_asset"]
    assert observed is not None
    endpoints = [n for n in snapshot["nodes"] if n["node_type"] == "ENDPOINT"]
    assert len(endpoints) == len(observed["endpoints"])
    for node in endpoints:
        row = next(r for r in observed["endpoints"] if r["observation_id"] == node["record_id"])
        assert node["evidence_refs"] == [row["evidence_ref"]]
        assert node["attributes"]["method"] == row["method"]
    forged = deepcopy(observed)
    forged["asset_id"] = "enumasset-forged"
    with pytest.raises(ValueError, match="binding"):
        enrichment(snapshot["source_hypothesis"], forged)


def test_real_graph_handoff_keeps_governance_and_stage6_authority(tmp_path):
    from tests.test_stage5_6_exploitation_agent import _start_repo as start56, exploitation_request
    item = knowledge_item()
    item["vulnerability_id"] = "CVE-2021-1234"
    item["attack_chain"] = normalize_attack_chain(_raw_full(), entry="CPE")
    repo, boundary, _, orch, _, _, _, attack_path, *_ = start56(tmp_path, knowledge_items=[item])
    run, created = repo.run_exploitation(orch["orchestration_id"], exploitation_request(boundary, attack_path))
    assert created
    assert run["output"]["semantics"]["target_actuation"] is False
    assert run["output"]["semantics"]["authorization_minted"] is False


def test_legacy_v1_records_remain_verifiable(tmp_path):
    from pentest_subsystem.attack_path_planning import (
        build_attack_path_graph, build_candidate_path_ranking,
        verify_attack_path_graph,
    )
    repo, boundary, task, orch, _, _, hyp, *_ = _start_repo(tmp_path)
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp))
    output = deepcopy(run["output"])
    path = deepcopy(output["candidate_paths"][0])
    for field in ("graph_context", "knowledge_graph_snapshot_id", "graph_enrichment_status", "action_model",
                  "applicability", "uncertainty", "selection_reason", "integrity"):
        path.pop(field, None)
    path["schema_version"] = "apts-stage5.5-candidate-attack-path-v1"
    path = _with_integrity(path, domain="APTS_STAGE5_5_CANDIDATE_ATTACK_PATH_V1")
    assert verify_candidate_attack_path(path)
    graph = build_attack_path_graph(run_id=run["attack_path_planning_run_id"], task=task, candidate_paths=[path])
    graph.pop("integrity")
    graph["semantics"].pop("catalog_edges_are_non_causal")
    graph["schema_version"] = "apts-stage5.5-attack-path-graph-v1"
    graph = _with_integrity(graph, domain="APTS_STAGE5_5_ATTACK_PATH_GRAPH_V1")
    assert verify_attack_path_graph(graph)
    output["schema_version"] = "apts-stage5.5-attack-path-planning-output-v1"
    output["candidate_paths"] = [path]
    output["attack_path_graph"] = graph
    output["candidate_path_ranking"] = build_candidate_path_ranking(
        run_id=run["attack_path_planning_run_id"], candidate_paths=[path], max_candidate_paths=25)
    for field in ("knowledge_graph_snapshots", "knowledge_graph_schema_version", "knowledge_graph_snapshot_id",
                  "graph_enrichment_status", "candidate_pruning", "integrity"):
        output.pop(field, None)
    output = _with_integrity(output, domain="APTS_STAGE5_5_ATTACK_PATH_PLANNING_OUTPUT_V1")
    assert verify_attack_path_planning_output(output)


def test_bounded_traversal_prunes_deterministically_and_preserves_direction():
    nodes = [{"node_id": "root", "node_type": "CWE"}] + [
        {"node_id": f"leaf-{i:03}", "node_type": "CAPEC"} for i in range(100)]
    edges = [{"edge_id": f"edge-{i:03}", "from": f"leaf-{i:03}", "to": "root",
              "relation": "CATALOG_PATTERN_ASSOCIATION"} for i in range(100)]
    snapshot = {"nodes": nodes, "edges": edges, "root_node_ids": ["root"], "knowledge_graph_snapshot_id": "test"}
    routes, pruning = traverse(snapshot)
    assert len(routes) == LIMITS["fan_out"]
    assert pruning["pruned"] == 92
    assert traverse(snapshot) == traverse({**snapshot, "edges": list(reversed(edges))})
    assert edges[0]["from"] == "leaf-000" and routes[0]["node_ids"][0] == "root"
