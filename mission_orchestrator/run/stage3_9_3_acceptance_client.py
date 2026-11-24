from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# When this file is executed directly (``python run\stage3_9_3_acceptance_client.py``),
# Python places only the ``run`` directory at sys.path[0].  Bootstrap the repository
# root explicitly so the sibling ``mission_orchestrator`` package is importable on
# Windows and on POSIX hosts without relying on an ambient PYTHONPATH.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from mission_orchestrator.e2e_intake_lifecycle_qualification import build_intake_lifecycle_command_request
from mission_orchestrator.e2e_mission_acceptance import materialize_canonical_e2e_mission_request
from mission_orchestrator.e2e_planning_task_graph_qualification import (
    PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS,
    PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES,
    build_planning_dependency_graph_request,
    build_planning_decomposition_request,
    build_planning_plan_request,
    build_planning_snapshot_request,
)

EXPECTED_CONTROL = "stage3.9.3-planning-task-graph-dependency-verification"
EXPECTED_SCHEMA = "apts-stage3.9-planning-task-graph-dependency-qualification-v1"
EXPECTED_MIGRATION = 53


def get_json(base: str, path: str):
    with urlopen(base.rstrip("/") + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base: str, path: str, payload: dict):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = Request(base.rstrip("/") + path, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8780")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    base = args.base_url
    run_id = args.run_id

    health = get_json(base, "/health")
    check(health.get("status") == "ok", "runtime health status is not ok")
    check(health.get("control_version") == EXPECTED_CONTROL, "Stage 3.9.3 control is not active")
    check(health.get("mission_repository_migration_level") == EXPECTED_MIGRATION, "migration level must remain 53")
    check(health.get("stage3_9_3_planning_task_graph_qualification_schema_version") == EXPECTED_SCHEMA, "qualification schema mismatch")
    check(health.get("stage3_9_3_planning_task_graph_qualification_task_count") == 3, "task count contract mismatch")
    check(health.get("stage3_9_3_planning_task_graph_qualification_edge_count") == 2, "edge count contract mismatch")
    check(health.get("stage3_9_3_planning_task_graph_qualification_graph_status") == "PASS", "graph status contract mismatch")
    check(health.get("stage3_9_3_planning_task_graph_qualification_runtime_verifier_read_only") is True, "verifier must be read-only")

    contract1 = get_json(base, "/api/e2e/planning-task-graph-qualification-contract")
    contract2 = get_json(base, "/api/e2e/planning-task-graph-qualification-contract")
    check(contract1 == contract2, "qualification contract route is non-deterministic")
    check(contract1.get("control_version") == EXPECTED_CONTROL, "contract control mismatch")
    check(contract1.get("definition", {}).get("next_stage") == "3.9.4", "next-stage handoff mismatch")

    create_req = materialize_canonical_e2e_mission_request(run_id)
    created = post_json(base, "/api/missions", create_req)
    mission_id = created["canonical_identity"]["mission_id"]
    check(created.get("idempotent_replay") is False, "fresh mission unexpectedly replayed")

    lifecycle_requests = []
    for command in ("BIND_PIP", "START_PLANNING"):
        state = get_json(base, f"/api/missions/{mission_id}/state")["mission_state"]
        vector = get_json(base, f"/api/missions/{mission_id}/version-vector")
        req = build_intake_lifecycle_command_request(
            run_id=run_id,
            command=command,
            expected_version_sha256=vector["version_sha256"],
            expected_state_version=state["state_version"],
        )
        lifecycle_requests.append(req)
        result = post_json(base, f"/api/missions/{mission_id}/lifecycle/commands", req)
        check(result.get("idempotent_replay") is False, f"fresh {command} unexpectedly replayed")

    state = get_json(base, f"/api/missions/{mission_id}/state")["mission_state"]
    check((state.get("state"), state.get("state_version")) == ("PLANNING", 3), "Stage 3.9.2 entry head mismatch")

    vector = get_json(base, f"/api/missions/{mission_id}/version-vector")
    plan_req = build_planning_plan_request(run_id=run_id, expected_version_sha256=vector["version_sha256"], expected_state_version=3)
    plan = post_json(base, f"/api/missions/{mission_id}/plan-contract", plan_req)
    check(plan.get("plan_version") == 1 and plan.get("idempotent_replay") is False, "canonical Plan materialization failed")

    snapshot_req = build_planning_snapshot_request(run_id=run_id, plan=plan, expected_state_version=3)
    snapshot = post_json(base, f"/api/missions/{mission_id}/planner-input-snapshot", snapshot_req)
    check(snapshot.get("snapshot_version") == 1 and snapshot.get("idempotent_replay") is False, "planner-input snapshot failed")

    vector = get_json(base, f"/api/missions/{mission_id}/version-vector")
    decomp_req = build_planning_decomposition_request(
        run_id=run_id,
        expected_version_sha256=vector["version_sha256"],
        expected_state_version=3,
        plan=plan,
        snapshot=snapshot,
    )
    decomposition = post_json(base, f"/api/missions/{mission_id}/task-decomposition", decomp_req)
    check(decomposition.get("task_count") == 3 and decomposition.get("idempotent_replay") is False, "task decomposition failed")

    vector = get_json(base, f"/api/missions/{mission_id}/version-vector")
    graph_req = build_planning_dependency_graph_request(
        run_id=run_id,
        expected_version_sha256=vector["version_sha256"],
        expected_state_version=3,
        plan=plan,
        snapshot=snapshot,
        decomposition=decomposition,
    )
    graph = post_json(base, f"/api/missions/{mission_id}/task-dependency-graph", graph_req)
    check(graph.get("validation_status") == "PASS", "dependency graph validation did not PASS")
    check(graph.get("node_count") == 3 and graph.get("edge_count") == 2, "dependency graph cardinality mismatch")

    proof1 = get_json(base, f"/api/missions/{mission_id}/e2e-planning-task-graph-qualification")
    proof2 = get_json(base, f"/api/missions/{mission_id}/e2e-planning-task-graph-qualification")
    qualification = proof1.get("qualification", {})
    check(proof1 == proof2, "read-only qualification proof is non-deterministic")
    check(qualification.get("status") == "QUALIFIED" and qualification.get("qualified") is True, "Stage 3.9.3 qualification rejected")
    check(qualification.get("failed_check_ids") == [], "Stage 3.9.3 qualification has failed checks")
    check(qualification.get("segment_head", {}).get("task_count") == 3, "qualified task count mismatch")
    check(qualification.get("segment_head", {}).get("edge_count") == 2, "qualified edge count mismatch")
    check(qualification.get("segment_head", {}).get("graph_validation_status") == "PASS", "qualified graph status mismatch")

    events = get_json(base, f"/api/missions/{mission_id}/events")
    check(events.get("integrity_status") == "PASS", "event integrity failed")
    check([e.get("event_type") for e in events.get("events", [])] == list(PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES), "event sequence mismatch")

    # Exact replay of every mutation must be idempotent and must not add events/artifacts.
    check(post_json(base, "/api/missions", create_req).get("idempotent_replay") is True, "Mission replay is not idempotent")
    for req in lifecycle_requests:
        check(post_json(base, f"/api/missions/{mission_id}/lifecycle/commands", req).get("idempotent_replay") is True, "lifecycle replay is not idempotent")
    check(post_json(base, f"/api/missions/{mission_id}/plan-contract", plan_req).get("idempotent_replay") is True, "Plan replay is not idempotent")
    check(post_json(base, f"/api/missions/{mission_id}/planner-input-snapshot", snapshot_req).get("idempotent_replay") is True, "snapshot replay is not idempotent")
    check(post_json(base, f"/api/missions/{mission_id}/task-decomposition", decomp_req).get("idempotent_replay") is True, "decomposition replay is not idempotent")
    check(post_json(base, f"/api/missions/{mission_id}/task-dependency-graph", graph_req).get("idempotent_replay") is True, "graph replay is not idempotent")

    replay_proof = get_json(base, f"/api/missions/{mission_id}/e2e-planning-task-graph-qualification")
    check(replay_proof.get("qualification", {}).get("status") == "QUALIFIED", "replay changed qualification status")

    summary = {
        "status": "PASS",
        "control_version": EXPECTED_CONTROL,
        "mission_id": mission_id,
        "state": "PLANNING",
        "state_version": 3,
        "plan_id": plan["plan_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "decomposition_id": decomposition["decomposition_id"],
        "graph_id": graph["graph_id"],
        "graph_validation_status": graph["validation_status"],
        "task_count": graph["node_count"],
        "edge_count": graph["edge_count"],
        "event_count": len(events["events"]),
        "expected_nonzero_repository_counts": PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, TypeError, ValueError, HTTPError, URLError) as exc:
        print(f"STAGE 3.9.3 ACCEPTANCE CLIENT: FAIL - {exc}", file=sys.stderr)
        raise SystemExit(1)
