from __future__ import annotations

from typing import Callable

from config import Config
from cwe_api import CweApiClient
from cwe_mapper import (
    api_version_from_payload,
    extract_cwe_objects,
    map_cwe_object,
    normalize_cwe_id,
)
from cwe_repositories import CweCatalogRepository
from db import session_scope
from repositories import SyncAuditRepository

ProgressCallback = Callable[[dict], None]


class CweService:
    def list_cwes(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        with session_scope() as session:
            repo = CweCatalogRepository(session)
            return repo.list_items(keyword=keyword, limit=limit, offset=offset)

    def count_cwes(self, keyword: str | None = None) -> int:
        with session_scope() as session:
            repo = CweCatalogRepository(session)
            return repo.count_items(keyword=keyword)

    def get_cwe_detail(self, cwe_id: str) -> dict | None:
        with session_scope() as session:
            repo = CweCatalogRepository(session)
            return repo.get_detail_by_cwe_id(cwe_id)


class CweSyncService:
    def __init__(self) -> None:
        self.api_client = CweApiClient()

    def _get_api_version(self) -> str | None:
        try:
            payload = self.api_client.get_version()
            return api_version_from_payload(payload)
        except Exception:
            return None

    def _emit(self, progress_callback: ProgressCallback | None, payload: dict) -> None:
        if progress_callback:
            progress_callback(payload)

    def sync_single_cwe(self, cwe_id: str, progress_callback: ProgressCallback | None = None) -> dict:
        normalized = normalize_cwe_id(cwe_id)
        if not normalized or not normalized.startswith("CWE-"):
            raise ValueError(f"CWE ID tidak valid: {cwe_id}")

        api_version = self._get_api_version()
        with session_scope() as session:
            audit_repo = SyncAuditRepository(session)
            repo = CweCatalogRepository(session)
            audit = audit_repo.create_running(sync_type="CWE_SINGLE", page_size=1)
            session.commit()
            total_fetched = 0
            total_inserted = 0
            total_updated = 0
            total_failed = 0
            try:
                payload = self.api_client.fetch_weakness(normalized)
                objects = extract_cwe_objects(payload)
                if not objects:
                    raise ValueError(f"MITRE CWE API tidak mengembalikan objek untuk {normalized}")
                for obj in objects:
                    mapped = map_cwe_object(obj, api_version=api_version)
                    if mapped is None:
                        continue
                    action, _ = repo.upsert_mapped_cwe(mapped)
                    total_fetched += 1
                    if action == "inserted":
                        total_inserted += 1
                    else:
                        total_updated += 1
                session.commit()
                self._emit(progress_callback, {
                    "mode": "CWE_SINGLE", "current_page": 1, "total_pages": 1,
                    "current_type": normalized, "total_fetched": total_fetched,
                    "total_inserted": total_inserted, "total_updated": total_updated,
                    "total_failed": total_failed,
                })
                audit_repo.mark_success(audit, total_fetched, total_inserted, total_updated, total_failed)
                session.commit()
                return {
                    "status": "SUCCESS", "mode": "CWE_SINGLE", "total_fetched": total_fetched,
                    "total_inserted": total_inserted, "total_updated": total_updated,
                    "total_failed": total_failed,
                }
            except Exception as exc:
                session.rollback()
                with session_scope() as session2:
                    audit_repo2 = SyncAuditRepository(session2)
                    audit2 = session2.get(type(audit), audit.id)
                    if audit2 is not None:
                        audit_repo2.mark_failed(audit2, str(exc), total_fetched, total_inserted, total_updated, total_failed + 1)
                        session2.commit()
                raise

    def sync_known_cwes(self, only_missing_details: bool = True, progress_callback: ProgressCallback | None = None) -> dict:
        with session_scope() as session:
            repo = CweCatalogRepository(session)
            cwe_ids = repo.list_known_cwe_ids(only_missing_details=only_missing_details)

        # One complete snapshot includes deprecated categories as well as weaknesses.
        catalog, api_version = self.api_client.fetch_catalog() if cwe_ids else ({}, None)
        return self._sync_cwe_id_list(cwe_ids, mode="CWE_KNOWN", api_version=api_version,
                                     progress_callback=progress_callback, catalog=catalog)

    def sync_range(self, start_id: int | None = None, end_id: int | None = None, progress_callback: ProgressCallback | None = None) -> dict:
        start_id = int(start_id if start_id is not None else Config.CWE_DEFAULT_RANGE_START)
        end_id = int(end_id if end_id is not None else Config.CWE_DEFAULT_RANGE_END)
        if start_id < 1:
            start_id = 1
        if end_id < start_id:
            raise ValueError("Range CWE tidak valid: end_id lebih kecil dari start_id")
        api_version = self._get_api_version()
        cwe_ids = [f"CWE-{i}" for i in range(start_id, end_id + 1)]
        return self._sync_cwe_id_list(cwe_ids, mode="CWE_RANGE", api_version=api_version, progress_callback=progress_callback)

    def sync_view(self, view_id: int | None = None, progress_callback: ProgressCallback | None = None) -> dict:
        view_id = int(view_id if view_id is not None else Config.CWE_DEFAULT_VIEW_ID)
        api_version = self._get_api_version()

        with session_scope() as session:
            audit_repo = SyncAuditRepository(session)
            repo = CweCatalogRepository(session)
            audit = audit_repo.create_running(sync_type="CWE_VIEW", page_size=None)
            session.commit()
            total_fetched = 0
            total_inserted = 0
            total_updated = 0
            total_failed = 0
            try:
                payload = self.api_client.fetch_view(view_id)
                objects = extract_cwe_objects(payload)
                if len(objects) <= 1:
                    raise ValueError(
                        f"MITRE CWE API view {view_id} tidak mengembalikan daftar CWE yang cukup untuk bulk import. "
                        "Gunakan Sync Range untuk mengunggah katalog CWE secara bertahap, atau Sync Known untuk memperkaya CWE yang sudah ada dari data CVE."
                    )
                total_pages = len(objects)
                for idx, obj in enumerate(objects, start=1):
                    try:
                        mapped = map_cwe_object(obj, api_version=api_version)
                        if mapped is None:
                            continue
                        action, _ = repo.upsert_mapped_cwe(mapped)
                        total_fetched += 1
                        if action == "inserted":
                            total_inserted += 1
                        else:
                            total_updated += 1
                    except Exception as item_error:
                        total_failed += 1
                        print(f"[CWE_VIEW] failed object idx={idx}: {item_error}")
                    if idx % 50 == 0:
                        session.commit()
                    self._emit(progress_callback, {
                        "mode": "CWE_VIEW", "current_page": idx, "total_pages": total_pages,
                        "current_type": f"view={view_id}", "total_fetched": total_fetched,
                        "total_inserted": total_inserted, "total_updated": total_updated,
                        "total_failed": total_failed,
                    })
                session.commit()
                audit_repo.mark_success(audit, total_fetched, total_inserted, total_updated, total_failed)
                session.commit()
                return {
                    "status": "SUCCESS", "mode": "CWE_VIEW", "total_fetched": total_fetched,
                    "total_inserted": total_inserted, "total_updated": total_updated,
                    "total_failed": total_failed,
                }
            except Exception as exc:
                session.rollback()
                with session_scope() as session2:
                    audit_repo2 = SyncAuditRepository(session2)
                    audit2 = session2.get(type(audit), audit.id)
                    if audit2 is not None:
                        audit_repo2.mark_failed(audit2, str(exc), total_fetched, total_inserted, total_updated, total_failed)
                        session2.commit()
                raise

    def _sync_cwe_id_list(
        self,
        cwe_ids: list[str],
        mode: str,
        api_version: str | None,
        progress_callback: ProgressCallback | None = None,
        catalog: dict[str, dict] | None = None,
    ) -> dict:
        with session_scope() as session:
            audit_repo = SyncAuditRepository(session)
            repo = CweCatalogRepository(session)
            audit = audit_repo.create_running(sync_type=mode, page_size=len(cwe_ids) or None)
            session.commit()

            total_fetched = 0
            total_inserted = 0
            total_updated = 0
            total_failed = 0
            total_pages = max(len(cwe_ids), 1)

            try:
                if not cwe_ids:
                    self._emit(progress_callback, {
                        "mode": mode, "current_page": 1, "total_pages": 1,
                        "current_type": "no CWE to sync", "total_fetched": 0,
                        "total_inserted": 0, "total_updated": 0, "total_failed": 0,
                    })

                for idx, cwe_id in enumerate(cwe_ids, start=1):
                    try:
                        if catalog is None:
                            payload = self.api_client.fetch_weakness(cwe_id)
                        else:
                            payload = catalog.get(cwe_id)
                        objects = extract_cwe_objects(payload)
                        if not objects:
                            raise ValueError(f"No CWE object returned for {cwe_id}")
                        for obj in objects:
                            mapped = map_cwe_object(obj, api_version=api_version)
                            if mapped is None or not mapped.get('cwe_name'):
                                raise ValueError(f"Nama CWE tidak tersedia untuk {cwe_id}")
                            action, _ = repo.upsert_mapped_cwe(mapped)
                            total_fetched += 1
                            if action == "inserted":
                                total_inserted += 1
                            else:
                                total_updated += 1
                    except Exception as item_error:
                        total_failed += 1
                        print(f"[{mode}] failed cwe_id={cwe_id}: {item_error}")

                    if idx % 25 == 0:
                        session.commit()
                    self._emit(progress_callback, {
                        "mode": mode, "current_page": idx, "total_pages": total_pages,
                        "current_type": cwe_id, "total_fetched": total_fetched,
                        "total_inserted": total_inserted, "total_updated": total_updated,
                        "total_failed": total_failed,
                    })

                session.commit()
                status = 'SUCCESS' if not total_failed else ('PARTIAL' if total_fetched else 'FAILED')
                audit_repo.mark_success(audit, total_fetched, total_inserted, total_updated, total_failed)
                audit.status_value = status
                if total_failed:
                    audit.error_message = f"{total_failed} CWE gagal diperkaya; periksa ID dan sumber katalog."
                session.commit()
                return {
                    "status": status, "mode": mode, "total_fetched": total_fetched,
                    "total_inserted": total_inserted, "total_updated": total_updated,
                    "total_failed": total_failed,
                }
            except Exception as exc:
                session.rollback()
                with session_scope() as session2:
                    audit_repo2 = SyncAuditRepository(session2)
                    audit2 = session2.get(type(audit), audit.id)
                    if audit2 is not None:
                        audit_repo2.mark_failed(audit2, str(exc), total_fetched, total_inserted, total_updated, total_failed)
                        session2.commit()
                raise
