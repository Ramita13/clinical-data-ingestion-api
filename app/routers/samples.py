from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, Text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.sample import Sample
from app.schemas.sample import SampleOut, SampleListResponse

router = APIRouter(prefix="/samples", tags=["samples"])


@router.get("", response_model=SampleListResponse)
async def list_samples(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> SampleListResponse:
    """Returns all sample records, paginated, most recently modified first."""
    total = await db.scalar(select(func.count()).select_from(Sample))

    result = await db.execute(
        select(Sample)
        .order_by(Sample.last_modified.desc())
        .offset(skip)
        .limit(limit)
    )
    records = result.scalars().all()

    return SampleListResponse(
        total=total or 0,
        count=len(records),
        records=records,
    )


@router.get("/search/fulltext", response_model=SampleListResponse)
async def search_samples(
    q: str = Query(..., min_length=2),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> SampleListResponse:
    """
    Full-text search across clinical description fields.
    Will be wired to translations table in Step 6.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Full-text search will be available after translation pipeline is complete.",
    )


@router.get("/filter/query", response_model=SampleListResponse)
async def filter_samples(
    gender: str | None = Query(None, max_length=1),
    age_min: int | None = Query(None, ge=0),
    age_max: int | None = Query(None, le=130),
    diagnosis_year: int | None = Query(None),
    test_category: str | None = Query(None),
    diagnosis_1: str | None = Query(None, description="Filter by primary diagnosis (partial match)"),
    icd_code: str | None = Query(None, description="Filter by any ICD code (partial match)"),
    location: str | None = Query(None, description="Filter by location (partial match across all location fields)"),
    diagnosis_any: str | None = Query(None, description="Filter by any diagnosis field including diagnosis_1 and diagnoses 2-12 (partial match)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> SampleListResponse:
    """Filter records by demographic or clinical criteria."""
    query = select(Sample)
    count_query = select(func.count()).select_from(Sample)

    if gender:
        f = Sample.gender == gender.upper()
        query = query.where(f)
        count_query = count_query.where(f)
    if age_min is not None:
        f = Sample.age >= age_min
        query = query.where(f)
        count_query = count_query.where(f)
    if age_max is not None:
        f = Sample.age <= age_max
        query = query.where(f)
        count_query = count_query.where(f)
    if diagnosis_year:
        f = Sample.diagnosis_year == diagnosis_year
        query = query.where(f)
        count_query = count_query.where(f)
    if test_category:
        f = Sample.test_category.ilike(f"%{test_category}%")
        query = query.where(f)
        count_query = count_query.where(f)
    if diagnosis_1:
        f = Sample.diagnosis_1.ilike(f"%{diagnosis_1}%")
        query = query.where(f)
        count_query = count_query.where(f)
    if icd_code:
        f = (
            (Sample.icd_code_1.ilike(f"%{icd_code}%")) |
            (Sample.icd_code_2.ilike(f"%{icd_code}%")) |
            (Sample.icd_code_3.ilike(f"%{icd_code}%")) |
            (Sample.icd_code_4.ilike(f"%{icd_code}%"))
        )
        query = query.where(f)
        count_query = count_query.where(f)

    if location:
        # Cast JSONB to text and do partial match across all location slots
        f = Sample.locations.cast(Text).ilike(f"%{location}%")
        query = query.where(f)
        count_query = count_query.where(f)
    if diagnosis_any:
        # Search diagnosis_1 (flat) AND diagnoses JSONB (2..12)
        f = (
            Sample.diagnosis_1.ilike(f"%{diagnosis_any}%") |
            Sample.diagnoses.cast(Text).ilike(f"%{diagnosis_any}%")
        )
        query = query.where(f)
        count_query = count_query.where(f)

    total = await db.scalar(count_query)
    query = query.order_by(Sample.last_modified.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    records = result.scalars().all()

    return SampleListResponse(
        total=total or 0,
        count=len(records),
        records=records,
    )


@router.get("/{anonymized_sample_id}", response_model=SampleOut)
async def get_sample(
    anonymized_sample_id: str,
    db: AsyncSession = Depends(get_db),
) -> SampleOut:
    """Returns the current record for a sample ID."""
    result = await db.execute(
        select(Sample).where(
            Sample.anonymized_sample_id == anonymized_sample_id
        )
    )
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample '{anonymized_sample_id}' not found.",
        )
    return sample
