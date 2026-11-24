from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from mitre_attack_services import MitreAttackSyncService


class MitreSyncWorker(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, mode: str = "MITRE_FULL"):
        super().__init__()
        self.mode = mode

    @Slot()
    def run(self):
        try:
            service = MitreAttackSyncService()
            if self.mode == "MITRE_INCREMENTAL":
                result = service.run_incremental_sync(progress_callback=lambda payload: self.progress.emit(payload))
            else:
                result = service.run_full_sync(progress_callback=lambda payload: self.progress.emit(payload))
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))
