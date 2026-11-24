from __future__ import annotations

import traceback
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot

from config import Config
from services import SyncService


class SyncWorker(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        mode: str = "FULL",
        max_pages: int | None = None,
        page_size: int | None = None,
    ):
        super().__init__()
        self.mode = mode
        self.max_pages = max_pages
        self.page_size = page_size or Config.NVD_PAGE_SIZE

    @Slot()
    def run(self):
        try:
            service = SyncService()

            if self.mode == "INCREMENTAL":
                result = service.run_incremental_sync(
                    max_pages=self.max_pages,
                    page_size=self.page_size,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            else:
                result = service.run_full_sync(
                    max_pages=self.max_pages,
                    page_size=self.page_size,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )

            self.finished.emit(result)

        except Exception as error:
            log_path = Config.app_base_dir() / "vulndesk_sync.log"
            try:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n" + "=" * 90 + "\n")
                    handle.write(f"{datetime.now().isoformat()} mode={self.mode}\n")
                    handle.write("".join(traceback.format_exception(error)))
            except Exception:
                pass
            self.failed.emit(
                f"{type(error).__name__}: {error}\n\n"
                f"Traceback lengkap disimpan di: {log_path}"
            )
