"""
Ingestion service.

Flow per file:
  1. Validate all rows with Pydantic (collect valid + rejected)
  2. Fetch all existing records for incoming IDs in one query
  3. For each valid row:
     a. Not found            -> INSERT new row
     b. Found, no changes    -> update last_modified only (skip translation)
     c. Found, data changed  -> UPDATE in place, update last_modified
  4. Bulk insert new rows + rejected rows in one transaction
  5. Return counts + IDs that need translation (inserted + updated only)
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rejected_row import RejectedRow
from app.models.sample import Sample
from app.schemas.sample import SampleRowIn
from app.core.logging import logger


def now_utc() -> datetime:
    """Current UTC time with no microseconds — clean for storage and display."""
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


# Fields excluded from change detection
_IGNORED_IN_COMPARE = {
    "last_modified", "created_at", "id", "ingestion_log_id",
    "upload_date_time", "file_checksum", "file_size_bytes",
    "storage_name", "bucket_name", "checksum_algorithm",
}


def _normalise(val: Any) -> Any:
    """
    Normalise a value for comparison:
    - Empty strings -> None
    - Empty dicts -> None
    - Timezone-naive datetimes -> UTC timezone-aware
    - Strip microseconds for consistent comparison
    """
    if val is None or val == "" or val == {}:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).replace(microsecond=0)
    return val


def _has_changed(existing: Sample, incoming: SampleRowIn) -> bool:
    """
    Returns True if any clinical data field differs between
    the existing DB row and the incoming validated row.
    """
    incoming_dict = incoming.model_dump(by_alias=False)
    for field, new_val in incoming_dict.items():
        if field in _IGNORED_IN_COMPARE:
            continue
        db_val = getattr(existing, field, None)
        if _normalise(db_val) != _normalise(new_val):
            logger.debug(f"Field '{field}' changed: {_normalise(db_val)!r} -> {_normalise(new_val)!r}")
            return True
    return False


def _build_sample(row: SampleRowIn, log_id: int) -> Sample:
    """Build a new Sample ORM object from a validated Pydantic row."""
    data = row.model_dump(by_alias=False, exclude={"extra_fields"})
    return Sample(
        **data,
        last_modified=now_utc(),
        ingestion_log_id=log_id,
        extra_fields=row.extra_fields,
    )


def _update_values(row: SampleRowIn, log_id: int) -> dict[str, Any]:
    """Build the dict of values for an UPDATE statement."""
    data = row.model_dump(by_alias=False, exclude={"extra_fields"})
    return {
        **data,
        "extra_fields": row.extra_fields,
        "last_modified": now_utc(),
        "ingestion_log_id": log_id,
    }


async def ingest_rows(
    db: AsyncSession,
    raw_rows: list[dict[str, Any]],
    ingestion_log_id: int,
) -> dict[str, Any]:
    """
    Main ingestion function. Validates, deduplicates, persists rows.

    Returns:
        counts:              inserted, updated, unchanged, rejected
        inserted_ids:        anonymized_sample_ids of new rows (need translation)
        updated_ids:         anonymized_sample_ids of changed rows (need retranslation)
        unchanged_ids:       anonymized_sample_ids of complete duplicates (skip translation)
    """
    now = now_utc()

    # ------------------------------------------------------------------ #
    # Step 1 — Validate all rows with Pydantic first
    # ------------------------------------------------------------------ #
    valid_rows: list[SampleRowIn] = []
    rejected_rows: list[RejectedRow] = []

    for i, raw in enumerate(raw_rows, start=1):
        try:
            validated = SampleRowIn.model_validate(raw, by_alias=True)
            valid_rows.append(validated)
        except ValidationError as exc:
            reason = "; ".join(
                f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            rejected_rows.append(
                RejectedRow(
                    ingestion_log_id=ingestion_log_id,
                    row_number=i,
                    raw_data={k: str(v) for k, v in raw.items()},
                    rejection_reason=reason,
                    rejected_at=now,
                )
            )
            logger.warning(f"Row {i} rejected: {reason}")

    # ------------------------------------------------------------------ #
    # Step 2 — Fetch all existing records for incoming IDs in one query
    # ------------------------------------------------------------------ #
    incoming_ids = [r.anonymized_sample_id for r in valid_rows]
    existing_map: dict[str, Sample] = {}

    # Fetch existing records in chunks to avoid PostgreSQL parameter limit
    # IN clause with thousands of IDs hits the 65,535 parameter limit
    ID_CHUNK_SIZE = 1000
    if incoming_ids:
        for i in range(0, len(incoming_ids), ID_CHUNK_SIZE):
            id_chunk = incoming_ids[i:i + ID_CHUNK_SIZE]
            result = await db.execute(
                select(Sample).where(
                    Sample.anonymized_sample_id.in_(id_chunk)
                )
            )
            for sample in result.scalars().all():
                existing_map[sample.anonymized_sample_id] = sample

    # ------------------------------------------------------------------ #
    # Step 3 — Classify and process each valid row
    # ------------------------------------------------------------------ #
    to_insert: list[Sample] = []
    inserted_ids: list[str] = []
    updated_ids: list[str] = []
    unchanged_ids: list[str] = []

    counts = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": len(rejected_rows),
    }

    for row in valid_rows:
        sid = row.anonymized_sample_id
        existing = existing_map.get(sid)

        if existing is None:
            # New record — insert
            to_insert.append(_build_sample(row, log_id=ingestion_log_id))
            inserted_ids.append(sid)
            counts["inserted"] += 1

        elif _has_changed(existing, row):
            # Data changed — update in place
            await db.execute(
                update(Sample)
                .where(Sample.anonymized_sample_id == sid)
                .values(**_update_values(row, log_id=ingestion_log_id))
            )
            updated_ids.append(sid)
            counts["updated"] += 1
            logger.info(f"Updated '{sid}' — content changed")

        else:
            # Complete duplicate — update last_modified only, skip translation
            await db.execute(
                update(Sample)
                .where(Sample.anonymized_sample_id == sid)
                .values(last_modified=now, ingestion_log_id=ingestion_log_id)
            )
            unchanged_ids.append(sid)
            counts["unchanged"] += 1

    # ------------------------------------------------------------------ #
    # Step 4 — Bulk insert new rows + rejected rows in chunks
    # PostgreSQL has a hard limit of 65,535 parameters per query.
    # Each row has ~22 columns so max safe batch = 500 rows (500 * 22 = 11,000 params).
    # ------------------------------------------------------------------ #
    BATCH_SIZE = 500

    if to_insert:
        for i in range(0, len(to_insert), BATCH_SIZE):
            chunk = to_insert[i:i + BATCH_SIZE]
            db.add_all(chunk)
            await db.flush()   # sends this chunk to DB, clears SQLAlchemy identity map
            logger.info(f"Inserted batch {i // BATCH_SIZE + 1} of {-(-len(to_insert) // BATCH_SIZE)} ({len(chunk)} rows)")

    if rejected_rows:
        for i in range(0, len(rejected_rows), BATCH_SIZE):
            chunk = rejected_rows[i:i + BATCH_SIZE]
            db.add_all(chunk)
            await db.flush()

    return {
        **counts,
        "inserted_ids": inserted_ids,
        "updated_ids": updated_ids,
        "unchanged_ids": unchanged_ids,
    }
