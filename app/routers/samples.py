from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.sample import Sample
from app.schemas.sample import SampleOut

router = APIRouter(prefix="/samples", tags=["samples"])


@router.get("", response_model=list[SampleOut])
async def list_samples(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[SampleOut]:
    """Returns all current (latest) sample records, paginated."""
    result = await db.execute(
        select(Sample)
        .where(Sample.is_latest.is_(True))
        .order_by(Sample.last_modified.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/search/fulltext", response_model=list[SampleOut])
async def search_samples(
    q: str = Query(..., min_length=2),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[SampleOut]:
    """Full-text search across all clinical description fields via tsvector GIN index."""
    result = await db.execute(
        select(Sample)
        .where(
            Sample.is_latest.is_(True),
            func.to_tsvector("spanish", func.coalesce(Sample.search_vector, "")).op("@@")(
                func.plainto_tsquery("spanish", q)
            ),
        )
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/filter/query", response_model=list[SampleOut])
async def filter_samples(
    gender: str | None = Query(None, max_length=1),
    age_min: int | None = Query(None, ge=0),
    age_max: int | None = Query(None, le=130),
    diagnosis_year: int | None = Query(None),
    test_category: str | None = Query(None),
    diagnosis_1: str | None = Query(None, description="Filter by primary diagnosis (partial match)"),
    icd_code: str | None = Query(None, description="Filter by any ICD code (partial match)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[SampleOut]:
    """Filter latest records by demographic or clinical criteria."""
    query = select(Sample).where(Sample.is_latest.is_(True))

    if gender:
        query = query.where(Sample.gender == gender.upper())
    if age_min is not None:
        query = query.where(Sample.age >= age_min)
    if age_max is not None:
        query = query.where(Sample.age <= age_max)
    if diagnosis_year:
        query = query.where(Sample.diagnosis_year == diagnosis_year)
    if test_category:
        query = query.where(Sample.test_category.ilike(f"%{test_category}%"))
    if diagnosis_1:
        query = query.where(Sample.diagnosis_1.ilike(f"%{diagnosis_1}%"))
    if icd_code:
        query = query.where(
            (Sample.icd_code_1.ilike(f"%{icd_code}%")) |
            (Sample.icd_code_2.ilike(f"%{icd_code}%")) |
            (Sample.icd_code_3.ilike(f"%{icd_code}%")) |
            (Sample.icd_code_4.ilike(f"%{icd_code}%"))
        )

    query = query.order_by(Sample.last_modified.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{anonymized_sample_id}", response_model=SampleOut)
async def get_sample(
    anonymized_sample_id: str,
    db: AsyncSession = Depends(get_db),
) -> SampleOut:
    """Returns the current (latest) version of a sample."""
    result = await db.execute(
        select(Sample).where(
            Sample.anonymized_sample_id == anonymized_sample_id,
            Sample.is_latest.is_(True),
        )
    )
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample '{anonymized_sample_id}' not found.",
        )
    return sample


@router.get("/{anonymized_sample_id}/history", response_model=list[SampleOut])
async def get_sample_history(
    anonymized_sample_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[SampleOut]:
    """Returns all versions of a sample, oldest first."""
    result = await db.execute(
        select(Sample)
        .where(Sample.anonymized_sample_id == anonymized_sample_id)
        .order_by(Sample.version.asc())
    )
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample '{anonymized_sample_id}' not found.",
        )
    return rows


@router.get("/{anonymized_sample_id}/diff")
async def get_sample_diff(
    anonymized_sample_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Field-level diff between every consecutive version pair."""
    result = await db.execute(
        select(Sample)
        .where(Sample.anonymized_sample_id == anonymized_sample_id)
        .order_by(Sample.version.asc())
    )
    versions = result.scalars().all()
    if len(versions) < 2:
        return {"message": "Only one version exists — no diff available."}

    skip_fields = {
        "id", "version", "is_latest", "last_modified", "created_at",
        "ingestion_log_id", "search_vector"
    }
    diffs = []
    for prev, curr in zip(versions, versions[1:]):
        changed = {}
        for col in Sample.__table__.columns.keys():
            if col in skip_fields:
                continue
            old_val = getattr(prev, col)
            new_val = getattr(curr, col)
            if old_val != new_val:
                changed[col] = {"from": old_val, "to": new_val}
        diffs.append({
            "from_version": prev.version,
            "to_version": curr.version,
            "changed_at": curr.last_modified,
            "fields_changed": changed,
        })

    return {"anonymized_sample_id": anonymized_sample_id, "diffs": diffs}
