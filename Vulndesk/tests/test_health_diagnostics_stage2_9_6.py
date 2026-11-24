from types import SimpleNamespace

from cti_services.diagnostics import CTI_DIAGNOSTICS_SCHEMA_V1, CtiHealthDiagnostics


class FakeDb:
    def __init__(self, *, ping=True, missing=()):
        self.ping = ping
        self.missing = set(missing)

    def fetch_one(self, sql, params=None):
        if not self.ping:
            raise RuntimeError("db down")
        return {"ok": 1}

    def table_exists(self, table):
        if not self.ping:
            raise RuntimeError("db down")
        return table not in self.missing


class FakeGovernance:
    def __init__(self, *, enabled=True, reachable=True):
        self.status = SimpleNamespace(enabled=enabled, base_url="http://127.0.0.1:8770")
        self.reachable = reachable

    def health_check(self):
        if not self.reachable:
            raise RuntimeError("governance unreachable")
        return {"status": "ok", "component_id": "GOV-PLANE"}


class FakeOrchestrator:
    CONTROL_VERSION = "hybrid-event-driven-2.17-health-diagnostics"
    ARCHITECTURE_VERSION = "2026-08-harmonized"

    def __init__(self, *, db=None, dispatcher=True, queue=0, governance=None):
        self.db = db or FakeDb()
        self.dispatcher = SimpleNamespace(is_running=dispatcher)
        self.event_bus = SimpleNamespace(pending_count=lambda: queue)
        self.governance = governance or FakeGovernance()

    def probe_task_integrity(self, task_id):
        return {}

    def probe_mission_integrity(self, mission_id):
        return {}

    def project_mission_lineage(self, mission_id):
        return {
            "identity": {"mission_id": mission_id},
            "task_lineages": [{"identity": {"task_id": "task-1"}}],
            "projection_metadata": {"quality": "CANONICAL_V2"},
            "governance_correlation": {"status": "CORRELATED"},
            "integrity_probe": {
                "status": "PASS",
                "violation_count": 0,
                "verification_complete": True,
            },
        }


def test_shallow_diagnostics_ready_when_mandatory_checks_pass():
    result = CtiHealthDiagnostics(FakeOrchestrator()).snapshot()
    assert result["schema_version"] == CTI_DIAGNOSTICS_SCHEMA_V1
    assert result["health_status"] == "HEALTHY"
    assert result["readiness_status"] == "READY"
    assert result["summary"]["fail_count"] == 0


def test_database_failure_is_not_ready_and_unhealthy():
    result = CtiHealthDiagnostics(FakeOrchestrator(db=FakeDb(ping=False))).snapshot()
    assert result["health_status"] == "UNHEALTHY"
    assert result["readiness_status"] == "NOT_READY"
    db = next(c for c in result["checks"] if c["name"] == "DATABASE_CONNECTIVITY")
    assert db["status"] == "FAIL"


def test_deep_governance_unreachable_is_degraded_not_authority_fabrication():
    result = CtiHealthDiagnostics(
        FakeOrchestrator(governance=FakeGovernance(reachable=False))
    ).snapshot(deep=True)
    assert result["health_status"] == "DEGRADED"
    check = next(c for c in result["checks"] if c["name"] == "GOVERNANCE_REACHABILITY")
    assert check["status"] == "WARN"


def test_mission_diagnostics_projects_integrity_and_correlation_without_mutation():
    result = CtiHealthDiagnostics(FakeOrchestrator()).mission_snapshot("mission-296")
    assert result["status"] == "HEALTHY"
    assert result["integrity_status"] == "PASS"
    assert result["governance_correlation_status"] == "CORRELATED"
    assert result["task_count"] == 1
