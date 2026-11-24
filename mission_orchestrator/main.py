from __future__ import annotations

import math
import sys
import traceback
import faulthandler
from pathlib import Path as _Path
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QSignalBlocker, QObject, Slot, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog

from db import init_database
from export_utils import export_rows_to_csv
from main_window import MainWindow
from services import VulnerabilityService
from dataset_services import DatasetService
from sync_worker import SyncWorker
from mitre_attack_services import MitreAttackService
from mitre_sync_worker import MitreSyncWorker
from cwe_services import CweService
from cwe_sync_worker import CweSyncWorker
from cpe_dictionary_services import CpeDictionaryService
from cpe_dictionary_sync_worker import CpeDictionarySyncWorker


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


CRASH_LOG_PATH = _Path.cwd() / "vulndesk_crash.log"


def _append_crash_log(message: str) -> None:
    try:
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(message.rstrip() + "\n")
    except Exception:
        pass


def install_runtime_logging() -> None:
    try:
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n===== VulnDesk session start =====\n")
        fh = open(CRASH_LOG_PATH, "a", encoding="utf-8")
        faulthandler.enable(fh)
    except Exception:
        pass

    def _excepthook(exc_type, exc_value, exc_tb):
        _append_crash_log("[UNCAUGHT] " + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        try:
            QMessageBox.critical(None, "Unhandled Error", f"Terjadi error tak tertangani.\n\n{exc_value}\n\nLihat file log: {CRASH_LOG_PATH}")
        except Exception:
            pass

    sys.excepthook = _excepthook


class MainController(QObject):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.service = VulnerabilityService()
        self.mitre_service = MitreAttackService()
        self.dataset_service = DatasetService()
        self.cwe_service = CweService()
        self.cpe_service = CpeDictionaryService()

        self.current_page = 1
        self.total_rows = 0
        self.database_total_rows: int | None = None
        self.current_sort_by = "modified_at"
        self.current_sort_desc = True
        self.current_filters = self.default_filters()

        self.mitre_current_page = 1
        self.mitre_total_rows = 0

        self.dataset_current_page = 1
        self.dataset_total_rows = 0
        self.dataset_filters = self.default_dataset_filters()

        self.cwe_current_page = 1
        self.cwe_total_rows = 0
        self.cwe_keyword = None

        self.cpe_current_page = 1
        self.cpe_total_rows = 0
        self.cpe_keyword = None
        self.cpe_include_deprecated = False

        self.sync_thread = None
        self.sync_worker = None
        self.nvd_sync_thread = None
        self.nvd_sync_worker = None
        self.mitre_sync_thread = None
        self.mitre_sync_worker = None

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
        self.window.attack_page.actor_table.selectionModel().selectionChanged.connect(self.show_selected_attack_detail)
        self.window.attack_page.mitre_full_sync_button.clicked.connect(self.start_mitre_full_sync)
        self.window.attack_page.mitre_incremental_button.clicked.connect(self.start_mitre_incremental_sync)

        self.window.dataset_page.apply_button.clicked.connect(self.apply_dataset_filters)
        self.window.dataset_page.reset_button.clicked.connect(self.reset_dataset_filters)
        self.window.dataset_page.refresh_button.clicked.connect(self.refresh_dataset_views)
        self.window.dataset_page.search_input.returnPressed.connect(self.apply_dataset_filters)
        self.window.dataset_page.page_size_combo.currentTextChanged.connect(self.on_dataset_page_size_changed)
        self.window.dataset_page.prev_button.clicked.connect(self.go_dataset_prev_page)
        self.window.dataset_page.next_button.clicked.connect(self.go_dataset_next_page)
        self.window.dataset_page.upload_tweets_button.clicked.connect(self.upload_tweet_topics_csv)
        self.window.dataset_page.upload_topics_button.clicked.connect(self.upload_topics_master_csv)
        self.window.dataset_page.delete_tweets_button.clicked.connect(lambda: self.delete_dataset_by_type("tweet_topics"))
        self.window.dataset_page.delete_topics_button.clicked.connect(lambda: self.delete_dataset_by_type("topics_master"))
        self.window.dataset_page.tweet_table.selectionModel().selectionChanged.connect(self.show_selected_tweet_detail)

        self.window.cwe_page.search_button.clicked.connect(self.apply_cwe_filters)
        self.window.cwe_page.reset_button.clicked.connect(self.reset_cwe_filters)
        self.window.cwe_page.refresh_button.clicked.connect(self.load_cwe_list)
        self.window.cwe_page.search_input.returnPressed.connect(self.apply_cwe_filters)
        self.window.cwe_page.page_size_combo.currentTextChanged.connect(self.on_cwe_page_size_changed)
        self.window.cwe_page.prev_button.clicked.connect(self.go_cwe_prev_page)
        self.window.cwe_page.next_button.clicked.connect(self.go_cwe_next_page)
        self.window.cwe_page.table.selectionModel().selectionChanged.connect(self.show_selected_cwe_detail)
        self.window.cwe_page.fetch_one_button.clicked.connect(lambda: self.start_cwe_sync("CWE_SINGLE"))
        self.window.cwe_page.sync_known_button.clicked.connect(lambda: self.start_cwe_sync("CWE_KNOWN"))
        self.window.cwe_page.sync_view_button.clicked.connect(lambda: self.start_cwe_sync("CWE_VIEW"))
        self.window.cwe_page.sync_range_button.clicked.connect(lambda: self.start_cwe_sync("CWE_RANGE"))

        self.window.cpe_page.search_button.clicked.connect(self.apply_cpe_filters)
        self.window.cpe_page.reset_button.clicked.connect(self.reset_cpe_filters)
        self.window.cpe_page.refresh_button.clicked.connect(self.load_cpe_list)
        self.window.cpe_page.search_input.returnPressed.connect(self.apply_cpe_filters)
        self.window.cpe_page.page_size_combo.currentTextChanged.connect(self.on_cpe_page_size_changed)
        self.window.cpe_page.include_deprecated_checkbox.stateChanged.connect(self.apply_cpe_filters)
        self.window.cpe_page.prev_button.clicked.connect(self.go_cpe_prev_page)
        self.window.cpe_page.next_button.clicked.connect(self.go_cpe_next_page)
        self.window.cpe_page.table.selectionModel().selectionChanged.connect(self.show_selected_cpe_detail)
        self.window.cpe_page.sync_keyword_button.clicked.connect(lambda: self.start_cpe_sync("CPE_KEYWORD"))
        self.window.cpe_page.sync_match_button.clicked.connect(lambda: self.start_cpe_sync("CPE_MATCH_STRING"))
        self.window.cpe_page.sync_page_button.clicked.connect(lambda: self.start_cpe_sync("CPE_PAGE"))

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
            "sort_by": self.current_sort_by,
            "sort_desc": self.current_sort_desc,
            "limit": self.page_size(),
            "offset": 0,
        }

    def default_dataset_filters(self) -> dict:
        return {
            "keyword": None,
            "topic": None,
            "upload_date": None,
            "limit": self.dataset_page_size(),
            "offset": 0,
        }

    def page_size(self) -> int:
        return int(self.window.filter_bar.page_size_combo.currentText())

    def mitre_page_size(self) -> int:
        return int(self.window.attack_page.page_size_combo.currentText())

    def dataset_page_size(self) -> int:
        return int(self.window.dataset_page.page_size_combo.currentText())

    def cwe_page_size(self) -> int:
        return int(self.window.cwe_page.page_size_combo.currentText())

    def cpe_page_size(self) -> int:
        return int(self.window.cpe_page.page_size_combo.currentText())

    def current_attack_mode(self) -> str:
        idx = self.window.attack_page.entity_tabs.currentIndex()
        if idx == 0:
            return "techniques"
        if idx == 1:
            return "malware"
        return "threat_actors"

    def initialize(self):
        self.update_sort_label()
        self.load_list()
        self.load_attack_list()
        self.refresh_dataset_views()
        self.load_cwe_list()
        self.load_cpe_list()

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

    def build_dataset_filters_from_ui(self) -> dict:
        topic = self.window.dataset_page.topic_combo.currentText()
        upload_date = self.window.dataset_page.upload_date_combo.currentText()
        return {
            "keyword": self.window.dataset_page.search_input.text().strip() or None,
            "topic": None if topic == "ALL" else topic,
            "upload_date": None if upload_date == "ALL" else upload_date,
            "limit": self.dataset_page_size(),
            "offset": (self.dataset_current_page - 1) * self.dataset_page_size(),
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

            sel_model = self.window.table.selectionModel()
            blocker = QSignalBlocker(sel_model) if sel_model is not None else None
            try:
                if sel_model is not None:
                    sel_model.clearSelection()
                self.window.table_model.set_rows(rows)
            finally:
                del blocker

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
                sel_model = self.window.attack_page.technique_table.selectionModel()
                blocker = QSignalBlocker(sel_model) if sel_model is not None else None
                try:
                    if sel_model is not None:
                        sel_model.clearSelection()
                    rows = self.mitre_service.list_attack_patterns(keyword=keyword, limit=limit, offset=offset)
                    self.mitre_total_rows = self.mitre_service.count_attack_patterns(keyword=keyword)
                    self.window.attack_page.technique_model.set_rows(rows)
                finally:
                    del blocker
            elif mode == "malware":
                sel_model = self.window.attack_page.malware_table.selectionModel()
                blocker = QSignalBlocker(sel_model) if sel_model is not None else None
                try:
                    if sel_model is not None:
                        sel_model.clearSelection()
                    rows = self.mitre_service.list_malware(keyword=keyword, limit=limit, offset=offset)
                    self.mitre_total_rows = self.mitre_service.count_malware(keyword=keyword)
                    self.window.attack_page.malware_model.set_rows(rows)
                finally:
                    del blocker
            else:
                sel_model = self.window.attack_page.actor_table.selectionModel()
                blocker = QSignalBlocker(sel_model) if sel_model is not None else None
                try:
                    if sel_model is not None:
                        sel_model.clearSelection()
                    rows = self.mitre_service.list_threat_actors(keyword=keyword, limit=limit, offset=offset)
                    self.mitre_total_rows = self.mitre_service.count_threat_actors(keyword=keyword)
                    self.window.attack_page.actor_model.set_rows(rows)
                finally:
                    del blocker

            total_pages = max(1, math.ceil(self.mitre_total_rows / limit))
            if self.mitre_current_page > total_pages:
                self.mitre_current_page = total_pages
            self.window.set_attack_pagination(self.mitre_current_page, total_pages, self.mitre_total_rows)
            self.window.set_status(
                f"Loaded {len(rows)} ATT&CK {mode} rows | total={self.mitre_total_rows} | page_size={limit}"
            )
        except Exception as e:
            self.window.set_status(f"Load ATT&CK failed: {e}")

    def refresh_dataset_views(self):
        self.refresh_dataset_filter_options()
        self.load_dataset_data()

    def refresh_dataset_filter_options(self):
        try:
            current_topic = self.window.dataset_page.topic_combo.currentText()
            current_date = self.window.dataset_page.upload_date_combo.currentText()

            topics = self.dataset_service.list_topic_options()
            dates = self.dataset_service.list_upload_date_options()

            self.window.dataset_page.topic_combo.blockSignals(True)
            self.window.dataset_page.upload_date_combo.blockSignals(True)
            try:
                self.window.dataset_page.topic_combo.clear()
                self.window.dataset_page.topic_combo.addItem("ALL")
                self.window.dataset_page.topic_combo.addItems(topics)
                if current_topic in topics or current_topic == "ALL":
                    self.window.dataset_page.topic_combo.setCurrentText(current_topic)
                else:
                    self.window.dataset_page.topic_combo.setCurrentText("ALL")

                self.window.dataset_page.upload_date_combo.clear()
                self.window.dataset_page.upload_date_combo.addItem("ALL")
                self.window.dataset_page.upload_date_combo.addItems(dates)
                if current_date in dates or current_date == "ALL":
                    self.window.dataset_page.upload_date_combo.setCurrentText(current_date)
                else:
                    self.window.dataset_page.upload_date_combo.setCurrentText("ALL")
            finally:
                self.window.dataset_page.topic_combo.blockSignals(False)
                self.window.dataset_page.upload_date_combo.blockSignals(False)
        except Exception as e:
            self.window.set_status(f"Refresh dataset filter failed: {e}")

    def load_dataset_data(self):
        try:
            self.dataset_filters["limit"] = self.dataset_page_size()
            self.dataset_filters["offset"] = (self.dataset_current_page - 1) * self.dataset_page_size()

            tweet_rows = self.dataset_service.list_tweets(self.dataset_filters)
            self.dataset_total_rows = self.dataset_service.count_tweets(self.dataset_filters)
            topic_rows = self.dataset_service.list_topics({"upload_date": self.dataset_filters.get("upload_date")})
            total_topics = self.dataset_service.count_topics({"upload_date": self.dataset_filters.get("upload_date")})
            summary = self.dataset_service.get_summary(upload_date=self.dataset_filters.get("upload_date"))

            sel_model = self.window.dataset_page.tweet_table.selectionModel()
            blocker = QSignalBlocker(sel_model) if sel_model is not None else None
            try:
                if sel_model is not None:
                    sel_model.clearSelection()
                self.window.dataset_page.tweet_model.set_rows(tweet_rows)
            finally:
                del blocker

            self.window.dataset_page.topics_model.set_rows(topic_rows)
            total_pages = max(1, math.ceil(self.dataset_total_rows / self.dataset_page_size()))
            if self.dataset_current_page > total_pages:
                self.dataset_current_page = total_pages
            self.window.dataset_page.page_label.setText(f"Page {self.dataset_current_page} / {total_pages}")
            self.window.dataset_page.total_label.setText(f"{self.dataset_total_rows} tweets")
            self.window.dataset_page.prev_button.setEnabled(self.dataset_current_page > 1)
            self.window.dataset_page.next_button.setEnabled(self.dataset_current_page < total_pages)
            self.window.dataset_page.topics_total_label.setText(f"{total_topics} topics")
            self.window.dataset_page.summary_label.setText(
                f"Uploads: {summary.get('upload_count', 0)} | Tweets: {summary.get('tweet_count', 0)} | Topics: {summary.get('topic_count', 0)}"
            )
            self.window.dataset_page.tweet_detail.clear()
            self.window.set_status(
                f"Loaded tweet dataset rows={len(tweet_rows)} of {self.dataset_total_rows} | topics={total_topics}"
            )
        except Exception as e:
            self.window.set_status(f"Load tweet dataset failed: {e}")


    def load_cwe_list(self):
        try:
            limit = self.cwe_page_size()
            offset = (self.cwe_current_page - 1) * limit
            rows = self.cwe_service.list_cwes(keyword=self.cwe_keyword, limit=limit, offset=offset)
            self.cwe_total_rows = self.cwe_service.count_cwes(keyword=self.cwe_keyword)

            sel_model = self.window.cwe_page.table.selectionModel()
            blocker = QSignalBlocker(sel_model) if sel_model is not None else None
            try:
                if sel_model is not None:
                    sel_model.clearSelection()
                self.window.cwe_page.table_model.set_rows(rows)
            finally:
                del blocker

            total_pages = max(1, math.ceil(self.cwe_total_rows / limit))
            if self.cwe_current_page > total_pages:
                self.cwe_current_page = total_pages
            self.window.cwe_page.set_pagination(self.cwe_current_page, total_pages, self.cwe_total_rows)
            self.window.cwe_page.show_detail(None)
            self.window.set_status(
                f"Loaded CWE rows={len(rows)} of {self.cwe_total_rows} | page_size={limit}"
            )
        except Exception as e:
            self.window.set_status(f"Load CWE failed: {e}")

    def apply_cwe_filters(self):
        self.cwe_current_page = 1
        self.cwe_keyword = self.window.cwe_page.search_input.text().strip() or None
        self.load_cwe_list()

    def reset_cwe_filters(self):
        self.window.cwe_page.search_input.clear()
        self.window.cwe_page.page_size_combo.setCurrentText("100")
        self.cwe_current_page = 1
        self.cwe_keyword = None
        self.load_cwe_list()

    def on_cwe_page_size_changed(self):
        self.cwe_current_page = 1
        self.load_cwe_list()

    def go_cwe_prev_page(self):
        if self.cwe_current_page > 1:
            self.cwe_current_page -= 1
            self.load_cwe_list()

    def go_cwe_next_page(self):
        total_pages = max(1, math.ceil(self.cwe_total_rows / self.cwe_page_size()))
        if self.cwe_current_page < total_pages:
            self.cwe_current_page += 1
            self.load_cwe_list()

    def load_cpe_list(self):
        try:
            limit = self.cpe_page_size()
            offset = (self.cpe_current_page - 1) * limit
            self.cpe_include_deprecated = self.window.cpe_page.include_deprecated_checkbox.isChecked()
            rows = self.cpe_service.list_cpes(
                keyword=self.cpe_keyword,
                include_deprecated=self.cpe_include_deprecated,
                limit=limit,
                offset=offset,
            )
            self.cpe_total_rows = self.cpe_service.count_cpes(
                keyword=self.cpe_keyword,
                include_deprecated=self.cpe_include_deprecated,
            )

            sel_model = self.window.cpe_page.table.selectionModel()
            blocker = QSignalBlocker(sel_model) if sel_model is not None else None
            try:
                if sel_model is not None:
                    sel_model.clearSelection()
                self.window.cpe_page.table_model.set_rows(rows)
            finally:
                del blocker

            total_pages = max(1, math.ceil(self.cpe_total_rows / limit))
            if self.cpe_current_page > total_pages:
                self.cpe_current_page = total_pages
            self.window.cpe_page.set_pagination(self.cpe_current_page, total_pages, self.cpe_total_rows)
            self.window.cpe_page.show_detail(None)
            self.window.set_status(f"Loaded CPE rows={len(rows)} of {self.cpe_total_rows} | page_size={limit}")
        except Exception as e:
            self.window.set_status(f"Load CPE failed: {e}")

    def apply_cpe_filters(self):
        self.cpe_current_page = 1
        self.cpe_keyword = self.window.cpe_page.search_input.text().strip() or None
        self.cpe_include_deprecated = self.window.cpe_page.include_deprecated_checkbox.isChecked()
        self.load_cpe_list()

    def reset_cpe_filters(self):
        self.window.cpe_page.search_input.clear()
        self.window.cpe_page.page_size_combo.setCurrentText("100")
        self.window.cpe_page.include_deprecated_checkbox.setChecked(False)
        self.cpe_current_page = 1
        self.cpe_keyword = None
        self.cpe_include_deprecated = False
        self.load_cpe_list()

    def on_cpe_page_size_changed(self):
        self.cpe_current_page = 1
        self.load_cpe_list()

    def go_cpe_prev_page(self):
        if self.cpe_current_page > 1:
            self.cpe_current_page -= 1
            self.load_cpe_list()

    def go_cpe_next_page(self):
        total_pages = max(1, math.ceil(self.cpe_total_rows / self.cpe_page_size()))
        if self.cpe_current_page < total_pages:
            self.cpe_current_page += 1
            self.load_cpe_list()

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

    def apply_dataset_filters(self):
        self.dataset_current_page = 1
        self.dataset_filters = self.build_dataset_filters_from_ui()
        self.load_dataset_data()

    def reset_dataset_filters(self):
        self.window.dataset_page.search_input.clear()
        self.window.dataset_page.topic_combo.setCurrentText("ALL")
        self.window.dataset_page.upload_date_combo.setCurrentText("ALL")
        self.window.dataset_page.page_size_combo.setCurrentText("100")
        self.dataset_current_page = 1
        self.dataset_filters = self.default_dataset_filters()
        self.load_dataset_data()

    def on_page_size_changed(self):
        self.current_page = 1
        self.current_filters["limit"] = self.page_size()
        self.current_filters["offset"] = 0
        self.load_list()

    def on_attack_page_size_changed(self):
        self.mitre_current_page = 1
        self.load_attack_list()

    def on_dataset_page_size_changed(self):
        self.dataset_current_page = 1
        self.dataset_filters["limit"] = self.dataset_page_size()
        self.dataset_filters["offset"] = 0
        self.load_dataset_data()

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

    def go_dataset_prev_page(self):
        if self.dataset_current_page > 1:
            self.dataset_current_page -= 1
            self.load_dataset_data()

    def go_dataset_next_page(self):
        total_pages = max(1, math.ceil(self.dataset_total_rows / self.dataset_page_size()))
        if self.dataset_current_page < total_pages:
            self.dataset_current_page += 1
            self.load_dataset_data()

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

    def upload_tweet_topics_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Pilih file tweet_topics.csv",
            str(Path.cwd()),
            "CSV Files (*.csv)",
        )
        if not file_path:
            return
        try:
            result = self.dataset_service.import_tweet_topics_csv(file_path)
            self.refresh_dataset_views()
            uploaded_at = result.get("uploaded_at")
            uploaded_label = uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if uploaded_at else "-"
            stored_path = result.get("stored_file_path") or "-"
            file_size = result.get("file_size_bytes")
            size_label = f"{file_size:,} bytes" if isinstance(file_size, int) else "-"
            QMessageBox.information(
                self.window,
                "Upload tweet_topics.csv",
                f"Upload berhasil.\n\nFile: {result.get('file_name')}\nRows: {result.get('row_count')}\nUploaded: {uploaded_label}\nStored path: {stored_path}\nFile size: {size_label}",
            )
        except Exception as e:
            QMessageBox.critical(self.window, "Upload tweet_topics.csv", f"Gagal upload dataset tweet.\n\n{e}")

    def delete_dataset_by_type(self, dataset_type: str):
        upload_date = self.window.dataset_page.upload_date_combo.currentText()
        selected_date = None if upload_date == "ALL" else upload_date
        label = "tweet_topics" if dataset_type == "tweet_topics" else "topics_master"
        scope_label = f"tanggal upload {selected_date}" if selected_date else "semua tanggal upload"
        answer = QMessageBox.question(
            self.window,
            f"Delete {label}",
            f"Hapus dataset {label} untuk {scope_label}?\n\nData pada database dan file CSV fisik yang tersimpan akan dihapus.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            result = self.dataset_service.delete_dataset(dataset_type, upload_date=selected_date)
            self.dataset_current_page = 1
            self.dataset_filters = self.build_dataset_filters_from_ui()
            self.refresh_dataset_views()
            QMessageBox.information(
                self.window,
                f"Delete {label}",
                f"Penghapusan selesai.\n\nUploads dihapus: {result.get('deleted_uploads', 0)}\nRows dihapus: {result.get('deleted_rows', 0)}\nFile dihapus: {result.get('deleted_files', 0)}\nFile gagal dihapus: {len(result.get('failed_files', []))}",
            )
        except Exception as e:
            QMessageBox.critical(self.window, f"Delete {label}", f"Gagal menghapus dataset.\n\n{e}")

    def upload_topics_master_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Pilih file topics_master.csv",
            str(Path.cwd()),
            "CSV Files (*.csv)",
        )
        if not file_path:
            return
        try:
            result = self.dataset_service.import_topics_master_csv(file_path)
            self.refresh_dataset_views()
            uploaded_at = result.get("uploaded_at")
            uploaded_label = uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if uploaded_at else "-"
            stored_path = result.get("stored_file_path") or "-"
            file_size = result.get("file_size_bytes")
            size_label = f"{file_size:,} bytes" if isinstance(file_size, int) else "-"
            QMessageBox.information(
                self.window,
                "Upload topics_master.csv",
                f"Upload berhasil.\n\nFile: {result.get('file_name')}\nRows: {result.get('row_count')}\nUploaded: {uploaded_label}\nStored path: {stored_path}\nFile size: {size_label}",
            )
        except Exception as e:
            QMessageBox.critical(self.window, "Upload topics_master.csv", f"Gagal upload master topic.\n\n{e}")

    def show_selected_detail(self):
        sel_model = self.window.table.selectionModel()
        indexes = sel_model.selectedRows() if sel_model is not None else []
        if not indexes:
            return
        row_index = indexes[0].row()
        if row_index < 0 or row_index >= self.window.table_model.rowCount():
            return
        row = self.window.table_model.get_row(row_index)
        detail = self.service.get_detail(row["id"])
        self.window.detail_panel.show_detail(detail)

    def show_selected_tweet_detail(self):
        sel_model = self.window.dataset_page.tweet_table.selectionModel()
        indexes = sel_model.selectedRows() if sel_model is not None else []
        if not indexes:
            self.window.dataset_page.tweet_detail.clear()
            return
        row_index = indexes[0].row()
        if row_index < 0 or row_index >= self.window.dataset_page.tweet_model.rowCount():
            return
        row = self.window.dataset_page.tweet_model.get_row(row_index)
        uploaded_at = row.get("uploaded_at")
        uploaded_label = uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if uploaded_at else "-"
        stored_path = row.get('stored_file_path') or '-'
        file_size = row.get('file_size_bytes')
        size_label = f"{file_size:,} bytes" if isinstance(file_size, int) else '-'
        self.window.dataset_page.tweet_detail.setPlainText(
            f"Topic: {row.get('topic_text') or '-'}\n"
            f"Uploaded: {uploaded_label}\n"
            f"File: {row.get('file_name') or '-'}\n"
            f"Stored path: {stored_path}\n"
            f"File size: {size_label}\n\n"
            f"{row.get('tweet_text') or ''}"
        )

    def show_selected_attack_detail(self):
        mode = self.current_attack_mode()
        if mode == "techniques":
            sel_model = self.window.attack_page.technique_table.selectionModel()
            indexes = sel_model.selectedRows() if sel_model is not None else []
            if not indexes:
                return
            row_index = indexes[0].row()
            if row_index < 0 or row_index >= self.window.attack_page.technique_model.rowCount():
                return
            row = self.window.attack_page.technique_model.get_row(row_index)
            detail = self.mitre_service.get_attack_pattern_detail(row["stix_id"])
            self.window.attack_page.detail_panel.show_attack_pattern_detail(detail)
        elif mode == "malware":
            sel_model = self.window.attack_page.malware_table.selectionModel()
            indexes = sel_model.selectedRows() if sel_model is not None else []
            if not indexes:
                return
            row_index = indexes[0].row()
            if row_index < 0 or row_index >= self.window.attack_page.malware_model.rowCount():
                return
            row = self.window.attack_page.malware_model.get_row(row_index)
            detail = self.mitre_service.get_malware_detail(row["stix_id"])
            self.window.attack_page.detail_panel.show_malware_detail(detail)
        else:
            sel_model = self.window.attack_page.actor_table.selectionModel()
            indexes = sel_model.selectedRows() if sel_model is not None else []
            if not indexes:
                return
            row_index = indexes[0].row()
            if row_index < 0 or row_index >= self.window.attack_page.actor_model.rowCount():
                return
            row = self.window.attack_page.actor_model.get_row(row_index)
            detail = self.mitre_service.get_threat_actor_detail(row["stix_id"])
            self.window.attack_page.detail_panel.show_threat_actor_detail(detail)


    def show_selected_cwe_detail(self):
        sel_model = self.window.cwe_page.table.selectionModel()
        indexes = sel_model.selectedRows() if sel_model is not None else []
        if not indexes:
            self.window.cwe_page.show_detail(None)
            return
        row_index = indexes[0].row()
        if row_index < 0 or row_index >= self.window.cwe_page.table_model.rowCount():
            return
        row = self.window.cwe_page.table_model.get_row(row_index)
        detail = self.cwe_service.get_cwe_detail(row["cwe_id"])
        self.window.cwe_page.show_detail(detail)

    def show_selected_cpe_detail(self):
        sel_model = self.window.cpe_page.table.selectionModel()
        indexes = sel_model.selectedRows() if sel_model is not None else []
        if not indexes:
            self.window.cpe_page.show_detail(None)
            return
        row_index = indexes[0].row()
        if row_index < 0 or row_index >= self.window.cpe_page.table_model.rowCount():
            return
        row = self.window.cpe_page.table_model.get_row(row_index)
        detail = self.cpe_service.get_cpe_detail(row["id"])
        self.window.cpe_page.show_detail(detail)

    def _cleanup_nvd_sync_refs(self):
        self.sync_thread = None
        self.sync_worker = None
        self.nvd_sync_thread = None
        self.nvd_sync_worker = None

    def _cleanup_mitre_sync_refs(self):
        self.sync_thread = None
        self.sync_worker = None
        self.mitre_sync_thread = None
        self.mitre_sync_worker = None

    def _cleanup_cwe_sync_refs(self):
        self.sync_thread = None
        self.sync_worker = None

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
        dataset_total_pages = max(1, math.ceil(self.dataset_total_rows / self.dataset_page_size()))
        self.window.dataset_page.prev_button.setEnabled(enabled and self.dataset_current_page > 1)
        self.window.dataset_page.next_button.setEnabled(enabled and self.dataset_current_page < dataset_total_pages)
        self.window.dataset_page.upload_tweets_button.setEnabled(enabled)
        self.window.dataset_page.upload_topics_button.setEnabled(enabled)
        self.window.dataset_page.delete_tweets_button.setEnabled(enabled)
        self.window.dataset_page.delete_topics_button.setEnabled(enabled)
        self.window.cwe_page.fetch_one_button.setEnabled(enabled)
        self.window.cwe_page.sync_known_button.setEnabled(enabled)
        self.window.cwe_page.sync_view_button.setEnabled(enabled)
        self.window.cwe_page.sync_range_button.setEnabled(enabled)
        cwe_total_pages = max(1, math.ceil(self.cwe_total_rows / self.cwe_page_size()))
        self.window.cwe_page.prev_button.setEnabled(enabled and self.cwe_current_page > 1)
        self.window.cwe_page.next_button.setEnabled(enabled and self.cwe_current_page < cwe_total_pages)
        self.window.cpe_page.sync_keyword_button.setEnabled(enabled)
        self.window.cpe_page.sync_match_button.setEnabled(enabled)
        self.window.cpe_page.sync_page_button.setEnabled(enabled)
        cpe_total_pages = max(1, math.ceil(self.cpe_total_rows / self.cpe_page_size()))
        self.window.cpe_page.prev_button.setEnabled(enabled and self.cpe_current_page > 1)
        self.window.cpe_page.next_button.setEnabled(enabled and self.cpe_current_page < cpe_total_pages)

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
        self.sync_worker.progress.connect(self.on_sync_progress, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.finished.connect(self.on_sync_finished, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.failed.connect(self.on_sync_failed, Qt.ConnectionType.QueuedConnection)

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
        self.sync_worker.progress.connect(self.on_sync_progress, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.finished.connect(self.on_sync_finished, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.failed.connect(self.on_sync_failed, Qt.ConnectionType.QueuedConnection)

        self.sync_worker.finished.connect(self.sync_thread.quit)
        self.sync_worker.failed.connect(self.sync_thread.quit)
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)

        self.sync_thread.start()
        self.window.set_status(f"{mode} sync started...")


    def start_cwe_sync(self, mode: str):
        cwe_id = self.window.cwe_page.search_input.text().strip()
        if mode == "CWE_SINGLE" and not cwe_id:
            QMessageBox.information(
                self.window,
                "Fetch CWE ID",
                "Isi field Search dengan CWE ID terlebih dahulu, misalnya CWE-79.",
            )
            return

        self.set_sync_controls_enabled(False)
        self.window.set_sync_status(f"{mode} running")
        self.window.set_sync_progress(0, 1, mode)

        start_id = self.window.cwe_page.range_start_spin.value()
        end_id = self.window.cwe_page.range_end_spin.value()
        view_id = self.window.cwe_page.view_id_spin.value()

        self.sync_thread = QThread()
        self.sync_worker = CweSyncWorker(
            mode=mode,
            cwe_id=cwe_id,
            start_id=start_id,
            end_id=end_id,
            view_id=view_id,
        )
        self.sync_worker.moveToThread(self.sync_thread)

        self.sync_thread.started.connect(self.sync_worker.run)
        self.sync_worker.progress.connect(self.on_sync_progress, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.finished.connect(self.on_sync_finished, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.failed.connect(self.on_sync_failed, Qt.ConnectionType.QueuedConnection)

        self.sync_worker.finished.connect(self.sync_thread.quit)
        self.sync_worker.failed.connect(self.sync_thread.quit)
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)

        self.sync_thread.start()
        self.window.set_status(f"{mode} started...")

    def start_cpe_sync(self, mode: str):
        value = self.window.cpe_page.sync_input.text().strip()
        if mode in {"CPE_KEYWORD", "CPE_MATCH_STRING"} and not value:
            QMessageBox.information(
                self.window,
                "NVD CPE Sync",
                "Isi field NVD CPE Sync terlebih dahulu dengan keyword atau cpeMatchString.",
            )
            return

        self.set_sync_controls_enabled(False)
        self.window.set_sync_status(f"{mode} running")
        self.window.set_sync_progress(0, 1, mode)

        self.sync_thread = QThread()
        self.sync_worker = CpeDictionarySyncWorker(
            mode=mode,
            value=value,
            max_pages=self.window.cpe_page.max_pages_spin.value(),
            page_size=self.window.cpe_page.sync_page_size_spin.value(),
        )
        self.sync_worker.moveToThread(self.sync_thread)

        self.sync_thread.started.connect(self.sync_worker.run)
        self.sync_worker.progress.connect(self.on_sync_progress, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.finished.connect(self.on_sync_finished, Qt.ConnectionType.QueuedConnection)
        self.sync_worker.failed.connect(self.on_sync_failed, Qt.ConnectionType.QueuedConnection)

        self.sync_worker.finished.connect(self.sync_thread.quit)
        self.sync_worker.failed.connect(self.sync_thread.quit)
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)

        self.sync_thread.start()
        self.window.set_status(f"{mode} started...")

    @Slot(dict)
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

    @Slot(dict)
    def on_sync_finished(self, result: dict):
        try:
            self.database_total_rows = None
            mode = str(result.get("mode", "SYNC"))
            self.window.set_sync_progress(1, 1, mode)
            self.window.progress_bar.setValue(100)
            self.window.progress_bar.setFormat(f"{mode} done")
            result_status = str(result.get("status", "SUCCESS"))
            self.window.set_sync_status(
                "Sync success" if result_status == "SUCCESS" else f"Sync {result_status.lower()}"
            )
            self.window.set_status(
                f"{mode} {result_status.lower()} | fetched={result.get('total_fetched', 0)} | "
                f"inserted={result.get('total_inserted', 0)} | updated={result.get('total_updated', 0)} | "
                f"skipped={result.get('total_skipped', 0)} | failed={result.get('total_failed', 0)}"
            )
            self.set_sync_controls_enabled(True)
            if mode.startswith("MITRE"):
                QTimer.singleShot(0, self, self.load_attack_list)
            elif mode.startswith("CWE"):
                QTimer.singleShot(0, self, self.load_cwe_list)
                QTimer.singleShot(0, self, self.load_list)
            elif mode.startswith("CPE"):
                QTimer.singleShot(0, self, self.load_cpe_list)
                QTimer.singleShot(0, self, self.load_list)
            else:
                QTimer.singleShot(0, self, self.load_list)
        except Exception as e:
            self.window.set_sync_status("Sync finished with UI error")
            self.window.set_status(f"Sync finished but UI refresh failed: {e}")
            self.set_sync_controls_enabled(True)

    @Slot(str)
    def on_sync_failed(self, error_message: str):
        try:
            # Prior batches may already have committed before the failing page.
            self.database_total_rows = None
            self.window.reset_sync_progress()
            self.window.set_sync_status("Sync failed")
            self.window.set_status(f"Sync failed: {error_message}")
            self.set_sync_controls_enabled(True)
            QMessageBox.critical(self.window, "Sync Failed", error_message)
            QTimer.singleShot(0, self, self.load_list)
            QTimer.singleShot(0, self, self.load_attack_list)
            QTimer.singleShot(0, self, self.load_dataset_data)
            QTimer.singleShot(0, self, self.load_cwe_list)
            QTimer.singleShot(0, self, self.load_cpe_list)
        except Exception as e:
            self.window.set_status(f"Sync failed and UI refresh error occurred: {e}")
            self.set_sync_controls_enabled(True)


def main():
    install_runtime_logging()
    try:
        init_database()
    except Exception as e:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "Database Error",
            f"Gagal menginisialisasi database.\n\n{e}\n\nPeriksa file .env dan koneksi MariaDB.",
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    window = MainWindow()
    controller = MainController(window)
    window.show()
    QTimer.singleShot(0, controller.initialize)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
