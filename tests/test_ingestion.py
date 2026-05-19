"""
test_ingestion.py — integration tests for app/services/ingestion.py

Uses real PostgreSQL (mda_test_db) via synchronous psycopg2 session
to avoid asyncpg event loop issues on Python 3.14/Windows.

The ingestion service itself uses async SQLAlchemy — we call it with
an AsyncSession created per test using the async engine.
"""

import asyncio
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.ingestion_log import IngestionLog
from app.models.rejected_row import RejectedRow
from app.models.sample import Sample
from app.services.ingestion import (
    _normalise,
    ingest_rows,
    now_utc,
)


# ------------------------------------------------------------------ #
# Per-test async session — fresh engine per test avoids loop issues
# ------------------------------------------------------------------ #
async def _get_async_session():
    """Creates a fresh async engine and session for one test."""
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession,
                                  expire_on_commit=False, autoflush=False)
    return engine, factory


async def _run_ingest(raw_rows, log_id_offset=0):
    """
    Helper: creates its own async engine, ingests rows, commits, returns results.
    Closes engine when done.
    """
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession,
                                  expire_on_commit=False, autoflush=False)
    async with factory() as session:
        # Create a log entry
        log = IngestionLog(
            file_name="test.xlsx",
            file_checksum=f"test_checksum_{log_id_offset}",
            status="processing",
            rows_total=len(raw_rows),
            started_at=now_utc(),
        )
        session.add(log)
        await session.flush()
        log_id = log.id

        result = await ingest_rows(session, raw_rows, log_id)
        await session.commit()

    await engine.dispose()
    return result, log_id


async def _query_sample(sid: str):
    """Query a sample by anonymized_sample_id."""
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession,
                                  expire_on_commit=False, autoflush=False)
    async with factory() as session:
        sample = await session.scalar(
            select(Sample).where(Sample.anonymized_sample_id == sid)
        )
    await engine.dispose()
    return sample


async def _query_all_samples():
    """Query all samples."""
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession,
                                  expire_on_commit=False, autoflush=False)
    async with factory() as session:
        result = await session.execute(select(Sample))
        samples = result.scalars().all()
    await engine.dispose()
    return samples


async def _query_rejected(log_id: int):
    """Query rejected rows for a given log id."""
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession,
                                  expire_on_commit=False, autoflush=False)
    async with factory() as session:
        result = await session.execute(
            select(RejectedRow).where(RejectedRow.ingestion_log_id == log_id)
        )
        rows = result.scalars().all()
    await engine.dispose()
    return rows


# ------------------------------------------------------------------ #
# _normalise — pure unit tests (no DB)
# ------------------------------------------------------------------ #
def test_normalise_empty_string_to_none():
    assert _normalise("") is None


def test_normalise_none_stays_none():
    assert _normalise(None) is None


def test_normalise_empty_dict_to_none():
    assert _normalise({}) is None


def test_normalise_non_empty_dict_unchanged():
    assert _normalise({"1": "text"}) == {"1": "text"}


def test_normalise_string_unchanged():
    assert _normalise("hello") == "hello"


def test_normalise_integer_unchanged():
    assert _normalise(42) == 42


# ------------------------------------------------------------------ #
# New record inserted
# ------------------------------------------------------------------ #
async def test_new_record_inserted(db_session, valid_row):
    result, log_id = await _run_ingest([valid_row])

    assert result["inserted"] == 1
    assert result["updated"] == 0
    assert result["unchanged"] == 0
    assert result["rejected"] == 0
    assert "test_sample_001" in result["inserted_ids"]

    sample = await _query_sample("test_sample_001")
    assert sample is not None
    assert sample.gender == "M"
    assert sample.age == 45
    assert sample.diagnosis_year == 2024


async def test_new_record_has_correct_ingestion_log_id(db_session, valid_row):
    result, log_id = await _run_ingest([valid_row])
    sample = await _query_sample("test_sample_001")
    assert sample.ingestion_log_id == log_id


