"""
test_samples.py — API tests for GET /samples endpoints

Tests all query endpoints using AsyncClient + ASGITransport.
Seeds data via the upload endpoint before querying.
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


async def _upload(client, rows: list[dict], filename: str = "test.xlsx") -> dict:
    """Upload rows via the API and return the response body."""
    data = _make_xlsx(rows)
    response = await client.post(
        "/upload/upload_data",
        files={"file": (filename, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    return response.json()


# ------------------------------------------------------------------ #
# Test data
# ------------------------------------------------------------------ #
ROW_M_45 = {
    "AnonymizedSampleID": "sample_m_45",
    "FileName": "slide_m_45.ndpi",
    "Gender": "M", "Age": "45", "DiagnosisYear": "2024",
    "ClinicalInfo1": "Biopsia de ganglio linfático.",
    "Diagnosis1": "Ganglio linfático: linfoma T angioinmunoblástico.",
    "TopographicCode1": "T08000", "Location1": "GANGLIO LINFATICO",
    "IcdCode1": "M97053",
    "ChecksumAlgorithm": "MD5", "FileChecksum": "aaa111",
    "FileSizeBytes": "100000", "UploadDateTime": "11/12/2025 10:00",
    "StorageName": "Hetzner-Primary", "BucketName": "histofy1",
}

ROW_F_33 = {
    "AnonymizedSampleID": "sample_f_33",
    "FileName": "slide_f_33.ndpi",
    "Gender": "F", "Age": "33", "DiagnosisYear": "2023",
    "ClinicalInfo1": "Masa mamaria derecha.",
    "Diagnosis1": "Mama derecha: carcinoma ductal invasivo.",
    "TopographicCode1": "T04000", "Location1": "MAMA DERECHA",
    "IcdCode1": "M85003",
    "ChecksumAlgorithm": "MD5", "FileChecksum": "bbb222",
    "FileSizeBytes": "200000", "UploadDateTime": "12/12/2025 11:00",
    "StorageName": "Hetzner-Primary", "BucketName": "histofy1",
}

ROW_M_60 = {
    "AnonymizedSampleID": "sample_m_60",
    "FileName": "slide_m_60.ndpi",
    "Gender": "M", "Age": "60", "DiagnosisYear": "2022",
    "ClinicalInfo1": "Nódulo pulmonar izquierdo.",
    "Diagnosis1": "Pulmón izquierdo: adenocarcinoma.",
    "TopographicCode1": "T28000", "Location1": "PULMON IZQUIERDO",
    "IcdCode1": "M81403",
    "ChecksumAlgorithm": "MD5", "FileChecksum": "ccc333",
    "FileSizeBytes": "300000", "UploadDateTime": "13/12/2025 12:00",
    "StorageName": "Hetzner-Primary", "BucketName": "histofy1",
}

ROW_F_48 = {
    "AnonymizedSampleID": "sample_f_48",
    "FileName": "slide_f_48.ndpi",
    "Gender": "F", "Age": "48", "DiagnosisYear": "2024",
    "ClinicalInfo1": "Biopsia de colon.",
    "Diagnosis1": "Colon: adenocarcinoma bien diferenciado.",
    "TopographicCode1": "T59000", "Location1": "COLON",
    "IcdCode1": "M81403",
    "ChecksumAlgorithm": "MD5", "FileChecksum": "ddd444",
    "FileSizeBytes": "400000", "UploadDateTime": "14/12/2025 13:00",
    "StorageName": "Hetzner-Primary", "BucketName": "histofy1",
}

ALL_ROWS = [ROW_M_45, ROW_F_33, ROW_M_60, ROW_F_48]


# ------------------------------------------------------------------ #
# GET /samples — list all
# ------------------------------------------------------------------ #
async def test_list_samples_returns_200(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples")
    assert response.status_code == 200


async def test_list_samples_returns_all_records(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples")
    assert len(response.json()) == 4


async def test_list_samples_default_limit_50(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples")
    body = response.json()
    assert isinstance(body, list)
    assert len(body) <= 50


async def test_list_samples_pagination_skip(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples?skip=2&limit=10")
    assert len(response.json()) == 2


async def test_list_samples_pagination_limit(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples?skip=0&limit=2")
    assert len(response.json()) == 2


async def test_list_samples_empty_db_returns_empty_list(client):
    response = await client.get("/samples")
    assert response.status_code == 200
    assert response.json() == []


# ------------------------------------------------------------------ #
# GET /samples/{id} — get by ID
# ------------------------------------------------------------------ #
async def test_get_sample_by_id_returns_200(client):
    await _upload(client, [ROW_M_45])
    response = await client.get("/samples/sample_m_45")
    assert response.status_code == 200


async def test_get_sample_by_id_correct_data(client):
    await _upload(client, [ROW_M_45])
    response = await client.get("/samples/sample_m_45")
    body = response.json()
    assert body["anonymized_sample_id"] == "sample_m_45"
    assert body["gender"] == "M"
    assert body["age"] == 45
    assert body["diagnosis_year"] == 2024


async def test_get_sample_by_id_unknown_returns_404(client):
    response = await client.get("/samples/does_not_exist_xyz")
    assert response.status_code == 404


async def test_get_sample_404_error_message(client):
    response = await client.get("/samples/does_not_exist_xyz")
    assert "not found" in response.json()["detail"].lower()


async def test_get_sample_clinical_info_in_response(client):
    await _upload(client, [ROW_M_45])
    response = await client.get("/samples/sample_m_45")
    body = response.json()
    assert body["clinical_info"] is not None
    assert "1" in body["clinical_info"]


async def test_get_sample_diagnosis_1_in_response(client):
    await _upload(client, [ROW_M_45])
    response = await client.get("/samples/sample_m_45")
    body = response.json()
    assert body["diagnosis_1"] == "Ganglio linfático: linfoma T angioinmunoblástico."


# ------------------------------------------------------------------ #
# GET /samples/filter/query — filter by demographics
# ------------------------------------------------------------------ #
async def test_filter_by_gender_male(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?gender=M")
    body = response.json()
    assert len(body) == 2
    assert all(s["gender"] == "M" for s in body)


async def test_filter_by_gender_female(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?gender=F")
    body = response.json()
    assert len(body) == 2
    assert all(s["gender"] == "F" for s in body)


async def test_filter_by_gender_lowercase_normalised(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?gender=m")
    body = response.json()
    assert len(body) == 2


async def test_filter_by_age_min(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?age_min=50")
    body = response.json()
    assert len(body) == 1
    assert body[0]["age"] == 60


async def test_filter_by_age_max(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?age_max=40")
    body = response.json()
    assert len(body) == 1
    assert body[0]["age"] == 33


async def test_filter_by_age_range(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?age_min=40&age_max=50")
    body = response.json()
    assert len(body) == 2
    ages = {s["age"] for s in body}
    assert ages == {45, 48}


async def test_filter_by_diagnosis_year(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?diagnosis_year=2024")
    body = response.json()
    assert len(body) == 2
    assert all(s["diagnosis_year"] == 2024 for s in body)


async def test_filter_by_diagnosis_year_no_results(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?diagnosis_year=1999")
    assert response.json() == []


async def test_filter_by_diagnosis_1_partial_match(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?diagnosis_1=linfoma")
    body = response.json()
    assert len(body) == 1
    assert body[0]["anonymized_sample_id"] == "sample_m_45"


async def test_filter_by_icd_code(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?icd_code=M81403")
    body = response.json()
    assert len(body) == 2
    ids = {s["anonymized_sample_id"] for s in body}
    assert ids == {"sample_m_60", "sample_f_48"}


async def test_filter_combined_gender_and_year(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query?gender=M&diagnosis_year=2024")
    body = response.json()
    assert len(body) == 1
    assert body[0]["anonymized_sample_id"] == "sample_m_45"


async def test_filter_no_params_returns_all(client):
    await _upload(client, ALL_ROWS)
    response = await client.get("/samples/filter/query")
    assert len(response.json()) == 4


# ------------------------------------------------------------------ #
# GET /samples/search/fulltext — returns 501 (not implemented yet)
# ------------------------------------------------------------------ #
async def test_fulltext_search_returns_501(client):
    response = await client.get("/samples/search/fulltext?q=linfoma")
    assert response.status_code == 501


# ------------------------------------------------------------------ #
# Response structure
# ------------------------------------------------------------------ #
async def test_sample_response_has_required_fields(client):
    await _upload(client, [ROW_M_45])
    response = await client.get("/samples/sample_m_45")
    body = response.json()
    required = [
        "id", "anonymized_sample_id", "gender", "age",
        "diagnosis_year", "diagnosis_1", "clinical_info",
        "last_modified", "created_at",
    ]
    for field in required:
        assert field in body, f"Missing field: {field}"
