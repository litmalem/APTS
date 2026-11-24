from types import SimpleNamespace

from app.diagnostics import GOVERNANCE_DIAGNOSTICS_SCHEMA_V1, GovernanceHealthDiagnostics


class Thread:
    def __init__(self, alive=True): self.alive = alive
    def is_alive(self): return self.alive


class Repo:
    def __init__(self, *, db_ok=True, failed=0, emergency=False):
        self.db = SimpleNamespace(ping=lambda: db_ok)
        self.failed = failed
        self.emergency = emergency

    def outbox_stats(self):
        return {"total": 4, "pending": 0, "failed": self.failed, "delivered": 4 - self.failed}

    def get_emergency_state(self):
        return {"active": self.emergency, "status": "ACTIVE" if self.emergency else "INACTIVE"}


class Service:
    def __init__(self, *, db_ok=True, worker=True, failed=0, emergency=False):
        self.repo = Repo(db_ok=db_ok, failed=failed, emergency=emergency)
        self.events = SimpleNamespace(_thread=Thread(worker))


def test_governance_diagnostics_ready_when_core_checks_pass():
    result = GovernanceHealthDiagnostics(Service()).snapshot()
    assert result["schema_version"] == GOVERNANCE_DIAGNOSTICS_SCHEMA_V1
    assert result["health_status"] == "HEALTHY"
    assert result["readiness_status"] == "READY"


def test_outbox_worker_down_is_not_ready():
    result = GovernanceHealthDiagnostics(Service(worker=False)).snapshot()
    assert result["health_status"] == "UNHEALTHY"
    assert result["readiness_status"] == "NOT_READY"


def test_failed_outbox_or_active_emergency_stop_degrades_observability_not_authority():
    result = GovernanceHealthDiagnostics(Service(failed=1, emergency=True)).snapshot()
    assert result["health_status"] == "DEGRADED"
    statuses = {c["name"]: c["status"] for c in result["checks"]}
    assert statuses["OUTBOX_DELIVERY_STATE"] == "WARN"
    assert statuses["EMERGENCY_STOP_STATE"] == "WARN"
