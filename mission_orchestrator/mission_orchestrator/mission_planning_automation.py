"""Deterministic, recoverable planning after an immutable Mission PIP is bound.

This worker creates canonical planning artifacts and registers declared GSS
targets with Recon as non-observed, non-executable context. It never starts a
Pentest orchestration, requests GSS authorization, or performs target I/O.
"""
from __future__ import annotations

import hashlib
import logging

from .canonical import sha256_hex
from .planner_generation import PLANNER_PROFILE_CANONICAL_DAG_V1


def _key(mission_id: str, stage: str) -> str:
    return "auto-plan-" + hashlib.sha256(mission_id.encode()).hexdigest()[:32] + "-" + stage


def _base(service, mission_id: str, stage: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "idempotency_key": _key(mission_id, stage),
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "created_by": "mission-auto-planning",
        "reason": "Deterministic autonomous planning from bound Mission and active GSS scope",
        "metadata": {"automation": "PIP_BOUND_TO_PLANNING_V1", "mission_id": mission_id},
    }


def _planning_command(service, mission_id: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    key = _key(mission_id, "start")
    return service.execute_mission_lifecycle_command(mission_id, {
        "command_id": key,
        "idempotency_key": key,
        "command": "START_PLANNING",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "actor": "mission-auto-planning",
        "reason_code": "AUTOMATIC_PLANNING_FROM_PIP_BOUND",
        "reason": "Start deterministic planning after verified Mission PIP binding",
        "evidence_refs": ["mission-pip-bound:" + mission_id],
        "metadata": {"automation": "PIP_BOUND_TO_PLANNING_V1"},
    })


def _task_specs(scope_contract: dict, required_subsystems: list[str], scope_sha256: str) -> tuple[list[dict], list[dict]]:
    targets = scope_contract.get("scope", {}).get("targets") or []
    if not targets:
        raise ValueError("autonomous planning requires at least one allowed canonical Mission scope target")
    metadata = scope_contract.get("metadata", {}).get("gss_scope_sync", {})
    specs, edges = [], []
    required = {str(item).upper() for item in required_subsystems}
    if "PENTEST" in required and "CTI" not in required:
        raise ValueError("the governed Pentest plan requires both PENTEST and CTI subsystems")
    for index, target in enumerate(targets, 1):
        target_type, target_value = target.get("target_type"), target.get("target_value")
        if not target_type or not target_value:
            raise ValueError("canonical Mission scope target is incomplete")
        prefix = f"t{index}"
        shared = {"target_ref": target_value, "target_type": target_type,
                  "environment": target.get("environment"),
                  "scope_snapshot_sha256": scope_sha256,
                  "source_gss_scope_contract_id": metadata.get("source_scope_contract_id"),
                  "source_gss_scope_version": metadata.get("source_version")}
        chain = []

        def add(key, task_type, subsystem, capability, goal, output, evidence, *,
                stage6_profile=None, intake_profile=None, knowledge_inputs=None):
            if subsystem not in required:
                return
            stage6_required = stage6_profile is not None
            spec = {
                "task_key": key, "task_type": task_type,
                "objective": {"goal": goal, **shared},
                "required_capability": capability, "required_subsystem": subsystem,
                "preconditions": ([{"kind": "PREDECESSOR_TASK_COMPLETED", "task_key": chain[-1]}]
                                  if chain else [{"kind": "ACTIVE_GSS_SCOPE_TARGET", "required": True}]),
                "expected_outputs": [{"artifact": output, "format": "STRUCTURED"}],
                "success_criteria": [{"metric": key + "_artifact_present", "expected": True}],
                "evidence_requirements": [{"type": evidence, "provenance_required": True}],
                "priority": min(100, 10 + len(specs) * 5),
                "metadata": {
                    "automation": "PIP_BOUND_TO_PLANNING_V2_FULL_PENTEST_DAG",
                    "target_index": index,
                    "planning_stage": key.rsplit("-", 1)[-1].upper(),
                    "input_artifacts": list(knowledge_inputs or []),
                    "stage6_profile": stage6_profile,
                    "wpt_intake_profile": intake_profile,
                    "stage6_authorization_required": stage6_required,
                    "capability_registration_required": stage6_required,
                    "execution_authorized": False,
                    "dispatch_requested": False,
                    "target_io_performed": False,
                    "planning_only": True,
                    "mission_completion_authority": "GLOBAL_MISSION_VERIFIED_COMPLETION_GATE",
                },
            }
            specs.append(spec)
            if chain:
                edges.append({"from_task_key": chain[-1], "to_task_key": key})
            chain.append(key)

        # The global Mission plan declares the entire Pentest workflow. These
        # entries are task/evidence contracts only; Stage 6 remains the sole
        # execution authority and the plan itself never performs target I/O.
        add(f"{prefix}-pentest-orchestration", "PENTEST_TASK_ORCHESTRATION_HANDOFF", "PENTEST", "pentest.recon",
            "Materialize and acknowledge the PIP/scope-bound Pentest task and its local orchestration",
            "pentest_task_orchestration_reference", "PENTEST_TASK_AND_ORCHESTRATION_ACK")
        add(f"{prefix}-recon", "RECONNAISSANCE_CONTEXT", "PENTEST", "pentest.recon",
            "Bootstrap Recon context from the exact declared GSS target",
            "recon_bootstrap_reference", "RECON_SCOPE_AND_TASK_BINDING")
        add(f"{prefix}-wpt-intake", "WPT_GOVERNED_FINGERPRINTING_INTAKE", "PENTEST", "pentest.recon",
            "Submit exact scoped target for governed WPT fingerprinting intake",
            "wpt_governed_intake_reference", "WPT_INTAKE_AND_SCOPE_BINDING",
            intake_profile="fingerprinting")
        add(f"{prefix}-wpt-fingerprint", "STAGE6_WPT_FINGERPRINTING", "PENTEST", "pentest.validate",
            "Run bounded WPT fingerprinting only through a registered Stage 6 adapter after fresh authorization",
            "sealed_wpt_fingerprinting_evidence", "STAGE6_AUTHORIZATION_AND_SEALED_WPT_EVIDENCE",
            stage6_profile="web_technology_fingerprinting")
        add(f"{prefix}-recon-wpt-result", "VERIFIED_WPT_TO_RECON_HANDOFF", "PENTEST", "pentest.recon",
            "Deliver the sealed Stage 6 WPT result to the matching Recon run and persist its acknowledgement",
            "recon_wpt_observation_reference", "RECON_ACK_AND_WPT_EVIDENCE_LINEAGE")
        add(f"{prefix}-vulndesk-cti", "CTI_TECHNOLOGY_VULNERABILITY_ENRICHMENT", "CTI", "cti.analyze.context",
            "Enrich verified Recon/WPT technology observations with provenance-bound Vulndesk CTI knowledge",
            "vulndesk_cti_knowledge_reference", "CTI_PROVENANCE_AND_CONTENT_HASH")
        add(f"{prefix}-enumeration", "ENUMERATION_AGENT_ANALYSIS", "PENTEST", "pentest.recon",
            "Build Enumeration observations from Recon evidence and authorized collection results",
            "enumeration_evidence_bundle", "ENUMERATION_PREDECESSOR_AND_AUTHORIZED_EVIDENCE")
        add(f"{prefix}-vulnerability-hypothesis", "VULNERABILITY_HYPOTHESIS_ANALYSIS", "PENTEST", "pentest.recon",
            "Correlate authoritative Enumeration evidence with provenance-bound CTI knowledge",
            "unvalidated_vulnerability_hypothesis_bundle", "HYPOTHESIS_TO_ENUMERATION_AND_CTI_LINEAGE",
            knowledge_inputs=["enumeration_evidence_bundle", "vulndesk_cti_knowledge_reference"])
        add(f"{prefix}-attack-path", "ATTACK_PATH_CANDIDATE_PLANNING", "PENTEST", "pentest.recon",
            "Construct conditional, evidence-bound candidate paths from unvalidated vulnerability hypotheses",
            "conditional_attack_path_graph", "ATTACK_PATH_TO_HYPOTHESIS_AND_EVIDENCE_LINEAGE")
        add(f"{prefix}-validation-proposal", "STAGE6_VALIDATION_ACTION_PROPOSAL", "PENTEST", "pentest.validate",
            "Prepare a bounded validation proposal from the approved candidate path; do not execute in planning",
            "stage6_validation_request_reference", "VALIDATION_PROPOSAL_AND_STAGE6_REQUEST_BINDING")
        add(f"{prefix}-stage6-validation", "STAGE6_AUTHORIZED_VALIDATION", "PENTEST", "pentest.validate",
            "Execute only the exact action allowed by fresh GSS authorization and the fixed Stage 6 adapter",
            "sealed_validation_execution_evidence", "STAGE6_AUTHORIZATION_RUNTIME_AND_SEALED_EVIDENCE",
            stage6_profile="authorized_validation")
        add(f"{prefix}-impact", "POST_EXPLOITATION_IMPACT_ANALYSIS", "PENTEST", "pentest.recon",
            "Assess impact from verified Stage 6 evidence and preserve unknown or unconfirmed outcomes",
            "post_exploitation_impact_evidence", "IMPACT_TO_STAGE6_EXECUTION_EVIDENCE_LINEAGE")
        add(f"{prefix}-cleanup", "CLEANUP_AND_POST_ACTION_VERIFICATION", "PENTEST", "pentest.validate",
            "Perform only authorized cleanup and verify post-action state before Mission completion review",
            "verified_cleanup_receipt", "STAGE6_CLEANUP_AND_POST_ACTION_VERIFICATION",
            stage6_profile="authorized_cleanup")
    if not specs:
        raise ValueError("Mission required_subsystems do not include a supported autonomous planning stage")
    if len(specs) > 128:
        raise ValueError("active scope produces more than 128 planned tasks")
    return specs, edges


def _publish_scope_targets(service, mission_id: str, scope_record: dict, repository=None) -> list[dict]:
    metadata = scope_record["contract"].get("metadata", {}).get("gss_scope_sync")
    if not isinstance(metadata, dict):
        # A locally authored scope is valid planning context, but the Recon
        # queue only accepts targets whose governance source can be read back.
        return []
    from .gss_scope_sync import fetch
    source = fetch(service, mission_id)
    source_sha = sha256_hex(source)
    if source_sha != metadata.get("source_snapshot_sha256"):
        raise ValueError("active GSS scope changed after Mission scope synchronization")
    if repository is None:
        # The active Pentest Workspace uses the newest compatible repository
        # subclass. Opening its DB through the stage-5.2 class would correctly
        # reject a later repository migration level.
        from pentest_subsystem.agentic_pentest_acceptance_service import AgenticPentestAcceptanceService
        from pentest_subsystem.task_repository import default_pentest_repository_path
        repository = AgenticPentestAcceptanceService(
            repository=None
        ).repository
        if str(repository.sqlite_path) != str(default_pentest_repository_path()):
            raise ValueError("Mission and Pentest Workspace must share APTS_PENTEST_DB")
    repository.initialize()
    sent = []
    for target in scope_record["contract"].get("scope", {}).get("targets", []):
        target_hash = sha256_hex(target)
        key = "reconscope-" + hashlib.sha256(
            f"{mission_id}:{metadata['source_scope_contract_id']}:{metadata['source_version']}:{target_hash}".encode()
        ).hexdigest()[:40]
        record = {
            "schema_version": "apts-recon-mission-scope-target-v1",
            "mission_id": mission_id,
            "scope_contract_id": metadata["source_scope_contract_id"],
            "scope_version": int(metadata["source_version"]),
            "scope_contract_hash": metadata["source_contract_hash"],
            "source_snapshot_sha256": source_sha,
            "target_key": key,
            "target": {"target_type": target["target_type"], "target_value": target["target_value"],
                       "environment": target["environment"]},
            "status": "READY_FOR_COLLECTION",
            "semantics": {"target_is_observed": False, "execution_authorized": False,
                          "recon_run_created": False, "external_network_io_performed": False},
        }
        stored, created = repository.register_mission_scope_target(record)
        sent.append({"target_key": stored["target_key"], "created": created,
                     "target": stored["target"], "execution_authorized": False})
    return sent


def plan_mission(service, mission_id: str, recon_repository=None) -> dict:
    """Advance one PIP_BOUND Mission to a fully materialized feasible plan."""
    state = service.repository.get_state(mission_id)
    if state is None:
        service.get_mission(mission_id)
    if state["state"] not in {"PIP_BOUND", "PLANNING"}:
        return {"status": "unchanged", "state": state["state"]}
    envelope = service.get_envelope(mission_id)["envelope"]
    if not envelope.get("bindings", {}).get("pip", {}).get("pip_id"):
        raise ValueError("PIP_BOUND planning requires an immutable bound PIP")
    from .gss_scope_sync import synchronize
    scope = synchronize(service, mission_id)
    scope_contract = scope["contract"]
    required_subsystems = envelope["mission"].get("required_subsystems") or []
    scope_targets = _publish_scope_targets(service, mission_id, scope, recon_repository)
    if state["state"] == "PIP_BOUND":
        _planning_command(service, mission_id)

    # Each artifact API is immutable and idempotent. This sequence can be
    # replayed after a crash at any stage without creating a second plan.
    if service.repository.get_mission_plan(mission_id) is None:
        service.create_mission_plan_contract(mission_id, _base(service, mission_id, "plan"))
    plan = service.get_mission_plan_contract(mission_id)
    if service.repository.get_planner_input_snapshot(mission_id) is None:
        payload = _base(service, mission_id, "snapshot")
        payload.pop("expected_version_sha256")
        payload.update({"expected_plan_id": plan["plan_id"], "expected_plan_version": plan["plan_version"],
                        "expected_plan_sha256": plan["canonical_sha256"]})
        service.create_planner_input_snapshot(mission_id, payload)
    snapshot = service.get_planner_input_snapshot(mission_id)
    if service.repository.get_task_decomposition(mission_id) is None:
        payload = _base(service, mission_id, "decomposition")
        payload.update({"expected_plan_id": plan["plan_id"], "expected_plan_version": plan["plan_version"],
                        "expected_plan_sha256": plan["canonical_sha256"],
                        "expected_snapshot_id": snapshot["snapshot_id"],
                        "expected_snapshot_version": snapshot["snapshot_version"],
                        "expected_snapshot_sha256": snapshot["canonical_sha256"],
                        "tasks": _task_specs(scope_contract, required_subsystems, scope["canonical_sha256"])[0]})
        service.create_task_decomposition(mission_id, payload)
    decomposition = service.get_task_decomposition(mission_id)
    if service.repository.get_task_dependency_graph(mission_id) is None:
        _, edges = _task_specs(scope_contract, required_subsystems, scope["canonical_sha256"])
        payload = _base(service, mission_id, "graph")
        payload.update({"expected_plan_id": plan["plan_id"], "expected_plan_version": plan["plan_version"],
                        "expected_plan_sha256": plan["canonical_sha256"],
                        "expected_snapshot_id": snapshot["snapshot_id"],
                        "expected_snapshot_version": snapshot["snapshot_version"],
                        "expected_snapshot_sha256": snapshot["canonical_sha256"],
                        "expected_decomposition_id": decomposition["decomposition_id"],
                        "expected_decomposition_version": decomposition["decomposition_version"],
                        "expected_decomposition_sha256": decomposition["canonical_sha256"],
                        "expected_task_set_sha256": decomposition["task_set_sha256"],
                        "edges": edges})
        service.create_task_dependency_graph(mission_id, payload)
    graph = service.get_task_dependency_graph(mission_id)
    if service.repository.get_planner_invocation(mission_id) is None:
        tasks = service.repository.list_planned_tasks(mission_id)
        payload = _base(service, mission_id, "planner")
        payload.update({"expected_plan_id": plan["plan_id"], "expected_plan_version": plan["plan_version"],
                        "expected_plan_sha256": plan["canonical_sha256"],
                        "expected_snapshot_id": snapshot["snapshot_id"],
                        "expected_snapshot_version": snapshot["snapshot_version"],
                        "expected_snapshot_sha256": snapshot["canonical_sha256"],
                        "expected_decomposition_id": decomposition["decomposition_id"],
                        "expected_decomposition_version": decomposition["decomposition_version"],
                        "expected_decomposition_sha256": decomposition["canonical_sha256"],
                        "expected_task_set_sha256": decomposition["task_set_sha256"],
                        "expected_graph_id": graph["graph_id"], "expected_graph_version": graph["graph_version"],
                        "expected_graph_sha256": graph["canonical_sha256"],
                        "expected_node_set_sha256": graph["node_set_sha256"],
                        "expected_edge_set_sha256": graph["edge_set_sha256"],
                        "planner_profile": PLANNER_PROFILE_CANONICAL_DAG_V1})
        service.invoke_planner_and_generate_plan(mission_id, payload)
    generated = service.get_generated_plan(mission_id)
    if service.repository.get_plan_validation(mission_id) is None:
        payload = _base(service, mission_id, "validation")
        payload.update({"expected_generated_plan_id": generated["generated_plan_id"],
                        "expected_generated_plan_sha256": generated["canonical_sha256"]})
        service.validate_generated_plan_feasibility(mission_id, payload)
    validation = service.get_plan_validation(mission_id)
    return {"status": "completed", "mission_id": mission_id,
            "state": service.repository.get_state(mission_id)["state"],
            "plan_id": plan["plan_id"], "planned_task_count": decomposition["task_count"],
            "generated_plan_id": generated["generated_plan_id"],
            "validation_status": validation["validation_status"],
            "scope_targets_registered": scope_targets,
            "execution_authorized": False, "orchestration_started": False,
            "target_io_performed": False}


def sweep(service, recon_repository=None) -> None:
    """Retry PIP_BOUND planning work on the same durable worker cadence as AutoPIP."""
    ids = []
    for mission_state in ("PIP_BOUND", "PLANNING"):
        offset = 0
        while True:
            page = service.list_missions(state=mission_state, limit=100, offset=offset)
            ids.extend(row["mission_id"] for row in page["missions"])
            offset += len(page["missions"])
            if offset >= page["mission_count"] or not page["missions"]:
                break
    for mission_id in ids:
        try:
            plan_mission(service, mission_id, recon_repository)
        except Exception:
            logging.getLogger(__name__).exception("Autonomous planning deferred for %s", mission_id)
