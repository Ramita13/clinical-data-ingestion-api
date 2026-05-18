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
    """Returns all sample records, paginated, most recently modified first."""
    result = await db.execute(
        select(Sample)
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
    """
    Full-text search across clinical description fields.
    Queries sample_translations.search_vector (English).
    Will be wired to translations table in Step 6.
    """
    # Placeholder until sample_translations is built in Step 6
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Full-text search will be available after translation pipeline is complete.",
    )


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
    """Filter records by demographic or clinical criteria."""
    query = select(Sample)

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
