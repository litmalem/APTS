from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.observability_diagnostics import build_integrity_gap_consistency_diagnostics
from mission_orchestrator.observability_live_projection import HASH_DOMAIN as LIVE_HASH_DOMAIN
from mission_orchestrator.observability_metrics import (
    SCHEMA_VERSION, build_observability_metrics_health,
    canonical_observability_metrics_health_definition,
    verify_observability_metrics_health,
)
from mission_orchestrator.observability_trace import sha256_hex
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService, MissionNotFound
from tests.test_stage3_1_1_identity_envelope import payload
from tests.test_stage3_8_7_integrity_gap_consistency_diagnostics import _inputs


def _service(tmp_path, key="stage388"):
    db = tmp_path / "mission.db"
    svc = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    mid = svc.create_mission(payload(key))["canonical_identity"]["mission_id"]
    return db, svc, mid


def _report(sources):
    diagnostics = build_integrity_gap_consistency_diagnostics(**sources)
    return build_observability_metrics_health(**sources, diagnostics=diagnostics)


def test_real_mission_report_is_read_only_restart_stable_and_source_bound(tmp_path):
    db, svc, mid = _service(tmp_path)
    before = svc.repository.list_mission_events(mid)
    first = svc.get_observability_metrics_health(mid)
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    assert first == restarted.get_observability_metrics_health(mid)
    assert svc.repository.list_mission_events(mid) == before
    report = first["report"]
    assert first["integrity_status"] == "PASS"
    assert report["observability_health"]["status"] == "HEALTHY"
    assert report["metrics"]["status"] == "AVAILABLE"
    assert report["metrics"]["event_count"] == len(before)
    assert report["operator_diagnostics"]["blocking_finding_count"] == 0
    assert verify_observability_metrics_health(report)


def test_metrics_count_categories_and_keep_external_refs_informational():
    report = _report(_inputs())
    metrics, operator = report["metrics"], report["operator_diagnostics"]
    assert report["observability_health"]["status"] == "HEALTHY"
    assert metrics["event_count"] == 4
    assert metrics["event_counts_by_type"]["MISSION_REGISTERED"] == 1
    assert metrics["event_counts_by_component"] == {"APTS-MO01": 4}
    assert metrics["decision_category_counts"] == {"DECISION": 1, "EVIDENCE": 1, "GOVERNANCE": 1}
    assert metrics["unresolved_external_causation_count"] == 1
    assert metrics["backward_timestamp_count"] == 0
    assert operator["finding_counts_by_code"]["UNRESOLVED_EXTERNAL_CAUSATION"] == 1
    assert operator["items"][0]["impact"] == "INFORMATIONAL"
    assert operator["diagnostics_path"] == "/api/missions/mission-synthetic/observability-diagnostics"
    assert report["semantics"]["time_based_rates_inferred"] is False


def test_consistency_finding_degrades_health_and_withholds_all_metrics():
    sources = _inputs()
    sources["live_projection"] = deepcopy(sources["live_projection"])
    live = sources["live_projection"]
    live["source_counts"]["normalized_event_count"] += 1
    core = dict(live)
    core.pop("integrity")
    live["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": LIVE_HASH_DOMAIN, "core": core})
    report = _report(sources)
    assert report["diagnostics_status"] == "FINDINGS"
    assert report["observability_health"]["status"] == "DEGRADED"
    assert report["metrics"]["status"] == "WITHHELD"
    assert report["metrics"]["event_count"] is None
    assert report["metrics"]["live_snapshot"] is None
    assert report["operator_diagnostics"]["finding_counts_by_code"]["LIVE_LEDGER_DIVERGENCE"] == 1
    assert any(item["impact"] == "REVIEW_REQUIRED" for item in report["operator_diagnostics"]["items"])
    assert verify_observability_metrics_health(report)


def test_unavailable_source_is_unknown_and_never_reported_as_zero():
    sources = _inputs()
    sources["causal_graph"] = None
    diagnostics = build_integrity_gap_consistency_diagnostics(
        **sources, source_errors={"causal_graph": "ValueError"})
    report = build_observability_metrics_health(**sources, diagnostics=diagnostics)
    assert report["observability_health"]["status"] == "UNKNOWN"
    assert report["metrics"]["event_count"] is None
    assert report["metrics"]["decision_event_count"] is None
    assert report["operator_diagnostics"]["unavailable_sources"] == ["causal_graph"]
    assert report["operator_diagnostics"]["source_status"]["normalized_events"] == "PASS"
    assert verify_observability_metrics_health(report)


