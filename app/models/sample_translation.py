from datetime import datetime
from sqlalchemy import (
    BigInteger, CHAR, DateTime, ForeignKey, Index,
    Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class SampleTranslation(Base):
    """
    Complete mirror of samples table with translatable text fields
    replaced by their English equivalents. All other fields copied as-is.

    This is the operational table — all queries run here.
    samples table is the raw Spanish audit record — never queried directly.

    Translatable fields (Spanish -> English):
        clinical_info, macroscopic_desc, microscopic_desc,
        diagnosis_1, diagnoses, additional_techniques,
        additional_report, locations

    Copied fields (unchanged from samples):
        everything else
    """
    __tablename__ = "sample_translations"

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("samples.id"), nullable=False
    )
    translated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    translation_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Identity — copied from samples
    # ------------------------------------------------------------------ #
    anonymized_sample_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquisition: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Demographics — copied from samples
    # ------------------------------------------------------------------ #
    gender: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnosis_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------ #
    # Translated text fields — English versions
    # ------------------------------------------------------------------ #
    clinical_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    macroscopic_desc: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    microscopic_desc: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    additional_techniques: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnoses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    additional_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    locations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Codes — copied from samples (internationally standardised, no translation)
    # ------------------------------------------------------------------ #
    topographic_codes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    icd_code_1: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icd_code_2: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icd_code_3: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icd_code_4: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ------------------------------------------------------------------ #
    # File provenance — copied from samples
    # ------------------------------------------------------------------ #
    checksum_algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    upload_date_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    bucket_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------ #
    # Soft column handling — copied from samples
    # ------------------------------------------------------------------ #
    extra_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Full-text search vector — built from ALL English text combined
    # Populated after translation completes
    # ------------------------------------------------------------------ #
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # ------------------------------------------------------------------ #
    # Indexes
    # ------------------------------------------------------------------ #
    __table_args__ = (
        Index("ix_st_sample_id", "sample_id"),
        Index("ix_st_sid", "anonymized_sample_id"),
        Index("ix_st_demographics", "gender", "age"),
        Index("ix_st_year", "diagnosis_year"),
        Index("ix_st_search", "search_vector", postgresql_using="gin"),
    )
