from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QTabWidget,
    QTableView,
    QAbstractItemView,
    QHeaderView,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QSplitter,
)


class AttackPatternTableModel(QAbstractTableModel):
    HEADERS = ["ATT&CK ID", "Technique", "Kind", "Platforms", "Domains", "Modified", "Used By"]

    def __init__(self, rows=None):
        super().__init__()
        self.rows = rows or []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("attack_id") or ""
            if col == 1:
                return row.get("name") or ""
            if col == 2:
                return "Sub-technique" if row.get("is_subtechnique") else "Technique"
            if col == 3:
                return row.get("platforms_text") or ""
            if col == 4:
                return row.get("domains_text") or ""
            if col == 5:
                dt = row.get("modified_at_source")
                return dt.strftime("%Y-%m-%d") if dt else ""
            if col == 6:
                total = int(row.get("malware_count", 0)) + int(row.get("actor_count", 0))
                return total

        if role == Qt.TextAlignmentRole and col in (0, 2, 6):
            return Qt.AlignCenter

        if role == Qt.FontRole and col == 0:
            font = QFont()
            font.setBold(True)
            return font

        return None

    def get_row(self, row_index: int):
        return self.rows[row_index]


class MalwareTableModel(QAbstractTableModel):
    HEADERS = ["Software ID", "Malware", "Family", "Platforms", "Domains", "Modified", "Uses"]

    def __init__(self, rows=None):
        super().__init__()
        self.rows = rows or []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("software_id") or ""
            if col == 1:
                return row.get("name") or ""
            if col == 2:
                return "Family" if row.get("is_family") else "Malware"
            if col == 3:
                return row.get("platforms_text") or ""
            if col == 4:
                return row.get("domains_text") or ""
            if col == 5:
                dt = row.get("modified_at_source")
                return dt.strftime("%Y-%m-%d") if dt else ""
            if col == 6:
                return row.get("technique_count", 0)

        if role == Qt.TextAlignmentRole and col in (0, 2, 6):
            return Qt.AlignCenter

        if role == Qt.FontRole and col == 0:
            font = QFont()
            font.setBold(True)
            return font

        if role == Qt.ForegroundRole and col == 2 and row.get("is_family"):
            return QBrush(QColor("#bfdbfe"))

        return None

    def get_row(self, row_index: int):
        return self.rows[row_index]


class ThreatActorTableModel(QAbstractTableModel):
    HEADERS = ["Group ID", "Threat Actor", "Aliases", "Primary Motivation", "Modified", "Techniques", "Software"]

    def __init__(self, rows=None):
        super().__init__()
        self.rows = rows or []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("group_id") or ""
            if col == 1:
                return row.get("name") or ""
            if col == 2:
                return row.get("aliases_text") or ""
            if col == 3:
                return row.get("primary_motivation") or ""
            if col == 4:
                dt = row.get("modified_at_source")
                return dt.strftime("%Y-%m-%d") if dt else ""
            if col == 5:
                return row.get("technique_count", 0)
            if col == 6:
                return row.get("malware_count", 0)

        if role == Qt.TextAlignmentRole and col in (0, 4, 5, 6):
            return Qt.AlignCenter

        if role == Qt.FontRole and col == 0:
            font = QFont()
            font.setBold(True)
            return font

        return None

    def get_row(self, row_index: int):
        return self.rows[row_index]


