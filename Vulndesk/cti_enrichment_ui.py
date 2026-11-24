from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Table models
# ---------------------------------------------------------------------------

class EvidenceTableModel(QAbstractTableModel):
    COLUMNS = [
        ("intake_id", "Intake ID"),
        ("mission_id", "Mission"),
        ("task_id", "Task"),
        ("recon_run_id", "Recon Run"),
        ("technology_count", "Technologies"),
        ("cpe_candidate_count", "CPE Candidates"),
        ("classification", "Classification"),
        ("created_at", "Created"),
    ]

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def get_row(self, row: int) -> dict:
        return self._rows[row]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        row = self._rows[index.row()]
        key = self.COLUMNS[index.column()][0]
        value = row.get(key)
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if value is None:
            return ""
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section][1]
        return str(section + 1)


class TechnologyTableModel(QAbstractTableModel):
    COLUMNS = [
        ("name", "Technology"),
        ("version", "Version"),
    ]

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        row = self._rows[index.row()]
        key = self.COLUMNS[index.column()][0]
        return str(row.get(key, ""))

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section][1]
        return str(section + 1)


class CpeCandidateTableModel(QAbstractTableModel):
    COLUMNS = [
        ("technology_name", "Technology"),
        ("technology_version", "Version"),
        ("cpe23_uri", "CPE 2.3 URI"),
        ("match_confidence", "Confidence"),
        ("status", "Status"),
        ("exploitability_confirmed", "Exploitable"),
    ]

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def get_row(self, row: int) -> dict:
        return self._rows[row]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        row = self._rows[index.row()]
        key = self.COLUMNS[index.column()][0]
        value = row.get(key)
        if key == "exploitability_confirmed":
            return "Yes" if value else "No"
        if key == "match_confidence" and isinstance(value, (int, float)):
            return f"{value:.2f}"
        if value is None:
            return ""
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section][1]
        return str(section + 1)


# ---------------------------------------------------------------------------
# Helper: build a standard read-only table
# ---------------------------------------------------------------------------

