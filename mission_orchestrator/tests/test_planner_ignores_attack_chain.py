"""Stage 5.5 attack-chain provenance (#5): the planner carries the attack_chain as
DESCRIPTIVE, NON-CAUSAL provenance only. It must never enter STRIPS
preconditions/effects, and chain-free paths stay byte-identical (nodes/edges/stages).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from pentest_subsystem.attack_path_planning import (
    build_candidate_attack_paths,
    verify_candidate_attack_path,
    verify_attack_path_planning_output,
)
from pentest_subsystem.cti_attack_chain import normalize_attack_chain

from tests.test_stage5_4_vulnerability_hypothesis_agent import knowledge_item
from tests.test_stage5_5_attack_path_planning_agent import _start_repo, attack_path_request


def _chain():
    raw = {
        "snapshot": {"source": "vulndesk", "graph_snapshot_id": "ctigs-plan55"},
        "links": [
            {"from_type": "CPE", "from_id": "cpe:2.3:a:apache:http_server:2.4.1:*", "to_type": "CVE",
             "to_id": "CVE-2021-0001", "mapping_level": "authoritative", "source_ref": "vulndesk://cpe"},
            {"from_type": "CVE", "from_id": "CVE-2021-0001", "to_type": "CWE", "to_id": "CWE-79",
             "mapping_level": "authoritative", "source_ref": "vulndesk://cve-cwes"},
            {"from_type": "CWE", "from_id": "CWE-79", "to_type": "CAPEC", "to_id": "CAPEC-63",
             "mapping_level": "related", "source_ref": "vulndesk://capec"},
            {"from_type": "CAPEC", "from_id": "CAPEC-63", "to_type": "ATTACK", "to_id": "T1190",
             "tactic": "Initial Access", "mapping_level": "partial", "source_ref": "vulndesk://attack"},
        ],
    }
    return normalize_attack_chain(raw, entry="CPE")


def _item_with_chain():
    item = knowledge_item("planchain")
    item["attack_chain"] = _chain()
    return item


def _plan(tmp_path: Path, items):
    repo, boundary, task, orch, recon, enum, hyp, _, _ = _start_repo(
        tmp_path, "planchain", knowledge_items=items)
    run, created = repo.run_attack_path_planning(
        orch["orchestration_id"], attack_path_request(boundary, hyp, "planchain"))
    assert created is True
    return run


def test_chain_is_descriptive_provenance_not_strips(tmp_path: Path):
    run = _plan(tmp_path, [_item_with_chain()])
    output = run["output"]
    assert verify_attack_path_planning_output(output)
    paths = output["candidate_paths"]
    assert paths
    for path in paths:
        assert verify_candidate_attack_path(path)
        # Chain rides in provenance.knowledge and the descriptive summary.
        assert "attack_chain" in path["provenance"]["knowledge"]
        summary = path["attack_techniques"]
        assert summary["semantics"] == "DESCRIPTIVE_NON_CAUSAL_ATTACK_CHAIN_PROVENANCE"
        assert all(t["is_causal"] is False for t in summary["techniques"])
        assert any(t["technique_id"] == "T1190" for t in summary["techniques"])

    # The technique id and attack_chain must NOT appear anywhere in STRIPS.
    actions = output["symbolic_plan"]["problem"]["actions"]
    for action in actions:
        blob = str(action.get("preconditions")) + str(action.get("effects"))
        assert "T1190" not in blob
        assert "attack_chain" not in blob
        assert "attack_techniques" not in blob
    # No node/edge references the technique either.
    for path in paths:
        for node in path["nodes"]:
            assert "T1190" not in str(node.get("required_evidence"))
            assert "attack_chain" not in str(node)


def _skeleton(path):
    """Id-independent planner skeleton: stages, node logic, edge relations, score.
    Node ids and provenance refs depend on run/hypothesis ids (different per repo),
    so they are excluded; everything the planner DECIDES is kept."""
    return {
        "stage_sequence": path["stage_sequence"],
        "nodes": [{"sequence": n["sequence"], "stage": n["stage"], "state": n["state"],
                   "description": n["description"], "required_evidence": n["required_evidence"],
                   "execution_authorized": n["execution_authorized"]} for n in path["nodes"]],
        "edge_relations": [e["relation"] for e in path["edges"]],
        "planning_score": path["planning_score"],
    }


def test_chain_free_paths_are_byte_identical(tmp_path: Path):
    chained = _plan(tmp_path / "a", [_item_with_chain()])
    baseline = _plan(tmp_path / "b", [knowledge_item("planchain")])

    cpaths = chained["output"]["candidate_paths"]
    bpaths = baseline["output"]["candidate_paths"]
    assert len(cpaths) == len(bpaths) == 1
    cpath, bpath = cpaths[0], bpaths[0]
    # Adding the chain changes NOTHING the planner decides; only the additive
    # descriptive summary is new.
    assert _skeleton(cpath) == _skeleton(bpath)
    assert "attack_techniques" in cpath and "attack_techniques" not in bpath
    # Provenance evidence binding (the hypothesis knowledge) is unchanged except for
    # the additive attack_chain field.
    assert "attack_chain" in cpath["provenance"]["knowledge"]
    assert "attack_chain" not in bpath["provenance"]["knowledge"]
