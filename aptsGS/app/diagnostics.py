from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from .architecture import ARCHITECTURE_VERSION, SERVICE_ID
from .config import Settings, settings
from .interface_catalog import cti_health_url


GOVERNANCE_DIAGNOSTICS_SCHEMA_V1 = "governance-health-diagnostics-v1"


class GovernanceHealthDiagnostics:
    """Stage 2.9.6 read-only Governance health/readiness aggregator.

    The diagnostic plane observes persistence, event-outbox delivery, emergency
    stop state, and (for deep probes) CTI reachability.  It never issues policy
    decisions, retries events, or changes emergency-stop state.
    """

    def __init__(self, service: Any, cfg: Settings = settings):
        self.service = service
        self.cfg = cfg

    def snapshot(self, *, deep: bool = False) -> Dict[str, Any]:
        started = time.monotonic()
        checks: List[Dict[str, Any]] = []
        checks.append(self._database_check())
        checks.append(self._outbox_worker_check())
        checks.append(self._outbox_state_check())
        checks.append(self._emergency_state_check())
        if deep:
            checks.append(self._cti_reachability_check())

        mandatory_failed = [c for c in checks if c.get("mandatory") and c.get("status") == "FAIL"]
        degraded = [c for c in checks if c.get("status") in {"WARN", "FAIL"}]
        if mandatory_failed:
            health = "UNHEALTHY"
            readiness = "NOT_READY"
        elif degraded:
            health = "DEGRADED"
            readiness = "DEGRADED"
        else:
            health = "HEALTHY"
            readiness = "READY"

        return {
            "schema_version": GOVERNANCE_DIAGNOSTICS_SCHEMA_V1,
            "scope": "GOVERNANCE_RUNTIME",
            "health_status": health,
            "readiness_status": readiness,
            "deep": bool(deep),
            "component_id": SERVICE_ID,
            "architecture_version": ARCHITECTURE_VERSION,
            "checks": checks,
            "summary": {
                "check_count": len(checks),
                "pass_count": sum(c.get("status") == "PASS" for c in checks),
                "warn_count": sum(c.get("status") == "WARN" for c in checks),
                "fail_count": sum(c.get("status") == "FAIL" for c in checks),
                "mandatory_fail_count": len(mandatory_failed),
            },
            "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
        }

    def _database_check(self) -> Dict[str, Any]:
        try:
            ok = bool(self.service.repo.db.ping())
            return self._check("DATABASE_CONNECTIVITY", "PASS" if ok else "FAIL", mandatory=True)
        except Exception as exc:
            return self._check("DATABASE_CONNECTIVITY", "FAIL", mandatory=True, detail=str(exc))

    def _outbox_worker_check(self) -> Dict[str, Any]:
        thread = getattr(self.service.events, "_thread", None)
        running = bool(thread and thread.is_alive())
        return self._check("OUTBOX_WORKER", "PASS" if running else "FAIL", mandatory=True, detail={"running": running})

    def _outbox_state_check(self) -> Dict[str, Any]:
        try:
            stats = dict(self.service.repo.outbox_stats() or {})
            failed = int(stats.get("failed") or 0)
            pending = int(stats.get("pending") or 0)
            status = "WARN" if failed > 0 else "PASS"
            return self._check(
                "OUTBOX_DELIVERY_STATE",
                status,
                mandatory=False,
                detail={"pending": pending, "failed": failed, "delivered": int(stats.get("delivered") or 0), "total": int(stats.get("total") or 0)},
            )
        except Exception as exc:
            return self._check("OUTBOX_DELIVERY_STATE", "WARN", mandatory=False, detail=str(exc))

    def _emergency_state_check(self) -> Dict[str, Any]:
        try:
            state = self.service.repo.get_emergency_state() or {}
            active = self._emergency_active(state)
            return self._check(
                "EMERGENCY_STOP_STATE",
                "WARN" if active else "PASS",
                mandatory=False,
                detail={"active": active, "state": state},
            )
        except Exception as exc:
            return self._check("EMERGENCY_STOP_STATE", "WARN", mandatory=False, detail=str(exc))

    def _cti_reachability_check(self) -> Dict[str, Any]:
        url = cti_health_url(self.cfg)
        try:
            response = requests.get(url, timeout=min(max(self.cfg.cti_event_api_timeout_seconds, 0.5), 3.0))
            ok = 200 <= response.status_code < 300
            body: Any = None
            try:
                body = response.json()
            except Exception:
                body = {"http_status": response.status_code}
            remote_status = str((body or {}).get("status") or "unknown").lower() if isinstance(body, dict) else "unknown"
            # HTTP 2xx with remote degraded is still a dependency degradation.
            status = "PASS" if ok and remote_status == "ok" else "WARN"
            return self._check(
                "CTI_RUNTIME_REACHABILITY",
                status,
                mandatory=False,
                detail={"url": url, "http_status": response.status_code, "remote_status": remote_status},
            )
        except Exception as exc:
            return self._check("CTI_RUNTIME_REACHABILITY", "WARN", mandatory=False, detail={"url": url, "error": str(exc)})

    @staticmethod
    def _emergency_active(state: Any) -> bool:
        if not isinstance(state, dict):
            return False
        for key in ("active", "is_active", "enabled"):
            if key in state:
                return bool(state.get(key))
        status = str(state.get("status") or state.get("state") or "").upper()
        return status in {"ACTIVE", "ENABLED", "STOPPED", "EMERGENCY_STOP"}

    @staticmethod
    def _check(name: str, status: str, *, mandatory: bool, detail: Optional[Any] = None) -> Dict[str, Any]:
        row: Dict[str, Any] = {"name": name, "status": status, "mandatory": bool(mandatory)}
        if detail is not None:
            row["detail"] = detail
        return row
