from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, CHAR, DateTime, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Sample(Base):
    """
    Silver layer. One row per version of a sample record.
    is_latest=True marks the current version. Historical rows kept for audit.

    Sparse text groups (clinical_info, macroscopic_desc, microscopic_desc,
    diagnoses, topographic_codes, locations) are stored as JSONB with only
    non-empty values — e.g. {"1": "text", "3": "text"}.
    ICD codes and diagnosis_1 are kept flat for direct filtering.
    """
    __tablename__ = "samples"

    # ------------------------------------------------------------------ #
    # Internal versioning columns
    # ------------------------------------------------------------------ #
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ingestion_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    anonymized_sample_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
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
    # e.g. clinical_info = {"1": "Se solicita...", "3": "Otro hallazgo"}
    # ------------------------------------------------------------------ #
    clinical_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    macroscopic_desc: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    microscopic_desc: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Diagnoses
    # diagnosis_1 kept flat — primary diagnosis, filtered directly
    # diagnoses JSONB — secondary diagnoses 2..12
    # ------------------------------------------------------------------ #
    additional_techniques: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnoses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Codes and locations — JSONB for sparse groups
    # ICD codes kept flat for direct filtering
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
    # Soft column handling — unexpected columns land here, never dropped
    # ------------------------------------------------------------------ #
    extra_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Full-text search vector
    # ------------------------------------------------------------------ #
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # ------------------------------------------------------------------ #
    # Constraints and indexes
    # ------------------------------------------------------------------ #
    __table_args__ = (
        UniqueConstraint("anonymized_sample_id", "version", name="uq_sample_version"),
        Index("ix_samples_id_latest", "anonymized_sample_id", "is_latest"),
        Index("ix_samples_demographics", "gender", "age"),
        Index("ix_samples_year_latest", "diagnosis_year", "is_latest"),
        Index("ix_samples_search_vector", "search_vector", postgresql_using="gin"),
    )
