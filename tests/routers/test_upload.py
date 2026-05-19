"""
test_upload.py — API tests for POST /upload/upload_data

Tests the full HTTP layer using AsyncClient + ASGITransport.
No real server needed — requests go directly to the FastAPI app.
Uses real PostgreSQL (mda_test_db) via the client fixture.
"""

import io
import pytest
import pandas as pd


# ------------------------------------------------------------------ #
# Helpers
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
    return b"\xef\xbb\xbf" + data if bom else data


VALID_ROW = {
    "AnonymizedSampleID": "upload_test_001",
    "FileName": "slide_upload_001.ndpi",
    "Gender": "M",
    "Age": "45",
    "DiagnosisYear": "2024",
    "ClinicalInfo1": "Se solicita revisión de biopsia.",
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

VALID_ROW_2 = {**VALID_ROW, "AnonymizedSampleID": "upload_test_002", "Gender": "F", "Age": "33"}
VALID_ROW_3 = {**VALID_ROW, "AnonymizedSampleID": "upload_test_003", "Gender": "M", "Age": "60"}

INVALID_ROW_BLANK_ID = {**VALID_ROW, "AnonymizedSampleID": ""}
INVALID_ROW_BAD_AGE = {**VALID_ROW, "AnonymizedSampleID": "upload_bad_age", "Age": "999"}


# ------------------------------------------------------------------ #
# POST /upload/upload_data — valid files
# ------------------------------------------------------------------ #
async def test_upload_valid_xlsx_returns_200(client):
    data = _make_xlsx([VALID_ROW])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200


async def test_upload_valid_xlsx_correct_counts(client):
    data = _make_xlsx([VALID_ROW, VALID_ROW_2, VALID_ROW_3])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = response.json()
    assert body["rows_total"] == 3
    assert body["rows_inserted"] == 3
    assert body["rows_rejected"] == 0


async def test_upload_valid_csv_comma_returns_200(client):
    data = _make_csv([VALID_ROW])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.csv", data, "text/csv")},
    )
    assert response.status_code == 200


async def test_upload_valid_csv_semicolon_returns_200(client):
    data = _make_csv([VALID_ROW], sep=";")
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.csv", data, "text/csv")},
    )
    assert response.status_code == 200


async def test_upload_valid_csv_bom_returns_200(client):
    data = _make_csv([VALID_ROW], sep=";", bom=True)
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.csv", data, "text/csv")},
    )
    assert response.status_code == 200


# ------------------------------------------------------------------ #
# POST /upload/upload_data — response body structure
# ------------------------------------------------------------------ #
async def test_upload_response_has_required_fields(client):
    data = _make_xlsx([VALID_ROW])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = response.json()
    assert "file_name" in body
    assert "rows_total" in body
    assert "rows_inserted" in body
    assert "rows_updated" in body
    assert "rows_unchanged" in body
    assert "rows_rejected" in body
    assert "ingestion_log_id" in body
    assert "duplicate_file_warning" in body
    assert "translation_status" in body


async def test_upload_translation_status_queued(client):
    data = _make_xlsx([VALID_ROW])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.json()["translation_status"] == "queued"


async def test_upload_returns_correct_filename(client):
    data = _make_xlsx([VALID_ROW])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("my_samples.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.json()["file_name"] == "my_samples.xlsx"


async def test_upload_ingestion_log_id_is_integer(client):
    data = _make_xlsx([VALID_ROW])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert isinstance(response.json()["ingestion_log_id"], int)
    assert response.json()["ingestion_log_id"] > 0


# ------------------------------------------------------------------ #
# POST /upload/upload_data — wrong file type
# ------------------------------------------------------------------ #
async def test_upload_pdf_returns_400(client):
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("file.pdf", b"fake pdf content", "application/pdf")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


async def test_upload_txt_returns_400(client):
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("file.txt", b"fake txt content", "text/plain")},
    )
    assert response.status_code == 400


