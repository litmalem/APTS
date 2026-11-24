from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PySide6.QtGui import QColor, QBrush, QFont


SEVERITY_BG = {
    "CRITICAL": QColor("#fee2e2"),
    "HIGH": QColor("#ffedd5"),
    "MEDIUM": QColor("#fef3c7"),
    "LOW": QColor("#dcfce7"),
}

SEVERITY_FG = {
    "CRITICAL": QColor("#991b1b"),
    "HIGH": QColor("#9a3412"),
    "MEDIUM": QColor("#92400e"),
    "LOW": QColor("#166534"),
}


class VulnerabilityTableModel(QAbstractTableModel):
    HEADERS = [
        "CVE ID",
        "Description",
        "Severity",
        "Score",
        "CVSS",
        "Published",
        "Modified",
        "CWE",
        "Refs",
        "CPE",
    ]

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
        severity = (row.get("preferred_base_severity") or "").upper()

        if role == Qt.DisplayRole:
            if col == 0:
                return row["cve_id"]
            if col == 1:
                return (row.get("description_text") or "")[:120]
            if col == 2:
                return severity
            if col == 3:
                return row.get("preferred_base_score") if row.get("preferred_base_score") is not None else ""
            if col == 4:
                return row.get("preferred_cvss_version") or ""
            if col == 5:
                dt = row.get("published_at")
                return dt.strftime("%Y-%m-%d") if dt else ""
            if col == 6:
                dt = row.get("modified_at")
                return dt.strftime("%Y-%m-%d") if dt else ""
            if col == 7:
                return row.get("cwe_count", 0)
            if col == 8:
                return row.get("reference_count", 0)
            if col == 9:
                return row.get("affected_product_count", 0)

        if role == Qt.TextAlignmentRole and col in (2, 3, 4, 7, 8, 9):
            return Qt.AlignCenter

        if role == Qt.ForegroundRole and col == 2 and severity in SEVERITY_FG:
            return QBrush(SEVERITY_FG[severity])

        if role == Qt.BackgroundRole and col == 2 and severity in SEVERITY_BG:
            return QBrush(SEVERITY_BG[severity])

        if role == Qt.FontRole and col == 2:
            font = QFont()
            font.setBold(True)
            return font

        return None

    def get_row(self, row_index: int):
        return self.rows[row_index]
