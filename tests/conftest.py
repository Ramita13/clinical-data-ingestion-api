"""
conftest.py — shared fixtures for the entire test suite.

Key design decisions:
- Uses real PostgreSQL (mda_test_db) not SQLite — our schema uses JSONB/TSVECTOR
- Each test runs inside a transaction that rolls back — clean state per test
- Tables created once per session, not per test — fast
- get_db dependency overridden to use the test session
- AsyncClient used for API tests — no real server needed
"""

import asyncio
import io
from typing import AsyncGenerator

import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.session import get_db
from main import app
from app.models import Base


# ------------------------------------------------------------------ #
# Event loop — one loop for the entire test session
# ------------------------------------------------------------------ #
@pytest.fixture(scope="session")
def event_loop():
    """Single event loop shared across all tests in the session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ------------------------------------------------------------------ #
# Test database engine — created once per session
# ------------------------------------------------------------------ #
@pytest.fixture(scope="session")
def test_engine():
    """
    Creates an async engine pointing at mda_test_db.
    Scope=session means this is created once for all tests.
    """
    url = settings.TEST_DATABASE_URL
    if not url:
        raise ValueError(
            "TEST_DATABASE_URL not set in .env. "
            "Add: TEST_DATABASE_URL=postgresql+asyncpg://mda_user:abc123@localhost:5432/mda_test_db"
        )
    engine = create_async_engine(url, echo=False)
    return engine


# ------------------------------------------------------------------ #
# Create all tables once per session, drop after all tests finish
# ------------------------------------------------------------------ #
@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables(test_engine, event_loop):
    """
    Creates all tables in mda_test_db before any tests run.
    Drops them after all tests finish.
    autouse=True means this runs automatically for every test session.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


# ------------------------------------------------------------------ #
# Test session — each test gets a fresh transaction that rolls back
# ------------------------------------------------------------------ #
@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a DB session wrapped in a transaction.
    Transaction is rolled back after each test — clean state guaranteed.
    This means every test starts with empty tables.
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        async with session_factory() as session:
            yield session
        await conn.rollback()


# ------------------------------------------------------------------ #
# Override FastAPI's get_db dependency to use the test session
# ------------------------------------------------------------------ #
@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Yields an async HTTP client that talks to the FastAPI app directly.
    No real server needed — uses ASGITransport.
    DB dependency is overridden to use the test session (with rollback).
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ------------------------------------------------------------------ #
# Sample data fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def valid_row() -> dict:
    """A single valid row matching the expected Excel format."""
    return {
        "AnonymizedSampleID": "test_sample_001",
        "FileName": "slide_test_001.ndpi",
        "Gender": "M",
        "Age": "45",
        "DiagnosisYear": "2024",
        "ClinicalInfo1": "Se solicita revisión de biopsia.",
        "MacroscopicDesc1": "Un bloque de parafina identificado.",
        "MicroscopicDesc1": "Fragmentos de ganglio linfático.",
        "Diagnosis1": "Ganglio linfático: linfoma T angioinmunoblástico.",
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
    """Same ID as valid_row but with changed clinical data — triggers UPDATE."""
    row = valid_row.copy()
    row["Diagnosis1"] = "UPDATED: Ganglio linfático: linfoma T, estadio IV."
    row["Age"] = "46"
    return row


@pytest.fixture
def row_blank_id() -> dict:
    """Row with blank AnonymizedSampleID — should be rejected."""
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
    """Row with age=999 — should be rejected."""
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
    """Row with DiagnosisYear=1750 — should be rejected."""
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
    """Row with unexpected extra columns — should land in extra_fields JSONB."""
    row = valid_row.copy()
    row["AnonymizedSampleID"] = "test_extra_001"
    row["NewColumn2026"] = "unexpected_value"
    row["TissueType"] = "FFPE"
    return row


@pytest.fixture
def row_sparse() -> dict:
    """Row with only required fields — most optional fields empty."""
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
    """Row with multiple diagnoses filled — tests diagnoses JSONB grouping."""
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
# File fixtures — Excel and CSV bytes for upload endpoint tests
# ------------------------------------------------------------------ #

def _rows_to_xlsx_bytes(rows: list[dict]) -> bytes:
    """Convert a list of row dicts to Excel bytes."""
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _rows_to_csv_bytes(rows: list[dict], sep: str = ",") -> bytes:
    """Convert a list of row dicts to CSV bytes."""
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=sep)
    return buf.getvalue().encode("utf-8")


def _rows_to_csv_bytes_bom(rows: list[dict], sep: str = ";") -> bytes:
    """Convert rows to CSV bytes with UTF-8 BOM — mimics European Excel export."""
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=sep)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


@pytest.fixture
def valid_xlsx_bytes(valid_row) -> bytes:
    """Valid single-row Excel file as bytes."""
    return _rows_to_xlsx_bytes([valid_row])


@pytest.fixture
def multi_row_xlsx_bytes(valid_row, row_sparse, row_multi_diagnosis) -> bytes:
    """Valid multi-row Excel file — 3 different valid rows."""
    return _rows_to_xlsx_bytes([valid_row, row_sparse, row_multi_diagnosis])


@pytest.fixture
def mixed_xlsx_bytes(valid_row, row_blank_id, row_invalid_age) -> bytes:
    """Excel with valid and invalid rows mixed — tests partial ingestion."""
    return _rows_to_xlsx_bytes([valid_row, row_blank_id, row_invalid_age])


@pytest.fixture
def valid_csv_bytes(valid_row) -> bytes:
    """Valid CSV with comma delimiter."""
    return _rows_to_csv_bytes([valid_row])


@pytest.fixture
def semicolon_csv_bytes(valid_row) -> bytes:
    """Valid CSV with semicolon delimiter — European Excel export."""
    return _rows_to_csv_bytes([valid_row], sep=";")


@pytest.fixture
def bom_csv_bytes(valid_row) -> bytes:
    """Valid CSV with UTF-8 BOM and semicolon delimiter."""
    return _rows_to_csv_bytes_bom([valid_row])
