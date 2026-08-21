"""Disc Set endpoints — read-only, data is seeded from import."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_disc_set_repo
from app.repositories.disc import DiscSetRepository
from app.schemas.common import PaginatedResponse
from app.schemas.disc import DiscSetRead, DiscSetSummary

router = APIRouter(prefix="/disc-sets", tags=["disc-sets"])


@router.get("", response_model=PaginatedResponse[DiscSetSummary])
async def list_disc_sets(
    repo: Annotated[DiscSetRepository, Depends(get_disc_set_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[DiscSetSummary]:
    """List disc drive sets with their 2pc/4pc set-bonus summaries."""
    sets = await repo.get_all(offset=offset, limit=limit)
    total = await repo.count()
    return PaginatedResponse(
        items=[DiscSetSummary.model_validate(s) for s in sets],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{set_id}", response_model=DiscSetRead)
async def get_disc_set(
    set_id: str,
    repo: Annotated[DiscSetRepository, Depends(get_disc_set_repo)],
) -> DiscSetRead:
    """Fetch a single disc drive set by id, including full bonus text."""
    disc_set = await repo.get_by_id(set_id)
    if disc_set is None:
        raise HTTPException(status_code=404, detail="Disc set not found")
    return DiscSetRead.model_validate(disc_set)
