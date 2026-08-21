"""W-Engine endpoints — read-only, data is seeded from import."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_w_engine_repo
from app.repositories.w_engine import WEngineRepository
from app.schemas.common import PaginatedResponse
from app.schemas.w_engine import WEngineRead, WEngineSummary

router = APIRouter(prefix="/w-engines", tags=["w-engines"])


@router.get("", response_model=PaginatedResponse[WEngineSummary])
async def list_w_engines(
    repo: Annotated[WEngineRepository, Depends(get_w_engine_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    specialty: str | None = None,
    rarity: str | None = None,
) -> PaginatedResponse[WEngineSummary]:
    """List W-Engines, optionally filtered by specialty or rarity."""
    engines = await repo.get_all(
        offset=offset,
        limit=limit,
        specialty=specialty,
        rarity=rarity,
    )
    total = await repo.count(specialty=specialty, rarity=rarity)
    return PaginatedResponse(
        items=[WEngineSummary.model_validate(e) for e in engines],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{engine_id}", response_model=WEngineRead)
async def get_w_engine(
    engine_id: str,
    repo: Annotated[WEngineRepository, Depends(get_w_engine_repo)],
) -> WEngineRead:
    """Fetch a single W-Engine by id, including passive details."""
    engine = await repo.get_by_id(engine_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="W-Engine not found")
    return WEngineRead.model_validate(engine)
