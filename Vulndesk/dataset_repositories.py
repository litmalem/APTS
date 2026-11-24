from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import desc, func, or_, select

from orm_models_dataset import DatasetUploadORM, TopicMasterRecordORM, TweetTopicRecordORM


class DatasetRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _normalize_header(value: str | None) -> str:
        return "".join(ch for ch in (value or "").strip().lower() if ch.isalnum())

    def _resolve_column(self, fieldnames: list[str] | None, *candidates: str) -> str | None:
        if not fieldnames:
            return None
        normalized_map = {self._normalize_header(name): name for name in fieldnames}
        for candidate in candidates:
            found = normalized_map.get(self._normalize_header(candidate))
            if found:
                return found
        return None

    def import_tweet_topics_csv(
        self,
        file_path: str,
        *,
        original_file_name: str | None = None,
        stored_file_path: str | None = None,
        file_size_bytes: int | None = None,
    ) -> dict:
        path = Path(file_path)
        upload = DatasetUploadORM(
            dataset_type="tweet_topics",
            file_name=original_file_name or path.name,
            stored_file_path=stored_file_path,
            file_size_bytes=file_size_bytes,
            uploaded_at=datetime.utcnow(),
        )
        self.session.add(upload)
        self.session.flush()

        row_count = 0
        batch: list[TweetTopicRecordORM] = []

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            tweet_col = self._resolve_column(reader.fieldnames, "TWEETS", "tweet", "tweets", "text")
            topic_col = self._resolve_column(reader.fieldnames, "TOPICS", "topic", "topics")
            if not tweet_col or not topic_col:
                raise ValueError("Kolom CSV tweet tidak valid. Diperlukan kolom TWEETS dan TOPICS.")

            for row in reader:
                tweet_text = (row.get(tweet_col) or "").strip()
                topic_text = (row.get(topic_col) or "").strip() or None
                if not tweet_text and not topic_text:
                    continue
                batch.append(
                    TweetTopicRecordORM(
                        upload_id=upload.id,
                        tweet_text=tweet_text,
                        topic_text=topic_text,
                    )
                )
                row_count += 1
                if len(batch) >= 1000:
                    self.session.bulk_save_objects(batch)
                    batch.clear()

        if batch:
            self.session.bulk_save_objects(batch)

        upload.row_count = row_count
        self.session.flush()
        return {
            "upload_id": upload.id,
            "dataset_type": upload.dataset_type,
            "file_name": upload.file_name,
            "stored_file_path": upload.stored_file_path,
            "file_size_bytes": upload.file_size_bytes,
            "row_count": row_count,
            "uploaded_at": upload.uploaded_at,
        }

    def import_topics_master_csv(
        self,
        file_path: str,
        *,
        original_file_name: str | None = None,
        stored_file_path: str | None = None,
        file_size_bytes: int | None = None,
    ) -> dict:
        path = Path(file_path)
        upload = DatasetUploadORM(
            dataset_type="topics_master",
            file_name=original_file_name or path.name,
            stored_file_path=stored_file_path,
            file_size_bytes=file_size_bytes,
            uploaded_at=datetime.utcnow(),
        )
        self.session.add(upload)
        self.session.flush()

        row_count = 0
        batch: list[TopicMasterRecordORM] = []

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            topic_col = self._resolve_column(reader.fieldnames, "TOPIC", "topics", "topic")
            if not topic_col:
                raise ValueError("Kolom CSV topic tidak valid. Diperlukan kolom TOPIC.")

            for row in reader:
                topic_text = (row.get(topic_col) or "").strip()
                if not topic_text:
                    continue
                batch.append(
                    TopicMasterRecordORM(
                        upload_id=upload.id,
                        topic_text=topic_text,
                    )
                )
                row_count += 1
                if len(batch) >= 1000:
                    self.session.bulk_save_objects(batch)
                    batch.clear()

        if batch:
            self.session.bulk_save_objects(batch)

        upload.row_count = row_count
        self.session.flush()
        return {
            "upload_id": upload.id,
            "dataset_type": upload.dataset_type,
            "file_name": upload.file_name,
            "stored_file_path": upload.stored_file_path,
            "file_size_bytes": upload.file_size_bytes,
            "row_count": row_count,
            "uploaded_at": upload.uploaded_at,
        }


    def list_uploads_for_delete(self, dataset_type: str, upload_date: str | None = None) -> list[dict]:
        stmt = select(
            DatasetUploadORM.id,
            DatasetUploadORM.file_name,
            DatasetUploadORM.stored_file_path,
            DatasetUploadORM.row_count,
            DatasetUploadORM.uploaded_at,
        ).where(DatasetUploadORM.dataset_type == dataset_type)

        if upload_date:
            stmt = stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)

        stmt = stmt.order_by(desc(DatasetUploadORM.uploaded_at), desc(DatasetUploadORM.id))
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "file_name": row[1],
                "stored_file_path": row[2],
                "row_count": row[3],
                "uploaded_at": row[4],
            }
            for row in rows
        ]

    def delete_uploads_by_type(self, dataset_type: str, upload_date: str | None = None) -> dict:
        uploads = self.list_uploads_for_delete(dataset_type, upload_date=upload_date)
        if not uploads:
            return {
                "deleted_uploads": 0,
                "deleted_rows": 0,
                "files": [],
            }

        upload_ids = [item["id"] for item in uploads]
        deleted_rows = sum(int(item.get("row_count") or 0) for item in uploads)

        stmt = select(DatasetUploadORM).where(DatasetUploadORM.id.in_(upload_ids))
        objects = self.session.execute(stmt).scalars().all()
        for obj in objects:
            self.session.delete(obj)
        self.session.flush()

        return {
            "deleted_uploads": len(uploads),
            "deleted_rows": deleted_rows,
            "files": uploads,
        }

    def list_tweets(self, filters: dict) -> list[dict]:
        stmt = (
            select(
                TweetTopicRecordORM.id,
                TweetTopicRecordORM.tweet_text,
                TweetTopicRecordORM.topic_text,
                DatasetUploadORM.file_name,
                DatasetUploadORM.stored_file_path,
                DatasetUploadORM.file_size_bytes,
                DatasetUploadORM.uploaded_at,
            )
            .select_from(TweetTopicRecordORM)
            .join(DatasetUploadORM, DatasetUploadORM.id == TweetTopicRecordORM.upload_id)
        )

        keyword = (filters.get("keyword") or "").strip()
        if keyword:
            kw = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    TweetTopicRecordORM.tweet_text.ilike(kw),
                    TweetTopicRecordORM.topic_text.ilike(kw),
                )
            )

        topic = (filters.get("topic") or "").strip()
        if topic:
            stmt = stmt.where(TweetTopicRecordORM.topic_text == topic)

        upload_date = filters.get("upload_date")
        if upload_date:
            stmt = stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)

        limit = int(filters.get("limit", 100))
        offset = int(filters.get("offset", 0))
        stmt = stmt.order_by(desc(DatasetUploadORM.uploaded_at), desc(TweetTopicRecordORM.id)).limit(limit).offset(offset)

        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "tweet_text": row[1],
                "topic_text": row[2],
                "file_name": row[3],
                "stored_file_path": row[4],
                "file_size_bytes": row[5],
                "uploaded_at": row[6],
            }
            for row in rows
        ]

    def count_tweets(self, filters: dict) -> int:
        stmt = (
            select(func.count(TweetTopicRecordORM.id))
            .select_from(TweetTopicRecordORM)
            .join(DatasetUploadORM, DatasetUploadORM.id == TweetTopicRecordORM.upload_id)
        )

        keyword = (filters.get("keyword") or "").strip()
        if keyword:
            kw = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    TweetTopicRecordORM.tweet_text.ilike(kw),
                    TweetTopicRecordORM.topic_text.ilike(kw),
                )
            )

        topic = (filters.get("topic") or "").strip()
        if topic:
            stmt = stmt.where(TweetTopicRecordORM.topic_text == topic)

        upload_date = filters.get("upload_date")
        if upload_date:
            stmt = stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)

        return int(self.session.execute(stmt).scalar_one() or 0)

    def list_topics(self, filters: dict) -> list[dict]:
        stmt = (
            select(
                TopicMasterRecordORM.id,
                TopicMasterRecordORM.topic_text,
                DatasetUploadORM.file_name,
                DatasetUploadORM.stored_file_path,
                DatasetUploadORM.file_size_bytes,
                DatasetUploadORM.uploaded_at,
            )
            .select_from(TopicMasterRecordORM)
            .join(DatasetUploadORM, DatasetUploadORM.id == TopicMasterRecordORM.upload_id)
        )

        upload_date = filters.get("upload_date")
        if upload_date:
            stmt = stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)

        stmt = stmt.order_by(desc(DatasetUploadORM.uploaded_at), desc(TopicMasterRecordORM.id))
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "topic_text": row[1],
                "file_name": row[2],
                "stored_file_path": row[3],
                "file_size_bytes": row[4],
                "uploaded_at": row[5],
            }
            for row in rows
        ]

    def count_topics(self, filters: dict) -> int:
        stmt = (
            select(func.count(TopicMasterRecordORM.id))
            .select_from(TopicMasterRecordORM)
            .join(DatasetUploadORM, DatasetUploadORM.id == TopicMasterRecordORM.upload_id)
        )
        upload_date = filters.get("upload_date")
        if upload_date:
            stmt = stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)
        return int(self.session.execute(stmt).scalar_one() or 0)

    def list_topic_options(self) -> list[str]:
        stmt = select(TopicMasterRecordORM.topic_text).distinct().order_by(TopicMasterRecordORM.topic_text.asc())
        rows = [row[0] for row in self.session.execute(stmt).all() if row[0]]
        if rows:
            return rows
        fallback_stmt = select(TweetTopicRecordORM.topic_text).distinct().order_by(TweetTopicRecordORM.topic_text.asc())
        return [row[0] for row in self.session.execute(fallback_stmt).all() if row[0]]

    def list_upload_date_options(self) -> list[str]:
        stmt = select(func.date(DatasetUploadORM.uploaded_at)).distinct().order_by(desc(func.date(DatasetUploadORM.uploaded_at)))
        values: list[str] = []
        for (value,) in self.session.execute(stmt).all():
            if value is None:
                continue
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, datetime):
                values.append(value.date().isoformat())
            elif isinstance(value, date):
                values.append(value.isoformat())
            else:
                values.append(str(value))
        return values

    def get_summary(self, upload_date=None) -> dict:
        upload_stmt = select(func.count(DatasetUploadORM.id)).select_from(DatasetUploadORM)
        tweet_stmt = select(func.count(TweetTopicRecordORM.id)).select_from(TweetTopicRecordORM).join(
            DatasetUploadORM, DatasetUploadORM.id == TweetTopicRecordORM.upload_id
        )
        topic_stmt = select(func.count(TopicMasterRecordORM.id)).select_from(TopicMasterRecordORM).join(
            DatasetUploadORM, DatasetUploadORM.id == TopicMasterRecordORM.upload_id
        )
        if upload_date:
            upload_stmt = upload_stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)
            tweet_stmt = tweet_stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)
            topic_stmt = topic_stmt.where(func.date(DatasetUploadORM.uploaded_at) == upload_date)

        return {
            "upload_count": int(self.session.execute(upload_stmt).scalar_one() or 0),
            "tweet_count": int(self.session.execute(tweet_stmt).scalar_one() or 0),
            "topic_count": int(self.session.execute(topic_stmt).scalar_one() or 0),
        }
