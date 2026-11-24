from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import Config
from detail_panel import DetailPanel
from filter_bar import FilterBar
from dataset_ui import DatasetPage
from mitre_ui import MitreAttackPage
from cwe_ui import CweCatalogPage
from cpe_dictionary_ui import CpeDictionaryPage
from table_models import VulnerabilityTableModel


LIGHT_QSS = """
QWidget {
    background-color: #f6f8fb;
    color: #0f172a;
    font-size: 12px;
}
QWidget#BrandBar {
    background-color: #ffffff;
    border: 1px solid #dbe4f0;
    border-radius: 10px;
}
QLabel#BrandTitle {
    font-size: 18px;
    font-weight: 700;
    color: #0f3d91;
}
QLabel#BrandSubtitle {
    font-size: 12px;
    color: #475569;
}
QLabel#AppTitle {
    font-size: 16px;
    font-weight: 700;
    color: #0f172a;
}
QLabel#AppSubtitle {
    font-size: 11px;
    color: #64748b;
}
QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox, QSpinBox, QTableWidget, QTableView, QTabWidget::pane {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QTableView:focus {
    border: 1px solid #3b82f6;
}
QPushButton {
    background-color: #eff6ff;
    color: #0f172a;
    border: 1px solid #bfdbfe;
    border-radius: 6px;
    padding: 6px 10px;
}
QPushButton:hover {
    background-color: #dbeafe;
}
QPushButton:pressed {
    background-color: #bfdbfe;
}
QPushButton:disabled {
    background-color: #f8fafc;
    color: #94a3b8;
    border: 1px solid #e2e8f0;
}
QHeaderView::section {
    background-color: #eaf2ff;
    color: #0f172a;
    padding: 6px;
    border: 1px solid #cbd5e1;
    font-weight: 600;
}
QTableView {
    gridline-color: #e2e8f0;
    alternate-background-color: #f8fbff;
    selection-background-color: #cfe3ff;
    selection-color: #0f172a;
}
QTableCornerButton::section {
    background-color: #eaf2ff;
    border: 1px solid #cbd5e1;
}
QLabel {
    color: #0f172a;
}
QTabBar::tab {
    background: #edf2f7;
    color: #334155;
    padding: 7px 12px;
    margin-right: 2px;
    border: 1px solid #cbd5e1;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #0f3d91;
    font-weight: 600;
}
QProgressBar {
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    background-color: #ffffff;
    text-align: center;
    min-height: 18px;
}
QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 4px;
}
QSplitter::handle {
    background-color: #dbe4f0;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(Config.APP_TITLE)
        self.resize(1680, 980)
        self.setStyleSheet(LIGHT_QSS)

        self.status_label = QLabel("Ready")
        self.sync_label = QLabel("Sync idle")
        self.sort_label = QLabel("Sort: Modified ↓")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Idle")

        self.main_tabs = QTabWidget()

        # Vulnerability page
        self.filter_bar = FilterBar()
        self.detail_panel = DetailPanel()
        self.page_label = QLabel("Page 1 / 1")
        self.filtered_label = QLabel("Filtered results: 0")
        self.total_label = QLabel("Total vulnerabilities: 0")
        self.first_button = QPushButton("First")
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.last_button = QPushButton("Last")

        self.table = QTableView()
        self.table_model = VulnerabilityTableModel()
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
        header.setSectionsClickable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3, 4, 5, 6, 7, 8, 9):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([980, 560])

        pagination_layout = QHBoxLayout()
        pagination_layout.addWidget(self.first_button)
        pagination_layout.addWidget(self.prev_button)
        pagination_layout.addWidget(self.next_button)
        pagination_layout.addWidget(self.last_button)
        pagination_layout.addWidget(self.page_label)
        pagination_layout.addWidget(self.sort_label)
        pagination_layout.addStretch()
        pagination_layout.addWidget(self.filtered_label)
        pagination_layout.addWidget(self.total_label)

        vuln_page = QWidget()
        vuln_layout = QVBoxLayout(vuln_page)
        vuln_layout.addWidget(self.filter_bar)
        vuln_layout.addWidget(splitter, 1)
        vuln_layout.addLayout(pagination_layout)

        # ATT&CK page
        self.attack_page = MitreAttackPage()

        # Tweet/topic dataset page
        self.dataset_page = DatasetPage()

        # CWE catalog page
        self.cwe_page = CweCatalogPage()

        # NVD Official CPE Dictionary page
        self.cpe_page = CpeDictionaryPage()

        self.cti_services_page = self._build_cti_services_page()

        self.main_tabs.addTab(vuln_page, "Vulnerabilities")
        self.main_tabs.addTab(self.attack_page, "MITRE ATT&CK")
        self.main_tabs.addTab(self.dataset_page, "Tweet Topics")
        self.main_tabs.addTab(self.cwe_page, "CWE Catalog")
        self.main_tabs.addTab(self.cpe_page, "CPE Dictionary")
        self.main_tabs.addTab(self.cti_services_page, "CTI Components")

        status_layout = QHBoxLayout()
        status_layout.addWidget(self.status_label, 2)
        status_layout.addWidget(self.progress_bar, 2)
        status_layout.addWidget(self.sync_label, 1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._build_brand_bar())
        layout.addWidget(self.main_tabs, 1)
        layout.addLayout(status_layout)
        self.setCentralWidget(central)

    def _build_cti_services_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        header_row = QHBoxLayout()
        title = QLabel("CTI Component Manager")
        title.setObjectName("AppTitle")
        self.btn_back_from_cti_page = QPushButton("← Kembali ke Menu Utama")
        self.btn_back_from_cti_page.clicked.connect(self.go_main_menu)
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(self.btn_back_from_cti_page)

        desc = QLabel(
            "Kelola VulnDesk enrichment services: CPE→CVE, Vulnerability Context, "
            "ATT&CK Mapping, Threat Actor/Malware Context, dan Pentest Enrichment API."
        )
        desc.setWordWrap(True)
        btn = QPushButton("Open CTI Component Manager")
        btn.clicked.connect(self.open_cti_service_manager)
        layout.addLayout(header_row)
        layout.addWidget(desc)
        layout.addWidget(btn)
        layout.addStretch(1)
        return page

    def go_main_menu(self):
        """Return from the CTI service page/window to the main VulnDesk menu."""
        try:
            if hasattr(self, "_cti_service_window") and self._cti_service_window is not None:
                self._cti_service_window.hide()
            self.main_tabs.setCurrentIndex(0)
            self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception as exc:
            QMessageBox.warning(self, "Menu Utama", f"Gagal kembali ke menu utama.\n\nDetail: {exc}")

    def open_cti_service_manager(self):
        try:
            from cti_ui import VulnDeskServiceManagerWindow
            if not hasattr(self, "_cti_service_window") or self._cti_service_window is None:
                self._cti_service_window = VulnDeskServiceManagerWindow(
                    parent=self,
                    return_to_main_callback=self.go_main_menu,
                )
            self._cti_service_window.show()
            self._cti_service_window.raise_()
            self._cti_service_window.activateWindow()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "CTI Component Manager",
                f"Gagal membuka CTI Component Manager.\n\nPastikan SQL update sudah dijalankan dan dependensi terpasang.\n\nDetail: {exc}",
            )

    def _build_brand_bar(self) -> QWidget:
        brand_bar = QWidget()
        brand_bar.setObjectName("BrandBar")

        logo_label = QLabel()
        logo_label.setPixmap(self._load_brand_logo().scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo_label.setFixedSize(58, 58)
        logo_label.setAlignment(Qt.AlignCenter)

        brand_title = QLabel("SCRG Lab ITB")
        brand_title.setObjectName("BrandTitle")
        brand_subtitle = QLabel("Institut Teknologi Bandung")
        brand_subtitle.setObjectName("BrandSubtitle")

        app_title = QLabel("CYBER THREAT INTELLIGENCE")
        app_title.setObjectName("AppTitle")
        app_subtitle = QLabel("ACTIONABLE-ADAPTIVE CYBER THREAT INTELLIGENCE")
        app_subtitle.setObjectName("AppSubtitle")
        app_subtitle.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)
        text_layout.addWidget(brand_title)
        text_layout.addWidget(brand_subtitle)

        app_layout = QVBoxLayout()
        app_layout.setSpacing(0)
        app_layout.addWidget(app_title)
        app_layout.addWidget(app_subtitle)

        row = QHBoxLayout(brand_bar)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        row.addWidget(logo_label)
        row.addLayout(text_layout)
        row.addStretch()
        row.addLayout(app_layout)

        return brand_bar

    def _load_brand_logo(self) -> QPixmap:
        asset_dir = Config.app_base_dir() / "assets"
        candidates = [
            asset_dir / "itb_logo.png",
            asset_dir / "itb_logo.jpg",
            asset_dir / "itb_logo.jpeg",
            asset_dir / "itb_logo.svg",
        ]
        for path in candidates:
            if path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return pixmap
        return self._build_fallback_logo()

    def _build_fallback_logo(self, size: int = 256) -> QPixmap:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        outer_rect = pixmap.rect().adjusted(10, 10, -10, -10)
        ring_rect = pixmap.rect().adjusted(24, 24, -24, -24)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#0f3d91"))
        painter.drawEllipse(outer_rect)

        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(ring_rect)

        shield_path = QPainterPath()
        shield_path.moveTo(size * 0.50, size * 0.26)
        shield_path.lineTo(size * 0.70, size * 0.34)
        shield_path.lineTo(size * 0.65, size * 0.67)
        shield_path.quadTo(size * 0.50, size * 0.82, size * 0.35, size * 0.67)
        shield_path.lineTo(size * 0.30, size * 0.34)
        shield_path.closeSubpath()

        painter.setBrush(QColor("#0f3d91"))
        painter.drawPath(shield_path)

        painter.setPen(QColor("#ffffff"))
        font = QFont("Arial", int(size * 0.15))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(ring_rect, Qt.AlignCenter, "ITB")
        painter.end()
        return pixmap

    def set_status(self, message: str):
        self.status_label.setText(message)

    def set_sync_status(self, message: str):
        self.sync_label.setText(message)

    def set_sort_status(self, label: str):
        self.sort_label.setText(label)

    def set_pagination(
        self,
        current_page: int,
        total_pages: int,
        filtered_rows: int,
        database_total_rows: int,
    ):
        total_pages = max(total_pages, 1)
        self.page_label.setText(f"Page {current_page:,} / {total_pages:,}")
        self.filtered_label.setText(f"Filtered results: {filtered_rows:,}")
        self.total_label.setText(f"Total vulnerabilities: {database_total_rows:,}")
        at_first = current_page <= 1
        at_last = current_page >= total_pages
        self.first_button.setEnabled(not at_first)
        self.prev_button.setEnabled(not at_first)
        self.next_button.setEnabled(not at_last)
        self.last_button.setEnabled(not at_last)

    def set_attack_pagination(self, current_page: int, total_pages: int, total_rows: int):
        self.attack_page.page_label.setText(f"Page {current_page} / {max(total_pages, 1)}")
        self.attack_page.total_label.setText(f"{total_rows} records")
        self.attack_page.prev_button.setEnabled(current_page > 1)
        self.attack_page.next_button.setEnabled(current_page < total_pages)

    def set_sync_progress(self, current_page: int, total_pages: int, mode: str):
        total_pages = max(total_pages, 1)
        value = int((current_page / total_pages) * 100)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{mode}: {current_page}/{total_pages} ({value}%)")

    def reset_sync_progress(self):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Idle")
