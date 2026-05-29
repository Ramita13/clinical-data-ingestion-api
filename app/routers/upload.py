import time
from app.services.ingestion import now_utc

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.ingestion_log import IngestionLog
from app.models.raw_file import RawFile
from app.schemas.sample import UploadSummary
from app.services.ingestion import ingest_rows
from app.utils.file_parser import FileValidationError, parse_upload
from app.core.logging import logger

router = APIRouter(prefix="/upload", tags=["ingestion"])

MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 50 MB hard limit


@router.post(
    "/upload_data",
    response_model=UploadSummary,
    status_code=status.HTTP_200_OK,
    summary="Upload an Excel or CSV file of sample records",
)
async def upload_data(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> UploadSummary:
    """
    Accepts .xlsx, .xls, or .csv files.
    Validates structure, deduplicates by AnonymizedSampleID,
    and persists records — overwriting in place on change.
    Translation is queued as a background task after upload.
    """
    started_at = now_utc()
    start_ms = time.monotonic()

    # ------------------------------------------------------------------ #
    # 1. Read file bytes
    # ------------------------------------------------------------------ #
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum size of {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.",
        )

    # ------------------------------------------------------------------ #
    # 2. Parse and validate file structure (async — uses thread pool)
    # ------------------------------------------------------------------ #
    try:
        raw_rows, checksum, missing_expected_cols = await parse_upload(
            file_bytes=file_bytes,
            filename=file.filename or "unknown",
        )
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        f"File '{file.filename}' parsed: {len(raw_rows)} rows, checksum={checksum}"
    )
    if missing_expected_cols:
        logger.warning(f"Missing expected columns: {missing_expected_cols}")

    # ------------------------------------------------------------------ #
    # 3. Check for duplicate file (warning only — process anyway)
    # ------------------------------------------------------------------ #
    duplicate_file_warning = False
    existing_log = await db.execute(
        select(IngestionLog).where(IngestionLog.file_checksum == checksum).limit(1)
    )
    if existing_log.scalar_one_or_none():
        duplicate_file_warning = True
        logger.warning(f"Duplicate file checksum detected: {checksum} — processing anyway")

    # ------------------------------------------------------------------ #
    # 4. Record raw file in Bronze layer
    # ------------------------------------------------------------------ #
    raw_file = RawFile(
        file_name=file.filename or "unknown",
        file_size_bytes=len(file_bytes),
        file_checksum=checksum,
        checksum_algorithm="MD5",
        content_type=file.content_type,
        uploaded_at=started_at,
    )
    db.add(raw_file)
    await db.flush()

    # ------------------------------------------------------------------ #
    # 5. Create ingestion log entry
    # ------------------------------------------------------------------ #
    log_entry = IngestionLog(
        raw_file_id=raw_file.id,
        file_name=file.filename or "unknown",
        file_checksum=checksum,
        status="processing",
        rows_total=len(raw_rows),
        started_at=started_at,
    )
    db.add(log_entry)
    await db.flush()

    # ------------------------------------------------------------------ #
    # 6. Run ingestion
    # ------------------------------------------------------------------ #
    try:
        counts = await ingest_rows(
            db=db,
            raw_rows=raw_rows,
            ingestion_log_id=log_entry.id,
        )
    except Exception as exc:
        log_entry.status = "failed"
        log_entry.error_detail = str(exc)
        log_entry.completed_at = now_utc()
        await db.commit()
        logger.exception(f"Ingestion failed for '{file.filename}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingestion failed. The error has been logged.",
        )

    # ------------------------------------------------------------------ #
    # 7. Update ingestion log and commit
    # ------------------------------------------------------------------ #
    processing_ms = int((time.monotonic() - start_ms) * 1000)
    status_str = "success" if counts["rejected"] == 0 else "partial"

    log_entry.status = status_str
    log_entry.rows_inserted = counts["inserted"]
    log_entry.rows_updated = counts["updated"]
    log_entry.rows_versioned = 0  # versioning removed
    log_entry.rows_rejected = counts["rejected"]
    log_entry.completed_at = now_utc()
    log_entry.processing_ms = processing_ms

    await db.commit()

    logger.info(
        f"Upload complete in {processing_ms}ms — "
        f"inserted={counts['inserted']} updated={counts['updated']} "
        f"unchanged={counts['unchanged']} rejected={counts['rejected']}"
    )

    # ------------------------------------------------------------------ #
    # 8. Background translation task will be added in Step 4
    # For now translation_status reflects queued intent
    # ------------------------------------------------------------------ #

    return UploadSummary(
        file_name=file.filename or "unknown",
        rows_total=len(raw_rows),
        rows_inserted=counts["inserted"],
        rows_updated=counts["updated"],
        rows_unchanged=counts["unchanged"],
        rows_rejected=counts["rejected"],
        ingestion_log_id=log_entry.id,
        duplicate_file_warning=duplicate_file_warning,
        missing_expected_columns=missing_expected_cols,
        translation_status="queued",
    )
