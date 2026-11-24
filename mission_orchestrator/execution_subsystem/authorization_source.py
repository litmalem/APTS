"""Read-only current Mission and Pentest context. Never initialize either DB."""
from __future__ import annotations

from contextlib import closing
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from mission_orchestrator.governance_binding import verify_binding_contract, resource_in_canonical_scope
from mission_orchestrator.scope_contract import verify_contract
from pentest_subsystem.reconnaissance import ReconnaissanceAgentRepository
from pentest_subsystem.task_repository import PentestTaskRepository

from .authorization_contract import parse_time
from .execution_contract import (
    ExecutionRequestIntegrityError, ExecutionSourceNotFound, ExecutionSourceRejected,
    ExecutionSourceUnavailable, canonical_json, require_id, sha256_hex,
)
from .proposal_source import PentestProposalSource


class ExecutionAuthorizationProposalSource(PentestProposalSource):
    def current_context(self, envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            with closing(self._connect()) as conn:
                self._migration(conn)
                intake = envelope["intake"]
                current = self._build(conn, intake)
                if canonical_json(current) != canonical_json(envelope):
                    raise ExecutionSourceRejected("persisted proposal no longer matches the execution envelope")
                if intake.get("schema_version") == "apts-execution-request-intake-v4":
                    from .wpt_intake_source import WPTIntakeAuthoritySource
                    wpt_record = WPTIntakeAuthoritySource().resolve_wpt_intake_id(intake["wpt_intake_id"])
                    return {"boundary": wpt_record["current_boundary"], "task": wpt_record["current_task"],
                            "orchestration_status": wpt_record["orchestration_status"],
                            "source_type": "WPT_GOVERNED_INTAKE", "source_action_id": intake["wpt_intake_id"]}
                if intake.get("schema_version") in {"apts-execution-request-intake-v2", "apts-execution-request-intake-v3"}:
                    # _build_recon revalidates the persisted Action Request, task artifact,
                    # current scope/RoE snapshots, capability registry, orchestration node,
                    # task lifecycle, and evidence lineage before returning this context.
                    if intake["schema_version"] == "apts-execution-request-intake-v2":
                        run_id = self._recon_run_id_for_action(conn, intake["recon_action_id"])
                        run = self._one(conn, "pentest_recon_runs", "recon_run_id", run_id)
                        run_record = ReconnaissanceAgentRepository._run_row(run)
                        context = {"source_type": "STAGE5_2_RECON_ACTION_REQUEST",
                                   "source_action_id": intake["recon_action_id"]}
                    else:
                        run = self._one(conn, "pentest_enumeration_runs", "enumeration_run_id", intake["enumeration_run_id"])
                        run_record = __import__("pentest_subsystem.enumeration", fromlist=["EnumerationAgentRepository"]).EnumerationAgentRepository._enumeration_run_row(run)
                        context = {"source_type": "STAGE5_3_ENUMERATION_ACTION_PROPOSAL",
                                   "source_action_id": intake["enumeration_proposal_ref"]}
                    task_row = self._one(conn, "pentest_tasks", "pentest_task_id", run_record["pentest_task_id"])
                    task_record = PentestTaskRepository._row_to_record(task_row)
                    orchestration = self._one(conn, "pentest_agentic_orchestrations", "orchestration_id",
                                              run_record["orchestration_id"])
                    if orchestration["orchestration_status"] != "ACTIVE":
                        raise ExecutionSourceRejected("Recon orchestration is no longer active")
                    return {"boundary": run_record["request"]["boundary"],
                            "task": task_record["task"],
                            "orchestration_status": orchestration["orchestration_status"],
                            **context}
                run = self._one(conn, "pentest_exploitation_runs", "exploitation_run_id", envelope["intake"]["exploitation_run_id"])
                run_request = json.loads(run["request_json"])
                task = self._one(conn, "pentest_tasks", "pentest_task_id", envelope["source_binding"]["pentest_task_id"])
                orchestration = self._one(conn, "pentest_agentic_orchestrations", "orchestration_id", envelope["execution_request"]["proposing_agent"]["orchestration_id"])
                if orchestration["orchestration_status"] not in {"ACTIVE", "COMPLETED"}:
                    raise ExecutionSourceRejected("Pentest orchestration requires replanning, termination or escalation handling")
                return {"boundary": run_request["boundary"], "task": json.loads(task["task_json"]),
                        "orchestration_status": orchestration["orchestration_status"]}
        except (ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionSourceUnavailable, ExecutionRequestIntegrityError):
            raise
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("current Pentest context unavailable") from exc
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            raise ExecutionRequestIntegrityError("invalid current Pentest context") from exc


class MissionAuthorizationSource:
    def __init__(self, sqlite_path: str | Path | None = None):
        self.sqlite_path = Path(sqlite_path or os.getenv("APTS_EXECUTION_MISSION_DB")
                                or os.getenv("MISSION_SQLITE_PATH")
                                or Path(__file__).resolve().parents[1] / "data" / "mission_orchestrator.db").resolve()

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.sqlite_path.as_uri() + "?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            return conn
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("current Mission authorization source unavailable") from exc

    @staticmethod
    def _migration(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT migration_level FROM mission_repository_metadata WHERE repository_id=?",
                           ("canonical-mission-repository",)).fetchone()
        if row is None or row[0] != 53:
            raise ExecutionSourceUnavailable("Stage 6.2 requires Mission repository migration 53")
        return 53

    def migration_level(self) -> int:
        try:
            with closing(self._connect()) as conn:
                return self._migration(conn)
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("Mission source metadata unavailable") from exc

    def current_context(self, mission_id: str) -> dict[str, Any]:
        require_id(mission_id, "mission_id", "mission-gmo-")
        try:
            with closing(self._connect()) as conn:
                self._migration(conn)
                state = conn.execute("SELECT * FROM mission_states WHERE mission_id=?", (mission_id,)).fetchone()
                scope = conn.execute("""SELECT v.*,h.current_snapshot_id,h.current_sha256 FROM mission_scope_contract_versions v
                    JOIN mission_scope_contract_heads h ON h.mission_id=v.mission_id AND h.current_version=v.contract_version
                    WHERE v.mission_id=?""", (mission_id,)).fetchone()
                binding = conn.execute("""SELECT v.*,h.current_binding_snapshot_id,h.current_scope_snapshot_id,
                    h.current_governance_scope_contract_id FROM mission_governance_binding_versions v
                    JOIN mission_governance_binding_heads h ON h.mission_id=v.mission_id AND h.current_version=v.binding_version
                    WHERE v.mission_id=?""", (mission_id,)).fetchone()
                root = conn.execute("SELECT mission_id FROM global_missions WHERE mission_id=?", (mission_id,)).fetchone()
                if root is None or state is None or scope is None or binding is None:
                    raise ExecutionSourceRejected("current Mission state/scope/governance binding is missing")
                if state["state"] != "RUNNING" or state["terminal"] != 0:
                    raise ExecutionSourceRejected("execution authorization requires a RUNNING nonterminal Mission")
                contract = json.loads(scope["canonical_json"])
                gov_binding = json.loads(binding["canonical_json"])
                if not verify_contract(contract) or not verify_binding_contract(gov_binding):
                    raise ExecutionRequestIntegrityError("current Mission scope/governance binding failed verification")
                identity = contract["identity"]
                if (identity["mission_id"] != mission_id or identity["snapshot_id"] != scope["snapshot_id"]
                        or identity["mission_scope_contract_id"] != scope["mission_scope_contract_id"]
                        or identity["contract_version"] != scope["contract_version"]
                        or scope["current_snapshot_id"] != scope["snapshot_id"]
                        or scope["canonical_sha256"] != contract["integrity"]["canonical_sha256"]
                        or scope["current_sha256"] != scope["canonical_sha256"]):
                    raise ExecutionRequestIntegrityError("current Mission scope head/index mismatch")
                bid = gov_binding["identity"]
                bound = gov_binding["canonical_scope_binding"]
                gov = gov_binding["governance_authority"]
                expected_binding = {
                    "binding_snapshot_id": bid["binding_snapshot_id"],
                    "binding_version": bid["binding_version"],
                    "mission_governance_binding_id": bid["mission_governance_binding_id"],
                    "canonical_sha256": gov_binding["integrity"]["canonical_sha256"],
                    "mission_scope_snapshot_id": scope["snapshot_id"],
                    "mission_scope_sha256": scope["canonical_sha256"],
                    "governance_scope_contract_id": gov["governance_scope_contract_id"],
                    "governance_scope_version": gov["governance_scope_version"],
                    "governance_scope_contract_hash": gov["governance_scope_contract_hash"],
                    "policy_set_id": gov["policy_set_id"],
                    "current_binding_snapshot_id": bid["binding_snapshot_id"],
                    "current_scope_snapshot_id": scope["snapshot_id"],
                    "current_governance_scope_contract_id": gov["governance_scope_contract_id"],
                }
                if (bid["mission_id"] != mission_id
                        or any(binding[key] != value for key, value in expected_binding.items())
                        or bound != {"mission_scope_contract_id": identity["mission_scope_contract_id"],
                                     "mission_scope_contract_version": identity["contract_version"],
                                     "mission_scope_snapshot_id": identity["snapshot_id"],
                                     "mission_scope_sha256": scope["canonical_sha256"]}
                        or gov["authorization_authority"] != "aptsGSS"
                        or gov["authorization_authority_component"] != "GOV-PLANE"
                        or gov["governance_status"] != "BOUND"):
                    raise ExecutionRequestIntegrityError("current Mission governance binding is stale or inconsistent")
                return {"mission_id": mission_id, "mission_state": "RUNNING",
                        "state_version": state["state_version"], "mission_scope": contract,
                        "governance_binding": gov_binding, "governance_authority": gov}
        except (ExecutionSourceRejected, ExecutionRequestIntegrityError):
            raise
        except sqlite3.Error as exc:
            raise ExecutionSourceUnavailable("Mission authorization context could not be read") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("current Mission authorization context is invalid") from exc


def local_execution_checks(request: dict[str, Any], mission: dict[str, Any], pentest: dict[str, Any], now) -> dict[str, str]:
    """Mandatory local restrictions supplement, and never replace, GSS checks."""
    target = request["target"]
    action = request["action"]
    contexts = [mission["mission_scope"], pentest["boundary"], pentest["task"]]
    scope_ok = all(resource_in_canonical_scope(ctx, target["target_value"])[0] for ctx in contexts)
    for ctx in contexts:
        ranges = ctx["scope"].get("network_ranges", ctx.get("constraints", {}).get("network_ranges", []))
        if ranges:
            try:
                scope_ok = scope_ok and any(ipaddress.ip_address(target["target_value"]) in ipaddress.ip_network(x, strict=False) for x in ranges)
            except ValueError:
                scope_ok = False
    roe_ok = True
    technique_ok = True
    risk_ok = True
    impacts = {"NONE": 0, "LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4, "DESTRUCTIVE": 5}
    for ctx in contexts:
        roe = ctx.get("roe", pentest["boundary"]["roe"])
        constraints = ctx["constraints"]
        roe_ok = roe_ok and action["action_class"] in roe["allowed_action_classes"] and action["action_class"] not in roe.get("prohibited_action_classes", [])
        window = roe.get("allowed_time_window")
        if window:
            roe_ok = roe_ok and parse_time(window["start_at"], "start_at") <= now < parse_time(window["end_at"], "end_at")
        if action["action_class"] == "CREDENTIAL_USE":
            roe_ok = roe_ok and roe.get("credential_usage_allowed") is True
        if action["action_class"] == "PERSISTENCE":
            roe_ok = roe_ok and roe.get("persistence_allowed") is True
        technique_ok = technique_ok and action["technique"] not in roe.get("prohibited_techniques", []) and (not roe.get("allowed_techniques") or action["technique"] in roe["allowed_techniques"])
        threshold = constraints.get("impact_limit", constraints.get("risk_threshold"))
        risk_ok = risk_ok and threshold in impacts and impacts[request["parameters"]["estimated_impact"]] <= impacts.get(threshold, -1)
        if action["action_class"] == "DESTRUCTIVE_ACTION" or request["parameters"]["estimated_impact"] == "DESTRUCTIVE":
            risk_ok = risk_ok and roe.get("destructive_actions_allowed") is True
    return {"SCOPE": "PASS" if scope_ok else "FAIL", "ROE": "PASS" if roe_ok else "FAIL",
            "RISK": "PASS" if risk_ok else "FAIL", "TARGET": "PASS" if scope_ok else "FAIL",
            "TECHNIQUE": "PASS" if technique_ok else "FAIL"}
