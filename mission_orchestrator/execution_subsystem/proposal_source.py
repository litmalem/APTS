from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
from typing import Any
from mission_orchestrator.governance_binding import resource_in_canonical_scope

from pentest_subsystem.exploitation import ExploitationAgentRepository, EXPLOITATION_AGENT_ID
from pentest_subsystem.attack_path_planning import AttackPathPlanningAgentRepository
from pentest_subsystem.governance_contract import PENTEST_GOVERNANCE_EVALUATION_HASH_DOMAIN
from pentest_subsystem.governance_repository import PentestGovernanceRepository
from pentest_subsystem.lineage_repository import PentestLineageRepository
from pentest_subsystem.orchestration.orchestrator import AgenticPentestOrchestratorRepository
from pentest_subsystem.task_contract import verify_pentest_task_artifact, verify_pentest_task_binding
from pentest_subsystem.task_repository import PentestTaskRepository, default_pentest_repository_path
from pentest_subsystem.vulnerability_hypothesis import _assert_boundary_matches_task
from pentest_subsystem.reconnaissance import (
    RECON_ACTION_REQUEST_SCHEMA_VERSION, ReconnaissanceAgentRepository,
    normalize_recon_action_request,
)
from pentest_subsystem.enumeration import EnumerationAgentRepository
from pentest_subsystem.lifecycle_contract import build_lifecycle_state_projection
from pentest_subsystem.lineage_contract import verify_pentest_lineage_object
from pentest_subsystem.orchestration.task_graph import graph_node
from pentest_subsystem.capability_contract import (
    build_pentest_capability_registry_snapshot, verify_pentest_capability_registry_snapshot,
)

from .execution_contract import (
    ExecutionRequestIntegrityError, ExecutionSourceNotFound, ExecutionSourceRejected,
    ExecutionSourceUnavailable, REQUIRED_AUTHORIZATION_CHECKS, EXECUTION_REQUEST_SCHEMA_VERSION,
    build_canonical_action_envelope, canonical_execution_request_contract,
    deterministic_execution_id, normalize_execution_request_intake, seal_execution_request,
    sha256_hex, verify_integrity, WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
)


