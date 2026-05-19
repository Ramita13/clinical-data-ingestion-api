"""
conftest.py — shared fixtures for the entire test suite.

Uses synchronous psycopg2 driver for tests to avoid asyncpg event loop
issues with Python 3.14 + pytest-asyncio on Windows.

Production code uses asyncpg (async). Tests use psycopg2 (sync wrapped
in async via SQLAlchemy's sync_to_async pattern). Same PostgreSQL database,
same schema, same behaviour — just different driver for test isolation.
"""

import asyncio
import io
from typing import AsyncGenerator

import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.db.session import get_db
from main import app
from app.models import Base


# ------------------------------------------------------------------ #
# Build sync URL from async URL
# postgresql+asyncpg://... -> postgresql+psycopg2://...
# ------------------------------------------------------------------ #
def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


# ------------------------------------------------------------------ #
# Sync engine — used to set up/tear down tables and truncate
# ------------------------------------------------------------------ #
@pytest.fixture(scope="session")
def sync_engine():
    url = settings.TEST_DATABASE_URL
    if not url:
        raise ValueError("TEST_DATABASE_URL not set in .env")
    engine = create_engine(_sync_url(url), echo=False)
    return engine


# ------------------------------------------------------------------ #
# Create tables once, drop after all tests
# ------------------------------------------------------------------ #
@pytest.fixture(scope="session", autouse=True)
def create_tables(sync_engine):
    Base.metadata.drop_all(sync_engine)
    Base.metadata.create_all(sync_engine)
    yield
    Base.metadata.drop_all(sync_engine)
    sync_engine.dispose()


# ------------------------------------------------------------------ #
# Sync session factory
# ------------------------------------------------------------------ #
@pytest.fixture(scope="session")
def sync_session_factory(sync_engine):
    return sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


# ------------------------------------------------------------------ #
# DB session — sync session wrapped for use in async tests
# Truncates tables before each test for clean state
# ------------------------------------------------------------------ #
@pytest_asyncio.fixture
async def db_session(sync_session_factory, sync_engine) -> AsyncGenerator[Session, None]:
    """
    Yields a synchronous DB session for tests.
    Tables truncated before each test — clean state guaranteed.
    Works around asyncpg event loop issues on Python 3.14/Windows.
    """
    # Truncate before test
    with sync_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE rejected_rows, samples, ingestion_log, raw_files RESTART IDENTITY CASCADE"))
        conn.commit()

    session = sync_session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # Truncate after test
    with sync_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE rejected_rows, samples, ingestion_log, raw_files RESTART IDENTITY CASCADE"))
        conn.commit()


# ------------------------------------------------------------------ #
# HTTP test client — fresh async engine per test avoids asyncpg loop issues
# ------------------------------------------------------------------ #
@pytest_asyncio.fixture
async def client(sync_engine) -> AsyncGenerator[AsyncClient, None]:
    """
    Yields an async HTTP client for API endpoint tests.
    Creates a fresh async engine per test — avoids asyncpg event loop
    conflicts on Python 3.14/Windows.
    Tables truncated before each API test via sync engine.
    """
    # Fresh engine bound to current test event loop
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Truncate before API test using sync engine
    with sync_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE rejected_rows, samples, ingestion_log, raw_files RESTART IDENTITY CASCADE"))
        conn.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    try:
        await engine.dispose()
    except Exception:
        pass  # Suppress asyncpg teardown errors on Python 3.14/Windows


# ------------------------------------------------------------------ #
# Sample data fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def valid_row() -> dict:
    return {
        "AnonymizedSampleID": "test_sample_001",
        "FileName": "slide_test_001.ndpi",
        "Gender": "M",
        "Age": "45",
        "DiagnosisYear": "2024",
        "ClinicalInfo1": "Se solicita revisión de biopsia.",
        "MacroscopicDesc1": "Un bloque de parafina identificado.",
        "MicroscopicDesc1": "Fragmentos de ganglio linfático.",
        "Diagnosis1": "Ganglio linfático: linfoma T.",
        "TopographicCode1": "T08000",
        "Location1": "GANGLIO LINFATICO",
        "IcdCode1": "M97053",
        "ChecksumAlgorithm": "MD5",
        "FileChecksum": "abc123def456abc123def456abc12345",
        "FileSizeBytes": "555735588",
        "UploadDateTime": "11/12/2025 16:47",
        "StorageName": "Hetzner-Primary",
        "BucketName": "histofy1",
    }


@pytest.fixture
def valid_row_changed(valid_row) -> dict:
    row = valid_row.copy()
    row["Diagnosis1"] = "UPDATED: Ganglio linfático: linfoma T, estadio IV."
    row["Age"] = "46"
    return row


