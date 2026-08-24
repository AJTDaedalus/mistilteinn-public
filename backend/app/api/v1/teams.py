"""Team endpoints — CRUD only.

**Port state.** fairy's `teams.py` was 877 lines: five CRUD routes plus a whole
team-context evaluation surface (`POST /{team_id}/calculate`,
`POST /{team_id}/evaluate-discs`) and the ~600 lines of context loading, snapshot
building, attribution shaping, and build-delta plumbing behind them. B.6 keeps the CRUD
and deletes the rest, because every one of those helpers called into a service the
demolition removed — `team_calculator`, `attributed_eval`, `attribution`, `buff_roster`,
`build_delta`, `combo_step_resolver`, `combo_types`, `damage_calculator`, `lumiflux`,
`snapshot_builder`, `support_selection`, and the modifier DSL.

A team is still three builds and CRUD over that is game-neutral, so the table, the
schemas and these five routes stand. Genshin team evaluation is rebuilt on the Chunk F
damage chain and the Chunk I rotation model; recover the deleted surface from
fairy@76909c4:backend/app/api/v1/teams.py if it is wanted as structural reference.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.dependencies import get_owned_team_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.team import TeamRepository
from app.schemas.common import PaginatedResponse
from app.schemas.team import TEAM_SLOTS, TeamCreate, TeamRead, TeamUpdate, assert_slots_distinct

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=PaginatedResponse[TeamRead])
async def list_teams(
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[TeamRead]:
    """List the caller's saved teams."""
    teams = await repo.get_all(offset=offset, limit=limit)
    total = await repo.count()
    return PaginatedResponse(
        items=[TeamRead.model_validate(t) for t in teams],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=TeamRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_team(
    request: Request,
    body: TeamCreate,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> TeamRead:
    """Create a team of up to three builds."""
    team = await repo.create(body.model_dump())
    return TeamRead.model_validate(team)


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(
    team_id: str,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> TeamRead:
    """Fetch a single team by id."""
    team = await repo.get_by_id(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamRead.model_validate(team)


@router.patch("/{team_id}", response_model=TeamRead)
@limiter.limit(WRITE_LIMIT)
async def update_team(
    request: Request,
    team_id: str,
    body: TeamUpdate,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> TeamRead:
    """Partially update a team's name or member builds."""
    patch = body.model_dump(exclude_unset=True)

    # `TeamUpdate`'s validator only sees the patch body. A patch that moves one
    # slot onto an id the row already holds in another slot is a duplicate only
    # once merged, so check the *resulting* team, not the request.
    if any(k in patch for k in TEAM_SLOTS):
        existing = await repo.get_by_id(team_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Team not found")
        merged = {
            slot: patch.get(slot, getattr(existing, slot))
            for slot in TEAM_SLOTS
        }
        try:
            assert_slots_distinct(**merged)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    team = await repo.update(team_id, patch)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamRead.model_validate(team)


@router.delete("/{team_id}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def delete_team(
    request: Request,
    team_id: str,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> None:
    """Delete a team."""
    deleted = await repo.delete(team_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Team not found")
