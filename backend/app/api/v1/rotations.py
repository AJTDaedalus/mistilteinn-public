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

from app.dependencies import (
    get_enemy_profile_repo,
    get_owned_build_repo,
    get_owned_rotation_repo,
    get_owned_team_repo,
)
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.rotation import Rotation
from app.repositories.build import BuildRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.rotation import RotationRepository
from app.repositories.team import TeamRepository
from app.schemas.common import PaginatedResponse
from app.schemas.rotation import (
    ContextKeyRead,
    ContextKeyRequest,
    RosterCharacter,
    RotationCreate,
    RotationImportRead,
    RotationImportRequest,
    RotationOptions,
    RotationRead,
    RotationStep,
    RotationUpdate,
    TeamRoster,
)
from app.schemas.team import TEAM_SLOTS
from app.services import gcsim_keys
from app.services.gcsim_config import GcsimConfigError, target_fields
from app.services.gcsim_keys import GcsimKeyError, authorable_actions, pinned_commit
from app.services.rotation_compiler import (
    RotationCompileError,
    compile_rotation,
    rotation_signature,
)
from app.services.rotation_parser import RotationParseError, parse_action_block
from app.services.sim_context import context_key

router = APIRouter(prefix="/rotations", tags=["rotations"])

_Repo = Annotated[RotationRepository, Depends(get_owned_rotation_repo)]
_Teams = Annotated[TeamRepository, Depends(get_owned_team_repo)]
_Builds = Annotated[BuildRepository, Depends(get_owned_build_repo)]
_Enemies = Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)]
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


@router.get("/options", response_model=RotationOptions)
async def rotation_options(repo: _Repo) -> RotationOptions:
    """What an editor may offer: the ten actions, and the caller's teams with their rosters.

    Declared **above** `/{rotation_id}` — FastAPI matches in declaration order, and below it
    this path would be swallowed as a rotation whose id is the word "options".

    One request rather than a walk from team to four builds to four characters. That walk
    would also have to map `character_id` (a UUID) to the `nanoka_id` a step names, which is
    a conversion the client has no business performing.
    """
    return RotationOptions(
        actions=list(authorable_actions()),
        teams=[
            TeamRoster(
                id=str(team.id),
                name=team.name,
                characters=[
                    RosterCharacter(
                        nanoka_id=nanoka_id,
                        name=character.name,
                        element=str(character.element.value),
                        icon=character.icon,
                    )
                    for nanoka_id, character in sorted(roster.items())
                ],
            )
            for team, roster in await repo.rosters()
        ],
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


@router.post("/import", response_model=RotationImportRead)
@limiter.limit(WRITE_LIMIT)
async def import_from_gcsim(
    request: Request,  # slowapi reads the client address off it
    body: RotationImportRequest,
    repo: _Repo,
) -> RotationImportRead:
    """Read a gcsim config back into rotation steps, or refuse and say why.

    **This creates nothing.** The steps come back as a preview and are saved, if at all,
    through the ordinary create endpoint — see `RotationImportRead` on why.

    A config this app emitted round-trips exactly. Anything else is refused with **422 naming
    every line** it could not express, rather than imported without them. gcsim's language is
    far larger than a list of `(character, action, repeat)`: conditional guards on energy or
    status, `wait` for buff alignment, loops that are not `while 1`. Dropping an
    `if .noelle.energy > 40` would leave a rotation that looks like the author's, carries
    their name, and simulates to a number they never published — and the user would have no
    way to see the difference. `rotation_parser` is written at length about this.
    """
    roster = await repo.character_rows(body.team_id)
    if not roster:
        raise HTTPException(
            status_code=422,
            detail=(
                f"team {body.team_id!r} has no builds, so there is no roster to map gcsim's "
                f"character keys onto. A config names characters in gcsim's vocabulary; "
                f"turning `noelle` back into a catalogue row needs the team."
            ),
        )
    try:
        steps = parse_action_block(body.config, roster.values())
    except RotationParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RotationImportRead(steps=[RotationStep(**step) for step in steps])


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


@router.post("/{rotation_id}/context-key", response_model=ContextKeyRead)
@limiter.limit(WRITE_LIMIT)
async def rotation_context_key(
    request: Request,  # slowapi reads the client address off it
    rotation_id: str,
    body: ContextKeyRequest,
    repo: _Repo,
    teams: _Teams,
    builds: _Builds,
    enemies: _Enemies,
) -> ContextKeyRead:
    """The cache key identifying "this build, running this rotation, against this target".

    R.6. `context_key` decides whether a cached gcsim run answers the question being asked,
    and getting it wrong is not a performance bug — it serves a confident number computed for
    something else. **So the server computes it.** Before this, the only callers were tests,
    and a client wanting a cached run had to reproduce a canonicalising SHA-256 by hand; the
    second implementation would have drifted, and the drift would look like a cache hit.

    The rotation is fed in through `rotation_signature`, which shares `_resolve` with the
    compiler — so the key and the config gcsim actually receives cannot disagree about who a
    step names. The target comes through `gcsim_config.target_fields`, for the same reason.
    """
    rotation = await _require(repo, rotation_id)

    team = await teams.get_by_id(rotation.team_id)
    if team is None or body.build_id not in {
        getattr(team, slot) for slot in TEAM_SLOTS
    }:
        raise HTTPException(
            status_code=422,
            detail=(
                f"build {body.build_id!r} is not on this rotation's team. A context key is "
                f"per-character within the team that ran the rotation, so a build from "
                f"somewhere else would key a run that never happened."
            ),
        )

    build = await builds.get_full(body.build_id)
    if build is None or build.character is None:
        raise HTTPException(
            status_code=422,
            detail=f"build {body.build_id!r} has no character, so there is nothing to key.",
        )

    enemy = None
    if body.enemy_nanoka_id is not None:
        found = await enemies.get_by_filters({"nanoka_id": body.enemy_nanoka_id})
        if not found:
            raise HTTPException(
                status_code=404, detail=f"No enemy {body.enemy_nanoka_id!r}",
            )
        enemy = found[0]

    roster = await repo.character_rows(rotation.team_id)
    # `GcsimKeyError` is in here too: a character or weapon released after the pin has no
    # gcsim key, and that is a refusal with a written explanation, not a server fault. It
    # escaped as a 500 in the first version of this handler — the message was already right,
    # nobody was going to see it.
    try:
        signature = rotation_signature(rotation.steps or [], roster)
        target = target_fields(enemy)
        members = sorted(
            gcsim_keys.character_key(row.nanoka_id, row.name, row.element)
            for row in roster.values()
        )
        key = context_key(
            character_key=gcsim_keys.character_key(
                build.character.nanoka_id, build.character.name, build.character.element,
            ),
            weapon_key=(
                gcsim_keys.weapon_key(build.weapon.name)
                if build.weapon is not None
                else None
            ),
            character_level=build.character_level,
            constellation=build.constellation_level,
            weapon_level=build.weapon_level,
            refinement=build.refinement,
            talent_levels=build.talent_levels or {},
            rotation=signature,
            target=target,
            gcsim_pin=pinned_commit(),
            team=members,
        )
    except (RotationCompileError, GcsimConfigError, GcsimKeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ContextKeyRead(
        context_key=key, rotation=signature, team=members,
        target=target, gcsim_pin=pinned_commit(),
    )
