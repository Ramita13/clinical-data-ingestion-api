from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class TranslationLog(Base):
    """
    Per-row translation tracking.
    One row per sample per translation attempt.
    Enables retry of failed rows and status reporting per upload.

    status values:
        'pending'   — queued, not yet attempted
        'completed' — successfully translated
        'failed'    — attempted but failed, will be retried by scheduler
    """
    __tablename__ = "translation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Links
    ingestion_log_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingestion_log.id"), nullable=False
    )
    anonymized_sample_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )  # 'pending' | 'completed' | 'failed'
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Error detail if failed
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which engine translated this row
    translation_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_translation_log_ingestion", "ingestion_log_id"),
        Index("ix_translation_log_sid", "anonymized_sample_id"),
        Index("ix_translation_log_status", "status"),
    )
