"""Buff-preset endpoints — CRUD for saved stage-buff sets (issue #64, DESIGN §2.4).

A preset is a **client-side convenience**: applying one copies its buffs into the
request's ``custom_buffs``. No calculation endpoint resolves a preset id, so editing a
preset cannot retroactively change a result that was already computed with it — which is
the property that lets a user rewrite last patch's Deadly-Assault buffs without
invalidating anything they saved or screenshotted.

Every route goes through the owner-scoped repository, so one user's presets are neither
readable nor mutable by another.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.dependencies import get_owned_buff_preset_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.buff_preset import BuffPresetRepository
from app.schemas.buff_preset import BuffPresetCreate, BuffPresetRead, BuffPresetUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/buff-presets", tags=["buff-presets"])

_NOT_FOUND = "Buff preset not found"


@router.get("", response_model=PaginatedResponse[BuffPresetRead])
async def list_buff_presets(
    repo: Annotated[BuffPresetRepository, Depends(get_owned_buff_preset_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[BuffPresetRead]:
    """List the caller's saved stage-buff presets."""
    presets = await repo.get_all(offset=offset, limit=limit)
    total = await repo.count()
    return PaginatedResponse(
        items=[BuffPresetRead.model_validate(p) for p in presets],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=BuffPresetRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_buff_preset(
    request: Request,
    body: BuffPresetCreate,
    repo: Annotated[BuffPresetRepository, Depends(get_owned_buff_preset_repo)],
) -> BuffPresetRead:
    """Save a named set of stage buffs."""
    data = body.model_dump(mode="json")
    preset = await repo.create(data)
    return BuffPresetRead.model_validate(preset)


@router.get("/{preset_id}", response_model=BuffPresetRead)
async def get_buff_preset(
    preset_id: str,
    repo: Annotated[BuffPresetRepository, Depends(get_owned_buff_preset_repo)],
) -> BuffPresetRead:
    """Fetch a single preset by id."""
    preset = await repo.get_by_id(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return BuffPresetRead.model_validate(preset)


@router.patch("/{preset_id}", response_model=BuffPresetRead)
@limiter.limit(WRITE_LIMIT)
async def update_buff_preset(
    request: Request,
    preset_id: str,
    body: BuffPresetUpdate,
    repo: Annotated[BuffPresetRepository, Depends(get_owned_buff_preset_repo)],
) -> BuffPresetRead:
    """Partially update a preset's name or buff list.

    ``buffs`` is replaced wholesale rather than merged — the list is authored and applied
    as one unit, and a positional merge would need an id per buff that nothing else in
    this feature has.
    """
    data = body.model_dump(mode="json", exclude_unset=True)
    preset = await repo.update(preset_id, data)
    if preset is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return BuffPresetRead.model_validate(preset)


@router.delete("/{preset_id}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def delete_buff_preset(
    request: Request,
    preset_id: str,
    repo: Annotated[BuffPresetRepository, Depends(get_owned_buff_preset_repo)],
) -> None:
    """Delete a preset."""
    deleted = await repo.delete(preset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
