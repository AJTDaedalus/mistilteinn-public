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

from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import (
    CurrentUser,
    get_enemy_profile_repo,
    get_owned_build_repo,
    get_owned_rotation_repo,
    get_owned_sim_run_repo,
    get_owned_team_repo,
    get_rotation_library_repo,
)
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.enums import Visibility
from app.models.rotation import Rotation
from app.repositories.build import BuildRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.rotation import RotationLibraryRepository, RotationRepository
from app.repositories.sim_run import SimRunRepository
from app.repositories.team import TeamRepository
from app.schemas.common import PaginatedResponse
from app.schemas.rotation import (
    ContextKeyRead,
    ContextKeyRequest,
    LibraryRotationRead,
    RosterCharacter,
    RotationCopyRequest,
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
    signature_digest,
)
from app.services.rotation_converter import convert
from app.services.rotation_parser import RotationParseError, parse_action_block
from app.services.sim_context import context_key

if TYPE_CHECKING:
    from collections.abc import Sequence

router = APIRouter(prefix="/rotations", tags=["rotations"])

_Repo = Annotated[RotationRepository, Depends(get_owned_rotation_repo)]
_Teams = Annotated[TeamRepository, Depends(get_owned_team_repo)]
_Builds = Annotated[BuildRepository, Depends(get_owned_build_repo)]
_Enemies = Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)]
_Library = Annotated[RotationLibraryRepository, Depends(get_rotation_library_repo)]
_Runs = Annotated[SimRunRepository, Depends(get_owned_sim_run_repo)]
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
    # **Converted first, then parsed.** The converter rewrites what is mechanically
    # translatable — `for`→`while 1`, comma sequences into one step each, comments away, and
    # the `.ready` gates our own compiler adds to everything — and the parser refuses whatever
    # is left, by line. Owner ruling, `DECISIONS.md` §21.
    #
    # Measured against the four real database configs in `references/gcsim_db/`: one imports,
    # one is blocked only by gcsim's short aliases (`arle`, `esco`), and two use user-defined
    # functions and cycle-index conditionals that are different rotations rather than different
    # spellings.
    converted, notes = convert(body.config)
    try:
        steps = parse_action_block(converted, roster.values())
    except RotationParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RotationImportRead(
        steps=[RotationStep(**step) for step in steps], rewrites=notes,
    )


