"""Verify connected CTI and Mission exports without authorizing any action."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from execution_subsystem.cti_feedback_contract import verify_knowledge_export
from execution_subsystem.execution_contract import canonical_json, sha256_hex
from mission_orchestrator.observability_forensics import verify_forensic_evidence_bundle, reconstruct_forensic_mission
from mission_orchestrator.replan_candidate import verify_replan_candidate_contract
from mission_orchestrator.replan_commit import verify_replan_commit_contract
from mission_orchestrator.replan_snapshot import verify_replan_snapshot_contract
from mission_orchestrator.replan_validation import evaluate_replan_candidate_feasibility, verify_replan_validation_contract
from pentest_subsystem.pip_contract import verify_pip_artifact
from run.stage6_10_regression import strict_json


def check(condition, reason):
    if not condition: raise ValueError(reason)


def audit_connected(knowledge, bundle, cti_pip=None, pentest_pip=None):
    """Hashes establish internal consistency, not independent target authenticity."""
    check(verify_knowledge_export(knowledge), "invalid knowledge/VEP/evidence/retained bytes")
    check(verify_forensic_evidence_bundle(bundle) and bundle["status"] == "VERIFIED", "Mission forensic evidence withheld or invalid")
    pair = knowledge["revisions"][-1]
    record = pair["record"]
    vep = pair["feedback_export"]["post_action_export"]["vep_export"]["vep"]
    post = pair["feedback_export"]["post_action_export"]["report"]
    source, execution = vep["source_snapshot"], vep["execution_snapshot"]
    request = execution["envelope"]["execution_request"]
    records = bundle["records"]
    mid, task_id = record["subject"]["mission_id"], record["subject"]["task_id"]
    check(mid == bundle["mission_id"] == records["mission_envelope"]["identity"]["mission_id"], "cross-Mission export")
    check(request["mission_id"] == mid and request["task_id"] == task_id, "execution root lineage mismatch")
    task = next((t for t in records["planned_tasks"] if t["planned_task_id"] == task_id), None)
    check(task is not None and task["required_subsystem"] == "PENTEST" and task["required_capability"] == "pentest.validate", "missing canonical Pentest planned task")
    check(records["mission_envelope"]["bindings"]["pip"] ==
        {k: record["subject"]["pip_reference"][k] for k in ("pip_id", "pip_version")}, "PIP root binding mismatch")
    check(source["task"]["upstream_task_id"] == task_id and source["task"]["mission_id"] == mid, "Pentest task lineage mismatch")
    cti_proof = {}
    if cti_pip is not None or pentest_pip is not None:
        check(cti_pip is not None and pentest_pip is not None, "both native CTI and Pentest PIP exports are required")
        native = cti_pip["artifact"]
        material = deepcopy(native)
        material.pop("integrity")
        for key in ("validation_results", "readiness", "hard_gate_passed"): material["quality"].pop(key)
        native_hash = sha256_hex(material)
        check(native["schema_version"] == cti_pip["schema_version"] == "1.0-harmonized-2026-08"
            and native_hash == native["integrity"]["sha256"] == cti_pip["canonical_sha256"], "native CTI PIP hash mismatch")
        check(cti_pip["mission_id"] == native["mission_binding"]["mission_id"] == mid
            and native["mission_binding"]["target_url"] == request["target"]["target_value"], "native CTI belongs to a different Mission or target")
        gates = native["quality"]["validation_results"]
        check([g["gate_id"] for g in gates] == ["QG-H"+str(i) for i in range(1, 11)]
            and all(g["passed"] is True for g in gates) and cti_pip["validation_results"] == gates
            and native["quality"]["hard_gate_passed"] is True
            and cti_pip["readiness"] == native["quality"]["readiness"] != "REJECTED", "native CTI publication quality gates incomplete")
        check(cti_pip["immutable"] is True and cti_pip["execution_authorized"] is False
            and native["semantics"]["execution_authorized"] is False
            and native["semantics"]["execution_command"] is False, "native CTI became execution authority")
        # Reconstruct the historical ingestion point; an archived PIP may have
        # expired since its accepted intake and cannot authorize a new action.
        ingestion_time = datetime.fromisoformat(pentest_pip["issued_at"].replace("Z", "+00:00"))
        check(verify_pip_artifact(pentest_pip, now=ingestion_time), "Pentest PIP projection invalid")
        reference = record["subject"]["pip_reference"]
        check(pentest_pip["mission_id"] == mid and pentest_pip["task_id"] == task_id
            and pentest_pip["pip_id"] == cti_pip["pip_id"] == native["pip_id"] == reference["pip_id"]
            and pentest_pip["pip_version"] == str(cti_pip["revision"]) == str(native["revision"]) == reference["pip_version"]
            and pentest_pip["integrity"]["canonical_sha256"] == reference["pip_artifact_sha256"], "native PIP identity not retained through execution")
        check(pentest_pip["source_cti"] == {"source_type": "CTI", "source_system": "VULNDESK_CTI",
            "artifact_id": cti_pip["pip_id"], "artifact_version": str(cti_pip["revision"]), "artifact_sha256": native_hash}
            and pentest_pip["intelligence"] == native["intelligence"], "Pentest PIP lost exact native CTI intelligence")
        check(any(v["canonical_sha256"] == native["mission_binding"]["scope_sha256"] for v in records["scope_versions"])
            and any(v["canonical_sha256"] == native["mission_binding"]["governance_binding_sha256"] for v in records["governance_versions"]),
            "CTI publication context absent from Mission history")
        cti_proof = {"native_cti_pip_verified": True, "native_cti_pip_sha256": native_hash,
            "pentest_pip_sha256": pentest_pip["integrity"]["canonical_sha256"]}
    check(vep["observed_result"]["runtime_state"] == "SUCCEEDED" and post["execution_closed"] is True, "connected success requires verified local execution closure")
    auths = [execution["claim"]["authorization_record"], *execution["authorizations"]]
    boundary_auth = execution["adapter_result"]["boundary_authorization_record"]
    check(boundary_auth is not None, "fresh target-boundary governance missing")
    auths.append(boundary_auth)
    for auth in auths:
        context = auth["evaluation"]["current_context"]
        check(context["mission_id"] == mid, "foreign authorization context")
        scope = context["mission_scope"]
        binding = context["governance_binding"]
        check(any(canonical_json(v["contract"]) == canonical_json(scope) for v in records["scope_versions"]), "authorization scope absent from Mission history")
        check(any(canonical_json(v["binding"]) == canonical_json(binding) for v in records["governance_versions"]), "authorization governance binding absent from Mission history")
    episodes = [e for e in records["adaptation_episodes"] if
        e["adaptation_replan_contract"]["provenance"]["metadata"].get("cti_knowledge_revision") == record]
    check(len(episodes) == 1, "exact CTI revision is not bound to one Mission adaptation episode")
    episode = episodes[0]["adaptation_episode_id"]
    snapshots = [s for s in records["replan_snapshots"] if s["adaptation_episode_id"] == episode]
    check(len(snapshots) == 1, "CTI adaptation has no exact governed snapshot")
    snapshot = snapshots[0]["replan_snapshot_contract"]
    check(verify_replan_snapshot_contract(snapshot) and snapshot["cti_feedback_context"] == record, "trusted CTI context changed at snapshot")
    candidates = [c for c in records["replan_candidates"] if c["replan_snapshot_id"] == snapshots[0]["replan_snapshot_id"]]
    check(len(candidates) == 1, "snapshot candidate missing or ambiguous")
    candidate = candidates[0]["replan_candidate_contract"]
    check(verify_replan_candidate_contract(candidate) and evaluate_replan_candidate_feasibility(candidate, snapshot)["feasible"], "CTI successor candidate is not exactly feasible")
    validations = [v for v in records["replan_validations"] if v["replan_candidate_id"] == candidates[0]["replan_candidate_id"]]
    check(len(validations) == 1 and verify_replan_validation_contract(validations[0]["replan_validation_contract"])
        and validations[0]["validation_status"] == "VALIDATED_FOR_COMMIT", "candidate lacks exact validation")
    commits = [c for c in records["replan_commits"] if c["replan_candidate_id"] == candidates[0]["replan_candidate_id"]]
    check(len(commits) == 1 and verify_replan_commit_contract(commits[0]["replan_commit_contract"])
        and commits[0]["governance_decision"] == "ALLOW", "validated CTI delta lacks a governed commit")
    current = records["active_plan_version"]
    check(current["plan_version_record_id"] == commits[0]["successor_plan_version_record_id"]
        and current["canonical_sha256"] == commits[0]["successor_plan_sha256"], "committed successor is not the audited active plan")
    requirements = current["plan_version_contract"]["candidate_plan"]["cti_feedback_requirements"]
    check(requirements["knowledge_sha256"] == record["integrity"]["canonical_sha256"]
        and requirements["validation_still_required"] is True and requirements["execution_authorized"] is False,
        "successor lost unconfirmed validation requirement")
    reconstructed = reconstruct_forensic_mission(bundle)
    return {"status": "VERIFIED_CONNECTED_INTERNAL_LINEAGE", "mission_id": mid, "task_id": task_id,
        "execution_id": request["execution_id"], "attempt_id": vep["attempt_id"], "vep_id": vep["vep_id"],
        "knowledge_id": record["knowledge_id"], "revision": record["revision"], "adaptation_episode_id": episode,
        "successor_plan_version": current["plan_version"], "mission_state": records["mission_state"]["state"],
        "knowledge_sha256": record["integrity"]["canonical_sha256"], "mission_bundle_sha256": bundle["integrity"]["canonical_sha256"],
        "reconstruction_sha256": reconstructed["integrity"]["canonical_sha256"],
        "hypothesis_outcome": record["assessment"]["hypothesis_outcome"], "execution_authorized": False,
        "mission_success_declared": False, "independent_signature": False, **cti_proof}


def audit_files(knowledge_path, bundle_path, cti_pip_path=None, pentest_pip_path=None):
    try:
        paths = [knowledge_path, bundle_path]
        if cti_pip_path is not None or pentest_pip_path is not None:
            check(cti_pip_path is not None and pentest_pip_path is not None, "both CTI PIP export paths are required")
            paths += [cti_pip_path, pentest_pip_path]
        if any(Path(p).stat().st_size > 32 * 1024 * 1024 for p in paths):
            raise ValueError("offline export quota exceeded")
        return audit_connected(*(strict_json(p) for p in paths))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError, StopIteration) as exc:
        return {"status": "INVALID", "error": str(exc), "execution_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-export", required=True)
    parser.add_argument("--mission-bundle", required=True)
    parser.add_argument("--cti-pip")
    parser.add_argument("--pentest-pip")
    args = parser.parse_args()
    result = audit_files(args.knowledge_export, args.mission_bundle, args.cti_pip, args.pentest_pip)
    print(canonical_json(result))
    return 0 if result["status"] == "VERIFIED_CONNECTED_INTERNAL_LINEAGE" else 1


if __name__ == "__main__": raise SystemExit(main())
