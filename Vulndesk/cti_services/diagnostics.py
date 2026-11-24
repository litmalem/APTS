from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, List, Optional

from .db_adapter import make_json_safe
from .lineage_projection import LineageProjectionSchemaError, MissionLineageNotFound


CTI_DIAGNOSTICS_SCHEMA_V1 = "cti-health-diagnostics-v1"


class CtiHealthDiagnostics:
    """Stage 2.9.6 read-only health/readiness/diagnostic aggregator.

    The aggregator intentionally separates *process liveness* from *operational
    readiness*.  It does not mutate runtime state, repair lineage, retry events,
    or synthesize Governance authority.  Deep diagnostics may call the external
    authoritative Governance health endpoint; shallow diagnostics remain local.
    """

    REQUIRED_LINEAGE_TABLES = (
        "cti_task_contracts",
        "cti_events",
        "cti_decision_traces",
        "cti_audit_log",
    )

    def __init__(self, orchestrator: Any):
        self.orchestrator = orchestrator

    def snapshot(self, *, deep: bool = False) -> Dict[str, Any]:
        started = time.monotonic()
        checks: List[Dict[str, Any]] = []

        checks.append(self._database_check())
        checks.append(self._dispatcher_check())
        checks.append(self._event_queue_check())
        checks.append(self._lineage_schema_check())
        checks.append(self._integrity_capability_check())
        checks.append(self._governance_configuration_check())
        if deep:
            checks.append(self._governance_reachability_check())

        mandatory_failed = [c for c in checks if c.get("mandatory") and c.get("status") == "FAIL"]
        degraded = [c for c in checks if c.get("status") in {"WARN", "FAIL"}]
        if mandatory_failed:
            readiness = "NOT_READY"
            health = "UNHEALTHY"
        elif degraded:
            readiness = "DEGRADED"
            health = "DEGRADED"
        else:
            readiness = "READY"
            health = "HEALTHY"

        return make_json_safe({
            "schema_version": CTI_DIAGNOSTICS_SCHEMA_V1,
            "scope": "CTI_RUNTIME",
            "health_status": health,
            "readiness_status": readiness,
            "deep": bool(deep),
            "control_version": getattr(self.orchestrator, "CONTROL_VERSION", None),
            "architecture_version": getattr(self.orchestrator, "ARCHITECTURE_VERSION", None),
            "checks": checks,
            "summary": {
                "check_count": len(checks),
                "pass_count": sum(c.get("status") == "PASS" for c in checks),
                "warn_count": sum(c.get("status") == "WARN" for c in checks),
                "fail_count": sum(c.get("status") == "FAIL" for c in checks),
                "mandatory_fail_count": len(mandatory_failed),
            },
            "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
        })

    def mission_snapshot(self, mission_id: str) -> Dict[str, Any]:
        started = time.monotonic()
        mission_id = str(mission_id or "").strip()
        if not mission_id:
            raise ValueError("mission_id is required")

        lineage = self.orchestrator.project_mission_lineage(mission_id)
        metadata = lineage.get("projection_metadata") or {}
        correlation = lineage.get("governance_correlation") or {}
        integrity = lineage.get("integrity_probe") or {}
        task_rows = list(lineage.get("task_lineages") or lineage.get("tasks") or [])

        integrity_status = str(integrity.get("status") or "UNKNOWN").upper()
        correlation_status = str(correlation.get("status") or "UNKNOWN").upper()
        quality = str(metadata.get("quality") or "UNKNOWN").upper()

        issues: List[Dict[str, Any]] = []
        if integrity_status == "VIOLATION_DETECTED":
            issues.append({"code": "INTEGRITY_VIOLATION", "severity": "CRITICAL", "detail": integrity.get("violation_count", 0)})
        elif integrity_status == "UNVERIFIABLE":
            issues.append({"code": "INTEGRITY_UNVERIFIABLE", "severity": "WARN"})
        if correlation_status not in {"CORRELATED", "PASS", "COMPLETE", "OK"}:
            issues.append({"code": "GOVERNANCE_CORRELATION_NOT_COMPLETE", "severity": "WARN", "detail": correlation_status})
        if quality not in {"CANONICAL_V2", "CANONICAL"}:
            issues.append({"code": "LINEAGE_NOT_STRICT_CANONICAL", "severity": "WARN", "detail": quality})

        if any(i["severity"] == "CRITICAL" for i in issues):
            status = "VIOLATION_DETECTED"
        elif issues:
            status = "DEGRADED"
        else:
            status = "HEALTHY"

        return make_json_safe({
            "schema_version": CTI_DIAGNOSTICS_SCHEMA_V1,
            "scope": "MISSION",
            "mission_id": mission_id,
            "status": status,
            "projection_quality": quality,
            "governance_correlation_status": correlation_status,
            "integrity_status": integrity_status,
            "integrity_violation_count": int(integrity.get("violation_count") or 0),
            "integrity_verification_complete": bool(integrity.get("verification_complete", False)),
            "task_count": len(task_rows),
            "issues": issues,
            "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
        })

    def _database_check(self) -> Dict[str, Any]:
        try:
            row = self.orchestrator.db.fetch_one("SELECT 1 AS ok")
            ok = bool(row and int(row.get("ok") or 0) == 1)
            return self._check("DATABASE_CONNECTIVITY", "PASS" if ok else "FAIL", mandatory=True)
        except Exception as exc:
            return self._check("DATABASE_CONNECTIVITY", "FAIL", mandatory=True, detail=str(exc))

    def _dispatcher_check(self) -> Dict[str, Any]:
        try:
            running = bool(self.orchestrator.dispatcher.is_running)
            return self._check("EVENT_DISPATCHER", "PASS" if running else "FAIL", mandatory=True, detail={"running": running})
        except Exception as exc:
            return self._check("EVENT_DISPATCHER", "FAIL", mandatory=True, detail=str(exc))

    def _event_queue_check(self) -> Dict[str, Any]:
        warn_threshold = max(1, int(os.getenv("CTI_DIAGNOSTICS_QUEUE_WARN_THRESHOLD", "100")))
        fail_threshold = max(warn_threshold + 1, int(os.getenv("CTI_DIAGNOSTICS_QUEUE_FAIL_THRESHOLD", "1000")))
        try:
            depth = int(self.orchestrator.event_bus.pending_count())
            status = "FAIL" if depth >= fail_threshold else "WARN" if depth >= warn_threshold else "PASS"
            return self._check(
                "EVENT_QUEUE_BACKLOG",
                status,
                mandatory=False,
                detail={"depth": depth, "warn_threshold": warn_threshold, "fail_threshold": fail_threshold},
            )
        except Exception as exc:
            return self._check("EVENT_QUEUE_BACKLOG", "WARN", mandatory=False, detail=str(exc))

    def _lineage_schema_check(self) -> Dict[str, Any]:
        missing: List[str] = []
        try:
            for table in self.REQUIRED_LINEAGE_TABLES:
                if not self.orchestrator.db.table_exists(table):
                    missing.append(table)
            return self._check(
                "CANONICAL_LINEAGE_SCHEMA",
                "PASS" if not missing else "FAIL",
                mandatory=True,
                detail={"required_tables": list(self.REQUIRED_LINEAGE_TABLES), "missing_tables": missing},
            )
        except Exception as exc:
            return self._check("CANONICAL_LINEAGE_SCHEMA", "FAIL", mandatory=True, detail=str(exc))

    def _integrity_capability_check(self) -> Dict[str, Any]:
        ready = callable(getattr(self.orchestrator, "probe_task_integrity", None)) and callable(getattr(self.orchestrator, "probe_mission_integrity", None))
        return self._check(
            "INTEGRITY_PROBE_CAPABILITY",
            "PASS" if ready else "FAIL",
            mandatory=True,
            detail={"mode": "READ_ONLY_CANONICAL_LINEAGE_PLUS_AUTHORITATIVE_CORRELATION"},
        )

    def _governance_configuration_check(self) -> Dict[str, Any]:
        status = getattr(getattr(self.orchestrator, "governance", None), "status", None)
        enabled = bool(getattr(status, "enabled", False))
        base_url = getattr(status, "base_url", None)
        return self._check(
            "GOVERNANCE_CONFIGURATION",
            "PASS" if enabled else "WARN",
            mandatory=False,
            detail={"enabled": enabled, "base_url": base_url, "authority_mode": "EXTERNAL_AUTHORITATIVE_FAIL_CLOSED"},
        )

    def _governance_reachability_check(self) -> Dict[str, Any]:
        governance = getattr(self.orchestrator, "governance", None)
        try:
            body = governance.health_check()
            remote_status = str((body or {}).get("status") or "unknown").lower()
            ok = remote_status == "ok"
            return self._check(
                "GOVERNANCE_REACHABILITY",
                "PASS" if ok else "WARN",
                mandatory=False,
                detail={"remote_status": remote_status, "component_id": (body or {}).get("component_id")},
            )
        except Exception as exc:
            return self._check("GOVERNANCE_REACHABILITY", "WARN", mandatory=False, detail=str(exc))

    @staticmethod
    def _check(name: str, status: str, *, mandatory: bool, detail: Optional[Any] = None) -> Dict[str, Any]:
        row: Dict[str, Any] = {"name": name, "status": status, "mandatory": bool(mandatory)}
        if detail is not None:
            row["detail"] = detail
        return row