async def test_upload_docx_returns_400(client):
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("file.docx", b"fake docx content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 400


# ------------------------------------------------------------------ #
# POST /upload/upload_data — missing core column
# ------------------------------------------------------------------ #
async def test_upload_missing_sample_id_column_returns_400(client):
    row = VALID_ROW.copy()
    del row["AnonymizedSampleID"]
    data = _make_xlsx([row])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 400
    assert "AnonymizedSampleID" in response.json()["detail"]


# ------------------------------------------------------------------ #
# POST /upload/upload_data — row-level validation failures
# ------------------------------------------------------------------ #
async def test_upload_invalid_rows_rejected_valid_rows_inserted(client):
    data = _make_xlsx([VALID_ROW, INVALID_ROW_BLANK_ID, INVALID_ROW_BAD_AGE])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["rows_inserted"] == 1
    assert body["rows_rejected"] == 2


async def test_upload_all_invalid_rows_returns_200_with_zero_inserted(client):
    data = _make_xlsx([INVALID_ROW_BLANK_ID, INVALID_ROW_BAD_AGE])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["rows_inserted"] == 0
    assert body["rows_rejected"] == 2


# ------------------------------------------------------------------ #
# POST /upload/upload_data — duplicate file detection
# ------------------------------------------------------------------ #
async def test_upload_same_file_twice_triggers_warning(client):
    data = _make_xlsx([VALID_ROW])

    # First upload
    await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    # Second upload — same file
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.json()["duplicate_file_warning"] is True


async def test_upload_different_file_no_warning(client):
    data1 = _make_xlsx([VALID_ROW])
    data2 = _make_xlsx([VALID_ROW_2])

    await client.post(
        "/upload/upload_data",
        files={"file": ("test1.xlsx", data1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test2.xlsx", data2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.json()["duplicate_file_warning"] is False


# ------------------------------------------------------------------ #
# POST /upload/upload_data — deduplication via API
# ------------------------------------------------------------------ #
async def test_upload_same_data_twice_shows_unchanged(client):
    data = _make_xlsx([VALID_ROW])

    await client.post(
        "/upload/upload_data",
        files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    # Upload same row data in a different file (different filename = different checksum)
    # Only provenance fields differ — should be unchanged not updated
    import copy
    row2 = copy.deepcopy(VALID_ROW)
    # Change only checksum_algorithm to force a different file checksum
    # but keep all clinical/sample data identical
    data2 = _make_xlsx([row2])
    # Add a dummy second row to make the file different (different checksum)
    # but keep VALID_ROW identical
    dummy = {**VALID_ROW, "AnonymizedSampleID": "dummy_row_to_change_checksum"}
    data3 = _make_xlsx([VALID_ROW, dummy])

    # Upload the two-row file — VALID_ROW should be unchanged, dummy should insert
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test3.xlsx", data3, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = response.json()
    assert body["rows_unchanged"] == 1
    assert body["rows_inserted"] == 1


async def test_upload_changed_data_shows_updated(client):
    data1 = _make_xlsx([VALID_ROW])
    await client.post(
        "/upload/upload_data",
        files={"file": ("test1.xlsx", data1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    changed = {**VALID_ROW, "Diagnosis1": "UPDATED diagnosis", "Age": "50"}
    data2 = _make_xlsx([changed])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("test2.xlsx", data2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = response.json()
    assert body["rows_updated"] == 1
    assert body["rows_inserted"] == 0


# ------------------------------------------------------------------ #
# POST /upload/upload_data — missing expected columns warning
# ------------------------------------------------------------------ #
async def test_upload_missing_expected_columns_returns_warning_list(client):
    row = {"AnonymizedSampleID": "minimal_001"}
    data = _make_xlsx([row])
    response = await client.post(
        "/upload/upload_data",
        files={"file": ("minimal.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = response.json()
    assert response.status_code == 200
    assert len(body["missing_expected_columns"]) > 0


# ------------------------------------------------------------------ #
# GET /health — sanity check
# ------------------------------------------------------------------ #
async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
