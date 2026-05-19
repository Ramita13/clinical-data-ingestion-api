"""
test_schemas.py — unit tests for app/schemas/sample.py

Tests Pydantic validation logic on SampleRowIn.
No database, no HTTP — pure validation logic.
"""

import pytest
from pydantic import ValidationError

from app.schemas.sample import SampleRowIn, UploadSummary


# ------------------------------------------------------------------ #
# Base valid row — used as starting point for most tests
# ------------------------------------------------------------------ #
VALID = {
    "AnonymizedSampleID": "test_sample_001",
    "FileName": "slide_test.ndpi",
    "Gender": "M",
    "Age": "45",
    "DiagnosisYear": "2024",
    "ClinicalInfo1": "Se solicita revisión de biopsia.",
    "ClinicalInfo2": "Segunda información clínica.",
    "MacroscopicDesc1": "Un bloque de parafina.",
    "MicroscopicDesc1": "Fragmentos de ganglio linfático.",
    "Diagnosis1": "Ganglio linfático: linfoma T.",
    "Diagnosis2": "Médula ósea: infiltración.",
    "TopographicCode1": "T08000",
    "TopographicCode2": "T06000",
    "Location1": "GANGLIO LINFATICO",
    "Location2": "MEDULA OSEA",
    "IcdCode1": "M97053",
    "IcdCode2": "M96952",
    "ChecksumAlgorithm": "MD5",
    "FileChecksum": "abc123def456abc123def456abc12345",
    "FileSizeBytes": "555735588",
    "UploadDateTime": "11/12/2025 16:47",
    "StorageName": "Hetzner-Primary",
    "BucketName": "histofy1",
}


def _make(**overrides) -> dict:
    """Returns VALID row with any overrides applied."""
    row = VALID.copy()
    row.update(overrides)
    return row


def _remove(key: str) -> dict:
    """Returns VALID row with a key removed."""
    row = VALID.copy()
    del row[key]
    return row


# ------------------------------------------------------------------ #
# Valid row passes
# ------------------------------------------------------------------ #
def test_valid_row_passes():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.anonymized_sample_id == "test_sample_001"
    assert result.gender == "M"
    assert result.age == 45
    assert result.diagnosis_year == 2024


# ------------------------------------------------------------------ #
# AnonymizedSampleID validation
# ------------------------------------------------------------------ #
def test_blank_id_rejected():
    with pytest.raises(ValidationError) as exc_info:
        SampleRowIn.model_validate(_make(AnonymizedSampleID=""), by_alias=True)
    assert "AnonymizedSampleID" in str(exc_info.value) or "anonymized_sample_id" in str(exc_info.value)


def test_whitespace_only_id_rejected():
    with pytest.raises(ValidationError):
        SampleRowIn.model_validate(_make(AnonymizedSampleID="   "), by_alias=True)


def test_nan_id_rejected():
    with pytest.raises(ValidationError):
        SampleRowIn.model_validate(_make(AnonymizedSampleID="nan"), by_alias=True)


def test_valid_hash_id_accepted():
    result = SampleRowIn.model_validate(
        _make(AnonymizedSampleID="2dd52fe04a4792774181aea28ac3a485.A.1.2"),
        by_alias=True
    )
    assert result.anonymized_sample_id == "2dd52fe04a4792774181aea28ac3a485.A.1.2"


# ------------------------------------------------------------------ #
# Age validation
# ------------------------------------------------------------------ #
def test_age_above_130_rejected():
    with pytest.raises(ValidationError) as exc_info:
        SampleRowIn.model_validate(_make(Age="131"), by_alias=True)
    assert "age" in str(exc_info.value).lower()


def test_age_999_rejected():
    with pytest.raises(ValidationError):
        SampleRowIn.model_validate(_make(Age="999"), by_alias=True)


def test_age_negative_rejected():
    with pytest.raises(ValidationError):
        SampleRowIn.model_validate(_make(Age="-1"), by_alias=True)


def test_age_0_accepted():
    result = SampleRowIn.model_validate(_make(Age="0"), by_alias=True)
    assert result.age == 0


def test_age_130_accepted():
    result = SampleRowIn.model_validate(_make(Age="130"), by_alias=True)
    assert result.age == 130


def test_age_none_accepted():
    result = SampleRowIn.model_validate(_remove("Age"), by_alias=True)
    assert result.age is None


def test_age_empty_string_becomes_none():
    result = SampleRowIn.model_validate(_make(Age=""), by_alias=True)
    assert result.age is None


def test_age_nan_becomes_none():
    result = SampleRowIn.model_validate(_make(Age="nan"), by_alias=True)
    assert result.age is None


def test_age_string_coerced_to_int():
    result = SampleRowIn.model_validate(_make(Age="45"), by_alias=True)
    assert result.age == 45
    assert isinstance(result.age, int)


# ------------------------------------------------------------------ #
# DiagnosisYear validation
# ------------------------------------------------------------------ #
def test_year_below_1900_rejected():
    with pytest.raises(ValidationError) as exc_info:
        SampleRowIn.model_validate(_make(DiagnosisYear="1750"), by_alias=True)
    error_str = str(exc_info.value).lower()
    assert "diagnosisyear" in error_str or "diagnosis_year" in error_str or "1900" in error_str


def test_year_above_2100_rejected():
    with pytest.raises(ValidationError):
        SampleRowIn.model_validate(_make(DiagnosisYear="2101"), by_alias=True)


def test_year_1900_accepted():
    result = SampleRowIn.model_validate(_make(DiagnosisYear="1900"), by_alias=True)
    assert result.diagnosis_year == 1900


def test_year_2100_accepted():
    result = SampleRowIn.model_validate(_make(DiagnosisYear="2100"), by_alias=True)
    assert result.diagnosis_year == 2100


