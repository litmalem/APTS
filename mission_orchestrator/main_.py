from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog

from db import init_database
from export_utils import export_rows_to_csv
from main_window import MainWindow
from services import VulnerabilityService
from sync_worker import SyncWorker
from mitre_attack_services import MitreAttackService
from mitre_sync_worker import MitreSyncWorker


COLUMN_SORT_MAP = {
    0: "cve_id",
    1: "description_text",
    2: "preferred_base_severity",
    3: "preferred_base_score",
    4: "preferred_cvss_version",
    5: "published_at",
    6: "modified_at",
    7: "cwe_count",
    8: "reference_count",
    9: "affected_product_count",
}

COLUMN_LABEL_MAP = {
    "cve_id": "CVE ID",
    "description_text": "Description",
    "preferred_base_severity": "Severity",
    "preferred_base_score": "Score",
    "preferred_cvss_version": "CVSS",
    "published_at": "Published",
    "modified_at": "Modified",
    "cwe_count": "CWE",
    "reference_count": "Refs",
    "affected_product_count": "CPE",
}


class MainController:
    def __init__(self, window: MainWindow):
        self.window = window
        self.service = VulnerabilityService()
        self.mitre_service = MitreAttackService()

        self.current_page = 1
        self.total_rows = 0
        self.database_total_rows: int | None = None
        self.current_filters = self.default_filters()
        self.current_sort_by = "modified_at"
        self.current_sort_desc = True

        self.mitre_current_page = 1
        self.mitre_total_rows = 0

        self.sync_thread = None
        self.sync_worker = None

        self.window.filter_bar.apply_button.clicked.connect(self.apply_filters)
        self.window.filter_bar.reset_button.clicked.connect(self.reset_filters)
        self.window.filter_bar.export_button.clicked.connect(self.export_csv)
        self.window.filter_bar.full_sync_button.clicked.connect(self.start_full_sync)
        self.window.filter_bar.incremental_button.clicked.connect(self.start_incremental_sync)
        self.window.filter_bar.search_input.returnPressed.connect(self.apply_filters)
        self.window.filter_bar.page_size_combo.currentTextChanged.connect(self.on_page_size_changed)
        self.window.first_button.clicked.connect(self.go_first_page)
        self.window.prev_button.clicked.connect(self.go_prev_page)
        self.window.next_button.clicked.connect(self.go_next_page)
        self.window.last_button.clicked.connect(self.go_last_page)
        self.window.table.selectionModel().selectionChanged.connect(self.show_selected_detail)
        self.window.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)

        self.window.attack_page.search_button.clicked.connect(self.apply_attack_filters)
        self.window.attack_page.reset_button.clicked.connect(self.reset_attack_filters)
        self.window.attack_page.refresh_button.clicked.connect(self.load_attack_list)
        self.window.attack_page.search_input.returnPressed.connect(self.apply_attack_filters)
        self.window.attack_page.page_size_combo.currentTextChanged.connect(self.on_attack_page_size_changed)
        self.window.attack_page.prev_button.clicked.connect(self.go_attack_prev_page)
        self.window.attack_page.next_button.clicked.connect(self.go_attack_next_page)
        self.window.attack_page.entity_tabs.currentChanged.connect(self.on_attack_entity_changed)
        self.window.attack_page.technique_table.selectionModel().selectionChanged.connect(self.show_selected_attack_detail)
        self.window.attack_page.malware_table.selectionModel().selectionChanged.connect(self.show_selected_attack_detail)
        self.window.attack_page.mitre_full_sync_button.clicked.connect(self.start_mitre_full_sync)
        self.window.attack_page.mitre_incremental_button.clicked.connect(self.start_mitre_incremental_sync)

    def default_filters(self) -> dict:
        return {
            "keyword": None,
            "severity": None,
            "min_score": None,
            "max_score": None,
            "year": None,
            "cwe_id": None,
            "has_cpe": None,
            "modified_from": None,
            "modified_to": None,
            "sort_by": self.current_sort_by if hasattr(self, "current_sort_by") else "modified_at",
            "sort_desc": self.current_sort_desc if hasattr(self, "current_sort_desc") else True,
            "limit": self.page_size(),
            "offset": 0,
        }

    def page_size(self) -> int:
        return int(self.window.filter_bar.page_size_combo.currentText())

    def mitre_page_size(self) -> int:
        return int(self.window.attack_page.page_size_combo.currentText())

    def current_attack_mode(self) -> str:
        return "techniques" if self.window.attack_page.entity_tabs.currentIndex() == 0 else "malware"

    def initialize(self):
        self.update_sort_label()
        self.load_list()
        self.load_attack_list()

    def build_filters_from_ui(self) -> dict:
        severity = self.window.filter_bar.severity_combo.currentText()
        if severity == "ALL":
            severity = None

        keyword = self.window.filter_bar.search_input.text().strip() or None
        min_score = self.window.filter_bar.min_score.value()
        max_score = self.window.filter_bar.max_score.value()
        year = self.window.filter_bar.year_spin.value() or None
        cwe_id = (self.window.filter_bar.cwe_input.text().strip().upper() or None)
        has_cpe = True if self.window.filter_bar.has_cpe_checkbox.isChecked() else None

        return {
            "keyword": keyword,
            "severity": severity,
            "min_score": min_score if min_score > 0 else None,
            "max_score": max_score if max_score < 10 else None,
            "year": year,
            "cwe_id": cwe_id,
            "has_cpe": has_cpe,
            "modified_from": None,
            "modified_to": None,
            "sort_by": self.current_sort_by,
            "sort_desc": self.current_sort_desc,
            "limit": self.page_size(),
            "offset": (self.current_page - 1) * self.page_size(),
        }

    def update_sort_label(self):
        arrow = "↓" if self.current_sort_desc else "↑"
        label = COLUMN_LABEL_MAP.get(self.current_sort_by, self.current_sort_by)
        self.window.set_sort_status(f"Sort: {label} {arrow}")

    def load_list(self):
        try:
            self.current_filters["limit"] = self.page_size()
            self.current_filters["offset"] = (self.current_page - 1) * self.page_size()
            self.current_filters["sort_by"] = self.current_sort_by
            self.current_filters["sort_desc"] = self.current_sort_desc
            rows = self.service.get_list(self.current_filters)
            self.total_rows = self.service.get_total_count(self.current_filters)
            if self.database_total_rows is None:
                self.database_total_rows = self.service.get_database_total_count()
            self.window.table_model.set_rows(rows)
            self.window.detail_panel.clear_detail()

            total_pages = max(1, math.ceil(self.total_rows / self.page_size()))
            if self.current_page > total_pages:
                self.current_page = total_pages
            self.window.set_pagination(
                self.current_page,
                total_pages,
                self.total_rows,
                int(self.database_total_rows or 0),
            )
            self.update_sort_label()
            self.window.set_status(
                f"Loaded {len(rows)} CVE rows | total={self.total_rows} | page_size={self.page_size()}"
            )
        except Exception as e:
            self.window.set_status(f"Load failed: {e}")

    def load_attack_list(self):
        try:
            keyword = self.window.attack_page.search_input.text().strip() or None
            limit = self.mitre_page_size()
            offset = (self.mitre_current_page - 1) * limit
            mode = self.current_attack_mode()

            if mode == "techniques":
                rows = self.mitre_service.list_attack_patterns(keyword=keyword, limit=limit, offset=offset)
                self.mitre_total_rows = self.mitre_service.count_attack_patterns(keyword=keyword)
                self.window.attack_page.technique_model.set_rows(rows)
            else:
                rows = self.mitre_service.list_malware(keyword=keyword, limit=limit, offset=offset)
                self.mitre_total_rows = self.mitre_service.count_malware(keyword=keyword)
                self.window.attack_page.malware_model.set_rows(rows)

            self.window.attack_page.detail_panel.clear_detail()
            total_pages = max(1, math.ceil(self.mitre_total_rows / limit))
            if self.mitre_current_page > total_pages:
                self.mitre_current_page = total_pages
            self.window.set_attack_pagination(self.mitre_current_page, total_pages, self.mitre_total_rows)
            self.window.set_status(
                f"Loaded {len(rows)} ATT&CK {mode} rows | total={self.mitre_total_rows} | page_size={limit}"
            )
        except Exception as e:
            self.window.set_status(f"Load ATT&CK failed: {e}")

    def apply_filters(self):
        self.current_page = 1
        self.current_filters = self.build_filters_from_ui()
        self.load_list()

    def reset_filters(self):
        self.window.filter_bar.search_input.clear()
        self.window.filter_bar.severity_combo.setCurrentIndex(0)
        self.window.filter_bar.min_score.setValue(0.0)
        self.window.filter_bar.max_score.setValue(10.0)
        self.window.filter_bar.year_spin.setValue(0)
        self.window.filter_bar.cwe_input.clear()
        self.window.filter_bar.has_cpe_checkbox.setChecked(False)
        self.window.filter_bar.page_size_combo.setCurrentText("100")
        self.current_page = 1
        self.current_sort_by = "modified_at"
        self.current_sort_desc = True
        self.current_filters = self.default_filters()
        self.load_list()

    def apply_attack_filters(self):
        self.mitre_current_page = 1
        self.load_attack_list()

    def reset_attack_filters(self):
        self.window.attack_page.search_input.clear()
        self.window.attack_page.page_size_combo.setCurrentText("100")
        self.mitre_current_page = 1
        self.load_attack_list()

    def on_page_size_changed(self):
        self.current_page = 1
        self.current_filters["limit"] = self.page_size()
        self.current_filters["offset"] = 0
        self.load_list()

    def on_attack_page_size_changed(self):
        self.mitre_current_page = 1
        self.load_attack_list()

    def on_attack_entity_changed(self):
        self.mitre_current_page = 1
        self.load_attack_list()

    def on_header_clicked(self, section: int):
        new_sort_by = COLUMN_SORT_MAP.get(section)
        if not new_sort_by:
            return
        if self.current_sort_by == new_sort_by:
            self.current_sort_desc = not self.current_sort_desc
        else:
            self.current_sort_by = new_sort_by
            self.current_sort_desc = new_sort_by in {
                "modified_at", "published_at", "preferred_base_score", "cwe_count", "reference_count", "affected_product_count"
            }
        self.current_page = 1
        self.current_filters["sort_by"] = self.current_sort_by
        self.current_filters["sort_desc"] = self.current_sort_desc
        self.load_list()

    def go_first_page(self):
        if self.current_page != 1:
            self.current_page = 1
            self.load_list()

    def go_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_list()

    def go_next_page(self):
        total_pages = max(1, math.ceil(self.total_rows / self.page_size()))
        if self.current_page < total_pages:
            self.current_page += 1
            self.load_list()

    def go_last_page(self):
        total_pages = max(1, math.ceil(self.total_rows / self.page_size()))
        if self.current_page != total_pages:
            self.current_page = total_pages
            self.load_list()

    def go_attack_prev_page(self):
        if self.mitre_current_page > 1:
            self.mitre_current_page -= 1
            self.load_attack_list()

    def go_attack_next_page(self):
        total_pages = max(1, math.ceil(self.mitre_total_rows / self.mitre_page_size()))
        if self.mitre_current_page < total_pages:
            self.mitre_current_page += 1
            self.load_attack_list()

    def export_csv(self):
        try:
            export_filters = dict(self.current_filters)
            export_filters["limit"] = self.page_size()
            export_filters["offset"] = (self.current_page - 1) * self.page_size()
            rows = self.service.get_list(export_filters)
            if not rows:
                QMessageBox.information(self.window, "Export CSV", "Tidak ada data pada halaman aktif untuk diekspor.")
                return

            default_name = f"vulndesk_page_{self.current_page}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            target, _ = QFileDialog.getSaveFileName(
                self.window,
                "Save CSV",
                str(Path.cwd() / default_name),
                "CSV Files (*.csv)",
            )
            if not target:
                return

            export_rows_to_csv(rows, target)
            self.window.set_status(f"CSV exported: {target}")
            QMessageBox.information(self.window, "Export CSV", f"Data berhasil diekspor ke:\n{target}")
        except Exception as e:
            QMessageBox.critical(self.window, "Export CSV", f"Gagal export CSV.\n\n{e}")

    def show_selected_detail(self):
        indexes = self.window.table.selectionModel().selectedRows()
        if not indexes:
            self.window.detail_panel.clear_detail()
            return
        row_index = indexes[0].row()
        row = self.window.table_model.get_row(row_index)
        detail = self.service.get_detail(row["id"])
        self.window.detail_panel.show_detail(detail)

    def show_selected_attack_detail(self):
        mode = self.current_attack_mode()
        if mode == "techniques":
            indexes = self.window.attack_page.technique_table.selectionModel().selectedRows()
            if not indexes:
                self.window.attack_page.detail_panel.clear_detail()
                return
            row = self.window.attack_page.technique_model.get_row(indexes[0].row())
            detail = self.mitre_service.get_attack_pattern_detail(row["stix_id"])
            self.window.attack_page.detail_panel.show_attack_pattern_detail(detail)
        else:
            indexes = self.window.attack_page.malware_table.selectionModel().selectedRows()
            if not indexes:
                self.window.attack_page.detail_panel.clear_detail()
                return
            row = self.window.attack_page.malware_model.get_row(indexes[0].row())
            detail = self.mitre_service.get_malware_detail(row["stix_id"])
            self.window.attack_page.detail_panel.show_malware_detail(detail)

    def set_sync_controls_enabled(self, enabled: bool):
        self.window.filter_bar.full_sync_button.setEnabled(enabled)
        self.window.filter_bar.incremental_button.setEnabled(enabled)
        self.window.attack_page.mitre_full_sync_button.setEnabled(enabled)
        self.window.attack_page.mitre_incremental_button.setEnabled(enabled)
        total_pages = max(1, math.ceil(self.total_rows / self.page_size()))
        self.window.first_button.setEnabled(enabled and self.current_page > 1)
        self.window.prev_button.setEnabled(enabled and self.current_page > 1)
        self.window.next_button.setEnabled(enabled and self.current_page < total_pages)
        self.window.last_button.setEnabled(enabled and self.current_page < total_pages)
        attack_total_pages = max(1, math.ceil(self.mitre_total_rows / self.mitre_page_size()))
        self.window.attack_page.prev_button.setEnabled(enabled and self.mitre_current_page > 1)
        self.window.attack_page.next_button.setEnabled(enabled and self.mitre_current_page < attack_total_pages)

    def start_full_sync(self):
        self._start_sync(mode="FULL")

    def start_incremental_sync(self):
        self._start_sync(mode="INCREMENTAL")

    def start_mitre_full_sync(self):
        self._start_mitre_sync(mode="MITRE_FULL")

    def start_mitre_incremental_sync(self):
        self._start_mitre_sync(mode="MITRE_INCREMENTAL")

    def _start_sync(self, mode: str):
        self.set_sync_controls_enabled(False)
        self.window.set_sync_status(f"{mode} running")
        self.window.set_sync_progress(0, 1, mode)

        self.sync_thread = QThread()
        self.sync_worker = SyncWorker(mode=mode)
        self.sync_worker.moveToThread(self.sync_thread)

        self.sync_thread.started.connect(self.sync_worker.run)
        self.sync_worker.progress.connect(self.on_sync_progress)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.failed.connect(self.on_sync_failed)

        self.sync_worker.finished.connect(self.sync_thread.quit)
        self.sync_worker.failed.connect(self.sync_thread.quit)
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)

        self.sync_thread.start()
        self.window.set_status(f"{mode} sync started...")

    def _start_mitre_sync(self, mode: str):
        self.set_sync_controls_enabled(False)
        self.window.set_sync_status(f"{mode} running")
        self.window.set_sync_progress(0, 1, mode)

        self.sync_thread = QThread()
        self.sync_worker = MitreSyncWorker(mode=mode)
        self.sync_worker.moveToThread(self.sync_thread)

        self.sync_thread.started.connect(self.sync_worker.run)
        self.sync_worker.progress.connect(self.on_sync_progress)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.failed.connect(self.on_sync_failed)

        self.sync_worker.finished.connect(self.sync_thread.quit)
        self.sync_worker.failed.connect(self.sync_thread.quit)
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)

        self.sync_thread.start()
        self.window.set_status(f"{mode} sync started...")

    def on_sync_progress(self, payload: dict):
        self.window.set_sync_progress(payload["current_page"], payload["total_pages"], payload["mode"])
        current_type = payload.get("current_type")
        suffix = f" | {current_type}" if current_type else ""
        self.window.set_sync_status(
            f"{payload['mode']}{suffix} fetched={payload['total_fetched']} ins={payload['total_inserted']} upd={payload['total_updated']} skip={payload.get('total_skipped', 0)} fail={payload['total_failed']}"
        )
        self.window.set_status(
            f"{payload['mode']}{suffix} | step/page {payload['current_page']}/{payload['total_pages']} | "
            f"fetched={payload['total_fetched']} | inserted={payload['total_inserted']} | "
            f"updated={payload['total_updated']} | skipped={payload.get('total_skipped', 0)} | failed={payload['total_failed']}"
        )

    def on_sync_finished(self, result: dict):
        self.database_total_rows = None
        self.window.set_sync_progress(1, 1, result["mode"])
        self.window.progress_bar.setValue(100)
        self.window.progress_bar.setFormat(f"{result['mode']} done")
        self.window.set_sync_status("Sync success")
        self.window.set_status(
            f"{result['mode']} finished | fetched={result['total_fetched']} | "
            f"inserted={result['total_inserted']} | updated={result['total_updated']} | "
            f"skipped={result.get('total_skipped', 0)} | failed={result['total_failed']}"
        )
        self.set_sync_controls_enabled(True)
        if str(result.get("mode", "")).startswith("MITRE"):
            self.load_attack_list()
        else:
            self.load_list()

    def on_sync_failed(self, error_message: str):
        # Prior batches may already have committed before the failing page.
        self.database_total_rows = None
        self.window.reset_sync_progress()
        self.window.set_sync_status("Sync failed")
        self.window.set_status(f"Sync failed: {error_message}")
        self.set_sync_controls_enabled(True)
        QMessageBox.critical(self.window, "Sync Failed", error_message)
        self.load_list()
        self.load_attack_list()


def main():
    try:
        init_database()
    except Exception as e:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "Database Error",
            f"Gagal menginisialisasi database.\n\n{e}\n\nPeriksa file .env dan koneksi MariaDB."
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    window = MainWindow()
    controller = MainController(window)
    controller.initialize()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
