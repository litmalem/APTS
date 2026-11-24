from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QSpinBox,
    QTableView,
    QAbstractItemView,
    QHeaderView,
    QTextEdit,
    QSplitter,
)


class CweTableModel(QAbstractTableModel):
    COLUMNS = [
        ("cwe_id", "CWE ID"),
        ("cwe_name", "Name"),
        ("abstraction", "Abstraction"),
        ("status_value", "Status"),
        ("likelihood_of_exploit", "Likelihood"),
        ("cve_count", "CVE Links"),
        ("api_synced_at", "Synced"),
        ("description_text", "Description"),
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
            return value.strftime("%Y-%m-%d %H:%M")
        if value is None:
            return ""
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section][1]
        return str(section + 1)


class CweCatalogPage(QWidget):
    def __init__(self):
        super().__init__()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search CWE ID, name, or description... e.g. CWE-79, SQL Injection")
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250"])
        self.page_size_combo.setCurrentText("100")

        self.search_button = QPushButton("Search")
        self.reset_button = QPushButton("Reset")
        self.refresh_button = QPushButton("Refresh")

        self.fetch_one_button = QPushButton("Fetch CWE ID")
        self.sync_known_button = QPushButton("Sync Known CWE")
        self.sync_view_button = QPushButton("Sync View 1000")
        self.sync_range_button = QPushButton("Sync Range")

        self.view_id_spin = QSpinBox()
        self.view_id_spin.setRange(1, 99999)
        self.view_id_spin.setValue(1000)
        self.view_id_spin.setToolTip("MITRE CWE View ID. 1000 is commonly used for the comprehensive view.")
        self.view_id_spin.setMaximumWidth(90)

        self.range_start_spin = QSpinBox()
        self.range_start_spin.setRange(1, 99999)
        self.range_start_spin.setValue(1)
        self.range_start_spin.setMaximumWidth(90)
        self.range_end_spin = QSpinBox()
        self.range_end_spin.setRange(1, 99999)
        self.range_end_spin.setValue(1500)
        self.range_end_spin.setMaximumWidth(90)

        self.table_model = CweTableModel()
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3, 4, 5, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)

        self.detail_box = QTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setPlaceholderText("Select a CWE row to see complete CWE details.")

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_box)
        splitter.setSizes([560, 300])

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Search"))
        filter_layout.addWidget(self.search_input, 2)
        filter_layout.addWidget(QLabel("Page"))
        filter_layout.addWidget(self.page_size_combo)
        filter_layout.addWidget(self.search_button)
        filter_layout.addWidget(self.reset_button)
        filter_layout.addWidget(self.refresh_button)

        sync_layout = QHBoxLayout()
        sync_layout.addWidget(QLabel("View ID"))
        sync_layout.addWidget(self.view_id_spin)
        sync_layout.addWidget(self.sync_view_button)
        sync_layout.addSpacing(12)
        sync_layout.addWidget(QLabel("Range"))
        sync_layout.addWidget(self.range_start_spin)
        sync_layout.addWidget(QLabel("to"))
        sync_layout.addWidget(self.range_end_spin)
        sync_layout.addWidget(self.sync_range_button)
        sync_layout.addStretch()
        sync_layout.addWidget(self.fetch_one_button)
        sync_layout.addWidget(self.sync_known_button)

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

        root = QVBoxLayout(self)
        title = QLabel("CWE Catalog")
        title.setObjectName("AppTitle")
        desc = QLabel(
            "Upload/sinkronisasi data CWE dari MITRE CWE REST API, lalu gunakan search lokal untuk mencari CWE berdasarkan ID, nama, dan uraian."
        )
        desc.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(desc)
        root.addLayout(filter_layout)
        root.addLayout(sync_layout)
        root.addWidget(splitter, 1)
        root.addLayout(page_layout)

    def set_pagination(self, current_page: int, total_pages: int, total_rows: int):
        self.page_label.setText(f"Page {current_page} / {max(total_pages, 1)}")
        self.total_label.setText(f"{total_rows} records")
        self.prev_button.setEnabled(current_page > 1)
        self.next_button.setEnabled(current_page < total_pages)

    def show_detail(self, detail: dict | None):
        if not detail:
            self.detail_box.clear()
            return
        synced = detail.get("api_synced_at")
        if isinstance(synced, datetime):
            synced_label = synced.strftime("%Y-%m-%d %H:%M:%S")
        else:
            synced_label = str(synced or "-")
        text = (
            f"CWE ID: {detail.get('cwe_id') or '-'}\n"
            f"Name: {detail.get('cwe_name') or '-'}\n"
            f"Abstraction: {detail.get('abstraction') or '-'}\n"
            f"Structure: {detail.get('structure_value') or '-'}\n"
            f"Status: {detail.get('status_value') or '-'}\n"
            f"Likelihood of Exploit: {detail.get('likelihood_of_exploit') or '-'}\n"
            f"URL: {detail.get('cwe_url') or '-'}\n"
            f"Source: {detail.get('source_name') or '-'}\n"
            f"API Version: {detail.get('api_version') or '-'}\n"
            f"Synced: {synced_label}\n\n"
            f"Description:\n{detail.get('description_text') or '-'}\n\n"
            f"Extended Description:\n{detail.get('extended_description') or '-'}\n\n"
            f"Related Weaknesses JSON:\n{detail.get('related_weaknesses_json') or '-'}\n\n"
            f"Alternate Terms JSON:\n{detail.get('alternate_terms_json') or '-'}"
        )
        self.detail_box.setPlainText(text)
