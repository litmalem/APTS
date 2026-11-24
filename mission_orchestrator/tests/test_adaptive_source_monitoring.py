from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "Vulndesk_Web"
for path in (str(ROOT), str(WEB)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cti_services.source_change_detector import SourceChangeDetector
from cti_source_config import ADAPTERS
from adaptive_scheduler import AdaptiveSourceScheduler


def descriptor(kind, **extra):
    row = {
        "source_id": kind,
        "protocol": ADAPTERS[kind]["protocol"],
        "endpoint_ref": ADAPTERS[kind]["default_endpoint"],
        "credential_ref": None,
        "freshness_sla_seconds": 86400,
        "config_json": json.dumps({"adapter_type": kind, "auth_mode": "none"}),
    }
    row.update(extra)
    return row


def test_nvd_cpe_strategy_is_last_modified_window():
    assert ADAPTERS["nvd-cpe"]["strategy"] == "LAST_MODIFIED_WINDOW"


def test_nvd_cve_probe_uses_one_result_delta_request(monkeypatch):
    class Client:
        def __init__(self):
            self.base_url = ""
            self.session = types.SimpleNamespace(headers={})
            self.timeout_seconds = 30
            self.api_key = ""
            self.request_delay_seconds = 0
        def fetch_modified_range(self, **kwargs):
            assert kwargs["results_per_page"] == 1
            assert kwargs["last_mod_start_date"].tzinfo is not None
            return {"totalResults": 7, "vulnerabilities": []}
    module = types.SimpleNamespace(NvdApiClient=Client)
    monkeypatch.setitem(sys.modules, "nvd_api", module)
    result = SourceChangeDetector().probe(descriptor("nvd-cve"), {"watermark_value": "2026-10-06T00:00:00Z"}, {})
    assert result["changed"] is True
    assert result["total_results"] == 7
    assert result["detector_strategy"] == "LAST_MODIFIED_WINDOW"


def test_cwe_version_fingerprint_detects_only_version_change(monkeypatch):
    class Client:
        def __init__(self):
            self.base_url = ""
            self.session = types.SimpleNamespace(headers={})
            self.timeout = 30
        def get_version(self):
            return {"ContentVersion": "4.18"}
    monkeypatch.setitem(sys.modules, "cwe_api", types.SimpleNamespace(CweApiClient=Client))
    detector = SourceChangeDetector()
    first = detector.probe(descriptor("mitre-cwe"), {}, {})
    assert first["changed"] is True
    second = detector.probe(descriptor("mitre-cwe"), {"last_fingerprint": first["fingerprint"]}, {})
    assert second["changed"] is False


def test_adaptive_interval_grows_on_no_change_and_resets_on_change():
    adapter = MagicMock()
    adapter.root = ROOT
    scheduler = AdaptiveSourceScheduler(adapter)
    row = {"source_id": "nvd-cve", "freshness_sla_seconds": 86400, "unchanged_streak": 0}
    config = {"adaptive_min_interval_seconds": 300, "adaptive_max_interval_seconds": 3600}
    interval1, streak1 = scheduler._interval(row, {"changed": False, "checked_at": "2026-10-06T00:00:00Z"}, config)
    row["unchanged_streak"] = streak1
    interval2, streak2 = scheduler._interval(row, {"changed": False, "checked_at": "2026-10-06T00:05:00Z"}, config)
    reset, reset_streak = scheduler._interval(row, {"changed": True, "checked_at": "2026-10-06T00:10:00Z"}, config)
    assert streak1 == 1 and streak2 == 2 and reset_streak == 0
    assert interval2 > interval1
    assert 285 <= reset <= 315  # +/-5% deterministic jitter around 300s