def test_diagnostics_must_match_mission_and_exact_source_snapshot():
    sources = _inputs()
    diagnostics = build_integrity_gap_consistency_diagnostics(**sources)
    with pytest.raises(ValueError, match="cross-Mission"):
        build_observability_metrics_health(**{**sources, "mission_id": "another"}, diagnostics=diagnostics)
    changed = deepcopy(sources)
    changed["normalized_events"][0]["event_type"] = "TAMPERED"
    with pytest.raises(ValueError, match="source snapshot"):
        build_observability_metrics_health(**changed, diagnostics=diagnostics)
    modified = deepcopy(diagnostics)
    modified["finding_count"] = 17
    with pytest.raises(ValueError, match="invalid diagnostic"):
        build_observability_metrics_health(**sources, diagnostics=modified)


def test_mission_failure_state_does_not_relabel_observability_health():
    sources = _inputs()
    live = deepcopy(sources["live_projection"])
    live["mission"]["state"] = "FAILED"
    live["mission"]["terminal"] = True
    core = dict(live)
    core.pop("integrity")
    live["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": LIVE_HASH_DOMAIN, "core": core})
    sources["live_projection"] = live
    report = _report(sources)
    assert report["metrics"]["live_snapshot"]["mission_state"] == "FAILED"
    assert report["observability_health"]["status"] == "HEALTHY"
    assert report["observability_health"]["mission_success_asserted"] is False
    assert report["observability_health"]["runtime_liveness_asserted"] is False


def test_report_digest_detects_metric_and_operator_mutation():
    report = _report(_inputs())
    changed = deepcopy(report)
    changed["metrics"]["event_count"] += 1
    assert not verify_observability_metrics_health(changed)
    changed = deepcopy(report)
    changed["operator_diagnostics"]["items"][0]["impact"] = "REVIEW_REQUIRED"
    assert not verify_observability_metrics_health(changed)


def test_service_returns_unknown_when_stage387_source_read_fails(tmp_path, monkeypatch):
    _, svc, mid = _service(tmp_path, "stage388-source-failure")
    def unavailable(_mid):
        raise ValueError("source unavailable")
    monkeypatch.setattr(svc, "get_global_causal_lineage_graph", unavailable)
    result = svc.get_observability_metrics_health(mid)
    assert result["report"]["observability_health"]["status"] == "UNKNOWN"
    assert result["report"]["metrics"]["status"] == "WITHHELD"
    assert result["report"]["operator_diagnostics"]["unavailable_sources"] == [
        "causal_graph", "decision_trace", "timeline", "live_projection"]


def test_health_contract_unknown_mission_and_http_routes(tmp_path):
    _, svc, mid = _service(tmp_path, "stage388-http")
    with pytest.raises(MissionNotFound):
        svc.get_observability_metrics_health("mission-missing")
    definition = svc.get_observability_metrics_health_contract_definition()["definition"]
    assert definition == canonical_observability_metrics_health_definition()
    health = svc.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][-14:] == [
        "stage3.8.7-integrity-gap-consistency-diagnostics",
        "stage3.8.8-observability-metrics-health-operator-diagnostics",
        "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api",
        "stage3.8.10-observe-reconstruct-acceptance-regression-gate",
        "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract",
        "stage3.9.2-intake-lifecycle-e2e-segment-qualification",
        "stage3.9.3-planning-task-graph-dependency-verification",
        "stage3.9.4-routing-delegation-governance-continuity",
        "stage3.9.5-dispatch-execution-evidence-continuity",
        "stage3.9.6-task-completion-mission-outcome-closure",
        "stage3.9.7-adaptation-replanning-e2e-scenario",
        "stage3.9.8-restart-replay-recovery-e2e-verification",
        "stage3.9.9-global-observation-reconstruction-forensic-equivalence",
        "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == 53
    assert health["observability_metrics_health_schema_version"] == SCHEMA_VERSION
    assert health["observability_metrics_health_read_only"] is True
    assert health["observability_metrics_health_new_durable_store_added"] is False
    handler = type("MetricsHealthHandler", (MissionOrchestratorHandler,), {"service": svc})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/api/observability/metrics-health-contract") as response:
            assert response.status == 200
            assert json.load(response)["definition"]["schema_version"] == SCHEMA_VERSION
        with urlopen(base + f"/api/missions/{mid}/observability-metrics-health") as response:
            assert response.status == 200
            assert json.load(response)["report"]["observability_health"]["status"] == "HEALTHY"
        with pytest.raises(HTTPError) as exc:
            urlopen(base + "/api/missions/mission-missing/observability-metrics-health")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
