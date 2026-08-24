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

from app.dependencies import get_owned_build_repo, get_owned_team_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.build import BuildRepository
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


async def _validated_members(
    builds: BuildRepository, slots: dict[str, str | None],
) -> None:
    """Refuse a team whose slots name builds the caller does not own, or two of one character.

    T.1a. `create_team` was a bare `repo.create`, so a slot naming a build that does not exist
    reached the foreign key and became a **500**, and a slot naming a *stranger's* build was
    stored — after which every read of that team showed it.

    The character rule is the one that moved. `uq_builds_owner_character` used to make it
    impossible to own two builds of one character, so it was impossible to put two on a team
    by accident. With that constraint dropped (owner decision, 2026-08-24) the collection may
    hold a C0 and a C6 of the same character, and the team may not: gcsim refuses such a party
    outright — `pkg/simulation/setup.go:94` at pin `3647a07` returns `duplicated character
    %v`. Checked when the team is saved rather than when a simulation fails, which is both
    later and further from the edit.
    """
    wanted = [build_id for build_id in slots.values() if build_id is not None]
    if not wanted:
        return
    # `get_by_id` is owner-scoped, so a stranger's build reads as absent — which is the right
    # answer to give: confirming it exists would disclose that it does.
    found = {}
    for build_id in wanted:
        build = await builds.get_by_id(build_id)
        if build is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no build {build_id!r} of yours. A team is assembled from your own "
                    f"builds."
                ),
            )
        found[build_id] = build

    seen: dict[str, str] = {}
    for build_id, build in found.items():
        character_id = build.character_id
        if character_id is None:
            continue
        if character_id in seen:
            name = build.character.name if build.character is not None else character_id
            raise HTTPException(
                status_code=422,
                detail=(
                    f"this team holds {name} twice ({seen[character_id]} and {build_id}). "
                    f"A party cannot field the same character twice — gcsim refuses one "
                    f"outright — so it is refused here rather than when the simulation "
                    f"fails. Two builds of one character is fine to *own*; it is the team "
                    f"that cannot hold both."
                ),
            )
        seen[character_id] = build_id


@router.post("", response_model=TeamRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_team(
    request: Request,
    body: TeamCreate,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> TeamRead:
    """Create a team of up to four builds, having checked it is one that could be simulated."""
    await _validated_members(builds, {slot: getattr(body, slot) for slot in TEAM_SLOTS})
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
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
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
        # Against the merged team, for the same reason `assert_slots_distinct` is: a patch
        # adding a second Ayaka names one build, and is illegal only beside the one already
        # in another slot.
        await _validated_members(builds, merged)

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
