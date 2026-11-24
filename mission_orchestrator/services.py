from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time

from config import Config
from db import session_scope
from nvd_api import NvdApiClient
from nvd_mapper import NvdMapper
from repositories import (
    VulnerabilityRepository,
    UpsertRepository,
    SyncAuditRepository,
    SyncStateRepository,
)


FULL_SYNC_CHECKPOINT_KEY = "nvd_full_sync_start_index"
INCREMENTAL_SYNC_CHECKPOINT_KEY = "nvd_incremental_checkpoint"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_db_utc(value: datetime | None) -> datetime | None:
    """Store UTC in timezone-naive SQL DATETIME columns consistently."""
    if value is None:
        return None
    return _as_utc(value).replace(tzinfo=None, microsecond=0)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


class VulnerabilityService:
    def get_list(self, filters: dict) -> list[dict]:
        with session_scope() as session:
            repo = VulnerabilityRepository(session)
            return repo.list_items(filters)

    def get_total_count(self, filters: dict) -> int:
        with session_scope() as session:
            repo = VulnerabilityRepository(session)
            return repo.count_items(filters)

    def get_database_total_count(self) -> int:
        """Return the total number of vulnerability records without UI filters."""
        with session_scope() as session:
            repo = VulnerabilityRepository(session)
            return repo.count_items({})

    def get_detail(self, vulnerability_id: int) -> dict | None:
        with session_scope() as session:
            repo = VulnerabilityRepository(session)
            return repo.get_detail_by_id(vulnerability_id)