def _make_table(model) -> QTableView:
    table = QTableView()
    table.setModel(model)
    table.setSelectionBehavior(QTableView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    return table


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

class CtiEnrichmentPage(QWidget):
    """CTI Enrichment view — shows WPT verified evidence, technologies, and CPE candidates."""

    def __init__(self):
        super().__init__()

        # --- filter bar ---
        self.mission_input = QLineEdit()
        self.mission_input.setPlaceholderText("Filter by mission_id ...")
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100"])
        self.page_size_combo.setCurrentText("50")
        self.search_button = QPushButton("Search")
        self.refresh_button = QPushButton("Refresh")

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Mission"))
        filter_layout.addWidget(self.mission_input, 2)
        filter_layout.addWidget(QLabel("Page size"))
        filter_layout.addWidget(self.page_size_combo)
        filter_layout.addWidget(self.search_button)
        filter_layout.addWidget(self.refresh_button)

        # --- Evidence table (top) ---
        self.evidence_model = EvidenceTableModel()
        self.evidence_table = _make_table(self.evidence_model)
        header = self.evidence_table.horizontalHeader()
        header.setStretchLastSection(False)
        for col in range(len(EvidenceTableModel.COLUMNS) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(EvidenceTableModel.COLUMNS) - 1, QHeaderView.Stretch)

        # --- Detail tabs (bottom) ---
        self.detail_tabs = QTabWidget()

        # Tab 1: Evidence detail (text)
        self.evidence_detail = QTextEdit()
        self.evidence_detail.setReadOnly(True)
        self.evidence_detail.setPlaceholderText("Pilih satu baris evidence di atas untuk melihat detail lengkap.")
        self.detail_tabs.addTab(self.evidence_detail, "Evidence Detail")

        # Tab 2: Technologies
        self.tech_model = TechnologyTableModel()
        self.tech_table = _make_table(self.tech_model)
        th = self.tech_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.detail_tabs.addTab(self.tech_table, "Technologies")

        # Tab 3: CPE candidates
        self.cpe_model = CpeCandidateTableModel()
        self.cpe_table = _make_table(self.cpe_model)
        ch = self.cpe_table.horizontalHeader()
        ch.setStretchLastSection(False)
        for col in range(len(CpeCandidateTableModel.COLUMNS) - 1):
            ch.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        ch.setSectionResizeMode(2, QHeaderView.Stretch)
        self.detail_tabs.addTab(self.cpe_table, "CPE Candidates")

        # Tab 4: Pipeline status
        self.pipeline_detail = QTextEdit()
        self.pipeline_detail.setReadOnly(True)
        self.pipeline_detail.setPlaceholderText("Pipeline enrichment status untuk evidence yang dipilih.")
        self.detail_tabs.addTab(self.pipeline_detail, "Pipeline Status")

        # --- splitter ---
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.evidence_table)
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([420, 380])

        # --- pagination ---
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.page_label = QLabel("Page 1 / 1")
        self.total_label = QLabel("0 records")
        page_layout = QHBoxLayout()
        page_layout.addWidget(self.prev_button)
        page_layout.addWidget(self.next_button)
        page_layout.addWidget(self.page_label)
        page_layout.addStretch()
        page_layout.addWidget(self.total_label)

        # --- root layout ---
        root = QVBoxLayout(self)
        title = QLabel("CTI Enrichment — WPT Verified Evidence")
        title.setObjectName("AppTitle")
        desc = QLabel(
            "Data enrichment hasil observasi (fingerprinting) dari Recon Agent. "
            "Evidence dikirim melalui HMAC-authenticated delivery, diproses CPE matching, "
            "dan menjadi input untuk CTI pipeline (vulnerability correlation, ATT&CK mapping, risk prioritization)."
        )
        desc.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(desc)
        root.addLayout(filter_layout)
        root.addWidget(splitter, 1)
        root.addLayout(page_layout)

    # ------------------------------------------------------------------
    # Public API — called by the controller
    # ------------------------------------------------------------------

    def set_pagination(self, current_page: int, total_pages: int, total_rows: int):
        self.page_label.setText(f"Page {current_page} / {max(total_pages, 1)}")
        self.total_label.setText(f"{total_rows} records")
        self.prev_button.setEnabled(current_page > 1)
        self.next_button.setEnabled(current_page < total_pages)

    def show_evidence_detail(self, record: dict | None):
        if not record:
            self.evidence_detail.clear()
            self.tech_model.set_rows([])
            self.cpe_model.set_rows([])
            self.pipeline_detail.clear()
            return

        result = record.get("_result") or {}

        # Evidence detail text
        def fmt(v):
            return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else str(v or "-")

        text = (
            f"Intake ID: {record.get('intake_id', '-')}\n"
            f"Mission ID: {record.get('mission_id', '-')}\n"
            f"Task ID: {record.get('task_id', '-')}\n"
            f"Recon Run ID: {record.get('recon_run_id', '-')}\n"
            f"Input SHA-256: {record.get('input_sha256', '-')}\n"
            f"Evidence Manifest SHA-256: {record.get('evidence_manifest_sha256', '-')}\n"
            f"Created: {fmt(record.get('created_at'))}\n\n"
            f"--- Enrichment Result ---\n"
            f"Target: {result.get('target_io_performed_by_cti', '-')} (target I/O by CTI: False)\n"
            f"Technology Count: {result.get('technology_count', 0)}\n"
            f"CPE Candidates: {len(result.get('cpe_candidates', []))}\n"
            f"Verified Vulns: {result.get('verified_vulnerability_count', 0)}\n"
            f"Classification: {result.get('classification', '-')}\n"
        )
        self.evidence_detail.setPlainText(text)

        # Technologies
        technologies = result.get("technologies") or []
        self.tech_model.set_rows(technologies)

        # CPE candidates
        candidates = result.get("cpe_candidates") or []
        self.cpe_model.set_rows(candidates)

        # Pipeline status
        pipeline_text = (
            f"--- CTI Pipeline Status ---\n"
            f"Evidence status: SEALED\n"
            f"CPE Resolution: {len(candidates)} candidate(s)\n"
            f"Vulnerability Correlation: {'Pending' if result.get('verified_vulnerability_count', 0) == 0 else 'Completed'}\n"
            f"ATT&CK Mapping: Pending (awaiting confirmed vulnerabilities)\n"
            f"Risk Prioritization: Pending\n"
            f"PIP Assembly: Not started\n\n"
            f"Authority Invariants:\n"
            f"  - target_io_performed_by_cti: {result.get('target_io_performed_by_cti', False)}\n"
            f"  - Reasoning does not imply authority\n"
            f"  - Recommendation does not imply authorization\n"
            f"  - Vulnerability applicability does not imply exploitability\n"
        )
        self.pipeline_detail.setPlainText(pipeline_text)
