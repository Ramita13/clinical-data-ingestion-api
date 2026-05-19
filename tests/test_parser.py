"""
test_parser.py — unit tests for app/utils/file_parser.py

These are pure unit tests — no database, no HTTP, no fixtures needed.
Tests the file parsing logic in complete isolation.
"""

import io
import pytest
import pandas as pd

from app.utils.file_parser import (
    FileValidationError,
    _compute_checksum,
    _detect_csv_delimiter,
    _extract_extra_fields,
    parse_upload,
)
from app.schemas.sample import ALL_KNOWN_COLUMNS


# ------------------------------------------------------------------ #
# Helper — build minimal valid Excel bytes
# ------------------------------------------------------------------ #
def _make_xlsx(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _make_csv(rows: list[dict], sep: str = ",", bom: bool = False) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=sep)
    data = buf.getvalue().encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    return data


VALID_ROW = {
    "AnonymizedSampleID": "abc123",
    "FileName": "slide.ndpi",
    "Gender": "M",
    "Age": "45",
    "DiagnosisYear": "2024",
    "Diagnosis1": "Some diagnosis",
    "ChecksumAlgorithm": "MD5",
    "FileChecksum": "abc123",
    "FileSizeBytes": "100000",
    "UploadDateTime": "11/12/2025 16:47",
    "StorageName": "Hetzner-Primary",
    "BucketName": "histofy1",
}


# ------------------------------------------------------------------ #
# _compute_checksum
# ------------------------------------------------------------------ #
def test_checksum_is_md5_hex():
    data = b"hello world"
    result = _compute_checksum(data)
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_same_bytes_same_checksum():
    data = b"test data"
    assert _compute_checksum(data) == _compute_checksum(data)


def test_different_bytes_different_checksum():
    assert _compute_checksum(b"data1") != _compute_checksum(b"data2")


# ------------------------------------------------------------------ #
# _detect_csv_delimiter
# ------------------------------------------------------------------ #
def test_detects_comma_delimiter():
    csv = b"AnonymizedSampleID,Gender,Age\nabc,M,45"
    assert _detect_csv_delimiter(csv) == ","


def test_detects_semicolon_delimiter():
    csv = b"AnonymizedSampleID;Gender;Age\nabc;M;45"
    assert _detect_csv_delimiter(csv) == ";"


def test_detects_semicolon_with_bom():
    csv = b"\xef\xbb\xbfAnonymizedSampleID;Gender;Age\nabc;M;45"
    assert _detect_csv_delimiter(csv) == ";"


def test_defaults_to_comma_when_equal():
    # Equal counts — defaults to comma
    csv = b"A,B;C\n1,2;3"
    assert _detect_csv_delimiter(csv) == ","


# ------------------------------------------------------------------ #
# _extract_extra_fields
# ------------------------------------------------------------------ #
def test_known_columns_go_to_known():
    row = {"AnonymizedSampleID": "abc", "Gender": "M", "UnknownCol": "value"}
    known, extra = _extract_extra_fields(row)
    assert "AnonymizedSampleID" in known
    assert "Gender" in known
    assert "UnknownCol" not in known


def test_unknown_columns_go_to_extra():
    row = {"AnonymizedSampleID": "abc", "NewField": "value", "TissueType": "FFPE"}
    known, extra = _extract_extra_fields(row)
    assert extra == {"NewField": "value", "TissueType": "FFPE"}


def test_empty_extra_values_excluded():
    """Empty string extra fields should not be stored — prevents false change detection."""
    row = {"AnonymizedSampleID": "abc", "NewField": "", "TissueType": "FFPE"}
    known, extra = _extract_extra_fields(row)
    assert "NewField" not in extra
    assert extra == {"TissueType": "FFPE"}


def test_all_empty_extra_returns_none():
    row = {"AnonymizedSampleID": "abc", "NewField": "", "OtherField": "nan"}
    known, extra = _extract_extra_fields(row)
    assert extra is None


def test_no_extra_fields_returns_none():
    row = {"AnonymizedSampleID": "abc", "Gender": "M"}
    known, extra = _extract_extra_fields(row)
    assert extra is None


# ------------------------------------------------------------------ #
# parse_upload — extension validation
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_rejects_pdf_extension():
    with pytest.raises(FileValidationError, match="Unsupported file type"):
        await parse_upload(b"fake content", "file.pdf")


