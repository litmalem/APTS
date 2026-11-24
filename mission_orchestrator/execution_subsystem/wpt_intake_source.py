"""Read-only authority checks for WPT intake against current Mission/Pentest state."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from mission_orchestrator.governance_binding import resource_in_canonical_scope
from pentest_subsystem.lifecycle_contract import build_lifecycle_state_projection
from pentest_subsystem.task_contract import verify_pentest_task_artifact, verify_pentest_task_binding
from pentest_subsystem.task_repository import PentestTaskRepository

from .authorization_source import MissionAuthorizationSource
from .execution_contract import (
    ExecutionRequestIntegrityError, ExecutionSourceNotFound, ExecutionSourceRejected,
    ExecutionSourceUnavailable, sha256_hex,
)
from .proposal_source import PentestProposalSource
from .tool_registry import wpt_capability_profile_definitions


class WPTIntakeAuthoritySource:
    """Resolve caller IDs to current authoritative records; never trusts WPT scope claims."""
    def __init__(self, *, pentest_source: PentestProposalSource | None = None,
                 mission_source: MissionAuthorizationSource | None = None) -> None:
        self.pentest_source = pentest_source or PentestProposalSource()
        self.mission_source = mission_source or MissionAuthorizationSource()

    @staticmethod
    def _one(conn: sqlite3.Connection, table: str, key: str, value: str) -> sqlite3.Row:
        row = conn.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        if row is None:
            raise ExecutionSourceNotFound(f"unknown {key}")
        return row

    def resolve_wpt_intake_id(self, intake_id: str) -> dict[str, Any]:
        """Reload a sealed WPT intake and revalidate current Mission/Pentest authority."""
        from .wpt_intake_repository import default_wpt_intake_path, _verify
        from .execution_contract import require_id
        intake_id = require_id(intake_id, "intake_id", "wptreq-")
        path = default_wpt_intake_path()
        try:
            conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute("SELECT * FROM wpt_governed_intakes WHERE intake_id=?", (intake_id,)).fetchone()
            conn.close()
            if row is None:
                raise ExecutionSourceNotFound("unknown WPT intake")
            record = json.loads(row["record_json"])
            if (not _verify(record) or record["integrity"]["canonical_sha256"] != row["record_sha256"]
                    or record["intake"]["intake_id"] != intake_id):
                raise ExecutionRequestIntegrityError("WPT intake seal/index binding mismatch")
            return self.resolve(record["intake"])
        except (ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionRequestIntegrityError,
                ExecutionSourceUnavailable):
            raise
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ExecutionSourceUnavailable("WPT intake could not be revalidated") from exc

    def resolve(self, intake: dict[str, Any]) -> dict[str, Any]:
        # A retired duplicate must never regain execution authority, including
        # through a replay of its original immutable ExecutionRequest.
        from .wpt_intake_repository import default_wpt_intake_path, _verify
        path = default_wpt_intake_path()
        if path.exists():
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wpt_intake_retirements'").fetchone():
                    row = conn.execute('SELECT record_json FROM wpt_intake_retirements WHERE intake_id=?',
                                       (intake['intake_id'],)).fetchone()
                    if row:
                        proof = json.loads(row[0])
                        if (not _verify(proof) or proof.get('intake_id') != intake['intake_id']
                                or proof.get('schema_version') != 'apts-wpt-intake-retirement-v1'):
                            raise ExecutionRequestIntegrityError('WPT retirement seal mismatch')
                        raise ExecutionSourceRejected('WPT_INTAKE_RETIRED')
        if intake.get('schema_version') in ('apts-wpt-governed-intake-v3','apts-wpt-governed-intake-v4'):
            from pentest_subsystem.enumeration import EnumerationAgentRepository
            from .enumeration_followup_contract import build_intake
            run = EnumerationAgentRepository(self.pentest_source.sqlite_path).get_enumeration_run(
                intake['enumeration_context']['enumeration_run_id'])
            if run is None or build_intake(run, schema_version=intake['schema_version']) != intake:
                raise ExecutionRequestIntegrityError('CTI enumeration follow-up differs from authoritative analysis')
        mission = self.mission_source.current_context(intake["mission_id"])
        try:
            with closing(self.pentest_source._connect()) as conn:
                self.pentest_source._migration(conn)
                row = conn.execute(
                    "SELECT * FROM pentest_tasks WHERE upstream_task_id=? AND mission_id=?",
                    (intake["task_id"], intake["mission_id"]),
                ).fetchall()
                if not row:
                    raise ExecutionSourceNotFound("unknown task_id for this Mission")
                if len(row) != 1:
                    raise ExecutionRequestIntegrityError("task_id does not resolve to exactly one Pentest task")
                task_record = PentestTaskRepository._row_to_record(row[0])
                task, binding = task_record["task"], task_record["binding"]
                if (not verify_pentest_task_artifact(task) or not verify_pentest_task_binding(binding)
                        or binding.get("task") != task
                        or task["integrity"]["canonical_sha256"] != task_record["task_contract_sha256"]
                        or binding["integrity"]["canonical_sha256"] != task_record["task_binding_sha256"]):
                    raise ExecutionRequestIntegrityError("stored task artifact or binding failed integrity verification")
                if any(task.get(key) != intake[value] for key, value in
                       (("mission_id", "mission_id"), ("upstream_task_id", "task_id"))):
                    raise ExecutionRequestIntegrityError("task/Mission identity binding mismatch")

                # The WPT target must be an exact declared task target and inside
                # the current Mission scope, including exclusions.
                target = intake["target"]
                task_targets = task["scope"].get("targets", [])
                if not any(item.get("target_type") == target["target_type"]
                           and item.get("target_value") == target["target_value"] for item in task_targets):
                    raise ExecutionSourceRejected("target is not an exact target declared by the task")
                in_scope, _ = resource_in_canonical_scope(mission["mission_scope"], target["target_value"])
                in_task_scope, _ = resource_in_canonical_scope(task, target["target_value"])
                if not in_scope or not in_task_scope:
                    raise ExecutionSourceRejected("target is outside current Mission/task scope or explicitly excluded")

                lifecycle_row = self._one(conn, "pentest_task_lifecycle", "pentest_task_id", task_record["pentest_task_id"])
                lifecycle = build_lifecycle_state_projection(dict(lifecycle_row))
                if lifecycle["state"] != "RUNNING":
                    raise ExecutionSourceRejected("WPT intake requires a RUNNING task lifecycle")
                orch_rows = conn.execute(
                    "SELECT * FROM pentest_agentic_orchestrations WHERE pentest_task_id=? AND mission_id=? AND orchestration_status='ACTIVE'",
                    (task_record["pentest_task_id"], intake["mission_id"]),
                ).fetchall()
                if len(orch_rows) != 1:
                    raise ExecutionSourceRejected("WPT intake requires exactly one active task orchestration")
                orch = __import__("pentest_subsystem.orchestration.orchestrator", fromlist=["AgenticPentestOrchestratorRepository"]).AgenticPentestOrchestratorRepository._orchestration_row(orch_rows[0])
                if (orch["pentest_id"] != task["pentest_id"] or orch["upstream_task_id"] != intake["task_id"]):
                    raise ExecutionRequestIntegrityError("active orchestration is not bound to the selected task")
        except (ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionSourceUnavailable,
                ExecutionRequestIntegrityError):
            raise
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("current task authority source is unavailable") from exc
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise ExecutionRequestIntegrityError("current task authority records failed verification") from exc

        profiles = {item["profile_id"]: item for item in wpt_capability_profile_definitions()}
        profile_id = {"fingerprinting": "wpt.fingerprinting.v1",
                      "enumeration": "wpt.bounded-enumeration.v1"}[intake["profile"]]
        profile = profiles[profile_id]
        action_class = profile["action"]["action_class"]
        scope_contract = mission["mission_scope"]
        roe = scope_contract["roe"]
        if (action_class not in roe.get("allowed_action_classes", [])
                or action_class in roe.get("prohibited_action_classes", [])):
            raise ExecutionSourceRejected("Mission RoE does not permit the WPT action class")
        technique = profile["action"]["technique"]
        for rules in (roe, task["constraints"]):
            if (rules.get("allowed_techniques") and technique not in rules["allowed_techniques"]
                    or technique in rules.get("prohibited_techniques", [])):
                raise ExecutionSourceRejected("Mission/task rules do not permit the selected WPT technique")
        window = roe.get("allowed_time_window")
        if window:
            now = datetime.now(timezone.utc)
            start = datetime.fromisoformat(window["start_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(window["end_at"].replace("Z", "+00:00"))
            if not start <= now < end:
                raise ExecutionSourceRejected("WPT intake is outside the Mission RoE time window")

        profile_limit = profile["limits"]["max_requests"]
        resource_budget = scope_contract.get("constraints", {}).get("resource_budget", {})
        budget_values = [resource_budget[k] for k in ("max_network_requests", "max_requests")
                         if type(resource_budget.get(k)) is int]
        if not budget_values:
            raise ExecutionSourceRejected("current Mission scope has no explicit network-request budget")
        mission_budget = min(budget_values)
        task_constraints = task["constraints"]
        task_budget = task_constraints.get("max_network_requests", task_constraints.get("max_requests"))
        if type(task_budget) is int:
            mission_budget = min(mission_budget, task_budget)
        if mission_budget < 1:
            raise ExecutionSourceRejected("task/Mission network-request budget is exhausted")
        limits = deepcopy(profile["limits"])
        if intake["profile"] == "enumeration":
            # Reserve exactly the CTI-aware bounded plan length (5 base paths plus
            # any verified follow-up probes), never the full ceiling, so enumerations
            # without enrichment keep their original 5-request footprint.
            from adapters.profile_engine import plan_requests
            profile_limit = min(profile_limit, len(plan_requests(
                target["target_value"], "enumeration", intake.get("enumeration_context"))))
        limits["max_requests"] = min(profile_limit, mission_budget)
        if limits["max_requests"] < 1:
            raise ExecutionSourceRejected("no WPT requests remain within the current budget")

        boundary = {"scope": deepcopy(scope_contract["scope"]), "roe": deepcopy(roe),
                    "constraints": deepcopy(scope_contract["constraints"])}
        return {
            "mission_id": intake["mission_id"], "task_id": intake["task_id"],
            "pentest_task_id": task_record["pentest_task_id"], "pentest_id": task["pentest_id"],
            "target": deepcopy(target), "profile_id": profile_id,
            **({"enumeration_context": deepcopy(intake["enumeration_context"])}
               if "enumeration_context" in intake else {}),
            "action": deepcopy(profile["action"]), "limits": limits,
            "mission_network_request_budget": mission_budget,
            "mission_scope_sha256": scope_contract["mission_scope"]["integrity"]["canonical_sha256"]
                if "mission_scope" in scope_contract else scope_contract["integrity"]["canonical_sha256"],
            "task_artifact_sha256": task["integrity"]["canonical_sha256"],
            "task_binding_sha256": binding["integrity"]["canonical_sha256"],
            "task_lifecycle_state": lifecycle["state"], "orchestration_id": orch["orchestration_id"],
            "orchestration_status": orch["orchestration_status"],
            "governance_binding_sha256": mission["governance_binding"]["integrity"]["canonical_sha256"],
            "authorization_policy_reference": deepcopy(task["authorization_reference"]),
            "current_task": deepcopy(task), "current_boundary": boundary,
            "orchestration_graph_sha256": orch["task_graph_sha256"],
            "execution_status": profile["execution_status"],
        }
