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
    QCheckBox,
)


class CpeDictionaryTableModel(QAbstractTableModel):
    COLUMNS = [
        ("cpe_name_id", "CPE Name ID"),
        ("vendor", "Vendor"),
        ("product", "Product"),
        ("version", "Version"),
        ("part", "Part"),
        ("deprecated", "Deprecated"),
        ("modified_at_source", "NVD Modified"),
        ("title", "Title"),
        ("cpe23_uri", "CPE 2.3 URI"),
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
        if key == "deprecated":
            return "Yes" if bool(value) else "No"
        if value is None:
            return ""
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section][1]
        return str(section + 1)


class CpeDictionaryPage(QWidget):
    def __init__(self):
        super().__init__()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search vendor, product, version, title, CPE URI... e.g. apache http_server 2.4")
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250", "500"])
        self.page_size_combo.setCurrentText("100")
        self.include_deprecated_checkbox = QCheckBox("Include deprecated")

        self.search_button = QPushButton("Search")
        self.reset_button = QPushButton("Reset")
        self.refresh_button = QPushButton("Refresh")

        self.sync_keyword_button = QPushButton("Sync Keyword")
        self.sync_match_button = QPushButton("Sync Match String")
        self.sync_page_button = QPushButton("Sync First Page(s)")
        self.sync_input = QLineEdit()
        self.sync_input.setPlaceholderText("keyword or cpeMatchString, e.g. apache http_server or cpe:2.3:a:apache:http_server:*")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 500)
        self.max_pages_spin.setValue(1)
        self.max_pages_spin.setMaximumWidth(90)
        self.sync_page_size_spin = QSpinBox()
        self.sync_page_size_spin.setRange(1, 2000)
        self.sync_page_size_spin.setValue(100)
        self.sync_page_size_spin.setMaximumWidth(90)

        self.table_model = CpeDictionaryTableModel()
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for col in (0, 1, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        header.setSectionResizeMode(8, QHeaderView.Stretch)

        self.detail_box = QTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setPlaceholderText("Select a CPE row to see complete official dictionary details.")

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_box)
        splitter.setSizes([600, 320])

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Search"))
        filter_layout.addWidget(self.search_input, 2)
        filter_layout.addWidget(QLabel("Page"))
        filter_layout.addWidget(self.page_size_combo)
        filter_layout.addWidget(self.include_deprecated_checkbox)
        filter_layout.addWidget(self.search_button)
        filter_layout.addWidget(self.reset_button)
        filter_layout.addWidget(self.refresh_button)

        sync_layout = QHBoxLayout()
        sync_layout.addWidget(QLabel("NVD CPE Sync"))
        sync_layout.addWidget(self.sync_input, 2)
        sync_layout.addWidget(QLabel("Pages"))
        sync_layout.addWidget(self.max_pages_spin)
        sync_layout.addWidget(QLabel("Size"))
        sync_layout.addWidget(self.sync_page_size_spin)
        sync_layout.addWidget(self.sync_keyword_button)
        sync_layout.addWidget(self.sync_match_button)
        sync_layout.addWidget(self.sync_page_button)

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
        title = QLabel("NVD Official CPE Dictionary")
        title.setObjectName("AppTitle")
        desc = QLabel(
            "Kelola local mirror Official CPE Dictionary dari NVD. Data ini digunakan VulnDesk untuk "
            "memvalidasi dan menormalisasi technology fingerprint dari aplikasi Pentest sebelum mapping CPE→CVE."
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

        def fmt_dt(value):
            return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else str(value or "-")

        text = (
            f"CPE Name ID: {detail.get('cpe_name_id') or '-'}\n"
            f"CPE 2.3 URI: {detail.get('cpe23_uri') or '-'}\n"
            f"Part: {detail.get('part') or '-'}\n"
            f"Vendor: {detail.get('vendor') or '-'}\n"
            f"Product: {detail.get('product') or '-'}\n"
            f"Version: {detail.get('version') or '-'}\n"
            f"Update: {detail.get('update_value') or '-'}\n"
            f"Edition: {detail.get('edition') or '-'}\n"
            f"Language: {detail.get('language') or '-'}\n"
            f"SW Edition: {detail.get('sw_edition') or '-'}\n"
            f"Target SW: {detail.get('target_sw') or '-'}\n"
            f"Target HW: {detail.get('target_hw') or '-'}\n"
            f"Other: {detail.get('other') or '-'}\n"
            f"Deprecated: {'Yes' if detail.get('deprecated') else 'No'}\n"
            f"Source: {detail.get('source_name') or '-'}\n"
            f"Created at NVD: {fmt_dt(detail.get('created_at_source'))}\n"
            f"Modified at NVD: {fmt_dt(detail.get('modified_at_source'))}\n"
            f"Last synced: {fmt_dt(detail.get('last_synced_at'))}\n\n"
            f"Title:\n{detail.get('title') or '-'}\n\n"
            f"Titles JSON:\n{detail.get('titles_json') or '-'}\n\n"
            f"References JSON:\n{detail.get('references_json') or '-'}\n\n"
            f"Deprecated By JSON:\n{detail.get('deprecated_by_json') or '-'}\n"
        )
        self.detail_box.setPlainText(text)
