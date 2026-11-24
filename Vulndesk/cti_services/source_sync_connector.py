from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Optional

from .common import utcnow_iso
from cti_source_config import adapter_type, apply_client_settings, parse_config, source_binding


ProgressPublisher = Callable[[str, Dict[str, Any]], None]


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _parse_utc(value: Any) -> Optional[datetime]:
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


class SourceSyncConnector:
    """Adapter from CTI-A02 source proposals to VulnDesk's existing sync services.

    This is infrastructure, not an agent. It does not choose a source and it does
    not authorize acquisition. It only executes the source operation selected by
    CTI-A02 after an ALLOW policy decision.

    To avoid unexpectedly launching an unbounded NVD mirror from an agent event,
    the NVD-CVE and NVD-CPE adapters are bounded by default. The limits can be
    overridden in ``cti_source_registry.config_json`` or the mission acquisition
    objective.
    """

    COMPONENT_ID = "CTI-INF04"
    SERVICE_KEY = "cti_source_sync_connector"

    def __init__(self, progress_publisher: Optional[ProgressPublisher] = None, db=None):
        self.progress_publisher = progress_publisher
        self.db = db

    def execute(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        source_id = str(proposal.get("source_id") or "")
        if self.db is None:
            from .db_adapter import DbAdapter
            self.db = DbAdapter()
        descriptor = self.db.fetch_one(
            "SELECT source_id,protocol,endpoint_ref,credential_ref,config_json,enabled,freshness_sla_seconds FROM cti_source_registry WHERE source_id=%(source_id)s LIMIT 1",
            {"source_id": source_id},
        )
        if not descriptor or not descriptor.get("enabled"):
            raise ValueError("Sumber CTI telah dihapus atau dinonaktifkan; akuisisi tidak dijalankan.")
        if proposal.get("source_binding") and proposal["source_binding"] != source_binding(descriptor):
            raise ValueError("Konfigurasi sumber berubah setelah proposal. Buat misi akuisisi baru.")
        sync_config = parse_config(descriptor.get("config_json"))
        # Carry registry settings locally, never mutate process-wide Config or another source's client.
        sync_config = {**sync_config, "_descriptor": descriptor}
        kind = adapter_type(source_id, sync_config)
        if kind in {"ctid-cve-attack", "mitre-capec"}:
            from contextlib import contextmanager
            from mapping_source_services import sync
            from cti_source_config import resolve_endpoint
            @contextmanager
            def transaction():
                with self.db.connect() as connection:
                    with connection.cursor() as cursor:
                        yield cursor
            result = sync(kind, resolve_endpoint(descriptor['endpoint_ref'], kind, os.environ),
                          transaction, timeout=sync_config.get('timeout_seconds', 90))
            return self._outcome(source_id, result, watermark=result['sha256'])
        if kind == "nvd-cve":
            return self._sync_nvd_cve(proposal, sync_config)
        if kind == "nvd-cpe":
            return self._sync_nvd_cpe(proposal, sync_config)
        if kind == "mitre-attack":
            return self._sync_mitre_attack(proposal, sync_config)
        if kind == "mitre-cwe":
            return self._sync_mitre_cwe(proposal, sync_config)
        raise ValueError(f"No VulnDesk source-sync adapter registered for source_id={source_id}")

    @staticmethod
    def _configure(service, config):
        # Existing clients load .env through Config before this per-instance override.
        apply_client_settings(service.api_client, config["_descriptor"], os.environ)
        return service

    def _sync_nvd_cve(self, proposal: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        from services import SyncService

        max_pages = int(
            proposal.get("max_pages")
            or config.get("max_pages")
            or os.getenv("CTI_NVD_CVE_MAX_PAGES", "1")
        )
        page_size = int(
            proposal.get("page_size")
            or config.get("page_size")
            or os.getenv("CTI_NVD_CVE_PAGE_SIZE", "500")
        )
        source_id = proposal["source_id"]
        service = self._configure(SyncService(), config)
        result = service.run_incremental_sync(
            max_pages=max(1, max_pages),
            page_size=max(1, min(page_size, 2000)),
            progress_callback=lambda p: self._progress(source_id, p),
        )
        return self._outcome(source_id, result, watermark=result.get("checkpoint") or result.get("last_successful_modified_at"))

    def _sync_nvd_cpe(self, proposal: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        from cpe_dictionary_services import CpeDictionarySyncService

        source_id = proposal["source_id"]
        service = self._configure(CpeDictionarySyncService(), config)
        max_pages = int(
            proposal.get("max_pages")
            or config.get("max_pages")
            or os.getenv("CTI_NVD_CPE_MAX_PAGES", "1")
        )
        page_size = int(
            proposal.get("page_size")
            or config.get("page_size")
            or os.getenv("CTI_NVD_CPE_PAGE_SIZE", "500")
        )
        keyword = str(proposal.get("cpe_keyword") or config.get("keyword") or "").strip()
        match_string = str(proposal.get("cpe_match_string") or config.get("match_string") or "").strip()
        if match_string:
            result = service.sync_match_string(
                match_string,
                max_pages=max(1, max_pages),
                page_size=max(1, min(page_size, 2000)),
                progress_callback=lambda p: self._progress(source_id, p),
            )
        elif keyword:
            result = service.sync_keyword(
                keyword,
                max_pages=max(1, max_pages),
                page_size=max(1, min(page_size, 2000)),
                progress_callback=lambda p: self._progress(source_id, p),
            )
        else:
            # NVD CPE API 2.0 supports the same last-modified delta pattern as
            # the CVE API. The source-state watermark is the authoritative
            # cursor. A bounded PARTIAL result intentionally does not advance it.
            end = datetime.now(timezone.utc)
            start = _parse_utc(proposal.get("query_window_or_cursor"))
            if start is None:
                lookback = max(60, int(config.get("_descriptor", {}).get("freshness_sla_seconds") or 86400))
                start = end - timedelta(seconds=min(lookback, 86400))
            start = max(start, end - timedelta(days=119))
            result = service.sync_modified_range(
                last_mod_start_date=start,
                last_mod_end_date=end,
                max_pages=max(1, max_pages),
                page_size=max(1, min(page_size, 2000)),
                progress_callback=lambda p: self._progress(source_id, p),
            )
        watermark = result.get("last_successful_modified_at") if str(result.get("status") or "").upper() == "SUCCESS" else None
        return self._outcome(source_id, result, watermark=watermark)

    def _sync_mitre_attack(self, proposal: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        from mitre_attack_services import MitreAttackSyncService

        mode = str(proposal.get("sync_mode") or config.get("sync_mode") or "INCREMENTAL").upper()
        source_id = proposal["source_id"]
        service = self._configure(MitreAttackSyncService(), config)
        if mode == "FULL":
            result = service.run_full_sync(progress_callback=lambda p: self._progress(source_id, p))
        else:
            result = service.run_incremental_sync(progress_callback=lambda p: self._progress(source_id, p))
        return self._outcome(source_id, result, watermark=utcnow_iso())

    def _sync_mitre_cwe(self, proposal: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        import re
        from cwe_services import CweSyncService

        source_id = proposal["source_id"]
        mode = str(proposal.get("sync_mode") or config.get("sync_mode") or "KNOWN").upper()
        service = self._configure(CweSyncService(), config)
        progress = lambda p: self._progress(source_id, p)
        if mode == "KNOWN":
            # Perkaya semua stub CWE (dibuat saat impor CVE) yang nama/deskripsinya kosong.
            result = service.sync_known_cwes(only_missing_details=True, progress_callback=progress)
        elif mode == "RANGE":
            start_id = int(config.get("cwe_range_start") or 1)
            end_id = int(config.get("cwe_range_end") or 1500)
            result = service.sync_range(start_id, end_id, progress_callback=progress)
        else:
            cwe_id = str(config.get("cwe_id") or "CWE-20")
            if not re.fullmatch(r"CWE-[1-9][0-9]{0,4}", cwe_id):
                raise ValueError("CWE ID sumber tidak valid.")
            result = service.sync_single_cwe(cwe_id, progress_callback=progress)
        return self._outcome(source_id, result, watermark=utcnow_iso())

    def _progress(self, source_id: str, payload: Dict[str, Any]) -> None:
        if self.progress_publisher:
            self.progress_publisher(source_id, _json_safe(payload))

    @staticmethod
    def _outcome(source_id: str, result: Dict[str, Any], watermark: Any = None) -> Dict[str, Any]:
        result = _json_safe(result or {})
        sync_status = str(result.get("status") or "SUCCESS").upper()
        success = sync_status in {"SUCCESS", "COMPLETED", "OK"}
        partial = sync_status == "PARTIAL"
        return {
            "source_id": source_id,
            "http_status": 200 if success or partial else 503,
            "validation_status": "valid" if success else ("partial" if partial else "failed"),
            "sync_status": sync_status,
            "watermark_after_candidate": _json_safe(watermark),
            "retrieved_at": utcnow_iso(),
            "result": result,
        }
