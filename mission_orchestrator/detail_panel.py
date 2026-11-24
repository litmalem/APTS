from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
)


class DetailPanel(QWidget):
    def __init__(self):
        super().__init__()

        root = QVBoxLayout(self)

        self.title_label = QLabel("No vulnerability selected")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700;")

        self.summary_label = QLabel("")
        self.description_box = QTextEdit()
        self.description_box.setReadOnly(True)
        self.description_box.setMinimumHeight(130)

        self.tabs = QTabWidget()

        self.cvss_table = QTableWidget()
        self.cvss_table.setColumnCount(6)
        self.cvss_table.setHorizontalHeaderLabels(
            ["Version", "Severity", "Score", "Vector", "Source", "Preferred"]
        )

        self.cwe_table = QTableWidget()
        self.cwe_table.setColumnCount(6)
        self.cwe_table.setHorizontalHeaderLabels(["CWE ID", "Name", "Description", "Likelihood", "Status", "URL"])

        self.reference_table = QTableWidget()
        self.reference_table.setColumnCount(3)
        self.reference_table.setHorizontalHeaderLabels(["URL", "Source", "Tags"])

        self.cpe_table = QTableWidget()
        self.cpe_table.setColumnCount(6)
        self.cpe_table.setHorizontalHeaderLabels(
            ["Criteria", "Vulnerable", "Start Inc", "Start Exc", "End Inc", "End Exc"]
        )

        self.raw_json_box = QTextEdit()
        self.raw_json_box.setReadOnly(True)

        self.tabs.addTab(self.cvss_table, "CVSS")
        self.tabs.addTab(self.cwe_table, "CWE")
        self.tabs.addTab(self.reference_table, "References")
        self.tabs.addTab(self.cpe_table, "Affected Products")
        self.tabs.addTab(self.raw_json_box, "Raw JSON")

        root.addWidget(self.title_label)
        root.addWidget(self.summary_label)
        root.addWidget(self.description_box)
        root.addWidget(self.tabs, 1)

    def clear_detail(self):
        self.title_label.setText("No vulnerability selected")
        self.summary_label.setText("")
        self.description_box.setPlainText("")
        self.cvss_table.clearContents()
        self.cvss_table.setRowCount(0)
        self.cwe_table.clearContents()
        self.cwe_table.setRowCount(0)
        self.reference_table.clearContents()
        self.reference_table.setRowCount(0)
        self.cpe_table.clearContents()
        self.cpe_table.setRowCount(0)
        self.raw_json_box.setPlainText("")

    def show_detail(self, detail):
        if detail is None:
            self.clear_detail()
            return

        self.title_label.setText(detail["cve_id"])
        published = detail["published_at"].strftime("%Y-%m-%d") if detail.get("published_at") else "-"
        modified = detail["modified_at"].strftime("%Y-%m-%d") if detail.get("modified_at") else "-"
        self.summary_label.setText(
            f"{detail.get('preferred_base_severity') or '-'} | "
            f"Score: {detail.get('preferred_base_score') if detail.get('preferred_base_score') is not None else '-'} | "
            f"Published: {published} | Modified: {modified}"
        )
        self.description_box.setPlainText(detail.get("description_text") or "")
        self.raw_json_box.setPlainText(detail.get("raw_json") or "")

        self.cvss_table.setRowCount(len(detail["cvss_metrics"]))
        for i, m in enumerate(detail["cvss_metrics"]):
            self.cvss_table.setItem(i, 0, QTableWidgetItem(m.get("cvss_version") or ""))
            self.cvss_table.setItem(i, 1, QTableWidgetItem(m.get("base_severity") or ""))
            self.cvss_table.setItem(i, 2, QTableWidgetItem("" if m.get("base_score") is None else str(m["base_score"])))
            self.cvss_table.setItem(i, 3, QTableWidgetItem(m.get("vector_string") or ""))
            self.cvss_table.setItem(i, 4, QTableWidgetItem(m.get("source_name") or ""))
            self.cvss_table.setItem(i, 5, QTableWidgetItem("Yes" if m.get("is_preferred") else ""))

        self.cwe_table.setRowCount(len(detail["cwes"]))
        for i, c in enumerate(detail["cwes"]):
            self.cwe_table.setItem(i, 0, QTableWidgetItem(c.get("cwe_id") or ""))
            self.cwe_table.setItem(i, 1, QTableWidgetItem(c.get("cwe_name") or ""))
            self.cwe_table.setItem(i, 2, QTableWidgetItem(c.get("description_text") or ""))
            self.cwe_table.setItem(i, 3, QTableWidgetItem(c.get("likelihood_of_exploit") or ""))
            self.cwe_table.setItem(i, 4, QTableWidgetItem(c.get("status_value") or ""))
            self.cwe_table.setItem(i, 5, QTableWidgetItem(c.get("cwe_url") or ""))

        self.reference_table.setRowCount(len(detail["references"]))
        for i, r in enumerate(detail["references"]):
            self.reference_table.setItem(i, 0, QTableWidgetItem(r.get("url") or ""))
            self.reference_table.setItem(i, 1, QTableWidgetItem(r.get("source_name") or ""))
            self.reference_table.setItem(i, 2, QTableWidgetItem(r.get("tags_json") or ""))

        self.cpe_table.setRowCount(len(detail["cpe_matches"]))
        for i, cp in enumerate(detail["cpe_matches"]):
            self.cpe_table.setItem(i, 0, QTableWidgetItem(cp.get("criteria_uri") or ""))
            self.cpe_table.setItem(i, 1, QTableWidgetItem("Yes" if cp.get("is_vulnerable") else "No"))
            self.cpe_table.setItem(i, 2, QTableWidgetItem(cp.get("version_start_including") or ""))
            self.cpe_table.setItem(i, 3, QTableWidgetItem(cp.get("version_start_excluding") or ""))
            self.cpe_table.setItem(i, 4, QTableWidgetItem(cp.get("version_end_including") or ""))
            self.cpe_table.setItem(i, 5, QTableWidgetItem(cp.get("version_end_excluding") or ""))