async def test_new_record_has_last_modified(db_session, valid_row):
    await _run_ingest([valid_row])
    sample = await _query_sample("test_sample_001")
    assert sample.last_modified is not None


# ------------------------------------------------------------------ #
# JSONB storage
# ------------------------------------------------------------------ #
async def test_clinical_info_stored_as_jsonb(db_session, valid_row):
    await _run_ingest([valid_row])
    sample = await _query_sample("test_sample_001")
    assert sample.clinical_info is not None
    assert "1" in sample.clinical_info
    assert sample.clinical_info["1"] == "Se solicita revisión de biopsia."


async def test_diagnosis_1_stored_flat(db_session, valid_row):
    await _run_ingest([valid_row])
    sample = await _query_sample("test_sample_001")
    assert sample.diagnosis_1 == "Ganglio linfático: linfoma T."


async def test_multi_diagnosis_grouped_in_jsonb(db_session, row_multi_diagnosis):
    await _run_ingest([row_multi_diagnosis])
    sample = await _query_sample("test_multidiag_001")
    assert sample.diagnosis_1 == "Ganglio linfático: linfoma folicular grado 1."
    assert sample.diagnoses is not None
    assert "2" in sample.diagnoses
    assert "3" in sample.diagnoses
    assert "4" in sample.diagnoses


async def test_extra_fields_stored_in_jsonb(db_session, row_with_extra_fields):
    # Pre-process row as file_parser.py would — extract extra fields into extra_fields key
    from app.utils.file_parser import _extract_extra_fields
    known, extra = _extract_extra_fields(row_with_extra_fields)
    if extra:
        known["extra_fields"] = extra
    await _run_ingest([known])
    sample = await _query_sample("test_extra_001")
    assert sample.extra_fields is not None
    assert sample.extra_fields.get("NewColumn2026") == "unexpected_value"
    assert sample.extra_fields.get("TissueType") == "FFPE"


# ------------------------------------------------------------------ #
# Complete duplicate — updates last_modified only
# ------------------------------------------------------------------ #
async def test_duplicate_updates_last_modified_only(db_session, valid_row):
    await _run_ingest([valid_row], log_id_offset=0)
    result, _ = await _run_ingest([valid_row], log_id_offset=1)

    assert result["unchanged"] == 1
    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert "test_sample_001" in result["unchanged_ids"]


async def test_duplicate_not_in_translate_list(db_session, valid_row):
    await _run_ingest([valid_row], log_id_offset=0)
    result, _ = await _run_ingest([valid_row], log_id_offset=1)

    assert "test_sample_001" not in result["inserted_ids"]
    assert "test_sample_001" not in result["updated_ids"]


# ------------------------------------------------------------------ #
# Changed data — updates in place
# ------------------------------------------------------------------ #
async def test_changed_data_updates_in_place(db_session, valid_row, valid_row_changed):
    await _run_ingest([valid_row], log_id_offset=0)
    result, _ = await _run_ingest([valid_row_changed], log_id_offset=1)

    assert result["updated"] == 1
    assert result["inserted"] == 0
    assert "test_sample_001" in result["updated_ids"]

    sample = await _query_sample("test_sample_001")
    assert sample.diagnosis_1 == "UPDATED: Ganglio linfático: linfoma T, estadio IV."
    assert sample.age == 46


async def test_changed_data_only_one_row_in_db(db_session, valid_row, valid_row_changed):
    await _run_ingest([valid_row], log_id_offset=0)
    await _run_ingest([valid_row_changed], log_id_offset=1)

    samples = await _query_all_samples()
    matching = [s for s in samples if s.anonymized_sample_id == "test_sample_001"]
    assert len(matching) == 1


async def test_changed_data_ingestion_log_id_updated(db_session, valid_row, valid_row_changed):
    _, log_id1 = await _run_ingest([valid_row], log_id_offset=0)
    _, log_id2 = await _run_ingest([valid_row_changed], log_id_offset=1)

    sample = await _query_sample("test_sample_001")
    assert sample.ingestion_log_id == log_id2


