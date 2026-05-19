from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


# ------------------------------------------------------------------ #
# Column aliases — maps old/variant column names to canonical names
# ------------------------------------------------------------------ #
COLUMN_ALIASES: dict[str, str] = {}

# Core columns — must be present or file is rejected
CORE_COLUMNS: set[str] = {"AnonymizedSampleID"}

# Expected columns — absence is a warning not a failure
EXPECTED_COLUMNS: set[str] = {
    "FileName", "TestCategory", "TestName", "Acquisition",
    "Gender", "Age", "DiagnosisYear",
    "ClinicalInfo1", "ClinicalInfo2", "ClinicalInfo3", "ClinicalInfo4",
    "ClinicalInfo5", "ClinicalInfo6", "ClinicalInfo7", "ClinicalInfo8",
    "ClinicalInfo9", "ClinicalInfo10", "ClinicalInfo11", "ClinicalInfo12",
    "MacroscopicDesc1", "MacroscopicDesc2", "MacroscopicDesc3", "MacroscopicDesc4",
    "MacroscopicDesc5", "MacroscopicDesc6", "MacroscopicDesc7", "MacroscopicDesc8",
    "MacroscopicDesc9", "MacroscopicDesc10", "MacroscopicDesc11", "MacroscopicDesc12",
    "MicroscopicDesc1", "MicroscopicDesc2", "MicroscopicDesc3", "MicroscopicDesc4",
    "MicroscopicDesc5", "MicroscopicDesc6", "MicroscopicDesc7", "MicroscopicDesc8",
    "MicroscopicDesc9", "MicroscopicDesc10", "MicroscopicDesc11", "MicroscopicDesc12",
    "AdditionalTechniques",
    "Diagnosis1", "Diagnosis2", "Diagnosis3", "Diagnosis4",
    "Diagnosis5", "Diagnosis6", "Diagnosis7", "Diagnosis8",
    "Diagnosis9", "Diagnosis10", "Diagnosis11", "Diagnosis12",
    "TopographicCode1", "TopographicCode2", "TopographicCode3", "TopographicCode4",
    "Location1", "Location2", "Location3", "Location4",
    "IcdCode1", "IcdCode2", "IcdCode3", "IcdCode4",
    "AdditionalReport", "ChecksumAlgorithm", "FileChecksum",
    "FileSizeBytes", "UploadDateTime", "StorageName", "BucketName",
}

ALL_KNOWN_COLUMNS: set[str] = CORE_COLUMNS | EXPECTED_COLUMNS