class SyncService:
    def __init__(self):
        self.api_client = NvdApiClient()

    @staticmethod
    def _database_error_code(error: Exception) -> int | None:
        current = error
        for _ in range(5):
            original = getattr(current, "orig", None)
            args = getattr(original or current, "args", ())
            if args and isinstance(args[0], int):
                return int(args[0])
            if original is None or original is current:
                break
            current = original
        return None

    @classmethod
    def _is_transient_database_error(cls, error: Exception) -> bool:
        code = cls._database_error_code(error)
        if code in {1205, 1213, 2006, 2013, 2014, 2045, 2055}:
            return True
        message = str(error).lower()
        return any(
            token in message
            for token in (
                "server has gone away",
                "lost connection",
                "connection was killed",
                "connection invalidated",
                "deadlock",
                "lock wait timeout",
            )
        )

    @classmethod
    def _process_items(cls, session, upsert_repo, items: list[dict], mode: str) -> dict:
        # ``session`` and ``upsert_repo`` are retained in the signature for
        # compatibility, but writes intentionally use a fresh Session per batch.
        del session, upsert_repo

        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        max_modified_at: datetime | None = None
        first_error: Exception | None = None

        mapped_items: list[tuple[dict, dict]] = []
        for item in items:
            try:
                mapped = NvdMapper.map_full(item)
                if not mapped.get("vulnerability", {}).get("cve_id"):
                    raise ValueError("NVD item has no CVE ID")
                mapped_items.append((item, mapped))
            except Exception as item_error:
                failed += 1
                if first_error is None:
                    first_error = item_error
                cve_id = item.get("cve", {}).get("id") if isinstance(item, dict) else None
                print(f"[{mode} SYNC] mapping failed cve={cve_id}: {item_error}")

        def register_success(batch: list[tuple[dict, dict]], stats: dict) -> None:
            nonlocal inserted, updated, skipped, max_modified_at
            inserted += int(stats.get("inserted", 0))
            updated += int(stats.get("updated", 0))
            skipped += int(stats.get("skipped", 0))
            for _, mapped in batch:
                modified_at = mapped["vulnerability"].get("modified_at")
                if modified_at is not None:
                    modified_at = _as_utc(modified_at)
                    if max_modified_at is None or modified_at > max_modified_at:
                        max_modified_at = modified_at

        def persist_once(batch: list[tuple[dict, dict]]) -> dict:
            with session_scope() as batch_session:
                repo = UpsertRepository(batch_session)
                stats = repo.bulk_upsert_mapped_vulnerabilities(
                    [mapped for _, mapped in batch],
                    skip_unchanged=Config.NVD_SKIP_UNCHANGED,
                )
                batch_session.commit()
                return stats

        def persist_with_retry(batch: list[tuple[dict, dict]]) -> dict:
            last_error: Exception | None = None
            for attempt in range(Config.NVD_DB_TRANSIENT_RETRIES + 1):
                try:
                    return persist_once(batch)
                except Exception as error:
                    last_error = error
                    if not cls._is_transient_database_error(error):
                        raise
                    if attempt >= Config.NVD_DB_TRANSIENT_RETRIES:
                        raise
                    delay = Config.NVD_DB_RETRY_BASE_SECONDS * (2 ** attempt)
                    time.sleep(delay)
            assert last_error is not None
            raise last_error

        def persist_adaptive(batch: list[tuple[dict, dict]], offset: int) -> None:
            nonlocal failed, first_error
            if not batch:
                return
            try:
                stats = persist_with_retry(batch)
                register_success(batch, stats)
                return
            except Exception as error:
                code = cls._database_error_code(error)
                first_cve = batch[0][1]["vulnerability"]["cve_id"]
                last_cve = batch[-1][1]["vulnerability"]["cve_id"]
                print(
                    f"[{mode} SYNC] DB batch offset={offset} size={len(batch)} "
                    f"cve={first_cve}..{last_cve} code={code} failed: "
                    f"{type(error).__name__}: {error}"
                )
                if len(batch) > 1:
                    midpoint = len(batch) // 2
                    persist_adaptive(batch[:midpoint], offset)
                    persist_adaptive(batch[midpoint:], offset + midpoint)
                    return
                failed += 1
                if first_error is None:
                    first_error = error

        batch_size = Config.NVD_DB_BATCH_SIZE
        for offset in range(0, len(mapped_items), batch_size):
            persist_adaptive(mapped_items[offset : offset + batch_size], offset)

        if failed:
            cve_id = None
            for _, mapped in mapped_items:
                cve_id = mapped.get("vulnerability", {}).get("cve_id")
                if cve_id:
                    break
            raise RuntimeError(
                f"{failed} CVE gagal disimpan pada halaman NVD. Checkpoint tidak "
                f"dimajukan. Penyebab pertama: {type(first_error).__name__}: {first_error}"
            ) from first_error

        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "max_modified_at": max_modified_at,
        }

    @staticmethod
    def _mark_failed(
        audit,
        error: Exception,
        total_fetched: int,
        total_inserted: int,
        total_updated: int,
        total_failed: int,
    ) -> None:
        with session_scope() as session:
            audit_repo = SyncAuditRepository(session)
            audit_row = session.get(type(audit), audit.id)
            if audit_row is not None:
                audit_repo.mark_failed(
                    audit=audit_row,
                    error_message=str(error),
                    total_fetched=total_fetched,
                    total_inserted=total_inserted,
                    total_updated=total_updated,
                    total_failed=total_failed,
                )
                session.commit()

    def run_full_sync(
        self,
        max_pages: int | None = None,
        page_size: int | None = None,
        progress_callback=None,
    ) -> dict:
        """Mirror all NVD CVEs, resuming from the last committed page.

        ``max_pages`` remains available for diagnostics. Normal application use
        passes ``None`` so pagination continues until ``totalResults`` is reached.
        """
        page_size = max(1, min(int(page_size or Config.NVD_PAGE_SIZE), 2000))
        max_pages = None if max_pages is None else max(1, int(max_pages))

        with session_scope() as session:
            upsert_repo = UpsertRepository(session)
            audit_repo = SyncAuditRepository(session)
            state_repo = SyncStateRepository(session)

            audit = audit_repo.create_running(sync_type="FULL", page_size=page_size)
            session.commit()

            start_index = max(0, state_repo.get_int(FULL_SYNC_CHECKPOINT_KEY, 0))
            initial_start_index = start_index
            total_results: int | None = None
            processed_pages = 0
            total_fetched = 0
            total_inserted = 0
            total_updated = 0
            total_skipped = 0
            total_failed = 0
            max_modified_at: datetime | None = None

            try:
                while True:
                    payload = self.api_client.fetch_page(
                        start_index=start_index,
                        results_per_page=page_size,
                    )
                    vulnerabilities = payload.get("vulnerabilities") or []
                    total_results = max(0, int(payload.get("totalResults") or 0))

                    # A completed checkpoint can remain after an abrupt shutdown
                    # between the final page commit and checkpoint cleanup.
                    if (
                        not vulnerabilities
                        and start_index > 0
                        and total_results > 0
                        and start_index >= total_results
                        and processed_pages == 0
                    ):
                        state_repo.delete(FULL_SYNC_CHECKPOINT_KEY)
                        session.commit()
                        start_index = 0
                        initial_start_index = 0
                        continue

                    if not vulnerabilities:
                        break

                    page_stats = self._process_items(
                        session=session,
                        upsert_repo=upsert_repo,
                        items=vulnerabilities,
                        mode="FULL",
                    )
                    total_fetched += len(vulnerabilities)
                    total_inserted += page_stats["inserted"]
                    total_updated += page_stats["updated"]
                    total_skipped += page_stats["skipped"]
                    total_failed += page_stats["failed"]

                    page_max_modified = page_stats["max_modified_at"]
                    if page_max_modified is not None and (
                        max_modified_at is None or page_max_modified > max_modified_at
                    ):
                        max_modified_at = page_max_modified

                    next_start_index = start_index + len(vulnerabilities)
                    state_repo.set(FULL_SYNC_CHECKPOINT_KEY, str(next_start_index))
                    session.commit()

                    processed_pages += 1
                    total_pages = max(1, math.ceil(total_results / page_size))
                    current_page = min(total_pages, math.ceil(next_start_index / page_size))

                    if progress_callback:
                        progress_callback(
                            {
                                "mode": "FULL",
                                "current_page": current_page,
                                "total_pages": total_pages,
                                "current_type": f"startIndex={start_index}",
                                "total_results": total_results,
                                "total_fetched": total_fetched,
                                "total_inserted": total_inserted,
                                "total_updated": total_updated,
                                "total_skipped": total_skipped,
                                "total_failed": total_failed,
                            }
                        )

                    start_index = next_start_index
                    is_complete = start_index >= total_results
                    page_cap_reached = max_pages is not None and processed_pages >= max_pages

                    if is_complete or page_cap_reached:
                        break

                is_complete = total_results is not None and start_index >= total_results

                if is_complete:
                    state_repo.delete(FULL_SYNC_CHECKPOINT_KEY)
                    audit_repo.mark_success(
                        audit=audit,
                        total_fetched=total_fetched,
                        total_inserted=total_inserted,
                        total_updated=total_updated,
                        total_failed=total_failed,
                        last_successful_modified_at=_as_db_utc(max_modified_at),
                    )
                    status = "SUCCESS"
                else:
                    audit_repo.mark_partial(
                        audit=audit,
                        total_fetched=total_fetched,
                        total_inserted=total_inserted,
                        total_updated=total_updated,
                        total_failed=total_failed,
                        last_successful_modified_at=_as_db_utc(max_modified_at),
                    )
                    status = "PARTIAL"

                session.commit()
                return {
                    "status": status,
                    "mode": "FULL",
                    "initial_start_index": initial_start_index,
                    "next_start_index": 0 if is_complete else start_index,
                    "total_results": total_results or 0,
                    "total_fetched": total_fetched,
                    "total_inserted": total_inserted,
                    "total_updated": total_updated,
                    "total_skipped": total_skipped,
                    "total_failed": total_failed,
                    "last_successful_modified_at": _as_db_utc(max_modified_at),
                }

            except Exception as error:
                session.rollback()
                self._mark_failed(
                    audit=audit,
                    error=error,
                    total_fetched=total_fetched,
                    total_inserted=total_inserted,
                    total_updated=total_updated,
                    total_failed=total_failed,
                )
                raise

    def run_incremental_sync(
        self,
        max_pages: int | None = None,
        page_size: int | None = None,
        progress_callback=None,
    ) -> dict:
        """Synchronize every modified CVE in complete <=120-day windows.

        A window checkpoint is advanced only after every page in that window has
        committed. If the process fails mid-window, the next run safely repeats
        that window from page zero and relies on upsert idempotency.
        """
        page_size = max(1, min(int(page_size or Config.NVD_PAGE_SIZE), 2000))
        max_pages = None if max_pages is None else max(1, int(max_pages))
        window_delta = timedelta(days=Config.NVD_INCREMENTAL_WINDOW_DAYS)

        with session_scope() as session:
            upsert_repo = UpsertRepository(session)
            audit_repo = SyncAuditRepository(session)
            state_repo = SyncStateRepository(session)

            checkpoint = _parse_iso_datetime(
                state_repo.get(INCREMENTAL_SYNC_CHECKPOINT_KEY)
            )
            if checkpoint is None:
                latest_audit_time = audit_repo.get_latest_successful_incremental_time()
                if latest_audit_time is not None:
                    checkpoint = _as_utc(latest_audit_time)
            if checkpoint is None:
                checkpoint = _parse_iso_datetime(Config.NVD_INCREMENTAL_INITIAL_START)
            if checkpoint is None:
                raise ValueError(
                    "Invalid NVD_INCREMENTAL_INITIAL_START; use an ISO-8601 datetime"
                )

            sync_end = datetime.now(timezone.utc)
            if checkpoint > sync_end:
                checkpoint = sync_end

            audit = audit_repo.create_running(
                sync_type="INCREMENTAL",
                page_size=page_size,
            )
            session.commit()

            total_fetched = 0
            total_inserted = 0
            total_updated = 0
            total_skipped = 0
            total_failed = 0
            processed_pages = 0
            completed_windows = 0
            current_checkpoint = checkpoint

            total_seconds = max(0.0, (sync_end - checkpoint).total_seconds())
            total_windows = max(
                1,
                math.ceil(total_seconds / max(1.0, window_delta.total_seconds())),
            )

            try:
                window_start = checkpoint

                while window_start < sync_end:
                    window_end = min(window_start + window_delta, sync_end)
                    start_index = 0
                    window_page = 0
                    window_total_pages = 1
                    window_complete = False

                    while True:
                        payload = self.api_client.fetch_modified_range(
                            start_index=start_index,
                            results_per_page=page_size,
                            last_mod_start_date=window_start,
                            last_mod_end_date=window_end,
                        )
                        vulnerabilities = payload.get("vulnerabilities") or []
                        window_total_results = max(
                            0,
                            int(payload.get("totalResults") or 0),
                        )
                        window_total_pages = max(
                            1,
                            math.ceil(window_total_results / page_size),
                        )

                        if not vulnerabilities:
                            window_complete = start_index >= window_total_results
                            break

                        page_stats = self._process_items(
                            session=session,
                            upsert_repo=upsert_repo,
                            items=vulnerabilities,
                            mode="INCREMENTAL",
                        )
                        total_fetched += len(vulnerabilities)
                        total_inserted += page_stats["inserted"]
                        total_updated += page_stats["updated"]
                        total_skipped += page_stats["skipped"]
                        total_failed += page_stats["failed"]
                        session.commit()

                        processed_pages += 1
                        window_page += 1
                        start_index += len(vulnerabilities)
                        window_complete = start_index >= window_total_results

                        if progress_callback:
                            progress_callback(
                                {
                                    "mode": "INCREMENTAL",
                                    "current_page": completed_windows + 1,
                                    "total_pages": total_windows,
                                    "current_type": (
                                        f"window {completed_windows + 1}/{total_windows} "
                                        f"page {window_page}/{window_total_pages}"
                                    ),
                                    "window_start": window_start.isoformat(),
                                    "window_end": window_end.isoformat(),
                                    "window_total_results": window_total_results,
                                    "total_fetched": total_fetched,
                                    "total_inserted": total_inserted,
                                    "total_updated": total_updated,
                                    "total_skipped": total_skipped,
                                    "total_failed": total_failed,
                                }
                            )

                        if window_complete:
                            break
                        if max_pages is not None and processed_pages >= max_pages:
                            break

                    page_cap_reached = (
                        max_pages is not None
                        and processed_pages >= max_pages
                        and not window_complete
                    )
                    if page_cap_reached:
                        audit_repo.mark_partial(
                            audit=audit,
                            total_fetched=total_fetched,
                            total_inserted=total_inserted,
                            total_updated=total_updated,
                            total_failed=total_failed,
                            last_successful_modified_at=_as_db_utc(current_checkpoint),
                        )
                        session.commit()
                        return {
                            "status": "PARTIAL",
                            "mode": "INCREMENTAL",
                            "checkpoint": current_checkpoint,
                            "total_fetched": total_fetched,
                            "total_inserted": total_inserted,
                            "total_updated": total_updated,
                            "total_skipped": total_skipped,
                            "total_failed": total_failed,
                            "last_successful_modified_at": _as_db_utc(current_checkpoint),
                        }

                    # Advance only after the complete window is safely committed.
                    current_checkpoint = window_end
                    state_repo.set(
                        INCREMENTAL_SYNC_CHECKPOINT_KEY,
                        current_checkpoint.isoformat(),
                    )
                    audit.last_successful_modified_at = _as_db_utc(current_checkpoint)
                    session.commit()

                    completed_windows += 1
                    window_start = window_end

                    if (
                        max_pages is not None
                        and processed_pages >= max_pages
                        and window_start < sync_end
                    ):
                        audit_repo.mark_partial(
                            audit=audit,
                            total_fetched=total_fetched,
                            total_inserted=total_inserted,
                            total_updated=total_updated,
                            total_failed=total_failed,
                            last_successful_modified_at=_as_db_utc(current_checkpoint),
                        )
                        session.commit()
                        return {
                            "status": "PARTIAL",
                            "mode": "INCREMENTAL",
                            "checkpoint": current_checkpoint,
                            "completed_windows": completed_windows,
                            "total_fetched": total_fetched,
                            "total_inserted": total_inserted,
                            "total_updated": total_updated,
                            "total_skipped": total_skipped,
                            "total_failed": total_failed,
                            "last_successful_modified_at": _as_db_utc(current_checkpoint),
                        }

                audit_repo.mark_success(
                    audit=audit,
                    total_fetched=total_fetched,
                    total_inserted=total_inserted,
                    total_updated=total_updated,
                    total_failed=total_failed,
                    last_successful_modified_at=_as_db_utc(sync_end),
                )
                state_repo.set(INCREMENTAL_SYNC_CHECKPOINT_KEY, sync_end.isoformat())
                session.commit()

                return {
                    "status": "SUCCESS",
                    "mode": "INCREMENTAL",
                    "checkpoint": sync_end,
                    "completed_windows": completed_windows,
                    "total_fetched": total_fetched,
                    "total_inserted": total_inserted,
                    "total_updated": total_updated,
                    "total_skipped": total_skipped,
                    "total_failed": total_failed,
                    "last_successful_modified_at": _as_db_utc(sync_end),
                }

            except Exception as error:
                session.rollback()
                self._mark_failed(
                    audit=audit,
                    error=error,
                    total_fetched=total_fetched,
                    total_inserted=total_inserted,
                    total_updated=total_updated,
                    total_failed=total_failed,
                )
                raise