@pytest.fixture
def row_blank_id() -> dict:
    return {
        "AnonymizedSampleID": "",
        "FileName": "slide_bad.ndpi",
        "Gender": "M",
        "Age": "40",
        "DiagnosisYear": "2024",
        "Diagnosis1": "Some diagnosis",
        "ChecksumAlgorithm": "MD5",
        "FileChecksum": "abc123",
        "FileSizeBytes": "100000",
        "UploadDateTime": "11/12/2025 16:47",
        "StorageName": "Hetzner-Primary",
        "BucketName": "histofy1",
    }


@pytest.fixture
def row_invalid_age() -> dict:
    return {
        "AnonymizedSampleID": "test_bad_age_001",
        "FileName": "slide_bad_age.ndpi",
        "Gender": "F",
        "Age": "999",
        "DiagnosisYear": "2024",
        "Diagnosis1": "Some diagnosis",
        "ChecksumAlgorithm": "MD5",
        "FileChecksum": "abc123",
        "FileSizeBytes": "100000",
        "UploadDateTime": "11/12/2025 16:47",
        "StorageName": "Hetzner-Primary",
        "BucketName": "histofy1",
    }


@pytest.fixture
def row_invalid_year() -> dict:
    return {
        "AnonymizedSampleID": "test_bad_year_001",
        "FileName": "slide_bad_year.ndpi",
        "Gender": "M",
        "Age": "50",
        "DiagnosisYear": "1750",
        "Diagnosis1": "Some diagnosis",
        "ChecksumAlgorithm": "MD5",
        "FileChecksum": "abc123",
        "FileSizeBytes": "100000",
        "UploadDateTime": "11/12/2025 16:47",
        "StorageName": "Hetzner-Primary",
        "BucketName": "histofy1",
    }


@pytest.fixture
def row_with_extra_fields(valid_row) -> dict:
    row = valid_row.copy()
    row["AnonymizedSampleID"] = "test_extra_001"
    row["NewColumn2026"] = "unexpected_value"
    row["TissueType"] = "FFPE"
    return row


@pytest.fixture
def row_sparse() -> dict:
    return {
        "AnonymizedSampleID": "test_sparse_001",
        "FileName": "slide_sparse.ndpi",
        "Gender": "F",
        "Age": "33",
        "DiagnosisYear": "2023",
        "Diagnosis1": "Mama: carcinoma ductal invasivo.",
        "ChecksumAlgorithm": "MD5",
        "FileChecksum": "sparse123",
        "FileSizeBytes": "200000000",
        "UploadDateTime": "01/06/2024 10:00",
        "StorageName": "Hetzner-Primary",
        "BucketName": "histofy1",
    }


@pytest.fixture
def row_multi_diagnosis() -> dict:
    return {
        "AnonymizedSampleID": "test_multidiag_001",
        "FileName": "slide_multi.ndpi",
        "Gender": "F",
        "Age": "48",
        "DiagnosisYear": "2024",
        "Diagnosis1": "Ganglio linfático: linfoma folicular grado 1.",
        "Diagnosis2": "Médula ósea: infiltración por linfoma folicular (30%).",
        "Diagnosis3": "Bazo: afectación esplénica por linfoma folicular.",
        "Diagnosis4": "Hígado: infiltración portal por linfoma folicular.",
        "TopographicCode1": "T08000",
        "TopographicCode2": "T06000",
        "Location1": "GANGLIO LINFATICO",
        "Location2": "MEDULA OSEA",
        "IcdCode1": "M96953",
        "IcdCode2": "M96952",
        "ChecksumAlgorithm": "MD5",
        "FileChecksum": "multi123",
        "FileSizeBytes": "620000000",
        "UploadDateTime": "14/05/2026 09:40",
        "StorageName": "Hetzner-Primary",
        "BucketName": "histofy1",
    }


# ------------------------------------------------------------------ #
# File fixtures
# ------------------------------------------------------------------ #

def _rows_to_xlsx_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _rows_to_csv_bytes(rows: list[dict], sep: str = ",") -> bytes:
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=sep)
    return buf.getvalue().encode("utf-8")


def _rows_to_csv_bytes_bom(rows: list[dict], sep: str = ";") -> bytes:
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=sep)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


@pytest.fixture
def valid_xlsx_bytes(valid_row) -> bytes:
    return _rows_to_xlsx_bytes([valid_row])


@pytest.fixture
def multi_row_xlsx_bytes(valid_row, row_sparse, row_multi_diagnosis) -> bytes:
    return _rows_to_xlsx_bytes([valid_row, row_sparse, row_multi_diagnosis])


@pytest.fixture
def mixed_xlsx_bytes(valid_row, row_blank_id, row_invalid_age) -> bytes:
    return _rows_to_xlsx_bytes([valid_row, row_blank_id, row_invalid_age])


@pytest.fixture
def valid_csv_bytes(valid_row) -> bytes:
    return _rows_to_csv_bytes([valid_row])


@pytest.fixture
def semicolon_csv_bytes(valid_row) -> bytes:
    return _rows_to_csv_bytes([valid_row], sep=";")


@pytest.fixture
def bom_csv_bytes(valid_row) -> bytes:
    return _rows_to_csv_bytes_bom([valid_row])
