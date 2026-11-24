from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from cwe_services import CweSyncService


class CweSyncWorker(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        mode: str = "CWE_KNOWN",
        cwe_id: str | None = None,
        start_id: int = 1,
        end_id: int = 1500,
        view_id: int = 1000,
    ):
        super().__init__()
        self.mode = mode
        self.cwe_id = cwe_id
        self.start_id = start_id
        self.end_id = end_id
        self.view_id = view_id

    @Slot()
    def run(self):
        try:
            service = CweSyncService()
            if self.mode == "CWE_SINGLE":
                result = service.sync_single_cwe(
                    self.cwe_id or "",
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            elif self.mode == "CWE_RANGE":
                result = service.sync_range(
                    self.start_id,
                    self.end_id,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            elif self.mode == "CWE_VIEW":
                result = service.sync_view(
                    self.view_id,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            else:
                result = service.sync_known_cwes(
                    only_missing_details=True,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))