def test_year_none_accepted():
    result = SampleRowIn.model_validate(_remove("DiagnosisYear"), by_alias=True)
    assert result.diagnosis_year is None


# ------------------------------------------------------------------ #
# Gender normalisation
# ------------------------------------------------------------------ #
def test_gender_lowercase_normalised_to_upper():
    result = SampleRowIn.model_validate(_make(Gender="m"), by_alias=True)
    assert result.gender == "M"


def test_gender_f_accepted():
    result = SampleRowIn.model_validate(_make(Gender="F"), by_alias=True)
    assert result.gender == "F"


def test_gender_empty_becomes_none():
    result = SampleRowIn.model_validate(_make(Gender=""), by_alias=True)
    assert result.gender is None


def test_gender_nan_becomes_none():
    result = SampleRowIn.model_validate(_make(Gender="nan"), by_alias=True)
    assert result.gender is None


def test_gender_long_string_takes_first_char():
    result = SampleRowIn.model_validate(_make(Gender="Male"), by_alias=True)
    assert result.gender == "M"


# ------------------------------------------------------------------ #
# Empty string / NaN cleaning for text fields
# ------------------------------------------------------------------ #
def test_empty_string_diagnosis_becomes_none():
    result = SampleRowIn.model_validate(_make(Diagnosis1=""), by_alias=True)
    assert result.diagnosis_1 is None


def test_nan_diagnosis_becomes_none():
    result = SampleRowIn.model_validate(_make(Diagnosis1="nan"), by_alias=True)
    assert result.diagnosis_1 is None


def test_whitespace_filename_becomes_none():
    result = SampleRowIn.model_validate(_make(FileName="   "), by_alias=True)
    assert result.file_name is None


# ------------------------------------------------------------------ #
# JSONB grouping — clinical_info
# ------------------------------------------------------------------ #
def test_clinical_info_grouped_correctly():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.clinical_info == {
        "1": "Se solicita revisión de biopsia.",
        "2": "Segunda información clínica.",
    }


def test_clinical_info_none_when_all_empty():
    row = _make(ClinicalInfo1="", ClinicalInfo2="")
    result = SampleRowIn.model_validate(row, by_alias=True)
    assert result.clinical_info is None


def test_clinical_info_sparse_slots():
    """Only non-empty slots should appear in the JSONB dict."""
    row = _make(ClinicalInfo1="First", ClinicalInfo2="", ClinicalInfo3="Third")
    result = SampleRowIn.model_validate(row, by_alias=True)
    assert result.clinical_info == {"1": "First", "3": "Third"}
    assert "2" not in result.clinical_info


# ------------------------------------------------------------------ #
# JSONB grouping — diagnoses
# ------------------------------------------------------------------ #
def test_diagnosis_1_stays_flat():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.diagnosis_1 == "Ganglio linfático: linfoma T."


def test_diagnoses_2_plus_grouped():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.diagnoses == {"2": "Médula ósea: infiltración."}


def test_diagnoses_none_when_all_empty():
    row = _make(Diagnosis2="", Diagnosis3="")
    result = SampleRowIn.model_validate(row, by_alias=True)
    assert result.diagnoses is None


def test_multiple_diagnoses_grouped():
    row = _make(
        Diagnosis2="Second diagnosis",
        Diagnosis3="Third diagnosis",
        Diagnosis4="Fourth diagnosis",
    )
    result = SampleRowIn.model_validate(row, by_alias=True)
    assert result.diagnoses == {
        "2": "Second diagnosis",
        "3": "Third diagnosis",
        "4": "Fourth diagnosis",
    }


# ------------------------------------------------------------------ #
# JSONB grouping — topographic codes and locations
# ------------------------------------------------------------------ #
def test_topographic_codes_grouped():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.topographic_codes == {"1": "T08000", "2": "T06000"}


def test_locations_grouped():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.locations == {"1": "GANGLIO LINFATICO", "2": "MEDULA OSEA"}


# ------------------------------------------------------------------ #
# ICD codes — kept flat
# ------------------------------------------------------------------ #
def test_icd_codes_stay_flat():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.icd_code_1 == "M97053"
    assert result.icd_code_2 == "M96952"
    assert result.icd_code_3 is None
    assert result.icd_code_4 is None


# ------------------------------------------------------------------ #
# File size
# ------------------------------------------------------------------ #
def test_file_size_coerced_to_int():
    result = SampleRowIn.model_validate(VALID, by_alias=True)
    assert result.file_size_bytes == 555735588
    assert isinstance(result.file_size_bytes, int)


def test_file_size_empty_becomes_none():
    result = SampleRowIn.model_validate(_make(FileSizeBytes=""), by_alias=True)
    assert result.file_size_bytes is None


# ------------------------------------------------------------------ #
# UploadSummary response schema
# ------------------------------------------------------------------ #
def test_upload_summary_defaults():
    summary = UploadSummary(
        file_name="test.xlsx",
        rows_total=10,
        rows_inserted=8,
        rows_updated=1,
        rows_unchanged=1,
        rows_rejected=0,
        ingestion_log_id=1,
    )
    assert summary.duplicate_file_warning is False
    assert summary.missing_expected_columns == []
    assert summary.translation_status == "queued"


def test_upload_summary_with_warning():
    summary = UploadSummary(
        file_name="test.xlsx",
        rows_total=5,
        rows_inserted=0,
        rows_updated=5,
        rows_unchanged=0,
        rows_rejected=0,
        ingestion_log_id=2,
        duplicate_file_warning=True,
        missing_expected_columns=["TestCategory", "TestName"],
    )
    assert summary.duplicate_file_warning is True
    assert "TestCategory" in summary.missing_expected_columns
