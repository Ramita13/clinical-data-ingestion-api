import asyncio
import hashlib
import io
import os
from functools import partial
from typing import Any

import pandas as pd

from app.schemas.sample import ALL_KNOWN_COLUMNS, COLUMN_ALIASES, CORE_COLUMNS, EXPECTED_COLUMNS

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
print("DEBUG: file_parser.py loaded — sep= fix active")


class FileValidationError(Exception):
    """Raised when the uploaded file cannot be accepted."""
    pass


def _compute_checksum(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _has_sep_directive(file_bytes: bytes) -> bool:
    """
    Returns True if the file starts with a sep= directive line.
    Excel adds this when saving UTF-8 CSV with a non-comma delimiter.
    Example first line: sep=;
    """
    first_line = file_bytes.decode("utf-8-sig").split("\n")[0].strip()
    return first_line.lower().startswith("sep=")


def _detect_csv_delimiter(file_bytes: bytes) -> str:
    """
    Detect whether a CSV uses comma, semicolon, or tab as delimiter.
    Reads the header line and counts which appears most.
    Handles BOM and sep= directive lines added by Excel.
    """
    lines = file_bytes.decode("utf-8-sig").split("\n")
    # Skip sep= directive line if present — use the actual header line
    header_line = lines[1] if lines[0].strip().lower().startswith("sep=") else lines[0]
    comma_count = header_line.count(",")
    semicolon_count = header_line.count(";")
    tab_count = header_line.count("\t")
    max_count = max(comma_count, semicolon_count, tab_count)
    if tab_count == max_count and tab_count > 0:
        return "\t"
    if semicolon_count == max_count and semicolon_count > 0:
        return ";"
    return ","


def _read_file_sync(file_bytes: bytes, extension: str) -> pd.DataFrame:
    """
    Synchronous pandas read — runs in a thread pool via run_in_executor.
    Handles:
    - Excel (.xlsx, .xls)
    - CSV with comma, semicolon, or tab delimiter
    - BOM character added by Excel when saving as UTF-8 CSV
    - sep= directive line added by Excel (e.g. sep=;)
    """
    buf = io.BytesIO(file_bytes)
    if extension == ".csv":
        delimiter = _detect_csv_delimiter(file_bytes)
        skiprows = 1 if _has_sep_directive(file_bytes) else 0
        print(f"DEBUG: delimiter={repr(delimiter)}, skiprows={skiprows}, first_line={repr(file_bytes.decode('utf-8-sig').split(chr(10))[0][:30])}")
        return pd.read_csv(
            buf,
            dtype=str,
            keep_default_na=False,
            sep=delimiter,
            encoding="utf-8-sig",
            skiprows=skiprows,
        )
    df = pd.read_excel(buf, dtype=str, keep_default_na=False)
    # Strip BOM from column names — Excel sometimes adds \ufeff to the first column
    df.columns = [c.lstrip('\ufeff') for c in df.columns]
    return df


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Apply COLUMN_ALIASES map so renamed columns are handled transparently."""
    return df.rename(columns=COLUMN_ALIASES)


def _validate_schema(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """
    Returns (missing_core_columns, missing_expected_columns).
    Caller raises FileValidationError if missing_core is non-empty.
    """
    present = set(df.columns)
    missing_core = sorted(CORE_COLUMNS - present)
    missing_expected = sorted(EXPECTED_COLUMNS - present)
    return missing_core, missing_expected


def _extract_extra_fields(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Splits a row dict into known fields and unknown (extra) fields.
    Unknown fields are preserved in extra_fields — never dropped.
    Empty string values in extra fields are treated as None and excluded
    so they do not trigger false change detection on re-upload.
    """
    known = {k: v for k, v in row.items() if k in ALL_KNOWN_COLUMNS}
    extra = {
        k: v for k, v in row.items()
        if k not in ALL_KNOWN_COLUMNS
        and v is not None
        and str(v).strip() not in ("", "nan")
    }
    return known, extra if extra else None


async def parse_upload(
    file_bytes: bytes,
    filename: str,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    """
    Validates and parses an uploaded file asynchronously.

    Returns:
        rows          — list of row dicts ready for Pydantic validation
        checksum      — MD5 hex of the raw file bytes
        missing_cols  — expected columns absent from this file (warnings only)

    Raises:
        FileValidationError — wrong extension, missing core columns, unreadable file
    """
    # 1. Extension check
    ext = os.path.splitext(filename)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # 2. Compute checksum
    checksum = _compute_checksum(file_bytes)

    # 3. Parse with pandas in a thread pool — keeps the event loop free
    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(None, partial(_read_file_sync, file_bytes, ext))
    except Exception as exc:
        raise FileValidationError(f"Could not parse file: {exc}") from exc

    if df.empty:
        raise FileValidationError("Uploaded file contains no rows.")

    # 4. Normalise column names (apply aliases)
    df = _normalise_columns(df)

    # 5. Schema validation
    missing_core, missing_expected = _validate_schema(df)
    if missing_core:
        raise FileValidationError(
            f"Required column(s) missing: {', '.join(missing_core)}"
        )

    # 6. Convert to list of dicts, split extra fields
    rows: list[dict[str, Any]] = []
    for raw_row in df.to_dict(orient="records"):
        known, extra = _extract_extra_fields(raw_row)
        if extra:
            known["extra_fields"] = extra
        rows.append(known)

    return rows, checksum, missing_expected
