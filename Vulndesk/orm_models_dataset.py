from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class DatasetUploadORM(Base):
    __tablename__ = "dataset_uploads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_type: Mapped[str] = mapped_column(String(40), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    stored_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    tweet_rows: Mapped[list["TweetTopicRecordORM"]] = relationship(
        back_populates="upload",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    topic_rows: Mapped[list["TopicMasterRecordORM"]] = relationship(
        back_populates="upload",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TweetTopicRecordORM(Base):
    __tablename__ = "tweet_topic_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("dataset_uploads.id", ondelete="CASCADE"), index=True)
    tweet_text: Mapped[str] = mapped_column(Text)
    topic_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    upload: Mapped["DatasetUploadORM"] = relationship(back_populates="tweet_rows")


class TopicMasterRecordORM(Base):
    __tablename__ = "topic_master_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("dataset_uploads.id", ondelete="CASCADE"), index=True)
    topic_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    upload: Mapped["DatasetUploadORM"] = relationship(back_populates="topic_rows")