def _opt_str(v: Any) -> str | None:
    """Convert NaN / empty strings to None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _opt_int(v: Any) -> int | None:
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _build_jsonb_group(data: dict[str, Any], prefix: str, count: int) -> dict | None:
    """
    Collects numbered fields into a compact JSONB dict.
    Only stores non-empty values — nulls are implicit by absence.

    Example: prefix="ClinicalInfo", count=12
    Reads ClinicalInfo1..ClinicalInfo12 from data dict.
    Returns {"1": "text", "3": "other text"} — skipping empty slots.
    Returns None if all slots are empty.
    """
    result = {}
    for i in range(1, count + 1):
        val = _opt_str(data.get(f"{prefix}{i}"))
        if val is not None:
            result[str(i)] = val
    return result if result else None


class SampleRowIn(BaseModel):
    """
    Validates one row from the uploaded Excel/CSV.
    Groups sparse numbered fields into JSONB dicts.
    Invalid rows are routed to rejected_rows, not inserted.
    """
    # Identity — required
    anonymized_sample_id: str = Field(alias="AnonymizedSampleID")

    # Identity — optional
    file_name: str | None = Field(None, alias="FileName")
    test_category: str | None = Field(None, alias="TestCategory")
    test_name: str | None = Field(None, alias="TestName")
    acquisition: str | None = Field(None, alias="Acquisition")

    # Demographics
    gender: str | None = Field(None, alias="Gender", max_length=1)
    age: int | None = Field(None, alias="Age", ge=0, le=130)
    diagnosis_year: int | None = Field(None, alias="DiagnosisYear", ge=1900, le=2100)

    # JSONB groups — built in model_validator from raw row data
    clinical_info: dict | None = None
    macroscopic_desc: dict | None = None
    microscopic_desc: dict | None = None

    # Diagnoses
    additional_techniques: str | None = Field(None, alias="AdditionalTechniques")
    diagnosis_1: str | None = Field(None, alias="Diagnosis1")
    diagnoses: dict | None = None       # Diagnosis2..12 grouped

    # Codes and locations — JSONB groups
    topographic_codes: dict | None = None
    locations: dict | None = None

    # ICD codes — kept flat
    icd_code_1: str | None = Field(None, alias="IcdCode1")
    icd_code_2: str | None = Field(None, alias="IcdCode2")
    icd_code_3: str | None = Field(None, alias="IcdCode3")
    icd_code_4: str | None = Field(None, alias="IcdCode4")

    # Provenance
    additional_report: str | None = Field(None, alias="AdditionalReport")
    checksum_algorithm: str | None = Field(None, alias="ChecksumAlgorithm")
    file_checksum: str | None = Field(None, alias="FileChecksum")
    file_size_bytes: int | None = Field(None, alias="FileSizeBytes")
    upload_date_time: datetime | None = Field(None, alias="UploadDateTime")
    storage_name: str | None = Field(None, alias="StorageName")
    bucket_name: str | None = Field(None, alias="BucketName")

    # Unexpected columns
    extra_fields: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}

    @field_validator("anonymized_sample_id", mode="before")
    @classmethod
    def id_must_not_be_blank(cls, v: Any) -> str:
        s = _opt_str(v)
        if not s:
            raise ValueError("AnonymizedSampleID cannot be blank or null")
        return s

    @field_validator(
        "file_name", "test_category", "test_name", "acquisition",
        "additional_techniques", "additional_report", "diagnosis_1",
        "checksum_algorithm", "file_checksum", "storage_name", "bucket_name",
        mode="before",
    )
    @classmethod
    def clean_optional_str(cls, v: Any) -> str | None:
        return _opt_str(v)

    @field_validator("icd_code_1", "icd_code_2", "icd_code_3", "icd_code_4", mode="before")
    @classmethod
    def clean_icd_codes(cls, v: Any) -> str | None:
        return _opt_str(v)

    @field_validator("age", "file_size_bytes", mode="before")
    @classmethod
    def clean_optional_int(cls, v: Any) -> int | None:
        return _opt_int(v)

    @field_validator("diagnosis_year", mode="before")
    @classmethod
    def clean_diagnosis_year(cls, v: Any) -> int | None:
        return _opt_int(v)

    @field_validator("gender", mode="before")
    @classmethod
    def clean_gender(cls, v: Any) -> str | None:
        s = _opt_str(v)
        if s is None:
            return None
        return s[0].upper() if s else None

    @field_validator("upload_date_time", mode="before")
    @classmethod
    def clean_upload_datetime(cls, v: Any) -> datetime | None:
        if v is None or (isinstance(v, float) and str(v) == "nan"):
            return None
        if isinstance(v, datetime):
            return v
        try:
            import pandas as pd
            return pd.to_datetime(v, dayfirst=False, format="mixed").to_pydatetime()
        except Exception:
            return None

    @model_validator(mode="before")
    @classmethod
    def build_jsonb_groups(cls, data: Any) -> Any:
        """
        Runs before field validation. Reads all numbered Excel columns
        and groups them into compact JSONB dicts — only non-empty values kept.
        """
        if not isinstance(data, dict):
            return data

        data["clinical_info"] = _build_jsonb_group(data, "ClinicalInfo", 12)
        data["macroscopic_desc"] = _build_jsonb_group(data, "MacroscopicDesc", 12)
        data["microscopic_desc"] = _build_jsonb_group(data, "MicroscopicDesc", 12)

        # Diagnosis2..12 grouped — Diagnosis1 stays flat
        diagnoses = {}
        for i in range(2, 13):
            val = _opt_str(data.get(f"Diagnosis{i}"))
            if val is not None:
                diagnoses[str(i)] = val
        data["diagnoses"] = diagnoses if diagnoses else None

        # TopographicCode1..4 grouped
        data["topographic_codes"] = _build_jsonb_group(data, "TopographicCode", 4)

        # Location1..4 grouped
        data["locations"] = _build_jsonb_group(data, "Location", 4)

        return data


# ------------------------------------------------------------------ #
# Response schemas
# ------------------------------------------------------------------ #

class UploadSummary(BaseModel):
    file_name: str
    rows_total: int
    rows_inserted: int
    rows_updated: int
    rows_unchanged: int
    rows_rejected: int
    ingestion_log_id: int
    duplicate_file_warning: bool = False
    missing_expected_columns: list[str] = []
    translation_status: str = "queued"


class SampleOut(BaseModel):
    id: int
    last_modified: datetime
    created_at: datetime
    anonymized_sample_id: str
    file_name: str | None
    test_category: str | None
    test_name: str | None
    acquisition: str | None
    gender: str | None
    age: int | None
    diagnosis_year: int | None
    clinical_info: dict | None
    macroscopic_desc: dict | None
    microscopic_desc: dict | None
    additional_techniques: str | None
    diagnosis_1: str | None
    diagnoses: dict | None
    topographic_codes: dict | None
    locations: dict | None
    icd_code_1: str | None
    icd_code_2: str | None
    icd_code_3: str | None
    icd_code_4: str | None
    additional_report: str | None
    extra_fields: dict | None

    model_config = {"from_attributes": True}
