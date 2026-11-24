from __future__ import annotations

import json
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cti_services import DbAdapter, PentestEnrichmentApiService, ServiceRegistry, VulnerabilityContextService
from cti_services.interface_catalog import consumed_interfaces, provided_interfaces


class Worker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.finished_ok.emit(self.fn(*self.args, **self.kwargs))
        except Exception:
            self.failed.emit(traceback.format_exc())


class VulnDeskServiceManagerWindow(QWidget):
    """Service manager UI for VulnDesk CTI enrichment services."""

    def __init__(self, parent=None, db: Optional[DbAdapter] = None, return_to_main_callback: Optional[Callable[[], None]] = None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("VulnDesk - CTI Component Manager")
        self.resize(1320, 820)
        self.return_to_main_callback = return_to_main_callback
        self.db = db or DbAdapter()
        self.registry = ServiceRegistry(self.db)
        self.registry.ensure_default_services()
        cfg = self.registry.get_config("pentest_enrichment_api_service")
        self.api_service = PentestEnrichmentApiService(
            host=cfg.get("host", "127.0.0.1"),
            port=int(cfg.get("port", 8765)),
            registry=self.registry,
        )
        self.worker: Optional[Worker] = None
        self._build_ui()
        self.refresh_services()
        self.refresh_mappings()
        self.refresh_interfaces()

    def _build_ui(self):
        root = QVBoxLayout(self)

        top_row = QHBoxLayout()
        title = QLabel("CTI Component Manager — Agent / Service / Data Artifact")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.btn_back_main = QPushButton("← Kembali ke Menu Utama")
        self.btn_back_main.setToolTip("Tutup halaman service dan kembali ke tab utama VulnDesk")
        self.btn_back_main.clicked.connect(self.return_to_main_menu)
        top_row.addWidget(title)
        top_row.addStretch(1)
        top_row.addWidget(self.btn_back_main)
        root.addLayout(top_row)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        components_tab = QWidget()
        components_layout = QVBoxLayout(components_tab)
        self.tabs.addTab(components_tab, "Components & Runtime")

        service_box = QGroupBox("Harmonized CTI Component Registry")
        service_layout = QVBoxLayout(service_box)
        self.services_table = QTableWidget(0, 10)
        self.services_table.setHorizontalHeaderLabels([
            "ID", "Key", "Name", "Type", "Mechanism", "Authority Boundary",
            "Optional", "Enabled", "Status", "Last Error"
        ])
        self.services_table.horizontalHeader().setStretchLastSection(True)
        self.services_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        service_layout.addWidget(self.services_table)
        row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_enable = QPushButton("Enable Selected")
        self.btn_disable = QPushButton("Disable Selected")
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_enable)
        row.addWidget(self.btn_disable)
        row.addStretch(1)
        service_layout.addLayout(row)
        components_layout.addWidget(service_box)

        api_box = QGroupBox("Pentest Enrichment API")
        api_layout = QHBoxLayout(api_box)
        api_layout.addWidget(QLabel("Host:"))
        self.host_edit = QLineEdit(self.api_service.host)
        api_layout.addWidget(self.host_edit)
        api_layout.addWidget(QLabel("Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(self.api_service.port)
        api_layout.addWidget(self.port_spin)
        self.btn_start_api = QPushButton("Start API")
        self.btn_stop_api = QPushButton("Stop API")
        api_layout.addWidget(self.btn_start_api)
        api_layout.addWidget(self.btn_stop_api)
        self.api_runtime_label = QLabel()
        api_layout.addWidget(self.api_runtime_label)
        api_layout.addStretch(1)
        components_layout.addWidget(api_box)

        mapping_box = QGroupBox("ATT&CK Mapping Rules")
        mapping_layout = QVBoxLayout(mapping_box)
        self.mapping_table = QTableWidget(0, 7)
        self.mapping_table.setHorizontalHeaderLabels(["ID", "CVE", "CWE", "Vuln Type", "ATT&CK", "Confidence", "Rationale"])
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        mapping_layout.addWidget(self.mapping_table)
        row2 = QHBoxLayout()
        self.btn_refresh_mapping = QPushButton("Refresh Mappings")
        row2.addWidget(self.btn_refresh_mapping)
        row2.addStretch(1)
        mapping_layout.addLayout(row2)
        components_layout.addWidget(mapping_box, 1)

        output_box = QGroupBox("Output")
        output_layout = QVBoxLayout(output_box)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        output_layout.addWidget(self.output)
        components_layout.addWidget(output_box, 1)

        interfaces_tab = QWidget()
        interfaces_layout = QVBoxLayout(interfaces_tab)
        self.tabs.addTab(interfaces_tab, "Interfaces & Ports")

        intro = QLabel(
            "Daftar ini memisahkan interface yang DISEDIAKAN VulnDesk dari service eksternal yang DIGUNAKAN VulnDesk. "
            "Agent/service CTI internal berkomunikasi in-process melalui Event Bus/Dispatcher dan tidak memiliki port network dedicated; "
            "listener network VulnDesk saat ini adalah CTI-INF01 (default 8765). Nilai host/port dibaca dari konfigurasi runtime lokal; "
            "credential dan API key tidak ditampilkan."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #374151; padding: 2px 2px 6px 2px;")
        interfaces_layout.addWidget(intro)

        provided_box = QGroupBox("Port / Service Interface yang Disediakan VulnDesk")
        provided_layout = QVBoxLayout(provided_box)
        self.provided_interfaces_table = self._new_interface_table(peer_label="Entity / Consumer")
        provided_layout.addWidget(self.provided_interfaces_table)
        interfaces_layout.addWidget(provided_box, 1)

        consumed_box = QGroupBox("Service Interface yang Digunakan VulnDesk")
        consumed_layout = QVBoxLayout(consumed_box)
        self.consumed_interfaces_table = self._new_interface_table(peer_label="External Service / Provider")
        consumed_layout.addWidget(self.consumed_interfaces_table)
        interfaces_layout.addWidget(consumed_box, 1)

        interface_actions = QHBoxLayout()
        self.btn_refresh_interfaces = QPushButton("Refresh Interfaces / Ports")
        self.interface_summary = QLabel()
        self.interface_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        interface_actions.addWidget(self.btn_refresh_interfaces)
        interface_actions.addWidget(self.interface_summary)
        interface_actions.addStretch(1)
        interfaces_layout.addLayout(interface_actions)

        self.btn_refresh.clicked.connect(self.refresh_services)
        self.btn_enable.clicked.connect(lambda: self.set_selected_enabled(True))
        self.btn_disable.clicked.connect(lambda: self.set_selected_enabled(False))
        self.btn_start_api.clicked.connect(self.start_api)
        self.btn_stop_api.clicked.connect(self.stop_api)
        self.btn_refresh_mapping.clicked.connect(self.refresh_mappings)
        self.btn_refresh_interfaces.clicked.connect(self.refresh_interfaces)
        self.host_edit.textChanged.connect(self.refresh_interfaces)
        self.port_spin.valueChanged.connect(self.refresh_interfaces)

    @staticmethod
    def _new_interface_table(peer_label: str) -> QTableWidget:
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels([
            "Entity / Component",
            peer_label,
            "Protocol",
            "Host",
            "Port",
            "Interface / Endpoint",
            "Purpose",
            "Status / Notes",
        ])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        return table

    @staticmethod
    def _populate_interface_table(table: QTableWidget, rows, runtime_status: Optional[str] = None):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            status_notes = row.notes
            if runtime_status and row.direction == "PROVIDED":
                status_notes = f"{runtime_status}; {status_notes}" if status_notes else runtime_status
            values = [
                row.entity,
                row.peer,
                row.protocol,
                row.host,
                "" if row.port is None else str(row.port),
                row.interface,
                row.purpose,
                status_notes,
            ]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if j in {2, 4}:
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(i, j, item)
        table.resizeRowsToContents()

    def refresh_services(self):
        rows = self.registry.list_services()
        self.services_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [
                r.get("component_id"), r.get("service_key"), r.get("service_name"),
                r.get("component_type"), r.get("mechanism"), r.get("authority_boundary"),
                "Yes" if r.get("optional_component") else "No",
                "Yes" if r.get("enabled") else "No", r.get("status"), r.get("last_error"),
            ]
            for j, v in enumerate(values):
                item = QTableWidgetItem("" if v is None else str(v))
                if j in {0, 3, 6, 7, 8}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.services_table.setItem(i, j, item)
        self._refresh_api_runtime_label()

    def refresh_interfaces(self, *_args):
        host = self.host_edit.text().strip() or self.api_service.host or "127.0.0.1"
        port = int(self.port_spin.value())
        runtime_status = "RUNNING" if self.api_service.is_running() else "STOPPED"
        provided = provided_interfaces(host=host, port=port)
        consumed = consumed_interfaces()
        self._populate_interface_table(self.provided_interfaces_table, provided, runtime_status=runtime_status)
        self._populate_interface_table(self.consumed_interfaces_table, consumed)
        self.interface_summary.setText(
            f"Provided: {len(provided)} logical interfaces on {host}:{port} · "
            f"Consumed: {len(consumed)} configured external interfaces"
        )
        self._refresh_api_runtime_label()

    def _refresh_api_runtime_label(self):
        if not hasattr(self, "api_runtime_label"):
            return
        if self.api_service.is_running():
            self.api_runtime_label.setText(f"Runtime: RUNNING on {self.api_service.host}:{self.api_service.port}")
        else:
            self.api_runtime_label.setText("Runtime: STOPPED")

    def refresh_mappings(self):
        try:
            rows = self.db.fetch_all(
                """
                SELECT id, cve_id, cwe_id, vuln_type, attack_id, attack_name, confidence, rationale
                FROM vuln_attack_mappings
                WHERE is_active = 1
                ORDER BY cwe_id, cve_id, attack_id
                LIMIT 500
                """
            )
        except Exception as e:
            self.append_output(f"Failed loading mappings: {e}")
            return
        self.mapping_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [r.get("id"), r.get("cve_id"), r.get("cwe_id"), r.get("vuln_type"), f"{r.get('attack_id') or ''} {r.get('attack_name') or ''}", r.get("confidence"), r.get("rationale")]
            for j, v in enumerate(values):
                item = QTableWidgetItem("" if v is None else str(v))
                if j in {0, 4, 5}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.mapping_table.setItem(i, j, item)

    def selected_service_key(self) -> Optional[str]:
        row = self.services_table.currentRow()
        if row < 0:
            return None
        item = self.services_table.item(row, 1)
        return item.text() if item else None

    def set_selected_enabled(self, enabled: bool):
        key = self.selected_service_key()
        if not key:
            QMessageBox.information(self, "Komponen CTI", "Pilih komponen terlebih dahulu.")
            return
        self.registry.set_enabled(key, enabled)
        self.refresh_services()

    def start_api(self):
        if not self.registry.is_enabled("pentest_enrichment_api_service"):
            QMessageBox.warning(self, "API", "Pentest Enrichment API Service sedang disabled.")
            return
        if self.api_service.is_running():
            self.append_output("API already running.")
            self.refresh_interfaces()
            return
        self.api_service.host = self.host_edit.text().strip() or "127.0.0.1"
        self.api_service.port = int(self.port_spin.value())
        host, port = self.api_service.start()
        self.append_output(f"API running at http://{host}:{port}")
        self.refresh_services()
        self.refresh_interfaces()

    def stop_api(self):
        self.api_service.stop()
        self.append_output("API stopped.")
        self.refresh_services()
        self.refresh_interfaces()

    def return_to_main_menu(self):
        """Hide this service window and activate the main VulnDesk window."""
        try:
            if callable(self.return_to_main_callback):
                self.return_to_main_callback()
                return

            parent = self.parent()
            self.hide()
            if parent is not None:
                if hasattr(parent, "main_tabs"):
                    parent.main_tabs.setCurrentIndex(0)
                if hasattr(parent, "showNormal"):
                    parent.showNormal()
                if hasattr(parent, "raise_"):
                    parent.raise_()
                if hasattr(parent, "activateWindow"):
                    parent.activateWindow()
            else:
                self.close()
        except Exception as exc:
            QMessageBox.warning(self, "Menu Utama", f"Gagal kembali ke menu utama.\n\nDetail: {exc}")

    def append_output(self, value: Any):
        if not isinstance(value, str):
            value = json.dumps(value, indent=2, default=str, ensure_ascii=False)
        self.output.appendPlainText(value)