@router.get("/library", response_model=PaginatedResponse[LibraryRotationRead])
async def browse_library(
    repo: _Library,
    user: CurrentUser,
    runs: _Runs,
    owned: _Repo,
    characters: Annotated[list[str] | None, Query()] = None,
    q: str = "",
    sort: Annotated[Literal["recent", "likes", "dps"], Query()] = "dps",
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[LibraryRotationRead]:
    """Published rotations, from every user on this instance.

    Declared **above** `/{rotation_id}` for the reason `/options` is: FastAPI matches in
    declaration order, and below it this path would be swallowed as a rotation whose id is the
    word "library".

    `characters` matches a rotation whose character set is **exactly** these ids — not a
    superset. `DESIGN_rotation_library.md` §3 calls this filter one that "claims nothing", and
    that is only true if it means what it says: a four-character rotation surfacing for a
    three-character query would be a recommendation wearing a filter's clothes.

    Three queries for the page, not three per row: the rotations, their character sets, and
    their like counts. A per-row lookup is the shape that turns a twenty-row page into
    sixty-one round trips and looks fine until the page grows.
    """
    wanted = characters or []
    rows = await repo.search(characters=wanted, query=q, offset=offset, limit=limit)
    ids = [r.id for r in rows]
    by_rotation = await repo.characters_for(ids)
    counts = await repo.like_counts(ids)
    mine = await repo.liked_by(str(user.id), ids)
    yours = await _your_dps(rows, runs, owned)

    items = [
        LibraryRotationRead(
            id=r.id,
            name=r.name,
            description=r.description,
            steps=[RotationStep.model_validate(step) for step in r.steps],
            characters=by_rotation.get(r.id, []),
            like_count=counts.get(r.id, 0),
            liked_by_me=r.id in mine,
            your_dps=yours.get(r.id),
        )
        for r in rows
    ]

    # Ordered **after** assembly, because two of the three keys are facts about the caller
    # rather than columns. `search` returns newest-first and says so; sorting there by a
    # subquery the caller may have no row for would be a ranking dressed as a query.
    if sort == "dps":
        # DESIGN §3: "DPS where this user has run it, then likes, then anything else."
        # A rotation you have not run sorts **below** every one you have — not as zero, which
        # would rank it against numbers rather than admitting there is none.
        items.sort(key=lambda i: (i.your_dps is None, -(i.your_dps or 0.0), -i.like_count))
    elif sort == "likes":
        items.sort(key=lambda i: -i.like_count)

    return PaginatedResponse(
        items=items,
        total=await repo.count(characters=wanted, query=q),
        offset=offset,
        limit=limit,
    )


async def _your_dps(
    rows: Sequence[Rotation],
    runs: SimRunRepository,
    owned: RotationRepository,
) -> dict[str, float]:
    """The caller's own DPS per listed rotation. `DESIGN_rotation_library.md` §3.

    The signature is recomputed from the rotation **as it stands** and matched against what
    each cached run recorded. A run whose signature no longer matches described a previous
    version of that rotation, and is dropped rather than shown — the whole reason
    `sim_runs.rotation_signature` exists.

    ## In practice this answers for **your own** published rotations, and that is a real limit

    `character_rows` is owner-scoped, so a rotation on somebody else's team resolves to no
    roster, gets no signature, and reports `None`. **That is correct rather than a bug**: you
    cannot simulate a rotation on a team you do not own, so you have no run for it to report.

    What it means is that §3's ordering is live for rotations you published — you ran them,
    the number is yours — and silent for everyone else's until you copy one. **A copy is a
    different row**, so the DPS you then earn does not appear under the original's card. Making
    it appear needs the copy to remember where it came from, which is a column and a decision
    nobody has made. Recorded in `TASKS_rotation_library.md` rather than invented here.

    The owner scope doing this work is deliberate and worth not "fixing": widening it to read
    other users' teams would leak roster composition to answer a question that has no answer.

    A rotation whose characters no longer resolve is skipped rather than raising. It cannot
    have a current run either, and failing a whole listing because one shared rotation went
    stale would be the wrong trade.
    """
    # One query for every roster on the page, not one per rotation. The single-team form in a
    # loop was an N+1 that shipped in the first draft of this function and was caught by
    # `test_rotation_library_query_count` — the harness L.7 exists for, on its first run that
    # counted anything.
    rosters = await owned.rosters_for([r.team_id for r in rows])

    signatures: dict[str, str] = {}
    for rotation in rows:
        roster = rosters.get(rotation.team_id)
        if not roster:
            continue
        try:
            signature = rotation_signature(rotation.steps or [], roster)
        except (RotationCompileError, GcsimKeyError):
            continue
        signatures[rotation.id] = signature_digest(signature)
    return await runs.dps_by_rotation(signatures)


@router.post("/{rotation_id}/like", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def like_rotation(
    request: Request, repo: _Library, user: CurrentUser, rotation_id: str,
) -> None:
    """Mark a published rotation useful. Idempotent — liking twice is a no-op.

    **Liking your own is allowed.** It costs nothing to permit, and a rule against it is a rule
    to explain, enforce and test for no benefit anyone asked for.
    """
    if await repo.published(rotation_id) is None:
        raise HTTPException(status_code=404, detail=f"No published rotation {rotation_id!r}")
    await repo.like(rotation_id, str(user.id))


@router.delete("/{rotation_id}/like", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def unlike_rotation(
    request: Request, repo: _Library, user: CurrentUser, rotation_id: str,
) -> None:
    """Take a like back. Also idempotent: un-liking what you never liked is not an error."""
    if await repo.published(rotation_id) is None:
        raise HTTPException(status_code=404, detail=f"No published rotation {rotation_id!r}")
    await repo.unlike(rotation_id, str(user.id))


@router.post("/{rotation_id}/copy", response_model=RotationRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def copy_rotation(
    request: Request,
    library: _Library,
    repo: _Repo,
    teams: _Teams,
    body: RotationCopyRequest,
    rotation_id: str,
) -> RotationRead:
    """Copy a published rotation onto one of the caller's own teams.

    A shared rotation belongs to its author's team, so copying it means **re-resolving every
    step against the caller's**. A step naming a character their team does not field is
    **refused, naming the character** — never dropped and never substituted, which is the rule
    `app/models/rotation.py` (OQ-R2) already applies to a rotation gone stale.

    The copy is private, whatever the original was: publishing is something a user does.
    """
    original = await library.published(rotation_id)
    if original is None:
        raise HTTPException(status_code=404, detail=f"No published rotation {rotation_id!r}")
    if await teams.get_by_id(body.team_id) is None:
        raise HTTPException(status_code=404, detail=f"No team {body.team_id!r}")

    roster = await repo.team_characters(body.team_id)
    missing = sorted(
        {
            step.get("character")
            for step in original.steps
            if isinstance(step, dict) and step.get("character") not in roster
        }
        - {None},
    )
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"That team does not field {', '.join(missing)}, "
                "so those steps have nobody to run them. Nothing was copied."
            ),
        )

    created = await repo.create({
        "team_id": body.team_id,
        "name": f"{original.name} (copy)",
        "description": original.description,
        "steps": original.steps,
        "visibility": Visibility.PRIVATE,
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
    """Rename a rotation, replace its steps, or publish it.

    Steps are replaced wholesale rather than patched per index. A rotation is an ordered
    list, so "change step 3" and "insert before step 3" are the same edit to the client and
    a different one to a per-index API — and the ambiguity would land on whoever wrote the UI.

    **Publishing is `visibility`, not a `/publish` route** (L.2). A separate endpoint would be
    a second way to write one column, needing the same ownership check written twice — and this
    one is already here, in `_require` against the owner-scoped repository, which answers 404
    rather than 403 to a stranger and so does not confirm the row exists.
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
        context_key=key, rotation=signature, rotation_signature=signature_digest(signature),
        team=members, target=target, gcsim_pin=pinned_commit(),
    )