# ------------------------------------------------------------------ #
# Rejected rows
# ------------------------------------------------------------------ #
async def test_blank_id_goes_to_rejected(db_session, row_blank_id):
    result, log_id = await _run_ingest([row_blank_id])

    assert result["rejected"] == 1
    assert result["inserted"] == 0

    rejected = await _query_rejected(log_id)
    assert len(rejected) == 1
    reason = rejected[0].rejection_reason.lower()
    assert "blank" in reason or "null" in reason or "anonymized" in reason.lower()


async def test_invalid_age_goes_to_rejected(db_session, row_invalid_age):
    result, log_id = await _run_ingest([row_invalid_age])

    assert result["rejected"] == 1
    rejected = await _query_rejected(log_id)
    assert len(rejected) == 1
    assert rejected[0].row_number == 1
    assert "130" in rejected[0].rejection_reason or "age" in rejected[0].rejection_reason.lower()


async def test_invalid_year_goes_to_rejected(db_session, row_invalid_year):
    result, log_id = await _run_ingest([row_invalid_year])

    assert result["rejected"] == 1
    rejected = await _query_rejected(log_id)
    assert "1900" in rejected[0].rejection_reason


async def test_rejected_row_preserves_raw_data(db_session, row_invalid_age):
    result, log_id = await _run_ingest([row_invalid_age])

    rejected = await _query_rejected(log_id)
    assert rejected[0].raw_data is not None
    assert rejected[0].raw_data.get("AnonymizedSampleID") == "test_bad_age_001"


# ------------------------------------------------------------------ #
# Mixed valid and invalid rows
# ------------------------------------------------------------------ #
async def test_valid_rows_insert_despite_invalid_rows(
    db_session, valid_row, row_blank_id, row_invalid_age
):
    result, _ = await _run_ingest([valid_row, row_blank_id, row_invalid_age])

    assert result["inserted"] == 1
    assert result["rejected"] == 2

    sample = await _query_sample("test_sample_001")
    assert sample is not None


async def test_all_invalid_inserts_nothing(
    db_session, row_blank_id, row_invalid_age, row_invalid_year
):
    result, _ = await _run_ingest([row_blank_id, row_invalid_age, row_invalid_year])

    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["rejected"] == 3

    samples = await _query_all_samples()
    assert len(samples) == 0


# ------------------------------------------------------------------ #
# Multiple new rows
# ------------------------------------------------------------------ #
async def test_multiple_new_rows_all_inserted(
    db_session, valid_row, row_sparse, row_multi_diagnosis
):
    result, _ = await _run_ingest([valid_row, row_sparse, row_multi_diagnosis])

    assert result["inserted"] == 3
    assert result["rejected"] == 0

    samples = await _query_all_samples()
    assert len(samples) == 3


# ------------------------------------------------------------------ #
# Provenance fields do not trigger update
# ------------------------------------------------------------------ #
async def test_provenance_fields_do_not_trigger_update(db_session, valid_row):
    await _run_ingest([valid_row], log_id_offset=0)

    changed = valid_row.copy()
    changed["FileChecksum"] = "different_checksum_value"
    changed["StorageName"] = "Different-Storage"
    changed["FileSizeBytes"] = "999999999"

    result, _ = await _run_ingest([changed], log_id_offset=1)

    assert result["unchanged"] == 1
    assert result["updated"] == 0


# ------------------------------------------------------------------ #
# Sparse row
# ------------------------------------------------------------------ #
async def test_sparse_row_nulls_stored_correctly(db_session, row_sparse):
    await _run_ingest([row_sparse])
    sample = await _query_sample("test_sparse_001")
    assert sample is not None
    assert sample.clinical_info is None
    assert sample.macroscopic_desc is None
    assert sample.microscopic_desc is None
    assert sample.diagnoses is None
