from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from cpe_dictionary_services import CpeDictionarySyncService


class CpeDictionarySyncWorker(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, mode: str, value: str = "", max_pages: int = 1, page_size: int = 100):
        super().__init__()
        self.mode = mode
        self.value = value
        self.max_pages = max_pages
        self.page_size = page_size

    @Slot()
    def run(self):
        try:
            service = CpeDictionarySyncService()
            if self.mode == "CPE_MATCH_STRING":
                result = service.sync_match_string(
                    self.value,
                    max_pages=self.max_pages,
                    page_size=self.page_size,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            elif self.mode == "CPE_PAGE":
                result = service.sync_first_pages(
                    max_pages=self.max_pages,
                    page_size=self.page_size,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            else:
                result = service.sync_keyword(
                    self.value,
                    max_pages=self.max_pages,
                    page_size=self.page_size,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))