class PentestProposalSource:
    """Read an exact Stage-5.10 repository snapshot without initializing/migrating it.

    Connections use mode=ro and query_only. No Pentest repository instance is
    created, so reads cannot trigger a historical initializer or migration.
    """

    def __init__(self, sqlite_path: str | Path | None = None) -> None:
        self.sqlite_path = Path(sqlite_path).resolve() if sqlite_path else default_pentest_repository_path()

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.sqlite_path.as_uri() + "?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("BEGIN")
            return conn
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("Stage 5.10 Pentest proposal source is unavailable") from exc

    @staticmethod
    def _migration(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT migration_level FROM pentest_repository_meta WHERE repository_id=?",
            ("pentest-local-task-repository",),
        ).fetchone()
        if row is None or row[0] != 16:
            raise ExecutionSourceUnavailable("Stage 6.1 requires Pentest repository migration 16")
        return int(row[0])

    def migration_level(self) -> int:
        try:
            with closing(self._connect()) as conn:
                return self._migration(conn)
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("Pentest repository metadata is unreadable") from exc

    @staticmethod
    def _one(conn: sqlite3.Connection, table: str, key: str, value: str) -> sqlite3.Row:
        # table/key are internal constants; only values come from the intake.
        row = conn.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        if row is None:
            raise ExecutionSourceNotFound(f"unknown {key}: {value}")
        return row

    @classmethod
    def _lineage(cls, conn: sqlite3.Connection, record_id: str, kind: str,
                 task: dict[str, Any]) -> dict[str, Any]:
        row = cls._one(conn, "pentest_lineage_objects", "record_id", record_id)
        item = PentestLineageRepository._lineage_row(row)
        if item["record_type"] != kind or any(item[key] != task[key] for key in ("mission_id", "pentest_id", "pentest_task_id")):
            raise ExecutionRequestIntegrityError("lineage reference type or mission/task/pentest mismatch")
        return item["record"]

    def build_envelope(self, payload: Any) -> dict[str, Any]:
        intake = normalize_execution_request_intake(payload)
        try:
            with closing(self._connect()) as conn:
                self._migration(conn)
                return self._build(conn, intake)
        except (ExecutionSourceUnavailable, ExecutionSourceNotFound, ExecutionSourceRejected,
                ExecutionRequestIntegrityError):
            raise
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("Pentest proposal source could not be read") from exc
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("persisted Pentest proposal context failed verification") from exc

    def _build(self, conn: sqlite3.Connection, intake: dict[str, Any]) -> dict[str, Any]:
        if intake["schema_version"] == "apts-execution-request-intake-v2":
            return self._build_recon(conn, intake)
        if intake["schema_version"] == "apts-execution-request-intake-v3":
            return self._build_enumeration(conn, intake)
        if intake["schema_version"] == WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION:
            return self._build_wpt(intake)
        run_row = self._one(conn, "pentest_exploitation_runs", "exploitation_run_id", intake["exploitation_run_id"])
        run = ExploitationAgentRepository._exploitation_run_row(run_row)
        output = run["output"]
        if run["run_status"] != "COMPLETED":
            raise ExecutionSourceRejected("only completed specialist proposal runs can be used")
        for key in ("exploitation_run_id", "orchestration_id", "mission_id", "pentest_id",
                    "pentest_task_id", "agent_id", "validation_subtask_id", "exploitation_subtask_id"):
            if output[key] != run[key]:
                raise ExecutionRequestIntegrityError(f"persisted exploitation run column mismatch: {key}")
        bundle = run["evidence_bundle"]
        if (bundle["output_sha256"] != output["integrity"]["canonical_sha256"]
                or bundle["request_sha256"] != run["request_sha256"]
                or bundle["exploit_action_proposal_sha256"] != [x["integrity"]["canonical_sha256"] for x in output["exploit_action_proposals"]]
                or bundle["validation_task_sha256"] != [x["integrity"]["canonical_sha256"] for x in output["validation_tasks"]]):
            raise ExecutionRequestIntegrityError("specialist output/evidence-bundle binding mismatch")
        matches = [x for x in output["exploit_action_proposals"]
                   if x["exploit_action_proposal_id"] == intake["exploit_action_proposal_id"]]
        if len(matches) != 1:
            raise ExecutionSourceNotFound("proposal identity is absent or ambiguous in the selected run")
        proposal = matches[0]
        if proposal["integrity"]["canonical_sha256"] != intake["proposal_sha256"]:
            raise ExecutionRequestIntegrityError("proposal_sha256 does not match the stored proposal")
        if proposal["proposal_status"] == "BLOCKED_BY_SCOPE_ROE":
            raise ExecutionSourceRejected("a scope/RoE-blocked proposal cannot become an ExecutionRequest")
        if not proposal["stage6_handoff"]["execution_request_required"]:
            raise ExecutionSourceRejected("proposal does not request a Stage 6 handoff")
        path_row = self._one(conn, "pentest_attack_path_planning_runs", "attack_path_planning_run_id", run["attack_path_planning_run_id"])
        path_run = AttackPathPlanningAgentRepository._attack_path_run_row(path_row)
        if (path_run["output"]["integrity"]["canonical_sha256"] != run["attack_path_output_sha256"]
                or path_run["evidence_bundle"]["integrity"]["canonical_sha256"] != run["attack_path_evidence_bundle_sha256"]):
            raise ExecutionRequestIntegrityError("specialist predecessor attack-path binding mismatch")
        for key in ("mission_id", "pentest_id", "pentest_task_id", "orchestration_id"):
            if path_run[key] != run[key]:
                raise ExecutionRequestIntegrityError("cross-task attack-path predecessor is forbidden")
        paths = [x for x in path_run["output"]["candidate_paths"]
                 if x["attack_path_id"] == proposal["source_attack_path"]["attack_path_id"]]
        if (len(paths) != 1
                or paths[0]["integrity"]["canonical_sha256"] != proposal["source_attack_path"]["attack_path_sha256"]
                or paths[0]["target"] != proposal["target"]
                or paths[0]["provenance"]["supporting_evidence_refs"] != proposal["evidence_basis"]):
            raise ExecutionRequestIntegrityError("proposal attack-path/target/evidence binding mismatch")
        task_row = self._one(conn, "pentest_tasks", "pentest_task_id", run["pentest_task_id"])
        task_record = PentestTaskRepository._row_to_record(task_row)
        task, binding = task_record["task"], task_record["binding"]
        if (not verify_pentest_task_artifact(task) or not verify_pentest_task_binding(binding)
                or binding["task"] != task
                or task["integrity"]["canonical_sha256"] != task_row["task_contract_sha256"]
                or binding["integrity"]["canonical_sha256"] != task_row["task_binding_sha256"]):
            raise ExecutionRequestIntegrityError("Pentest task artifact/binding integrity mismatch")
        for key in ("pentest_task_id", "mission_id", "pentest_id", "upstream_task_id"):
            if task[key] != task_row[key]:
                raise ExecutionRequestIntegrityError(f"Pentest task column mismatch: {key}")
        for key in ("mission_id", "pentest_id", "pentest_task_id"):
            if run[key] != task[key] or proposal[key] != task[key]:
                raise ExecutionRequestIntegrityError("cross-mission/task/pentest proposal reference is forbidden")
        boundary = run["request"]["boundary"]
        _assert_boundary_matches_task(boundary, task)
        orch_row = self._one(conn, "pentest_agentic_orchestrations", "orchestration_id", run["orchestration_id"])
        orch = AgenticPentestOrchestratorRepository._orchestration_row(orch_row)
        if orch["orchestration_status"] in {"TERMINATED", "ESCALATED"}:
            raise ExecutionSourceRejected("terminated/escalated orchestrations cannot propose new execution requests")
        for key in ("mission_id", "pentest_id", "pentest_task_id", "upstream_task_id"):
            if orch[key] != task[key] or (key != "upstream_task_id" and orch["task_graph"][key] != task[key]):
                raise ExecutionRequestIntegrityError("orchestration graph lineage does not match the task")
        assignments = [x for x in orch["assignments"] if x["subtask_id"] == run["exploitation_subtask_id"]]
        if (len(assignments) != 1 or assignments[0]["agent_id"] != EXPLOITATION_AGENT_ID
                or assignments[0]["capability_id"] != proposal["capability_id"]
                or proposal["agent_id"] != assignments[0]["agent_id"]):
            raise ExecutionRequestIntegrityError("proposing agent does not own the persisted specialist subtask")
        assignment = assignments[0]
        node = next(x for x in orch["task_graph"]["nodes"] if x["subtask_id"] == assignment["subtask_id"])
        if node["status"] != "SUCCEEDED":
            raise ExecutionSourceRejected("specialist proposal preparation has not succeeded")
        validations = [x for x in output["validation_tasks"]
                       if x["validation_task_id"] == proposal["validation_task"]["validation_task_id"]]
        if len(validations) != 1:
            raise ExecutionRequestIntegrityError("proposal validation-task binding is missing or ambiguous")
        validation = validations[0]
        if validation["integrity"]["canonical_sha256"] != proposal["validation_task"]["validation_task_sha256"]:
            raise ExecutionRequestIntegrityError("proposal validation-task hash mismatch")
        for key in ("mission_id", "pentest_id", "pentest_task_id", "target", "technique", "evidence_basis", "governance"):
            if validation[key] != proposal[key]:
                raise ExecutionRequestIntegrityError(f"validation task/proposal mismatch: {key}")
        decisions = {}
        for capability in ("validation", "exploitation"):
            did = proposal["governance"][capability + "_decision_id"]
            row = self._one(conn, "pentest_scope_roe_decisions", "decision_id", did)
            stored = PentestGovernanceRepository._row(row)
            decision, evaluation = stored["decision"], stored["request"]
            if not verify_integrity(evaluation, PENTEST_GOVERNANCE_EVALUATION_HASH_DOMAIN):
                raise ExecutionRequestIntegrityError("stored governance evaluation integrity mismatch")
            if (decision["request_sha256"] != evaluation["integrity"]["canonical_sha256"]
                    or decision["status"] != proposal["governance"][capability + "_status"]
                    or decision["capability_id"] != capability
                    or evaluation["capability_id"] != capability
                    or evaluation["boundary"] != boundary):
                raise ExecutionRequestIntegrityError("proposal governance decision binding mismatch")
            for key in ("mission_id", "pentest_id", "pentest_task_id"):
                if decision[key] != task[key] or row[key] != task[key]:
                    raise ExecutionRequestIntegrityError("cross-task governance decision is forbidden")
            if (evaluation["pentest_task_id"] != task["pentest_task_id"]
                    or evaluation["target"] != proposal["target"]
                    or evaluation["action_class"] != proposal["action_class"]
                    or evaluation["technique"] != proposal["technique"]):
                raise ExecutionRequestIntegrityError("governance evaluated a different proposed action")
            if decision["status"] not in {"ELIGIBLE", "REVIEW_REQUIRED"}:
                raise ExecutionSourceRejected("local governance rejected the proposed action")
            if decision["semantics"]["decision_is_authorization"] is not False:
                raise ExecutionRequestIntegrityError("local governance cannot mint execution authorization")
            decisions[capability] = decision
        action_record = self._lineage(conn, proposal["lineage"]["action_proposal_ref"], "ACTION_PROPOSAL", task)
        if (action_record["integrity"]["canonical_sha256"] != proposal["lineage"]["action_proposal_sha256"]
                or action_record["provenance"]["source_id"] != run["exploitation_run_id"]
                or action_record["provenance"]["actor_id"] != assignment["agent_id"]):
            raise ExecutionRequestIntegrityError("action-proposal lineage hash/agent/run mismatch")
        for key in ("target", "technique", "action_class", "capability_id"):
            if action_record["data"][key] != proposal[key]:
                raise ExecutionRequestIntegrityError("lineage action differs from the selected proposal")
        if action_record["data"]["governance_decision_ref"] != decisions["exploitation"]["decision_id"]:
            raise ExecutionRequestIntegrityError("action lineage governance reference mismatch")
        hypothesis = self._lineage(conn, proposal["source_attack_path"]["hypothesis_ref"], "HYPOTHESIS", task)
        parent = action_record["parent_reference"]
        if (parent["reference_type"] != "HYPOTHESIS"
                or parent["reference_id"] != hypothesis["identity"]["record_id"]
                or parent["reference_sha256"] != hypothesis["integrity"]["canonical_sha256"]):
            raise ExecutionRequestIntegrityError("action proposal hypothesis parent mismatch")
        evidence_basis = []
        for evidence_id in proposal["evidence_basis"]:
            evidence = self._lineage(conn, evidence_id, "EVIDENCE", task)
            evidence_basis.append({"evidence_id": evidence_id,
                                   "canonical_sha256": evidence["integrity"]["canonical_sha256"]})
        policy = task["authorization_reference"]
        review_required = any(x["status"] == "REVIEW_REQUIRED" for x in decisions.values())
        expected_proposal_status = "AWAITING_HUMAN_REVIEW" if review_required else "ELIGIBLE_FOR_EXTERNAL_AUTHORIZATION"
        if proposal["proposal_status"] != expected_proposal_status:
            raise ExecutionRequestIntegrityError("proposal review state does not match local governance")
        request = seal_execution_request({
            "schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
            "execution_id": deterministic_execution_id(task["mission_id"], task["upstream_task_id"], task["pentest_id"], intake["idempotency_key"]),
            "mission_id": task["mission_id"], "task_id": task["upstream_task_id"], "pentest_id": task["pentest_id"],
            "proposing_agent": {key: assignment[key] for key in ("agent_id", "role", "orchestration_id", "subtask_id")},
            "action": {key: proposal[key] for key in ("action_class", "capability_id", "technique")},
            "target": deepcopy(proposal["target"]),
            "parameters": {key: deepcopy(validation[key]) for key in ("validation_task_id", "expected_evidence", "estimated_impact")},
            "evidence_basis": evidence_basis,
            "authorization_requirement": {
                "authority": "EXTERNAL_APTS_GSS", "revalidation_required": True,
                "required_checks": list(REQUIRED_AUTHORIZATION_CHECKS), "human_review_required": review_required,
                "policy_reference": {"policy_decision_id": policy["policy_decision_id"],
                                     "policy_decision_hash": policy["policy_decision_hash"],
                                     "policy_version": policy["policy_version"], "reference_sha256": sha256_hex(policy)},
            },
        })
        source_binding = {
            "pentest_task_id": task["pentest_task_id"],
            "task_artifact_sha256": task["integrity"]["canonical_sha256"],
            "task_binding_sha256": binding["integrity"]["canonical_sha256"],
            "source_run_output_sha256": output["integrity"]["canonical_sha256"],
            "source_run_evidence_bundle_sha256": run["evidence_bundle"]["integrity"]["canonical_sha256"],
            "action_proposal_ref": action_record["identity"]["record_id"],
            "action_proposal_sha256": action_record["integrity"]["canonical_sha256"],
            "orchestration_graph_sha256": orch["task_graph_sha256"],
            "scope_sha256": sha256_hex({"bound_scope": boundary["scope"], "local_scope": task["scope"]}),
            "roe_sha256": sha256_hex(boundary["roe"]), "constraints_sha256": sha256_hex(task["constraints"]),
            "policy_reference_sha256": sha256_hex(policy),
            "validation_decision_sha256": decisions["validation"]["integrity"]["canonical_sha256"],
            "exploitation_decision_sha256": decisions["exploitation"]["integrity"]["canonical_sha256"],
            "stage5_closure_contract_sha256": canonical_execution_request_contract()["predecessor"]["contract_sha256"],
        }
        return build_canonical_action_envelope(intake=intake, request=request, source_binding=source_binding)

    def _build_enumeration(self, conn: sqlite3.Connection, intake: dict[str, Any]) -> dict[str, Any]:
        """Build the sole Stage-5.3 active handoff from an immutable persisted proposal."""
        row = self._one(conn, "pentest_enumeration_runs", "enumeration_run_id", intake["enumeration_run_id"])
        run = EnumerationAgentRepository._enumeration_run_row(row)
        if run["run_status"] != "COMPLETED" or run["enumeration_run_id"] != intake["enumeration_run_id"]:
            raise ExecutionSourceRejected("only a completed Stage 5.3 Enumeration run can enter Stage 6")
        output, bundle = run["output"], run["evidence_bundle"]
        if (output["enumeration_run_id"] != run["enumeration_run_id"]
                or output["orchestration_id"] != run["orchestration_id"]
                or output["mission_id"] != run["mission_id"]
                or output["pentest_task_id"] != run["pentest_task_id"]
                or bundle["output_sha256"] != output["integrity"]["canonical_sha256"]
                or bundle["enumeration_run_id"] != run["enumeration_run_id"]):
            raise ExecutionRequestIntegrityError("Enumeration output/evidence bundle lineage mismatch")
        matches = [item for item in output["action_proposals"]
                   if item.get("action_proposal_ref") == intake["enumeration_proposal_ref"]]
        if len(matches) != 1:
            raise ExecutionSourceNotFound("Enumeration proposal is absent or ambiguous in its persisted run")
        action = matches[0]
        if action.get("action_proposal_sha256") != intake["proposal_sha256"]:
            raise ExecutionRequestIntegrityError("Enumeration proposal hash does not match the persisted proposal")
        # No semantic aliasing: only the exact Stage-6.4 registered primitive is executable.
        if action.get("technique") != "TCP_BANNER_READ":
            raise ExecutionSourceRejected("Stage 13 enables only an explicit TCP_BANNER_READ proposal")
        if action.get("execution_status") != "DEFERRED_TO_STAGE6":
            raise ExecutionSourceRejected("Enumeration proposal is not explicitly deferred to Stage 6")

        task_row = self._one(conn, "pentest_tasks", "pentest_task_id", run["pentest_task_id"])
        task_record = PentestTaskRepository._row_to_record(task_row)
        task, task_binding = task_record["task"], task_record["binding"]
        if (not verify_pentest_task_artifact(task) or not verify_pentest_task_binding(task_binding)
                or task_binding["task"] != task
                or task["integrity"]["canonical_sha256"] != task_row["task_contract_sha256"]
                or task_binding["integrity"]["canonical_sha256"] != task_row["task_binding_sha256"]
                or any(task[key] != run[key] for key in ("mission_id", "pentest_id", "pentest_task_id"))):
            raise ExecutionRequestIntegrityError("Enumeration task artifact or run binding failed verification")
        boundary = run["request"]["boundary"]
        _assert_boundary_matches_task(boundary, task)
        if ("TARGET_RECON" not in boundary["roe"].get("allowed_action_classes", [])
                or "TCP_BANNER_READ" not in boundary["roe"].get("allowed_techniques", [])
                or int(boundary["roe"].get("maximum_concurrency", 0)) < 1
                or int(boundary["constraints"].get("resource_budget", {}).get("max_network_requests", 0)) < 1):
            raise ExecutionSourceRejected("Enumeration intake requires explicit TCP_BANNER_READ RoE and a positive network budget")
        target = action["target"]
        if target.get("target_type") not in {"URL", "IP", "HOST", "DOMAIN"}:
            raise ExecutionSourceRejected("TCP_BANNER_READ target type is not supported by the fixed adapter")
        if not resource_in_canonical_scope(boundary, target["target_value"])[0] or not resource_in_canonical_scope(task, target["target_value"])[0]:
            raise ExecutionSourceRejected("Enumeration target is outside the current Mission/Pentest scope")

        orch_row = self._one(conn, "pentest_agentic_orchestrations", "orchestration_id", run["orchestration_id"])
        orch = AgenticPentestOrchestratorRepository._orchestration_row(orch_row)
        if (orch["orchestration_status"] != "ACTIVE" or orch["mission_id"] != run["mission_id"]
                or orch["pentest_id"] != run["pentest_id"] or orch["pentest_task_id"] != run["pentest_task_id"]):
            raise ExecutionSourceRejected("Enumeration orchestration is inactive or its task binding changed")
        node = graph_node(orch["task_graph"], run["subtask_id"])
        if (node is None or node.get("capability_id") != "enumeration"
                or node.get("specialist", {}).get("agent_id") != run["agent_id"]
                or node.get("status") != "SUCCEEDED" or run["agent_id"] != "PENTEST_ENUMERATION_AGENT"):
            raise ExecutionSourceRejected("persisted Enumeration proposal is not owned by a succeeded Stage-5.3 subtask")

        proposal = self._lineage(conn, action["action_proposal_ref"], "ACTION_PROPOSAL", task)
        if (not verify_pentest_lineage_object(proposal)
                or proposal["integrity"]["canonical_sha256"] != action["action_proposal_sha256"]
                or proposal["provenance"]["source_id"] != run["enumeration_run_id"]
                or proposal["provenance"]["actor_id"] != run["agent_id"]
                or proposal["data"].get("target") != target
                or proposal["data"].get("technique") != "TCP_BANNER_READ"
                or proposal["data"].get("capability_id") != "enumeration"
                or proposal["data"].get("action_class") != "TARGET_RECON"
                or proposal["provenance"]["metadata"].get("execution_deferred_to_stage6") is not True):
            raise ExecutionRequestIntegrityError("Enumeration ACTION_PROPOSAL lineage/hash/target mismatch")
        decisions = self._one(conn, "pentest_scope_roe_decisions", "decision_id", action["governance_decision_ref"])
        stored_decision = PentestGovernanceRepository._row(decisions)
        decision, evaluation = stored_decision["decision"], stored_decision["request"]
        if (not verify_integrity(evaluation, PENTEST_GOVERNANCE_EVALUATION_HASH_DOMAIN)
                or decision["status"] != "ELIGIBLE" or decision["capability_id"] != "enumeration"
                or decision["semantics"]["decision_is_authorization"] is not False
                or evaluation["boundary"] != boundary or evaluation["target"] != target
                or evaluation["technique"] != "TCP_BANNER_READ"
                or evaluation["action_class"] != "TARGET_RECON"
                or decision["request_sha256"] != evaluation["integrity"]["canonical_sha256"]
                or any(decision[key] != task[key] for key in ("mission_id", "pentest_id", "pentest_task_id"))):
            raise ExecutionSourceRejected("Stage-4.8 Enumeration eligibility is absent, stale, or does not authorize this exact action")
        impact = evaluation["estimated_impact"]
        rate_cost = evaluation["rate_cost"]
        active_concurrency = evaluation["active_concurrency"]
        budget = boundary["constraints"].get("resource_budget", {}).get("max_network_requests", 0)
        if (impact not in {"NONE", "LOW"} or rate_cost != 1 or active_concurrency != 1
                or rate_cost > int(budget) or active_concurrency > int(boundary["roe"].get("maximum_concurrency", 0))):
            raise ExecutionSourceRejected("TCP_BANNER_READ proposal exceeds the Stage 13 one-request/one-worker budget")
        evidence_basis = []
        for item in bundle["lineage_items"]:
            if item.get("scope_status") != "IN_LOCAL_TASK_SCOPE":
                continue
            evidence = self._lineage(conn, item["evidence_ref"], "EVIDENCE", task)
            if evidence["integrity"]["canonical_sha256"] != item["evidence_sha256"]:
                raise ExecutionRequestIntegrityError("Enumeration evidence lineage hash mismatch")
            evidence_basis.append({"evidence_id": item["evidence_ref"],
                                  "canonical_sha256": item["evidence_sha256"]})
        if not evidence_basis:
            raise ExecutionSourceRejected("Enumeration proposal has no verified source evidence")
        policy = task["authorization_reference"]
        request = seal_execution_request({
            "schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
            "execution_id": deterministic_execution_id(task["mission_id"], task["upstream_task_id"],
                                                       task["pentest_id"], intake["idempotency_key"]),
            "mission_id": task["mission_id"], "task_id": task["upstream_task_id"],
            "pentest_id": task["pentest_id"],
            "proposing_agent": {"agent_id": run["agent_id"], "role": "ENUMERATION",
                "orchestration_id": run["orchestration_id"], "subtask_id": run["subtask_id"]},
            "action": {"action_class": "TARGET_RECON", "capability_id": "enumeration",
                       "technique": "TCP_BANNER_READ"},
            "target": target,
            "parameters": {"source_proposal_id": action["action_proposal_ref"],
                "expected_evidence": ["bounded TCP banner response digest", "connected peer address"],
                "estimated_impact": impact},
            "evidence_basis": evidence_basis,
            "authorization_requirement": {"authority": "EXTERNAL_APTS_GSS", "revalidation_required": True,
                "required_checks": list(REQUIRED_AUTHORIZATION_CHECKS), "human_review_required": False,
                "policy_reference": {"policy_decision_id": policy["policy_decision_id"],
                    "policy_decision_hash": policy["policy_decision_hash"], "policy_version": policy["policy_version"],
                    "reference_sha256": sha256_hex(policy)}}})
        return build_canonical_action_envelope(intake=intake, request=request, source_binding={
            "pentest_task_id": task_record["pentest_task_id"],
            "task_artifact_sha256": task["integrity"]["canonical_sha256"],
            "task_binding_sha256": task_binding["integrity"]["canonical_sha256"],
            "source_run_output_sha256": output["integrity"]["canonical_sha256"],
            "source_run_evidence_bundle_sha256": bundle["integrity"]["canonical_sha256"],
            "action_proposal_ref": action["action_proposal_ref"],
            "action_proposal_sha256": action["action_proposal_sha256"],
            "orchestration_graph_sha256": orch["task_graph_sha256"],
            "scope_sha256": sha256_hex({"bound_scope": boundary["scope"], "local_scope": task["scope"]}),
            "roe_sha256": sha256_hex(boundary["roe"]), "constraints_sha256": sha256_hex(task["constraints"]),
            "policy_reference_sha256": sha256_hex(policy),
            "validation_decision_sha256": sha256_hex({"source": "STAGE5_3_ENUMERATION", "decision": decision["decision_id"]}),
            "exploitation_decision_sha256": sha256_hex({"source": "STAGE5_3_ENUMERATION", "decision": "NOT_APPLICABLE"}),
            "stage5_closure_contract_sha256": canonical_execution_request_contract()["predecessor"]["contract_sha256"]})

    def _build_wpt(self, intake: dict[str, Any]) -> dict[str, Any]:
        """Build a canonical Stage 6.1 request from one sealed, current WPT intake."""
        from .wpt_intake_repository import default_wpt_intake_path, _verify
        from .wpt_intake_source import WPTIntakeAuthoritySource

        path = default_wpt_intake_path()
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                row = db.execute("SELECT * FROM wpt_governed_intakes WHERE intake_id=?", (intake["wpt_intake_id"],)).fetchone()
                if row is None:
                    raise ExecutionSourceNotFound("WPT intake is unavailable")
                record = json.loads(row["record_json"])
        except (ExecutionSourceNotFound, ExecutionRequestIntegrityError):
            raise
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ExecutionSourceUnavailable("WPT intake source is unavailable or unreadable") from exc
        if (not _verify(record) or record["integrity"]["canonical_sha256"] != row["record_sha256"]
                or record["intake"]["intake_id"] != intake["wpt_intake_id"]
                or record["integrity"]["canonical_sha256"] != intake["wpt_intake_sha256"]
                or record["intake"]["idempotency_key"] != intake["idempotency_key"]):
            raise ExecutionRequestIntegrityError("WPT intake record identity or seal mismatch")
        wpt = record["intake"]
        if wpt["profile"] not in {"fingerprinting", "enumeration"}:
            raise ExecutionSourceRejected("Unsupported WPT execution profile")
        authority = WPTIntakeAuthoritySource().resolve(wpt)
        if (authority["execution_status"] != "EXECUTABLE"
                or authority["task_lifecycle_state"] != "RUNNING"
                or authority["orchestration_status"] != "ACTIVE"):
            raise ExecutionSourceRejected("WPT intake no longer satisfies executable task authority")
        policy = authority["authorization_policy_reference"]
        action = authority["action"]
        task = authority["current_task"]
        boundary = authority["current_boundary"]
        proposal_ref = "actp-wpt-" + intake["wpt_intake_sha256"][:32]
        evidence_id = "evi-wpt-" + intake["wpt_intake_sha256"][:32]
        request = seal_execution_request({
            "schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
            "execution_id": deterministic_execution_id(wpt["mission_id"], wpt["task_id"],
                                                       authority["pentest_id"], intake["idempotency_key"]),
            "mission_id": wpt["mission_id"], "task_id": wpt["task_id"],
            "pentest_id": authority["pentest_id"],
            "proposing_agent": {"agent_id": "PENTEST_WPT_ENUMERATION_AGENT" if wpt["profile"] == "enumeration" else "PENTEST_WPT_FINGERPRINTING_AGENT", "role": "ENUMERATION" if wpt["profile"] == "enumeration" else "RECONNAISSANCE",
                                "orchestration_id": authority["orchestration_id"],
                                "subtask_id": "wpt-intake-" + intake["wpt_intake_sha256"][:24]},
            "action": action, "target": wpt["target"],
            "parameters": {"source_wpt_intake_id": wpt["intake_id"],
                "expected_evidence": ["bounded WPT " + wpt["profile"] + " observations", "sealed Stage 6 result"],
                "estimated_impact": "LOW"},
            "evidence_basis": [{"evidence_id": evidence_id, "canonical_sha256": intake["wpt_intake_sha256"]}],
            "authorization_requirement": {"authority": "EXTERNAL_APTS_GSS", "revalidation_required": True,
                "required_checks": list(REQUIRED_AUTHORIZATION_CHECKS), "human_review_required": False,
                "policy_reference": {"policy_decision_id": policy["policy_decision_id"],
                    "policy_decision_hash": policy["policy_decision_hash"], "policy_version": policy["policy_version"],
                    "reference_sha256": sha256_hex(policy)}}})
        source_binding = {
            "pentest_task_id": authority["pentest_task_id"],
            "task_artifact_sha256": authority["task_artifact_sha256"],
            "task_binding_sha256": authority["task_binding_sha256"],
            "source_run_output_sha256": intake["wpt_intake_sha256"],
            "source_run_evidence_bundle_sha256": intake["wpt_intake_sha256"],
            "action_proposal_ref": proposal_ref, "action_proposal_sha256": intake["wpt_intake_sha256"],
            "orchestration_graph_sha256": authority["orchestration_graph_sha256"],
            "scope_sha256": sha256_hex({"mission_scope_sha256": authority["mission_scope_sha256"],
                                         "task_scope": task["scope"]}),
            "roe_sha256": sha256_hex(boundary["roe"]),
            "constraints_sha256": sha256_hex(task["constraints"]),
            "policy_reference_sha256": sha256_hex(policy),
            "validation_decision_sha256": sha256_hex({"source_type": "WPT_GOVERNED_INTAKE",
                                                       "intake_sha256": intake["wpt_intake_sha256"]}),
            "exploitation_decision_sha256": sha256_hex({"source_type": "WPT_GOVERNED_INTAKE",
                                                         "decision": "NOT_APPLICABLE"}),
            "stage5_closure_contract_sha256": canonical_execution_request_contract()["predecessor"]["contract_sha256"]}
        return build_canonical_action_envelope(intake=intake, request=request, source_binding=source_binding)

    def _build_recon(self, conn: sqlite3.Connection, intake: dict[str, Any]) -> dict[str, Any]:
        """Build a Stage 6.1 envelope from a persisted, lifecycle-bound Stage 5.2 request."""
        row = self._one(conn, "pentest_recon_runs", "recon_run_id",
                        self._recon_run_id_for_action(conn, intake["recon_action_id"]))
        run = ReconnaissanceAgentRepository._run_row(row)
        if run["run_status"] != "COMPLETED":
            raise ExecutionSourceRejected("only a completed Stage 5.2 Recon run can be a Stage 6.1 source")
        requests = [item for item in run["output"].get("action_requests", [])
                    if item.get("action_id") == intake["recon_action_id"]]
        if len(requests) != 1:
            raise ExecutionSourceNotFound("Recon Action Request is absent or ambiguous in its persisted run")
        action_request = normalize_recon_action_request(requests[0])
        if action_request["schema_version"] != RECON_ACTION_REQUEST_SCHEMA_VERSION:
            raise ExecutionSourceRejected("unsupported Recon Action Request schema version")
        if action_request["technique"] != "TCP_CONNECT_SCAN":
            raise ExecutionSourceRejected("Recon intake requires an explicit registered active technique")
        if action_request["integrity"]["canonical_sha256"] != intake["recon_request_sha256"]:
            raise ExecutionRequestIntegrityError("Recon Action Request hash does not match the persisted request")
        for key, actual in (("recon_run_id", run["recon_run_id"]),
                            ("orchestration_id", run["orchestration_id"]),
                            ("task_id", run["pentest_task_id"]),
                            ("mission_id", run["mission_id"]), ("pentest_id", run["pentest_id"]),
                            ("subtask_id", run["subtask_id"]), ("agent_id", run["agent_id"])):
            if action_request[key] != actual:
                raise ExecutionRequestIntegrityError(f"Recon Action Request run binding mismatch: {key}")

        task_row = self._one(conn, "pentest_tasks", "pentest_task_id", run["pentest_task_id"])
        task_record = PentestTaskRepository._row_to_record(task_row)
        task, binding = task_record["task"], task_record["binding"]
        if (not verify_pentest_task_artifact(task) or not verify_pentest_task_binding(binding)
                or binding["task"] != task
                or task["integrity"]["canonical_sha256"] != task_row["task_contract_sha256"]
                or binding["integrity"]["canonical_sha256"] != task_row["task_binding_sha256"]):
            raise ExecutionRequestIntegrityError("Recon source task artifact/binding integrity mismatch")
        if any(task[key] != run[key] for key in ("mission_id", "pentest_id", "pentest_task_id")):
            raise ExecutionRequestIntegrityError("Recon source task/run identity mismatch")
        if task["upstream_task_id"] != task_record["upstream_task_id"]:
            raise ExecutionRequestIntegrityError("Recon source global task binding mismatch")
        _assert_boundary_matches_task(run["request"]["boundary"], task)
        boundary = run["request"]["boundary"]
        if (sha256_hex(boundary["roe"]) != action_request["binding"]["roe_sha256"]
                or "TCP_CONNECT_SCAN" not in boundary["roe"].get("allowed_techniques", [])
                or "TARGET_RECON" not in boundary["roe"].get("allowed_action_classes", [])
                or int(boundary["roe"].get("maximum_concurrency", 0)) < 1
                or int(boundary["constraints"].get("resource_budget", {}).get("max_network_requests", 0)) < 1):
            raise ExecutionSourceRejected("Recon intake is not bound to the current explicit TCP_CONNECT_SCAN RoE and budget")

        orch_row = self._one(conn, "pentest_agentic_orchestrations", "orchestration_id", run["orchestration_id"])
        orch = AgenticPentestOrchestratorRepository._orchestration_row(orch_row)
        graph_snapshot_sha = action_request["binding"]["orchestration_graph_sha256"]
        if (orch["orchestration_status"] != "ACTIVE" or orch["pentest_task_id"] != task["pentest_task_id"]
                or orch["mission_id"] != task["mission_id"] or orch["pentest_id"] != task["pentest_id"]):
            raise ExecutionSourceRejected("Recon orchestration is inactive or its task/graph binding changed")
        node = graph_node(orch["task_graph"], action_request["subtask_id"])
        if (node is None or node.get("capability_id") != action_request["capability_id"]
                or node.get("specialist", {}).get("agent_id") != action_request["agent_id"]
                or node.get("status") not in {"READY", "RUNNING", "SUCCEEDED"}):
            raise ExecutionRequestIntegrityError("Recon Action Request no longer matches its assigned orchestration node")
        lifecycle_row = conn.execute("SELECT * FROM pentest_task_lifecycle WHERE pentest_task_id=?",
                                     (task["pentest_task_id"],)).fetchone()
        if lifecycle_row is None:
            raise ExecutionSourceRejected("current Pentest lifecycle is unavailable for Recon intake")
        lifecycle = build_lifecycle_state_projection(dict(lifecycle_row))
        if lifecycle["state"] != "RUNNING":
            raise ExecutionSourceRejected("Recon Action Request requires the current Pentest lifecycle to remain RUNNING")

        current_hashes = {
            "task_contract_sha256": task_record["task_contract_sha256"],
            "scope_sha256": sha256_hex(task["scope"]),
            "constraints_sha256": sha256_hex(task["constraints"]),
            "roe_sha256": sha256_hex(boundary["roe"]),
            "authorization_reference_sha256": sha256_hex(task["authorization_reference"]),
        }
        for key, value in current_hashes.items():
            if action_request["binding"][key] != value:
                raise ExecutionSourceRejected(f"Recon Action Request snapshot is stale: {key}")
        registry = build_pentest_capability_registry_snapshot()
        if (not verify_pentest_capability_registry_snapshot(registry)
                or registry["integrity"]["canonical_sha256"] != action_request["binding"]["capability_registry_sha256"]):
            raise ExecutionSourceRejected("Recon capability registry snapshot is stale")
        proposal = self._lineage(conn, action_request["proposal_ref"], "ACTION_PROPOSAL", task)
        if (not verify_pentest_lineage_object(proposal)
                or proposal["integrity"]["canonical_sha256"] != action_request["input_sha256"]
                or proposal["provenance"]["source_id"] != run["recon_run_id"]
                or proposal["provenance"]["actor_id"] != action_request["agent_id"]
                or proposal["data"]["target"] != {"target_type": action_request["target_ref"]["target_type"],
                                                   "target_value": action_request["target_ref"]["target_value"]}
                or proposal["data"]["capability_id"] != action_request["capability_id"]
                or proposal["data"]["technique"] != action_request["technique"]):
            raise ExecutionRequestIntegrityError("Recon Action Request proposal lineage binding mismatch")
        if (proposal["provenance"]["metadata"].get("proposal_lifecycle_status") != "AWAITING_STAGE6_INTAKE"
                or proposal["provenance"]["metadata"].get("execution_deferred_to_stage6") is not True):
            raise ExecutionSourceRejected("Recon proposal is not eligible for Stage 6 intake")

        action_proposals = [p for p in run["output"].get("action_proposals", [])
                            if p.get("action_proposal_ref") == action_request["proposal_ref"]]
        if len(action_proposals) != 1:
            raise ExecutionRequestIntegrityError("Recon proposal is absent or ambiguous in run output")
        proposal_output = action_proposals[0]
        evidence_basis = []
        source_refs = {item["source_observation_id"]: item for item in run["evidence_bundle"]["lineage_items"]}
        for observation_id in proposal_output.get("supporting_observation_ids", []):
            item = source_refs.get(observation_id)
            if item:
                evidence = self._lineage(conn, item["evidence_ref"], "EVIDENCE", task)
                if evidence["integrity"]["canonical_sha256"] != item["evidence_sha256"]:
                    raise ExecutionRequestIntegrityError("Recon evidence lineage hash mismatch")
                evidence_basis.append({"evidence_id": item["evidence_ref"],
                                       "canonical_sha256": item["evidence_sha256"]})
        if not evidence_basis:
            raise ExecutionSourceRejected("Recon proposal has no verified evidence basis")
        impacts = {"NONE": "NONE", "LOW": "LOW", "MODERATE": "MODERATE",
                   "HIGH": "HIGH", "DESTRUCTIVE": "DESTRUCTIVE"}
        impact = impacts.get(proposal_output["estimated_impact"])
        if impact is None:
            raise ExecutionSourceRejected("Recon proposal impact is unsupported by Stage 6.1")
        policy = task["authorization_reference"]
        action_id = action_request["action_id"]
        request = seal_execution_request({
            "schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
            "execution_id": deterministic_execution_id(task["mission_id"], task["upstream_task_id"],
                                                       task["pentest_id"], intake["idempotency_key"]),
            "mission_id": task["mission_id"], "task_id": task["upstream_task_id"], "pentest_id": task["pentest_id"],
            "proposing_agent": {"agent_id": action_request["agent_id"], "role": "RECONNAISSANCE",
                                "orchestration_id": action_request["orchestration_id"],
                                "subtask_id": action_request["subtask_id"]},
            "action": {"action_class": "TARGET_RECON", "capability_id": action_request["capability_id"],
                       "technique": action_request["technique"]},
            "target": {"target_type": action_request["target_ref"]["target_type"],
                       "target_value": action_request["target_ref"]["target_value"]},
            "parameters": {"source_action_id": action_id,
                           "expected_evidence": action_request["expected_evidence"],
                           "estimated_impact": impact},
            "evidence_basis": evidence_basis,
            "authorization_requirement": {"authority": "EXTERNAL_APTS_GSS", "revalidation_required": True,
                "required_checks": list(REQUIRED_AUTHORIZATION_CHECKS), "human_review_required": False,
                "policy_reference": {"policy_decision_id": policy["policy_decision_id"],
                    "policy_decision_hash": policy["policy_decision_hash"], "policy_version": policy["policy_version"],
                    "reference_sha256": sha256_hex(policy)}},
        })
        source_binding = {
            "pentest_task_id": task["pentest_task_id"],
            "task_artifact_sha256": task["integrity"]["canonical_sha256"],
            "task_binding_sha256": binding["integrity"]["canonical_sha256"],
            "source_run_output_sha256": run["output"]["integrity"]["canonical_sha256"],
            "source_run_evidence_bundle_sha256": run["evidence_bundle"]["integrity"]["canonical_sha256"],
            "action_proposal_ref": proposal["identity"]["record_id"],
            "action_proposal_sha256": proposal["integrity"]["canonical_sha256"],
            "orchestration_graph_sha256": graph_snapshot_sha,
            "scope_sha256": current_hashes["scope_sha256"],
            "roe_sha256": sha256_hex(run["request"]["boundary"]["roe"]),
            "constraints_sha256": current_hashes["constraints_sha256"],
            "policy_reference_sha256": sha256_hex(policy),
            "validation_decision_sha256": sha256_hex({"source": "STAGE5_2_RECON", "decision": proposal_output["governance_decision_ref"]}),
            "exploitation_decision_sha256": sha256_hex({"source": "STAGE5_2_RECON", "decision": "NOT_APPLICABLE"}),
            "stage5_closure_contract_sha256": canonical_execution_request_contract()["predecessor"]["contract_sha256"],
        }
        return build_canonical_action_envelope(intake=intake, request=request, source_binding=source_binding)

    @staticmethod
    def _recon_run_id_for_action(conn: sqlite3.Connection, action_id: str) -> str:
        rows = conn.execute("SELECT recon_run_id FROM pentest_recon_runs ORDER BY recon_run_id").fetchall()
        matches = []
        for row in rows:
            run = ReconnaissanceAgentRepository._run_row(
                PentestProposalSource._one(conn, "pentest_recon_runs", "recon_run_id", row["recon_run_id"]))
            if any(x.get("action_id") == action_id for x in run["output"].get("action_requests", [])):
                matches.append(run["recon_run_id"])
        if len(matches) != 1:
            raise ExecutionSourceNotFound("Recon Action Request is absent or not uniquely stored")
        return matches[0]
