"""
Ingestion service — the heart of the upload pipeline.

Flow per file:
  1. Validate all rows with Pydantic (collect valid + rejected)
  2. For each valid row, check if anonymized_sample_id exists in DB
     a. Not found            -> insert as version 1
     b. Found, no changes    -> update last_modified only
     c. Found, data changed  -> mark old row is_latest=False, insert new version
                                capture which fields changed for the response
  3. Bulk insert valid rows in a single transaction
  4. Bulk insert rejected rows
  5. Return counts + versioned diffs
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rejected_row import RejectedRow
from app.models.sample import Sample
from app.schemas.sample import SampleRowIn, VersionedDiff, FieldChange
from app.core.logging import logger


def now_utc() -> datetime:
    """Current UTC time with no microseconds — clean for storage and display."""
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


# Fields excluded from change-detection and diff reporting
_IGNORED_IN_DIFF = {
    "last_modified", "created_at", "is_latest", "version",
    "id", "ingestion_log_id",
    # File provenance — from source pipeline, not clinical data
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


def _get_changed_fields(
    existing: Sample,
    incoming: SampleRowIn,
) -> dict[str, FieldChange]:
    """
    Returns a dict of field name -> FieldChange for every field that differs.
    Empty dict means no changes detected.
    """
    changed: dict[str, FieldChange] = {}
    incoming_dict = incoming.model_dump(by_alias=False)

    for field, new_val in incoming_dict.items():
        if field in _IGNORED_IN_DIFF:
            continue
        db_val = getattr(existing, field, None)

        norm_db  = _normalise(db_val)
        norm_new = _normalise(new_val)

        if norm_db != norm_new:
            changed[field] = FieldChange(
                from_value=norm_db,
                to_value=norm_new,
            )

    return changed


def _sample_from_schema(row: SampleRowIn, version: int, log_id: int) -> Sample:
    """Build a Sample ORM object from a validated Pydantic row."""
    data = row.model_dump(by_alias=False, exclude={"extra_fields"})
    return Sample(
        **data,
        version=version,
        is_latest=True,
        last_modified=now_utc(),
        ingestion_log_id=log_id,
        extra_fields=row.extra_fields,
    )


async def ingest_rows(
    db: AsyncSession,
    raw_rows: list[dict[str, Any]],
    ingestion_log_id: int,
) -> dict[str, Any]:
    """
    Main ingestion function. Validates, deduplicates, and persists rows.
    Returns counts dict with inserted, updated, versioned, rejected, versioned_diffs.
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
    # Step 2 — Fetch all existing latest records in one query
    # ------------------------------------------------------------------ #
    incoming_ids = [r.anonymized_sample_id for r in valid_rows]
    existing_map: dict[str, Sample] = {}

    if incoming_ids:
        result = await db.execute(
            select(Sample).where(
                Sample.anonymized_sample_id.in_(incoming_ids),
                Sample.is_latest.is_(True),
            )
        )
        for sample in result.scalars().all():
            existing_map[sample.anonymized_sample_id] = sample

    # ------------------------------------------------------------------ #
    # Step 3 — Classify each valid row: insert / update / version
    # ------------------------------------------------------------------ #
    to_insert: list[Sample] = []
    versioned_diffs: list[VersionedDiff] = []
    counts = {
        "inserted": 0,
        "updated": 0,
        "versioned": 0,
        "rejected": len(rejected_rows),
    }

    for row in valid_rows:
        sid = row.anonymized_sample_id
        existing = existing_map.get(sid)

        if existing is None:
            to_insert.append(_sample_from_schema(row, version=1, log_id=ingestion_log_id))
            counts["inserted"] += 1

        else:
            changed_fields = _get_changed_fields(existing, row)

            if not changed_fields:
                # Complete duplicate — update last_modified only
                await db.execute(
                    update(Sample)
                    .where(Sample.id == existing.id)
                    .values(last_modified=now)
                )
                counts["updated"] += 1

            else:
                # Data changed — retire old row, insert new version
                await db.execute(
                    update(Sample)
                    .where(Sample.id == existing.id)
                    .values(is_latest=False)
                )
                new_version = existing.version + 1
                to_insert.append(
                    _sample_from_schema(row, version=new_version, log_id=ingestion_log_id)
                )
                versioned_diffs.append(VersionedDiff(
                    anonymized_sample_id=sid,
                    old_version=existing.version,
                    new_version=new_version,
                    fields_changed=changed_fields,
                ))
                logger.info(
                    f"Versioned '{sid}': v{existing.version} -> v{new_version} "
                    f"| changed: {list(changed_fields.keys())}"
                )
                counts["versioned"] += 1

    # ------------------------------------------------------------------ #
    # Step 4 — Bulk insert
    # ------------------------------------------------------------------ #
    if to_insert:
        db.add_all(to_insert)
    if rejected_rows:
        db.add_all(rejected_rows)

    return {**counts, "versioned_diffs": versioned_diffs}
