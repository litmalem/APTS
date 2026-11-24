from __future__ import annotations

import json
import math

from PySide6.QtCore import QThread, Signal

from cti_enrichment_ui import CtiEnrichmentPage


class _LoadWorker(QThread):
    finished = Signal(list, int)

    def __init__(self, db_adapter, mission_filter: str, page: int, page_size: int):
        super().__init__()
        self._db = db_adapter
        self._mission = mission_filter.strip()
        self._page = page
        self._page_size = page_size

    def run(self):
        try:
            if self._mission:
                count_sql = "SELECT COUNT(*) AS cnt FROM cti_wpt_verified_evidence WHERE mission_id = %(mid)s"
                count_params = {"mid": self._mission}
                data_sql = (
                    "SELECT intake_id, mission_id, task_id, recon_run_id, "
                    "input_sha256, evidence_manifest_sha256, result_json, created_at "
                    "FROM cti_wpt_verified_evidence WHERE mission_id = %(mid)s "
                    "ORDER BY created_at DESC LIMIT %(limit)s OFFSET %(offset)s"
                )
            else:
                count_sql = "SELECT COUNT(*) AS cnt FROM cti_wpt_verified_evidence"
                count_params = {}
                data_sql = (
                    "SELECT intake_id, mission_id, task_id, recon_run_id, "
                    "input_sha256, evidence_manifest_sha256, result_json, created_at "
                    "FROM cti_wpt_verified_evidence "
                    "ORDER BY created_at DESC LIMIT %(limit)s OFFSET %(offset)s"
                )
            offset = (self._page - 1) * self._page_size
            params = {**count_params, "limit": self._page_size, "offset": offset}
            total = self._db.fetch_one(count_sql, count_params or None)
            total_count = total["cnt"] if total else 0
            rows = self._db.fetch_all(data_sql, params)
            enriched = []
            for row in rows:
                record = dict(row)
                result_raw = record.pop("result_json", None)
                result = {}
                if result_raw:
                    try:
                        result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                    except (json.JSONDecodeError, TypeError):
                        pass
                record["technology_count"] = result.get("technology_count", 0)
                record["cpe_candidate_count"] = len(result.get("cpe_candidates", []))
                record["classification"] = result.get("classification", "")
                record["_result"] = result
                enriched.append(record)
            self.finished.emit(enriched, total_count)
        except Exception:
            self.finished.emit([], 0)


class CtiEnrichmentController:
    def __init__(self, page: CtiEnrichmentPage, db_adapter=None):
        self.page = page
        if db_adapter is None:
            from cti_services.db_adapter import DbAdapter
            db_adapter = DbAdapter()
        self.db = db_adapter
        self._current_page = 1
        self._total_count = 0
        self._rows: list[dict] = []
        self._worker: _LoadWorker | None = None

        page.search_button.clicked.connect(self._on_search)
        page.refresh_button.clicked.connect(self._on_refresh)
        page.prev_button.clicked.connect(self._on_prev)
        page.next_button.clicked.connect(self._on_next)
        page.evidence_table.selectionModel().selectionChanged.connect(self._on_row_selected)
        page.mission_input.returnPressed.connect(self._on_search)

    @property
    def _page_size(self) -> int:
        return int(self.page.page_size_combo.currentText())

    def load(self):
        self._current_page = 1
        self._fetch()

    def _on_search(self):
        self._current_page = 1
        self._fetch()

    def _on_refresh(self):
        self._fetch()

    def _on_prev(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._fetch()

    def _on_next(self):
        total_pages = max(1, math.ceil(self._total_count / self._page_size))
        if self._current_page < total_pages:
            self._current_page += 1
            self._fetch()

    def _fetch(self):
        mission_filter = self.page.mission_input.text()
        self._worker = _LoadWorker(self.db, mission_filter, self._current_page, self._page_size)
        self._worker.finished.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, rows: list[dict], total: int):
        self._rows = rows
        self._total_count = total
        self.page.evidence_model.set_rows(rows)
        total_pages = max(1, math.ceil(total / self._page_size))
        self.page.set_pagination(self._current_page, total_pages, total)
        self.page.show_evidence_detail(None)

    def _on_row_selected(self):
        indexes = self.page.evidence_table.selectionModel().selectedRows()
        if not indexes:
            self.page.show_evidence_detail(None)
            return
        row_idx = indexes[0].row()
        if 0 <= row_idx < len(self._rows):
            self.page.show_evidence_detail(self._rows[row_idx])
