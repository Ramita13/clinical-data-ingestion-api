from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class RejectedRow(Base):
    """
    Stores rows that failed Pydantic validation during ingestion.
    Preserves the raw data so nothing is ever silently lost.
    """
    __tablename__ = "rejected_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ingestion_log_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingestion_log.id"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based row in file
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False)      # original row as-received
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
