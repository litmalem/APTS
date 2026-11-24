"""Verified historical Pentest snapshots; never authorize or mutate upstream state."""
from __future__ import annotations

from contextlib import closing
import sqlite3

from pentest_subsystem.attack_path_planning import (AttackPathPlanningAgentRepository,
    verify_attack_path_planning_output, verify_attack_path_planning_evidence_bundle)
from pentest_subsystem.exploitation import (ExploitationAgentRepository,
    exploitation_run_request_sha256, verify_exploitation_output, verify_exploitation_evidence_bundle)
from pentest_subsystem.lineage_contract import verify_pentest_lineage_object
from pentest_subsystem.task_contract import verify_pentest_task_artifact, verify_pentest_task_binding
from pentest_subsystem.task_repository import PentestTaskRepository

from .execution_contract import (ExecutionRequestIntegrityError, ExecutionSourceUnavailable,
    ExecutionSourceRejected, verify_canonical_action_envelope, verify_integrity, with_integrity)
from .proposal_source import PentestProposalSource

SOURCE_DOMAIN = "APTS_VEP_PENTEST_SOURCE_SNAPSHOT_V1"
SOURCE_FIELDS = {"schema_version", "request", "output", "evidence_bundle", "path_output",
    "path_evidence_bundle", "task", "binding", "hypothesis", "action_proposal", "evidence_basis", "integrity"}


def selected(value, envelope):
    proposal = next(p for p in value["output"]["exploit_action_proposals"]
        if p["exploit_action_proposal_id"] == envelope["intake"]["exploit_action_proposal_id"])
    validation = next(v for v in value["output"]["validation_tasks"]
        if v["validation_task_id"] == proposal["validation_task"]["validation_task_id"])
    path = next(p for p in value["path_output"]["candidate_paths"]
        if p["attack_path_id"] == proposal["source_attack_path"]["attack_path_id"])
    return proposal, validation, path


def verify_source_snapshot(value, envelope):
    try:
        if (set(value) != SOURCE_FIELDS or value["schema_version"] != "apts-vep-pentest-source-snapshot-v1"
            or not verify_integrity(value, SOURCE_DOMAIN) or not verify_canonical_action_envelope(envelope)):
            return False
        output, bundle, task, binding = (value[k] for k in ("output", "evidence_bundle", "task", "binding"))
        path_output, path_bundle = value["path_output"], value["path_evidence_bundle"]
        req, src = envelope["execution_request"], envelope["source_binding"]
        if not (verify_exploitation_output(output) and verify_exploitation_evidence_bundle(bundle)
            and verify_attack_path_planning_output(path_output) and verify_attack_path_planning_evidence_bundle(path_bundle)
            and verify_pentest_task_artifact(task) and verify_pentest_task_binding(binding) and binding["task"] == task):
            return False
        for obj in (output, bundle, path_output, path_bundle, task):
            if any(obj[k] != req[k] for k in ("mission_id", "pentest_id")) or obj["pentest_task_id"] != src["pentest_task_id"]:
                return False
        if (task["upstream_task_id"] != req["task_id"]
            or task["integrity"]["canonical_sha256"] != src["task_artifact_sha256"]
            or binding["integrity"]["canonical_sha256"] != src["task_binding_sha256"]
            or output["exploitation_run_id"] != envelope["intake"]["exploitation_run_id"]
            or output["orchestration_id"] != req["proposing_agent"]["orchestration_id"]
            or output["agent_id"] != req["proposing_agent"]["agent_id"]
            or output["exploitation_subtask_id"] != req["proposing_agent"]["subtask_id"]
            or output["integrity"]["canonical_sha256"] != src["source_run_output_sha256"]
            or bundle["integrity"]["canonical_sha256"] != src["source_run_evidence_bundle_sha256"]
            or bundle["output_sha256"] != output["integrity"]["canonical_sha256"]
            or bundle["request_sha256"] != exploitation_run_request_sha256(value["request"])
            or bundle["validation_task_sha256"] != [v["integrity"]["canonical_sha256"] for v in output["validation_tasks"]]
            or bundle["exploit_action_proposal_sha256"] != [p["integrity"]["canonical_sha256"] for p in output["exploit_action_proposals"]]):
            return False
        predecessor = output["predecessor_attack_path_planning"]
        if (bundle["predecessor_attack_path_planning"] != predecessor
            or path_output["attack_path_planning_run_id"] != predecessor["attack_path_planning_run_id"]
            or path_output["integrity"]["canonical_sha256"] != predecessor["output_sha256"]
            or path_bundle["integrity"]["canonical_sha256"] != predecessor["evidence_bundle_sha256"]
            or path_bundle["output_sha256"] != predecessor["output_sha256"]):
            return False
        if sum(p["exploit_action_proposal_id"] == envelope["intake"]["exploit_action_proposal_id"]
               for p in output["exploit_action_proposals"]) != 1:
            return False
        proposal, validation, path = selected(value, envelope)
        if (proposal["integrity"]["canonical_sha256"] != envelope["intake"]["proposal_sha256"]
            or validation["integrity"]["canonical_sha256"] != proposal["validation_task"]["validation_task_sha256"]
            or path["integrity"]["canonical_sha256"] != proposal["source_attack_path"]["attack_path_sha256"]
            or path["target"] != proposal["target"] or proposal["target"] != req["target"]
            or any(proposal[k] != req["action"][k] for k in req["action"])
            or {k:validation[k] for k in req["parameters"]} != req["parameters"]
            or any(validation[k] != proposal[k] for k in ("mission_id", "pentest_id", "pentest_task_id", "target", "technique", "evidence_basis", "governance"))):
            return False
        hypothesis, action = value["hypothesis"], value["action_proposal"]
        for obj, kind in ((hypothesis, "HYPOTHESIS"), (action, "ACTION_PROPOSAL")):
            if (not verify_pentest_lineage_object(obj) or obj["identity"]["record_type"] != kind
                or any(obj["identity"][k] != task[k] for k in ("mission_id", "pentest_id", "pentest_task_id"))):
                return False
        if (hypothesis["identity"]["record_id"] != proposal["source_attack_path"]["hypothesis_ref"]
            or path["source_hypothesis"]["hypothesis_ref"] != hypothesis["identity"]["record_id"]
            or action["identity"]["record_id"] != src["action_proposal_ref"]
            or action["integrity"]["canonical_sha256"] != src["action_proposal_sha256"]
            or proposal["lineage"]["action_proposal_ref"] != src["action_proposal_ref"]
            or proposal["lineage"]["action_proposal_sha256"] != src["action_proposal_sha256"]
            or action["parent_reference"] != {"reference_type":"HYPOTHESIS",
                "reference_id":hypothesis["identity"]["record_id"],
                "reference_sha256":hypothesis["integrity"]["canonical_sha256"]}
            or action["provenance"]["source_id"] != output["exploitation_run_id"]
            or action["provenance"]["actor_id"] != output["agent_id"]
            or any(action["data"][k] != proposal[k] for k in ("target", "technique", "action_class", "capability_id"))):
            return False
        refs = []
        for evidence in value["evidence_basis"]:
            if (not verify_pentest_lineage_object(evidence) or evidence["identity"]["record_type"] != "EVIDENCE"
                or any(evidence["identity"][k] != task[k] for k in ("mission_id", "pentest_id", "pentest_task_id"))):
                return False
            refs.append({"evidence_id":evidence["identity"]["record_id"],
                "canonical_sha256":evidence["integrity"]["canonical_sha256"]})
        return (refs == req["evidence_basis"] and [r["evidence_id"] for r in refs] == proposal["evidence_basis"]
            and path["provenance"]["supporting_evidence_refs"] == proposal["evidence_basis"])
    except (KeyError, TypeError, ValueError, RuntimeError, StopIteration, RecursionError):
        return False


