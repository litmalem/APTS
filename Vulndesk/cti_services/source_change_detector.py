from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from cti_source_config import adapter_type, apply_client_settings, parse_config


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SourceChangeDetector:
    """Lightweight, source-specific CTI change probes.

    The detector never writes CTI data. It only answers whether a source has
    changed since the durable source/monitor cursor so the adaptive scheduler
    can avoid expensive synchronization when nothing changed.
    """

    def probe(self, descriptor: Dict[str, Any], state: Optional[Dict[str, Any]] = None,
              environment: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        state = dict(state or {})
        environment = dict(environment or {})
        config = parse_config(descriptor.get("config_json"))
        kind = adapter_type(str(descriptor.get("source_id") or ""), config)
        now = _utcnow()
        if kind == "nvd-cve":
            return self._probe_nvd_cve(descriptor, state, environment, now)
        if kind == "nvd-cpe":
            return self._probe_nvd_cpe(descriptor, state, environment, now)
        if kind == "mitre-attack":
            return self._probe_mitre_attack(descriptor, state, environment, now)
        if kind == "mitre-cwe":
            return self._probe_mitre_cwe(descriptor, state, environment, now)
        return self._probe_conditional_http(descriptor, state, environment, now)

    @staticmethod
    def _window(descriptor: Dict[str, Any], state: Dict[str, Any], now: datetime) -> tuple[datetime, datetime]:
        # Prefer the synchronization watermark. If unavailable, use the last
        # successful acquisition/probe. Limit NVD windows to <120 days.
        start = (_parse_time(state.get("watermark_value")) or
                 _parse_time(state.get("last_success_at")) or
                 _parse_time(state.get("last_probe_at")))
        if start is None:
            sla = max(60, int(descriptor.get("freshness_sla_seconds") or 86400))
            start = now - timedelta(seconds=min(sla, 86400))
        floor = now - timedelta(days=119)
        if start < floor:
            start = floor
        if start > now:
            start = now
        return start, now

    def _probe_nvd_cve(self, descriptor, state, environment, now):
        from nvd_api import NvdApiClient
        start, end = self._window(descriptor, state, now)
        client = NvdApiClient()
        apply_client_settings(client, descriptor, environment)
        payload = client.fetch_modified_range(start_index=0, results_per_page=1,
                                              last_mod_start_date=start, last_mod_end_date=end)
        total = max(0, int(payload.get("totalResults") or 0))
        return self._result("LAST_MODIFIED_WINDOW", total > 0, now,
                            total_results=total, window_start=_iso(start), window_end=_iso(end))

    def _probe_nvd_cpe(self, descriptor, state, environment, now):
        from nvd_cpe_api import NvdCpeApiClient
        start, end = self._window(descriptor, state, now)
        client = NvdCpeApiClient()
        apply_client_settings(client, descriptor, environment)
        payload = client.fetch_modified_range(start_index=0, results_per_page=1,
                                              last_mod_start_date=start, last_mod_end_date=end)
        total = max(0, int(payload.get("totalResults") or 0))
        return self._result("LAST_MODIFIED_WINDOW", total > 0, now,
                            total_results=total, window_start=_iso(start), window_end=_iso(end))

    def _probe_mitre_attack(self, descriptor, state, environment, now):
        from mitre_attack_api import MitreAttackApiClient
        # TAXII added_after is not subject to NVD's 120-day date-window limit.
        start = (_parse_time(state.get("watermark_value")) or
                 _parse_time(state.get("last_success_at")) or
                 _parse_time(state.get("last_probe_at")))
        if start is None:
            sla = max(60, int(descriptor.get("freshness_sla_seconds") or 604800))
            start = now - timedelta(seconds=sla)
        if start > now:
            start = now
        client = MitreAttackApiClient()
        apply_client_settings(client, descriptor, environment)
        changed = client.has_changes_since(_iso(start))
        return self._result("ADDED_AFTER", changed, now, added_after=_iso(start), total_results=1 if changed else 0)

    def _probe_mitre_cwe(self, descriptor, state, environment, now):
        from cwe_api import CweApiClient
        client = CweApiClient()
        apply_client_settings(client, descriptor, environment)
        payload = client.get_version()
        fingerprint = _fingerprint(payload)
        previous = str(state.get("last_fingerprint") or "")
        # The first observation is deliberately treated as changed so a newly
        # configured source gets one governed synchronization and a baseline.
        changed = not previous or previous != fingerprint
        return self._result("VERSION_FINGERPRINT", changed, now,
                            fingerprint=fingerprint, source_version=payload)

    def _probe_conditional_http(self, descriptor, state, environment, now):
        # Generic fallback for registry-only/custom HTTPS JSON feeds. It uses a
        # conditional HEAD where possible and falls back to a tiny GET. This
        # detector does not make the source acquisition-capable by itself.
        import requests
        from cti_source_config import resolve_endpoint
        config = parse_config(descriptor.get("config_json"))
        kind = adapter_type(str(descriptor.get("source_id") or ""), config)
        url = resolve_endpoint(descriptor.get("endpoint_ref"), kind, environment)
        headers = {"Accept": "application/json", "User-Agent": "VulnDesk/1.3 Source Monitor"}
        if state.get("etag"):
            headers["If-None-Match"] = str(state["etag"])
        if state.get("last_modified_header"):
            headers["If-Modified-Since"] = str(state["last_modified_header"])
        timeout = max(1, min(int(config.get("timeout_seconds") or 30), 60))
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=False)
        if response.status_code in {405, 501}:
            response = requests.get(url, headers={**headers, "Range": "bytes=0-4095"}, timeout=timeout,
                                    allow_redirects=False, stream=True)
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        if response.status_code == 304:
            changed = False
        else:
            response.raise_for_status()
            if etag and state.get("etag"):
                changed = etag != state.get("etag")
            elif last_modified and state.get("last_modified_header"):
                changed = last_modified != state.get("last_modified_header")
            else:
                changed = True
        return self._result("HTTP_CONDITIONAL", changed, now,
                            etag=etag, last_modified_header=last_modified,
                            http_status=response.status_code)

    @staticmethod
    def _result(strategy: str, changed: bool, now: datetime, **extra: Any) -> Dict[str, Any]:
        return {
            "status": "CHANGED" if changed else "UNCHANGED",
            "changed": bool(changed),
            "detector_strategy": strategy,
            "checked_at": _iso(now),
            **extra,
        }
