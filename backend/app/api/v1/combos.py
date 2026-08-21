"""Combo endpoints — CRUD for team attack sequences."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.dependencies import (
    get_owned_combo_repo,
)
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.build import ComboRepository
from app.schemas.build import ComboCreate, ComboRead, ComboUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/combos", tags=["combos"])


@router.get("", response_model=PaginatedResponse[ComboRead])
async def list_combos(
    repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
    team_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[ComboRead]:
    """List saved combos, optionally scoped to a single team."""
    if team_id:
        combos = await repo.get_by_team(team_id, offset=offset, limit=limit)
    else:
        combos = await repo.get_all(offset=offset, limit=limit)
    total = await repo.count()
    return PaginatedResponse(
        items=[ComboRead.model_validate(c) for c in combos],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=ComboRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_combo(
    request: Request,
    body: ComboCreate,
    repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
) -> ComboRead:
    """Create a combo — an ordered attack sequence for a team."""
    data = body.model_dump()
    if data.get("sequence"):
        data["sequence"] = [
            s.model_dump() if hasattr(s, "model_dump") else s for s in body.sequence
        ]
    combo = await repo.create(data)
    return ComboRead.model_validate(combo)


@router.get("/{combo_id}", response_model=ComboRead)
async def get_combo(
    combo_id: str,
    repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
) -> ComboRead:
    """Fetch a single combo by id."""
    combo = await repo.get_by_id(combo_id)
    if combo is None:
        raise HTTPException(status_code=404, detail="Combo not found")
    return ComboRead.model_validate(combo)


@router.patch("/{combo_id}", response_model=ComboRead)
@limiter.limit(WRITE_LIMIT)
async def update_combo(
    request: Request,
    combo_id: str,
    body: ComboUpdate,
    repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
) -> ComboRead:
    """Partially update a combo's name or attack sequence."""
    data = body.model_dump(exclude_unset=True)
    if "sequence" in data and data["sequence"] is not None:
        data["sequence"] = [
            s.model_dump() if hasattr(s, "model_dump") else s for s in body.sequence
        ]
    combo = await repo.update(combo_id, data)
    if combo is None:
        raise HTTPException(status_code=404, detail="Combo not found")
    return ComboRead.model_validate(combo)


@router.delete("/{combo_id}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def delete_combo(
    request: Request,
    combo_id: str,
    repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
) -> None:
    """Delete a combo."""
    deleted = await repo.delete(combo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Combo not found")