class MitreDetailPanel(QWidget):
    def __init__(self):
        super().__init__()

        root = QVBoxLayout(self)

        self.title_label = QLabel("No ATT&CK object selected")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700;")

        self.summary_label = QLabel("")
        self.description_box = QTextEdit()
        self.description_box.setReadOnly(True)
        self.description_box.setMinimumHeight(130)

        self.tabs = QTabWidget()

        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        self.related_table = QTableWidget()
        self.reference_table = QTableWidget()
        self.reference_table.setColumnCount(4)
        self.reference_table.setHorizontalHeaderLabels(["Source", "External ID", "URL", "Description"])

        self.raw_json_box = QTextEdit()
        self.raw_json_box.setReadOnly(True)

        self.tabs.addTab(self.metadata_table, "Metadata")
        self.tabs.addTab(self.related_table, "Relationships")
        self.tabs.addTab(self.reference_table, "References")
        self.tabs.addTab(self.raw_json_box, "Raw JSON")

        root.addWidget(self.title_label)
        root.addWidget(self.summary_label)
        root.addWidget(self.description_box)
        root.addWidget(self.tabs, 1)

    def clear_detail(self):
        self.title_label.setText("No ATT&CK object selected")
        self.summary_label.setText("")
        self.description_box.setPlainText("")
        self.metadata_table.clearContents()
        self.metadata_table.setRowCount(0)
        self.related_table.clearContents()
        self.related_table.setRowCount(0)
        self.related_table.setColumnCount(0)
        self.reference_table.clearContents()
        self.reference_table.setRowCount(0)
        self.raw_json_box.setPlainText("")

    def _set_metadata_rows(self, rows: list[tuple[str, str]]):
        self.metadata_table.setRowCount(len(rows))
        for i, (key, value) in enumerate(rows):
            self.metadata_table.setItem(i, 0, QTableWidgetItem(key))
            self.metadata_table.setItem(i, 1, QTableWidgetItem(value))

    def _set_reference_rows(self, rows: list[dict]):
        self.reference_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.reference_table.setItem(i, 0, QTableWidgetItem(row.get("source_name") or ""))
            self.reference_table.setItem(i, 1, QTableWidgetItem(row.get("external_id") or ""))
            self.reference_table.setItem(i, 2, QTableWidgetItem(row.get("url") or ""))
            self.reference_table.setItem(i, 3, QTableWidgetItem(row.get("description_text") or ""))

    def show_attack_pattern_detail(self, detail: dict | None):
        if detail is None:
            self.clear_detail()
            return

        self.title_label.setText(f"{detail.get('attack_id') or '-'} - {detail.get('name') or ''}")
        summary = ["Technique"]
        if detail.get("is_subtechnique"):
            summary = ["Sub-technique"]
        if detail.get("modified_at_source"):
            summary.append(f"Modified: {detail['modified_at_source'].strftime('%Y-%m-%d')}")
        summary.append(
            f"Used by: {len(detail.get('used_by_malware') or []) + len(detail.get('used_by_threat_actors') or [])}"
        )
        self.summary_label.setText(" | ".join(summary))
        self.description_box.setPlainText(detail.get("description_text") or "")
        self.raw_json_box.setPlainText(detail.get("raw_json") or "")

        metadata_rows = [
            ("STIX ID", detail.get("stix_id") or ""),
            ("ATT&CK ID", detail.get("attack_id") or ""),
            ("Name", detail.get("name") or ""),
            ("Type", "Sub-technique" if detail.get("is_subtechnique") else "Technique"),
            ("Platforms", ", ".join(detail.get("platforms") or [])),
            ("Domains", ", ".join(detail.get("domains") or [])),
            ("Data Sources", ", ".join(detail.get("data_sources") or [])),
            ("Detection", detail.get("detection_text") or ""),
            ("Version", detail.get("version_value") or ""),
            ("ATT&CK Spec", detail.get("attack_spec_version") or ""),
            ("STIX Spec", detail.get("stix_spec_version") or ""),
            ("Revoked", "Yes" if detail.get("revoked") else "No"),
            ("Deprecated", "Yes" if detail.get("deprecated") else "No"),
        ]
        if detail.get("created_at_source"):
            metadata_rows.insert(4, ("Created", detail["created_at_source"].strftime("%Y-%m-%d %H:%M:%S")))
        if detail.get("modified_at_source"):
            metadata_rows.insert(5, ("Modified", detail["modified_at_source"].strftime("%Y-%m-%d %H:%M:%S")))
        for phase in detail.get("kill_chain_phases") or []:
            metadata_rows.append(("Kill Chain", f"{phase.get('kill_chain_name')}: {phase.get('phase_name')}"))
        self._set_metadata_rows(metadata_rows)

        related = []
        for row in detail.get("used_by_threat_actors") or []:
            related.append(["Threat Actor", row.get("group_id") or "", row.get("actor_name") or "", row.get("relationship_type") or ""])
        for row in detail.get("used_by_malware") or []:
            related.append(["Malware", row.get("software_id") or "", row.get("malware_name") or "", row.get("relationship_type") or ""])

        self.related_table.setColumnCount(4)
        self.related_table.setHorizontalHeaderLabels(["Source Type", "ID", "Name", "Relation"])
        self.related_table.setRowCount(len(related))
        for i, row in enumerate(related):
            for j, value in enumerate(row):
                self.related_table.setItem(i, j, QTableWidgetItem(value))

        self._set_reference_rows(detail.get("references") or [])

    def show_malware_detail(self, detail: dict | None):
        if detail is None:
            self.clear_detail()
            return

        self.title_label.setText(f"{detail.get('software_id') or '-'} - {detail.get('name') or ''}")
        summary = ["Family" if detail.get("is_family") else "Malware"]
        if detail.get("modified_at_source"):
            summary.append(f"Modified: {detail['modified_at_source'].strftime('%Y-%m-%d')}")
        summary.append(f"Techniques used: {len(detail.get('uses_techniques') or [])}")
        summary.append(f"Used by actors: {len(detail.get('used_by_threat_actors') or [])}")
        self.summary_label.setText(" | ".join(summary))
        self.description_box.setPlainText(detail.get("description_text") or "")
        self.raw_json_box.setPlainText(detail.get("raw_json") or "")

        metadata_rows = [
            ("STIX ID", detail.get("stix_id") or ""),
            ("Software ID", detail.get("software_id") or ""),
            ("Name", detail.get("name") or ""),
            ("Type", "Family" if detail.get("is_family") else "Malware"),
            ("Platforms", ", ".join(detail.get("platforms") or [])),
            ("Domains", ", ".join(detail.get("domains") or [])),
            ("Aliases", ", ".join(detail.get("aliases") or [])),
            ("Version", detail.get("version_value") or ""),
            ("ATT&CK Spec", detail.get("attack_spec_version") or ""),
            ("STIX Spec", detail.get("stix_spec_version") or ""),
            ("Revoked", "Yes" if detail.get("revoked") else "No"),
            ("Deprecated", "Yes" if detail.get("deprecated") else "No"),
        ]
        if detail.get("created_at_source"):
            metadata_rows.insert(4, ("Created", detail["created_at_source"].strftime("%Y-%m-%d %H:%M:%S")))
        if detail.get("modified_at_source"):
            metadata_rows.insert(5, ("Modified", detail["modified_at_source"].strftime("%Y-%m-%d %H:%M:%S")))
        self._set_metadata_rows(metadata_rows)

        related = []
        for row in detail.get("uses_techniques") or []:
            related.append(["Technique", row.get("attack_id") or "", row.get("technique_name") or "", row.get("relationship_type") or ""])
        for row in detail.get("used_by_threat_actors") or []:
            related.append(["Threat Actor", row.get("group_id") or "", row.get("actor_name") or "", row.get("relationship_type") or ""])

        self.related_table.setColumnCount(4)
        self.related_table.setHorizontalHeaderLabels(["Target/Source", "ID", "Name", "Relation"])
        self.related_table.setRowCount(len(related))
        for i, row in enumerate(related):
            for j, value in enumerate(row):
                self.related_table.setItem(i, j, QTableWidgetItem(value))

        self._set_reference_rows(detail.get("references") or [])

    def show_threat_actor_detail(self, detail: dict | None):
        if detail is None:
            self.clear_detail()
            return

        self.title_label.setText(f"{detail.get('group_id') or '-'} - {detail.get('name') or ''}")
        summary = ["Threat Actor"]
        if detail.get("modified_at_source"):
            summary.append(f"Modified: {detail['modified_at_source'].strftime('%Y-%m-%d')}")
        summary.append(f"Techniques: {len(detail.get('uses_techniques') or [])}")
        summary.append(f"Software: {len(detail.get('uses_malware') or [])}")
        self.summary_label.setText(" | ".join(summary))
        self.description_box.setPlainText(detail.get("description_text") or "")
        self.raw_json_box.setPlainText(detail.get("raw_json") or "")

        metadata_rows = [
            ("STIX ID", detail.get("stix_id") or ""),
            ("Group ID", detail.get("group_id") or ""),
            ("Name", detail.get("name") or ""),
            ("Aliases", ", ".join(detail.get("aliases") or [])),
            ("Domains", ", ".join(detail.get("domains") or [])),
            ("Goals", ", ".join(detail.get("goals") or [])),
            ("Resource Level", detail.get("resource_level") or ""),
            ("Primary Motivation", detail.get("primary_motivation") or ""),
            ("Secondary Motivations", ", ".join(detail.get("secondary_motivations") or [])),
            ("Version", detail.get("version_value") or ""),
            ("ATT&CK Spec", detail.get("attack_spec_version") or ""),
            ("STIX Spec", detail.get("stix_spec_version") or ""),
            ("Revoked", "Yes" if detail.get("revoked") else "No"),
            ("Deprecated", "Yes" if detail.get("deprecated") else "No"),
        ]
        if detail.get("created_at_source"):
            metadata_rows.insert(4, ("Created", detail["created_at_source"].strftime("%Y-%m-%d %H:%M:%S")))
        if detail.get("modified_at_source"):
            metadata_rows.insert(5, ("Modified", detail["modified_at_source"].strftime("%Y-%m-%d %H:%M:%S")))
        if detail.get("first_seen_source"):
            metadata_rows.append(("First Seen", detail["first_seen_source"].strftime("%Y-%m-%d %H:%M:%S")))
        if detail.get("last_seen_source"):
            metadata_rows.append(("Last Seen", detail["last_seen_source"].strftime("%Y-%m-%d %H:%M:%S")))
        self._set_metadata_rows(metadata_rows)

        related = []
        for row in detail.get("uses_techniques") or []:
            related.append(["Technique", row.get("attack_id") or "", row.get("technique_name") or "", row.get("relationship_type") or ""])
        for row in detail.get("uses_malware") or []:
            related.append(["Malware", row.get("software_id") or "", row.get("malware_name") or "", row.get("relationship_type") or ""])

        self.related_table.setColumnCount(4)
        self.related_table.setHorizontalHeaderLabels(["Target Type", "ID", "Name", "Relation"])
        self.related_table.setRowCount(len(related))
        for i, row in enumerate(related):
            for j, value in enumerate(row):
                self.related_table.setItem(i, j, QTableWidgetItem(value))

        self._set_reference_rows(detail.get("references") or [])


