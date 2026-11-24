from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from config import Config
from db import session_scope
from dataset_repositories import DatasetRepository


class DatasetService:
    @staticmethod
    def _safe_name(file_name: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name or "dataset.csv").strip("._")
        return sanitized or "dataset.csv"

    def _copy_to_upload_storage(self, source_file_path: str, dataset_type: str) -> tuple[Path, str, int]:
        source = Path(source_file_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"File tidak ditemukan: {source_file_path}")

        upload_dir = Config.upload_dir() / dataset_type
        upload_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_name = f"{stamp}_{self._safe_name(source.name)}"
        target = upload_dir / target_name
        shutil.copy2(source, target)
        size = target.stat().st_size
        return target, str(target.resolve()), size

    def _cleanup_empty_dataset_dir(self, dataset_type: str) -> None:
        target_dir = Config.upload_dir() / dataset_type
        try:
            if target_dir.exists() and target_dir.is_dir() and not any(target_dir.iterdir()):
                target_dir.rmdir()
        except Exception:
            pass

    def import_tweet_topics_csv(self, file_path: str) -> dict:
        stored_path_obj, stored_path, file_size = self._copy_to_upload_storage(file_path, "tweet_topics")
        try:
            with session_scope() as session:
                repo = DatasetRepository(session)
                result = repo.import_tweet_topics_csv(
                    str(stored_path_obj),
                    original_file_name=Path(file_path).name,
                    stored_file_path=stored_path,
                    file_size_bytes=file_size,
                )
                session.commit()
                return result
        except Exception:
            try:
                if stored_path_obj.exists():
                    stored_path_obj.unlink()
            except Exception:
                pass
            raise

    def import_topics_master_csv(self, file_path: str) -> dict:
        stored_path_obj, stored_path, file_size = self._copy_to_upload_storage(file_path, "topics_master")
        try:
            with session_scope() as session:
                repo = DatasetRepository(session)
                result = repo.import_topics_master_csv(
                    str(stored_path_obj),
                    original_file_name=Path(file_path).name,
                    stored_file_path=stored_path,
                    file_size_bytes=file_size,
                )
                session.commit()
                return result
        except Exception:
            try:
                if stored_path_obj.exists():
                    stored_path_obj.unlink()
            except Exception:
                pass
            raise

    def delete_dataset(self, dataset_type: str, upload_date: str | None = None) -> dict:
        with session_scope() as session:
            repo = DatasetRepository(session)
            result = repo.delete_uploads_by_type(dataset_type, upload_date=upload_date)
            session.commit()

        deleted_files = 0
        failed_files: list[str] = []
        for item in result.get("files", []):
            stored_file_path = (item.get("stored_file_path") or "").strip()
            if not stored_file_path:
                continue
            try:
                target = Path(stored_file_path)
                if target.exists() and target.is_file():
                    target.unlink()
                    deleted_files += 1
            except Exception:
                failed_files.append(stored_file_path)

        self._cleanup_empty_dataset_dir(dataset_type)
        result["deleted_files"] = deleted_files
        result["failed_files"] = failed_files
        result["dataset_type"] = dataset_type
        result["upload_date"] = upload_date
        return result

    def list_tweets(self, filters: dict) -> list[dict]:
        with session_scope() as session:
            return DatasetRepository(session).list_tweets(filters)

    def count_tweets(self, filters: dict) -> int:
        with session_scope() as session:
            return DatasetRepository(session).count_tweets(filters)

    def list_topics(self, filters: dict) -> list[dict]:
        with session_scope() as session:
            return DatasetRepository(session).list_topics(filters)

    def count_topics(self, filters: dict) -> int:
        with session_scope() as session:
            return DatasetRepository(session).count_topics(filters)

    def list_topic_options(self) -> list[str]:
        with session_scope() as session:
            return DatasetRepository(session).list_topic_options()

    def list_upload_date_options(self) -> list[str]:
        with session_scope() as session:
            return DatasetRepository(session).list_upload_date_options()

    def get_summary(self, upload_date=None) -> dict:
        with session_scope() as session:
            return DatasetRepository(session).get_summary(upload_date=upload_date)
