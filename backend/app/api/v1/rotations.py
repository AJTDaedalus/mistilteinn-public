"""User-authored rotations, and compiling one to a gcsim action list.

`DESIGN_rotation.md`. The write path's job is to make a rotation that cannot compile
impossible to save in the first place — a step naming an action gcsim does not have, or a
character the team does not hold, is refused here rather than discovered later at the point
of simulation, far from the edit that caused it.

`POST /{id}/compile` exists so a user can **see what their rotation became**. gcsim's config
is a build artifact, not a format this repo reads back, but a compiler nobody can inspect is
a compiler nobody can check — and the owner's whole complaint was about a syntax that hides
what it is doing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import get_owned_rotation_repo, get_owned_team_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.rotation import Rotation
from app.repositories.rotation import RotationRepository
from app.repositories.team import TeamRepository
from app.schemas.common import PaginatedResponse
from app.schemas.rotation import (
    RotationCreate,
    RotationRead,
    RotationUpdate,
)
from app.services.rotation_compiler import RotationCompileError, compile_rotation

router = APIRouter(prefix="/rotations", tags=["rotations"])

_Repo = Annotated[RotationRepository, Depends(get_owned_rotation_repo)]
_Teams = Annotated[TeamRepository, Depends(get_owned_team_repo)]
_Offset = Annotated[int, Query(ge=0)]
_Limit = Annotated[int, Query(ge=1, le=200)]


async def _require(repo: RotationRepository, rotation_id: str) -> Rotation:
    rotation = await repo.get_by_id(rotation_id)
    if rotation is None:
        raise HTTPException(status_code=404, detail=f"No rotation {rotation_id!r}")
    return rotation


async def _check_steps_against_team(
    repo: RotationRepository, team_id: str, steps: list,
) -> None:
    """Refuse a step naming a character the team does not hold.

    Checked on **write**, not only at compile time. A rotation that cannot compile is not a
    rotation, and letting one be saved moves the error to whenever someone next simulates —
    which is both later and further from the edit that caused it.
    """
    if not steps:
        return
    on_team = await repo.team_characters(team_id)
    if not on_team:
        # Reachable only for a team that exists and holds no builds — both callers have
        # already established the team is there — so this is 422, not 404.
        raise HTTPException(
            status_code=422,
            detail=(
                f"team {team_id!r} has no builds yet. A rotation's steps are validated "
                f"against its team, so there is nothing to validate them against."
            ),
        )
    unknown = sorted(
        {str(step.character) for step in steps if str(step.character) not in on_team},
    )
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"these characters are not on that team: {unknown}. The team has "
                f"{sorted(on_team)}. A step naming someone who is not there cannot be "
                f"simulated, so it is refused now rather than at compile time."
            ),
        )


@router.get("", response_model=PaginatedResponse[RotationRead])
async def list_rotations(
    repo: _Repo, team_id: str | None = None, offset: _Offset = 0, limit: _Limit = 50,
) -> PaginatedResponse[RotationRead]:
    """The caller's rotations, optionally just one team's."""
    if team_id is not None:
        rows = await repo.list_for_team(team_id, offset=offset, limit=limit)
        return PaginatedResponse(
            items=[RotationRead.model_validate(r) for r in rows],
            total=await repo.count_for_team(team_id), offset=offset, limit=limit,
        )
    rows = await repo.get_all(offset=offset, limit=limit)
    return PaginatedResponse(
        items=[RotationRead.model_validate(r) for r in rows],
        total=await repo.count(), offset=offset, limit=limit,
    )


@router.post("", response_model=RotationRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_rotation(
    request: Request,  # slowapi reads the client address off it
    body: RotationCreate,
    repo: _Repo,
    teams: _Teams,
) -> RotationRead:
    """Save a rotation, having checked every step against its team."""
    if await teams.get_by_id(body.team_id) is None:
        raise HTTPException(status_code=404, detail=f"No team {body.team_id!r}")
    await _check_steps_against_team(repo, body.team_id, body.steps)

    created = await repo.create({
        "team_id": body.team_id,
        "name": body.name,
        "description": body.description,
        "steps": [step.model_dump() for step in body.steps],
    })
    return RotationRead.model_validate(created)


@router.get("/{rotation_id}", response_model=RotationRead)
async def get_rotation(repo: _Repo, rotation_id: str) -> RotationRead:
    """One rotation."""
    return RotationRead.model_validate(await _require(repo, rotation_id))


@router.patch("/{rotation_id}", response_model=RotationRead)
@limiter.limit(WRITE_LIMIT)
async def update_rotation(
    request: Request,  # slowapi reads the client address off it
    rotation_id: str,
    body: RotationUpdate,
    repo: _Repo,
) -> RotationRead:
    """Rename a rotation, or replace its steps.

    Steps are replaced wholesale rather than patched per index. A rotation is an ordered
    list, so "change step 3" and "insert before step 3" are the same edit to the client and
    a different one to a per-index API — and the ambiguity would land on whoever wrote the UI.
    """
    rotation = await _require(repo, rotation_id)
    patch = body.model_dump(exclude_unset=True)
    if "steps" in patch and body.steps is not None:
        await _check_steps_against_team(repo, rotation.team_id, body.steps)
        patch["steps"] = [step.model_dump() for step in body.steps]

    updated = await repo.update(rotation_id, patch)
    return RotationRead.model_validate(updated)


@router.delete("/{rotation_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(WRITE_LIMIT)
async def delete_rotation(
    request: Request,  # slowapi reads the client address off it
    rotation_id: str,
    repo: _Repo,
) -> None:
    """Delete a rotation."""
    await _require(repo, rotation_id)
    await repo.delete(rotation_id)


@router.post("/{rotation_id}/compile")
@limiter.limit(WRITE_LIMIT)
async def compile_to_gcsim(
    request: Request,  # slowapi reads the client address off it
    rotation_id: str,
    repo: _Repo,
) -> dict[str, str]:
    """The gcsim action list this rotation becomes.

    Offered because a compiler nobody can inspect is a compiler nobody can check, and the
    complaint that started this chunk was about a syntax that hides what it is doing.

    A rotation whose team has since lost a character compiles to a **422 naming every
    offending step** — see `rotation_compiler`. It is not repaired here, and the steps are
    left exactly as authored.
    """
    rotation = await _require(repo, rotation_id)
    roster = await repo.character_rows(rotation.team_id)
    try:
        return {"config": compile_rotation(rotation.steps or [], roster)}
    except RotationCompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