@pytest.mark.asyncio
async def test_rejects_txt_extension():
    with pytest.raises(FileValidationError, match="Unsupported file type"):
        await parse_upload(b"fake content", "file.txt")


@pytest.mark.asyncio
async def test_rejects_docx_extension():
    with pytest.raises(FileValidationError, match="Unsupported file type"):
        await parse_upload(b"fake content", "file.docx")


# ------------------------------------------------------------------ #
# parse_upload — valid file formats
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_accepts_xlsx():
    data = _make_xlsx([VALID_ROW])
    rows, checksum, missing = await parse_upload(data, "file.xlsx")
    assert len(rows) == 1
    assert rows[0]["AnonymizedSampleID"] == "abc123"


@pytest.mark.asyncio
async def test_accepts_csv_comma():
    data = _make_csv([VALID_ROW], sep=",")
    rows, checksum, missing = await parse_upload(data, "file.csv")
    assert len(rows) == 1
    assert rows[0]["AnonymizedSampleID"] == "abc123"


@pytest.mark.asyncio
async def test_accepts_csv_semicolon():
    data = _make_csv([VALID_ROW], sep=";")
    rows, checksum, missing = await parse_upload(data, "file.csv")
    assert len(rows) == 1
    assert rows[0]["AnonymizedSampleID"] == "abc123"


@pytest.mark.asyncio
async def test_accepts_csv_with_bom():
    data = _make_csv([VALID_ROW], sep=";", bom=True)
    rows, checksum, missing = await parse_upload(data, "file.csv")
    assert len(rows) == 1
    assert rows[0]["AnonymizedSampleID"] == "abc123"


# ------------------------------------------------------------------ #
# parse_upload — empty file
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_rejects_empty_xlsx():
    df = pd.DataFrame([])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    with pytest.raises(FileValidationError, match="no rows"):
        await parse_upload(buf.getvalue(), "empty.xlsx")


# ------------------------------------------------------------------ #
# parse_upload — missing core column
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_rejects_missing_anonymized_sample_id():
    row = VALID_ROW.copy()
    del row["AnonymizedSampleID"]
    data = _make_xlsx([row])
    with pytest.raises(FileValidationError, match="AnonymizedSampleID"):
        await parse_upload(data, "file.xlsx")


# ------------------------------------------------------------------ #
# parse_upload — checksum
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_returns_consistent_checksum():
    data = _make_xlsx([VALID_ROW])
    _, checksum1, _ = await parse_upload(data, "file.xlsx")
    _, checksum2, _ = await parse_upload(data, "file.xlsx")
    assert checksum1 == checksum2
    assert len(checksum1) == 32


# ------------------------------------------------------------------ #
# parse_upload — extra fields
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_extra_columns_go_to_extra_fields():
    row = VALID_ROW.copy()
    row["NewColumn2026"] = "unexpected"
    row["TissueType"] = "FFPE"
    data = _make_xlsx([row])
    rows, _, _ = await parse_upload(data, "file.xlsx")
    assert rows[0].get("extra_fields") == {
        "NewColumn2026": "unexpected",
        "TissueType": "FFPE",
    }


@pytest.mark.asyncio
async def test_empty_extra_columns_not_in_extra_fields():
    """Extra columns with empty values should not appear in extra_fields."""
    row = VALID_ROW.copy()
    row["NewColumn2026"] = ""
    row["TissueType"] = ""
    data = _make_xlsx([row])
    rows, _, _ = await parse_upload(data, "file.xlsx")
    assert rows[0].get("extra_fields") is None


# ------------------------------------------------------------------ #
# parse_upload — missing expected columns (warning not failure)
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_missing_expected_columns_returns_warning():
    """Missing non-core columns return a warning list but do not raise."""
    row = {"AnonymizedSampleID": "abc123"}
    data = _make_xlsx([row])
    rows, _, missing = await parse_upload(data, "file.xlsx")
    assert len(rows) == 1
    assert len(missing) > 0
    assert "Diagnosis1" in missing or "Gender" in missing


# ------------------------------------------------------------------ #
# parse_upload — multiple rows
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_parses_multiple_rows():
    rows_in = [
        {**VALID_ROW, "AnonymizedSampleID": f"sample_{i}"}
        for i in range(5)
    ]
    data = _make_xlsx(rows_in)
    rows_out, _, _ = await parse_upload(data, "file.xlsx")
    assert len(rows_out) == 5
    ids = [r["AnonymizedSampleID"] for r in rows_out]
    assert ids == [f"sample_{i}" for i in range(5)]