class PentestVEPSource(PentestProposalSource):
    def snapshot(self, envelope):
        if envelope.get("intake", {}).get("schema_version") == "apts-execution-request-intake-v2":
            raise ExecutionSourceRejected(
                "Stage 6.7 VEP source snapshots for Recon requests are not enabled; the request remains unauthorised and undispatched"
            )
        if envelope.get("intake", {}).get("schema_version") == "apts-execution-request-intake-v3":
            raise ExecutionSourceRejected(
                "Stage 6.7 VEP source snapshots for Stage 5.3 Enumeration proposals are not enabled; evidence remains a read-only Stage 6.6 result"
            )
        # Historical source records survive Mission stops and authorization expiry.
        # No current_context(), GSS, repository initializer, or target adapter is called.
        try:
            with closing(self._connect()) as conn:
                self._migration(conn)
                run = ExploitationAgentRepository._exploitation_run_row(self._one(conn,
                    "pentest_exploitation_runs", "exploitation_run_id", envelope["intake"]["exploitation_run_id"]))
                task_record = PentestTaskRepository._row_to_record(self._one(conn, "pentest_tasks",
                    "pentest_task_id", envelope["source_binding"]["pentest_task_id"]))
                task = task_record["task"]
                if (any(task_record[k] != task[k] for k in ("mission_id", "pentest_id", "pentest_task_id", "upstream_task_id"))
                    or task_record["task_contract_sha256"] != task["integrity"]["canonical_sha256"]
                    or task_record["task_binding_sha256"] != task_record["binding"]["integrity"]["canonical_sha256"]
                    or any(run[k] != run["output"][k] for k in ("mission_id", "pentest_id", "pentest_task_id",
                        "exploitation_run_id", "orchestration_id", "agent_id", "validation_subtask_id", "exploitation_subtask_id"))):
                    raise ExecutionRequestIntegrityError("VEP source indexes disagree with immutable source records")
                path_run = AttackPathPlanningAgentRepository._attack_path_run_row(self._one(conn,
                    "pentest_attack_path_planning_runs", "attack_path_planning_run_id", run["attack_path_planning_run_id"]))
                proposal = next(p for p in run["output"]["exploit_action_proposals"]
                    if p["exploit_action_proposal_id"] == envelope["intake"]["exploit_action_proposal_id"])
                value = with_integrity({"schema_version":"apts-vep-pentest-source-snapshot-v1",
                    "request":run["request"], "output":run["output"], "evidence_bundle":run["evidence_bundle"],
                    "path_output":path_run["output"], "path_evidence_bundle":path_run["evidence_bundle"],
                    "task":task, "binding":task_record["binding"],
                    "hypothesis":self._lineage(conn, proposal["source_attack_path"]["hypothesis_ref"], "HYPOTHESIS", task),
                    "action_proposal":self._lineage(conn, proposal["lineage"]["action_proposal_ref"], "ACTION_PROPOSAL", task),
                    "evidence_basis":[self._lineage(conn, ref, "EVIDENCE", task) for ref in proposal["evidence_basis"]]}, SOURCE_DOMAIN)
                if run["run_status"] != "COMPLETED" or not verify_source_snapshot(value, envelope):
                    raise ExecutionRequestIntegrityError("VEP Pentest source snapshot binding mismatch")
                return value
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("historical Pentest VEP source unavailable") from exc
        except (KeyError, TypeError, ValueError, RuntimeError, StopIteration) as exc:
            if isinstance(exc, (ExecutionRequestIntegrityError, ExecutionSourceUnavailable)):
                raise
            raise ExecutionRequestIntegrityError("historical VEP source failed verification") from exc
