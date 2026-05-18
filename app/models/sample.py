from datetime import datetime
from sqlalchemy import (
    BigInteger, CHAR, DateTime, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Sample(Base):
    """
    Silver layer. One row per sample — overwrite in place on change.
    No versioning. last_modified and ingestion_log_id track when and
    which upload last changed this record.

    Sparse text groups stored as JSONB with only non-empty values.
    search_vector lives in sample_translations (English translation table).
    """
    __tablename__ = "samples"

    # ------------------------------------------------------------------ #
    # Internal columns
    # ------------------------------------------------------------------ #
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ingestion_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    anonymized_sample_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquisition: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Demographics
    # ------------------------------------------------------------------ #
    gender: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnosis_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------ #
    # Sparse text groups — JSONB, only non-empty values stored
    # ------------------------------------------------------------------ #
    clinical_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    macroscopic_desc: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    microscopic_desc: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Diagnoses
    # ------------------------------------------------------------------ #
    additional_techniques: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnoses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Codes and locations
    # ------------------------------------------------------------------ #
    topographic_codes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    locations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    icd_code_1: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icd_code_2: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icd_code_3: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icd_code_4: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ------------------------------------------------------------------ #
    # Report & file provenance
    # ------------------------------------------------------------------ #
    additional_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    upload_date_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    bucket_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Soft column handling
    # ------------------------------------------------------------------ #
    extra_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Indexes
    # ------------------------------------------------------------------ #
    __table_args__ = (
        Index("ix_samples_demographics", "gender", "age"),
        Index("ix_samples_year", "diagnosis_year"),
    )
