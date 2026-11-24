from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
)


class FilterBar(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search CVE ID or description...")

        self.severity_combo = QComboBox()
        self.severity_combo.addItems(["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"])

        self.min_score = QDoubleSpinBox()
        self.min_score.setRange(0.0, 10.0)
        self.min_score.setDecimals(1)
        self.min_score.setSingleStep(0.1)
        self.min_score.setValue(0.0)

        self.max_score = QDoubleSpinBox()
        self.max_score.setRange(0.0, 10.0)
        self.max_score.setDecimals(1)
        self.max_score.setSingleStep(0.1)
        self.max_score.setValue(10.0)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(0, 2100)
        self.year_spin.setSpecialValueText("Any")
        self.year_spin.setValue(0)
        self.year_spin.setToolTip("Filter by CVE published year")

        self.cwe_input = QLineEdit()
        self.cwe_input.setPlaceholderText("CWE-79")
        self.cwe_input.setMaximumWidth(110)

        self.has_cpe_checkbox = QCheckBox("Has CPE")

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250"])
        self.page_size_combo.setCurrentText("100")

        self.apply_button = QPushButton("Apply")
        self.reset_button = QPushButton("Reset")
        self.export_button = QPushButton("Export CSV")
        self.full_sync_button = QPushButton("Full Sync")
        self.incremental_button = QPushButton("Incremental Sync")

        layout.addWidget(QLabel("Search"))
        layout.addWidget(self.search_input, 2)
        layout.addWidget(QLabel("Severity"))
        layout.addWidget(self.severity_combo)
        layout.addWidget(QLabel("Min"))
        layout.addWidget(self.min_score)
        layout.addWidget(QLabel("Max"))
        layout.addWidget(self.max_score)
        layout.addWidget(QLabel("Year"))
        layout.addWidget(self.year_spin)
        layout.addWidget(QLabel("CWE"))
        layout.addWidget(self.cwe_input)
        layout.addWidget(self.has_cpe_checkbox)
        layout.addWidget(QLabel("Page"))
        layout.addWidget(self.page_size_combo)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.export_button)
        layout.addStretch()
        layout.addWidget(self.incremental_button)
        layout.addWidget(self.full_sync_button)
