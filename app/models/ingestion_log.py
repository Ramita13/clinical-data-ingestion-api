from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class IngestionLog(Base):
    """
    One row per file upload attempt. Records outcome, counts, and any errors.
    Answers: was Tuesday's upload successful? How many rows were rejected?
    """
    __tablename__ = "ingestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_file_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("raw_files.id"), nullable=True
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Outcome
    status: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # 'success' | 'partial' | 'failed'

    # Row counts
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    rows_versioned: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