class MitreAttackPage(QWidget):
    def __init__(self):
        super().__init__()

        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search ATT&CK ID, software, group, alias, motivation...")
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250"])
        self.page_size_combo.setCurrentText("100")
        self.search_button = QPushButton("Apply")
        self.reset_button = QPushButton("Reset")
        self.refresh_button = QPushButton("Refresh View")
        self.mitre_incremental_button = QPushButton("MITRE Inc")
        self.mitre_full_sync_button = QPushButton("MITRE Full")

        toolbar.addWidget(QLabel("Search"))
        toolbar.addWidget(self.search_input, 2)
        toolbar.addWidget(QLabel("Page"))
        toolbar.addWidget(self.page_size_combo)
        toolbar.addWidget(self.search_button)
        toolbar.addWidget(self.reset_button)
        toolbar.addWidget(self.refresh_button)
        toolbar.addStretch()
        toolbar.addWidget(self.mitre_incremental_button)
        toolbar.addWidget(self.mitre_full_sync_button)

        self.entity_tabs = QTabWidget()

        self.technique_table = QTableView()
        self.technique_model = AttackPatternTableModel()
        self.technique_table.setModel(self.technique_model)

        self.malware_table = QTableView()
        self.malware_model = MalwareTableModel()
        self.malware_table.setModel(self.malware_model)

        self.actor_table = QTableView()
        self.actor_model = ThreatActorTableModel()
        self.actor_table.setModel(self.actor_model)

        for table in (self.technique_table, self.malware_table, self.actor_table):
            table.setSelectionBehavior(QTableView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.setAlternatingRowColors(True)
            table.setSortingEnabled(False)
            table.setWordWrap(False)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            header = table.horizontalHeader()
            header.setSectionsClickable(False)
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.Stretch)
            for col in range(2, 7):
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.entity_tabs.addTab(self.technique_table, "Techniques")
        self.entity_tabs.addTab(self.malware_table, "Malware")
        self.entity_tabs.addTab(self.actor_table, "Threat Actors")

        self.detail_panel = MitreDetailPanel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.entity_tabs)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([960, 580])

        pagination = QHBoxLayout()
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.page_label = QLabel("Page 1 / 1")
        self.total_label = QLabel("0 records")
        pagination.addWidget(self.prev_button)
        pagination.addWidget(self.next_button)
        pagination.addWidget(self.page_label)
        pagination.addStretch()
        pagination.addWidget(self.total_label)

        root.addLayout(toolbar)
        root.addWidget(splitter, 1)
        root.addLayout(pagination)
