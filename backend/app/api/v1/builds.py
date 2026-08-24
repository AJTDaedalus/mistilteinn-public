"""Saved builds, and explaining and comparing them.

## The hit is supplied, not derived

`POST /builds/{id}/explain` takes a `hit` — multiplier, scaling stat, damage channel,
scope. It does **not** work one out from the build's character. Deriving a talent's numbers
from its stored rows is the kit corpus's job (Chunk H) and this repo has no kit corpus;
parsing a multiplier out of a `desc` string and serving the result would be presenting a
guess as though it came from the game. `TODO(chunk-H)`.

## The search is not here any more

C.6 deleted `/optimize` and `/rank-artifacts`. Searching runs in the browser (DESIGN §3.5:
nothing combinatorial lands on the server), and what is left here is the part that reads the
database — explaining one build, and comparing candidate weapons in it. Both reach the damage
chain through `build_combination_log`, which stays the single definition of what five
artifacts are worth.
"""

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import (
    get_character_repo,
    get_enemy_profile_repo,
    get_owned_artifact_repo,
    get_owned_build_repo,
    get_owned_sim_run_repo,
    get_weapon_repo,
)
from app.formula.genshin.damage import Hit
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.artifact import ArtifactRepository
from app.repositories.build import BuildRepository
from app.repositories.character import CharacterRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.sim_run import SimRunRepository
from app.repositories.weapon import WeaponRepository
from app.schemas.build import (
    BuildCreate,
    BuildRead,
    BuildUpdate,
    CompareWeaponsRequest,
    CompareWeaponsResponse,
    ContributionRead,
    EnemySpec,
    ExplainRequest,
    ExplainResponse,
    HitSpec,
    SetEffectRead,
    SimulationNoteRead,
    StatAccountRead,
    StatDifferenceRead,
    UncitedRead,
    UnmodelledPassiveRead,
    WeaponScoreRead,
)
from app.schemas.common import PaginatedResponse
from app.services import (
    artifact_optimizer,
    build_assembler,
    build_explanation,
    sim_retrieval,
    weapon_comparison,
)
from app.services.build_assembler import BuildAssemblyError
from app.services.damage_calculator import BuildEvaluator, Enemy, enemy_from_profile
from app.services.gcsim_keys import pinned_commit
from app.services.stat_calculator import StatInputError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.formula.genshin.explain import Contribution
    from app.models.artifact import Artifact, ArtifactSet
    from app.models.build import Build
    from app.models.weapon import Weapon

router = APIRouter(prefix="/builds", tags=["builds"])

_Offset = Annotated[int, Query(ge=0)]
_Limit = Annotated[int, Query(ge=1, le=200)]


async def _refuse_duplicate(
    repo: BuildRepository, *, character_id: str | None, excluding: str | None,
) -> None:
    """Refuse a second build of the same character, rather than letting the DB 500.

    `uq_builds_owner_character` is one build per character per user. It was **enforced only
    by the database**, so making a second Ayaka build — an ordinary thing to do — raised a
    `UniqueViolationError` and the user was told the server broke.

    This makes the existing rule legible; it does not endorse it. `app/models/build.py`
    records that the constraint was inherited verbatim from fairy's `uq_builds_owner_agent`
    and kept *pending an owner decision*, because it forbids saving a C0 and a C6 of the same
    character side by side, or a Physical and a Cryo Eula. If that decision drops the
    constraint, this function goes with it — and until then the refusal says what the limit
    is instead of leaving a user to guess from a 500.
    """
    if character_id is None:
        return
    existing = await repo.get_by_filters({"character_id": character_id}, limit=2)
    clashes = [row for row in existing if str(row.id) != excluding]
    if clashes:
        raise HTTPException(
            status_code=409,
            detail=(
                f"you already have a build for this character ({clashes[0].id}). The schema "
                f"allows one build per character per user; edit that one, or delete it "
                f"first. This limit is inherited from fairy and is under review — see "
                f"app/models/build.py."
            ),
        )


_Characters = Annotated[CharacterRepository, Depends(get_character_repo)]
_Weapons = Annotated[WeaponRepository, Depends(get_weapon_repo)]


async def _validated_pairing(
    characters: CharacterRepository,
    weapons: WeaponRepository,
    *,
    character_id: str | None,
    weapon_id: str | None,
) -> None:
    """Refuse a build whose character or weapon is absent, or which pairs them illegally.

    T.1. The handler used to be a bare `repo.create`, so an absent `character_id` escaped as
    a **500** from the foreign key — the user told the server broke, when what happened is
    they named something that is not there — and a Sword character holding a Bow was stored
    without comment. The game cannot equip that and gcsim cannot simulate it; it would have
    surfaced at `/explain` or in a run, far from the edit that caused it (OQ-T1).

    `weapon_id` of `None` is **allowed and is not the same as absent**: a build being
    assembled is a real state, and the damage chain already refuses to run without a weapon,
    which is the right place for that requirement (OQ-T3).
    """
    character = await characters.get_by_id(character_id) if character_id else None
    if character_id and character is None:
        raise HTTPException(
            status_code=422,
            detail=f"no character {character_id!r}. A build has to be of someone.",
        )
    if weapon_id is None:
        return
    weapon = await weapons.get_by_id(weapon_id)
    if weapon is None:
        raise HTTPException(status_code=422, detail=f"no weapon {weapon_id!r}.")
    if character is not None and weapon.weapon_type != character.weapon_type:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{character.name} wields a {character.weapon_type.display} and "
                f"{weapon.name} is a {weapon.weapon_type.display}. The game cannot equip "
                f"that pairing and gcsim cannot simulate it, so it is refused here rather "
                f"than at the point of scoring."
            ),
        )


@router.get("", response_model=PaginatedResponse[BuildRead])
async def list_builds(
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[BuildRead]:
    """The caller's saved builds, newest first."""
    rows = await repo.search(offset=offset, limit=limit)
    return PaginatedResponse(
        items=[BuildRead.model_validate(row) for row in rows],
        total=await repo.count_filtered(),
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=BuildRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_build(
    request: Request,
    body: BuildCreate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    characters: _Characters,
    weapons: _Weapons,
) -> BuildRead:
    """Save a build, having checked it is one that could exist."""
    await _validated_pairing(
        characters, weapons,
        character_id=body.character_id, weapon_id=body.weapon_id,
    )
    await _refuse_duplicate(repo, character_id=body.character_id, excluding=None)
    build = await repo.create({**body.model_dump(), "owner_id": repo.owner_id})
    return BuildRead.model_validate(build)


@router.get("/{build_id}", response_model=BuildRead)
async def get_build(
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """One of the caller's builds."""
    return BuildRead.model_validate(await _require_build(repo, build_id))


@router.patch("/{build_id}", response_model=BuildRead)
@limiter.limit(WRITE_LIMIT)
async def update_build(
    request: Request,
    build_id: str,
    body: BuildUpdate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    characters: _Characters,
    weapons: _Weapons,
) -> BuildRead:
    """Partially update one of the caller's builds.

    The pairing is re-checked against the **merged** result, not against the patch body. What
    is being validated is character-and-weapon *together*, and a patch that moves a sword
    build onto an archer names only fields that are individually fine while leaving the
    stored weapon unwieldable.
    """
    existing = await _require_build(repo, build_id)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        return BuildRead.model_validate(existing)

    merged_character = patch.get("character_id", existing.character_id)
    # `.get` with a default is right here only because `exclude_unset` already dropped the
    # keys that were not sent: an explicit `"weapon_id": null` means *unequip* and must
    # survive as None rather than falling back to the stored weapon.
    merged_weapon = patch.get("weapon_id", existing.weapon_id)
    await _validated_pairing(
        characters, weapons,
        character_id=merged_character, weapon_id=merged_weapon,
    )
    if "character_id" in patch:
        await _refuse_duplicate(repo, character_id=merged_character, excluding=build_id)

    updated = await repo.update(build_id, patch)
    return BuildRead.model_validate(updated)


@router.delete("/{build_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(WRITE_LIMIT)
async def delete_build(
    request: Request,
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> None:
    """Delete one of the caller's builds. Its artifacts are unequipped, not deleted."""
    await _require_build(repo, build_id)
    await repo.delete(build_id)


#: How many owned pieces one request will read out of the database.
#:
#: `_SLOT_CAP` and `_capped_per_slot` went with the search in C.6: they bounded how much of a
#: large inventory a *combinatorial* run would look at, and nothing left here is
#: combinatorial. `explain` and `compare-weapons` read the whole inventory once, to resolve
#: set bonuses.
_FETCH_CAP = 20_000


def _sets_of(artifacts: "Sequence[Artifact]") -> list["ArtifactSet"]:
    """Each distinct catalogue set among these pieces, once.

    Once, because `set_bonuses` expands every affix of every set it is given: handing it the
    same set five times would register a 2-piece bonus five times over on any build wearing
    five of it, and the build would be reported as worth several times what it is.
    """
    seen: dict[int, ArtifactSet] = {}
    for artifact in artifacts:
        if artifact.artifact_set is not None:
            seen.setdefault(artifact.artifact_set.nanoka_id, artifact.artifact_set)
    return list(seen.values())


@router.post("/{build_id}/explain", response_model=ExplainResponse)
@limiter.limit(WRITE_LIMIT)
async def explain_build(
    request: Request,
    build_id: str,
    body: ExplainRequest,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    artifacts: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    enemies: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
    sim_runs: Annotated[SimRunRepository, Depends(get_owned_sim_run_repo)],
) -> ExplainResponse:
    """Why this build scores what it scores — and, by default, why it beats what is worn.

    Every number here **arrives** rather than being computed: contributions come from
    `build_combination_log`, the same path the search and the ranker use; set text comes from
    the catalogue verbatim; the simulation figure comes from `sim_retrieval` carrying its own
    measured divergence. Nothing in the explanation layer multiplies anything, because a
    second implementation of the chain would be free to disagree with the first (DESIGN §1
    A6).
    """
    build = await _require_full_build(builds, build_id)
    base = _base_contributions(build)
    owned = await artifacts.search(limit=_FETCH_CAP)
    by_id = {str(row.id): row for row in owned}
    bonuses = build_assembler.set_bonuses(_sets_of(owned))
    hit, enemy = _hit(body.hit), await _enemy(body.enemy, enemies)

    equipped_rows = list(build.artifacts)
    if body.artifact_ids is None:
        proposed_rows = equipped_rows
    else:
        missing = [aid for aid in body.artifact_ids if aid not in by_id]
        if missing:
            # 404 rather than "explained what we could find": an explanation of four pieces
            # presented as an explanation of five is wrong in the way that is hardest to see.
            raise HTTPException(
                status_code=404,
                detail=f"artifacts not in this account: {sorted(missing)}",
            )
        proposed_rows = [by_id[aid] for aid in body.artifact_ids]

    _require_one_per_slot(proposed_rows, "the pieces to explain")
    if body.compare_to_equipped and body.artifact_ids is not None:
        _require_one_per_slot(equipped_rows, "the equipped build")

    try:
        proposed, proposed_damage = _scored(
            base, proposed_rows, bonuses, hit, enemy, build.character_level,
        )
        equipped = proposed
        equipped_damage = proposed_damage
        if body.compare_to_equipped and body.artifact_ids is not None:
            equipped, equipped_damage = _scored(
                base, equipped_rows, bonuses, hit, enemy, build.character_level,
            )
    except (artifact_optimizer.OptimizerInputError, StatInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    retrieval = await _retrieval(body, sim_runs)
    account = build_explanation.explain(
        proposed,
        set_descriptions=_set_descriptions(owned),
        retrieval=retrieval,
    )
    comparing = equipped is not proposed
    diff = build_explanation.compare(equipped, proposed) if comparing else None

    return ExplainResponse(
        damage=proposed_damage,
        stats=[
            StatAccountRead(
                quantity=account_.quantity,
                parts=[_contribution(c) for c in account_.parts],
                sum_of_parts=account_.sum_of_parts,
                sources=list(account_.sources),
            )
            for account_ in account.stats
        ],
        set_effects=[
            SetEffectRead(
                note=effect.note,
                description=effect.description,
                contributions=[_contribution(c) for c in effect.contributions],
            )
            for effect in account.set_effects
        ],
        simulation=None if account.simulation is None else SimulationNoteRead(
            matched_bucket=account.simulation.matched_bucket,
            requested_bucket=account.simulation.requested_bucket,
            bucket_distance=account.simulation.bucket_distance,
            is_exact_bucket=account.simulation.is_exact_bucket,
            dps_mean=account.simulation.dps_mean,
            divergence_pct=account.simulation.divergence_pct,
            noise_floor=account.simulation.noise_floor,
            exceeds_noise=account.simulation.exceeds_noise,
            caveat=account.simulation.caveat,
        ),
        uncited=[UncitedRead(what=u.what, why=u.why) for u in account.uncited],
        differences=None if diff is None else [
            StatDifferenceRead(
                quantity=d.quantity,
                equipped=d.left,
                proposed=d.right,
                delta=d.delta,
                gained=[_contribution(c) for c in d.gained],
                lost=[_contribution(c) for c in d.lost],
            )
            for d in diff.differences
        ],
        equipped_damage=None if diff is None else equipped_damage,
        unchanged=None if diff is None else list(diff.unchanged),
    )


@router.post("/{build_id}/compare-weapons", response_model=CompareWeaponsResponse)
@limiter.limit(WRITE_LIMIT)
async def compare_weapons(
    request: Request,
    build_id: str,
    body: CompareWeaponsRequest,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    artifacts: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    enemies: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
    weapons: Annotated[WeaponRepository, Depends(get_weapon_repo)],
) -> CompareWeaponsResponse:
    """Score each candidate weapon in this build, holding the artifacts fixed.

    **Two limits are reported rather than buried, because both can change the answer and not
    merely its precision:**

    - **Weapon passives are not applied.** They are imported into `weapon_refinements` but
      turning text into modifiers is Chunk H's job. For weapons that gap is frequently the
      entire reason to equip one, so `unmodelled_passives` names every candidate that has a
      passive and the response's `caveat` says the ordering may be wrong.
    - **Artifacts are held fixed.** DESIGN §3.5's fuller version searches per weapon and
      compares the winners, but searches belong on the client. This answers "which weapon is
      better in the build I have", which is a cheaper and different question — a weapon
      wanting a different artifact set loses a comparison it would win with its own pieces.

    `TODO(chunk-H)` for the first.
    """
    build = await _require_full_build(builds, build_id)
    if build.weapon is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "this build has no weapon, so there is nothing to compare against. A "
                "marginal-value comparison measures each candidate against what is worn."
            ),
        )

    equipped_rows = list(build.artifacts)
    _require_one_per_slot(equipped_rows, "the equipped build")
    owned = await artifacts.search(limit=_FETCH_CAP)
    bonuses = build_assembler.set_bonuses(_sets_of(owned))
    combination = build_assembler.candidates(equipped_rows)

    # The equipped weapon is always a candidate whether or not the caller listed it: the
    # baseline is what is worn, and a comparison with no baseline reports every delta
    # against an arbitrary weapon while looking exactly like a ranking.
    wanted = list(dict.fromkeys([str(build.weapon.id), *body.weapon_ids]))
    rows = await weapons.get_many_with_refinements(wanted)
    found = {str(row.id): row for row in rows}
    missing = [wid for wid in wanted if wid not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"no such weapons: {sorted(missing)}")

    # A character can only hold one weapon type. Nothing downstream checks it —
    # `add_weapon` applies whatever stats it is handed — so a claymore compared for a sword
    # user would score, rank, and be recommended, and the user could not equip it.
    wrong_type = sorted(
        f"{found[wid].name} ({found[wid].weapon_type.value})"
        for wid in wanted
        if build.character is not None and found[wid].weapon_type != build.character.weapon_type
    )
    if wrong_type:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{build.character.name} uses "
                f"{build.character.weapon_type.value}; these cannot be equipped: "
                f"{wrong_type}. Scoring them would rank a weapon the character cannot hold."
            ),
        )

    try:
        candidates = [
            _weapon_candidate(build, found[wid]) for wid in wanted
        ]
        result = weapon_comparison.compare_weapons(
            candidates,
            str(build.weapon.id),
            combination,
            _hit(body.hit),
            await _enemy(body.enemy, enemies),
            character_level=build.character_level,
            set_bonuses=bonuses,
        )
    except (BuildAssemblyError, StatInputError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CompareWeaponsResponse(
        weapons=[
            WeaponScoreRead(
                weapon_id=score.weapon_id,
                name=score.name,
                damage=score.damage,
                delta=score.delta,
                delta_pct=score.delta_pct,
                is_equipped=score.weapon_id == result.equipped_weapon_id,
                differences=[
                    StatDifferenceRead(
                        quantity=d.quantity, equipped=d.left, proposed=d.right,
                        delta=d.delta,
                        gained=[_contribution(c) for c in d.gained],
                        lost=[_contribution(c) for c in d.lost],
                    )
                    for d in score.differences
                ],
            )
            for score in result.weapons
        ],
        equipped_weapon_id=result.equipped_weapon_id,
        unmodelled_passives=[
            UnmodelledPassiveRead(
                weapon_id=p.weapon_id, weapon_name=p.weapon_name,
                passive_name=p.passive_name, text=p.text, refinement=p.refinement,
            )
            for p in result.unmodelled_passives
        ],
        is_complete=result.is_complete,
        caveat=result.caveat(),
    )


def _weapon_candidate(build: "Build", weapon: "Weapon") -> weapon_comparison.WeaponCandidate:
    """One candidate, with the build's character half and *this* weapon's contribution.

    Assembled through `build_assembler`, not here: building a base from rows is that module's
    job, and a second way of doing it is how two definitions of "what a build starts from"
    begin.
    """
    base = build_assembler.base_contributions_with_weapon(
        build, weapon, weapon_level=build.weapon_level,
    )
    return weapon_comparison.WeaponCandidate(
        weapon_id=str(weapon.id),
        name=weapon.name,
        base_contributions=base,
        unmodelled_passive=_passive_of(weapon, build.refinement),
        passive_refinement=build.refinement,
    )


def _passive_of(weapon: "Weapon", refinement: int) -> "tuple[str, str] | None":
    """The refinement passive this comparison cannot apply, or None if there is none.

    Read off the stored row rather than assumed: a weapon with no passive is a real case —
    every white and green weapon — and reporting one anyway would put a permanent doubt
    beside a comparison that is actually complete.

    **The level is the build's**, because a candidate the user does not own has no refinement
    of its own to read. That is an assumption, so the response reports which level it quoted
    rather than leaving a reader to infer that an R1 Mistsplitter's text is what they were
    shown. It affects only the words: nothing here applies the passive at any level.
    """
    for row in weapon.refinements:
        if row.level == refinement and (row.description or row.name):
            return (row.name or "unnamed passive", row.description)
    return None


def _require_one_per_slot(rows: "Sequence[Artifact]", what: str) -> None:
    """Five pieces, one per slot.

    Nothing downstream checks this: `build_combination_log` iterates whatever it is handed,
    so two goblets would count a goblet twice and four pieces would be scored as four. The
    search never meets that because it builds combinations one-per-slot by construction, and
    the ranker refuses it explicitly. This endpoint takes ids from the caller, so it is the
    first place the question is actually open.

    Both failures produce a plausible number: a duplicated piece inflates the build a user
    cannot actually wear, and a short list quietly compares a three-piece proposal against a
    five-piece build and reports two slots' worth of "losses" as though the user had chosen
    them.
    """
    slots = [str(row.slot) for row in rows]
    ids = [str(row.id) for row in rows]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=422,
            detail=f"{what} names the same artifact more than once; a build wears each piece "
            f"at most once.",
        )
    missing = sorted(set(artifact_optimizer.SLOTS) - set(slots))
    if missing or len(slots) != len(artifact_optimizer.SLOTS):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{what} must be five pieces, one per slot. Missing {missing}; got "
                f"{sorted(slots)}. A partial build scores as a partial build, and next to a "
                f"full one that difference reads as a choice the user made."
            ),
        )


def _contribution(c: "Contribution") -> ContributionRead:
    return ContributionRead(quantity=c.quantity, value=c.value, source=c.source, note=c.note)


def _scored(
    base: "Sequence[Contribution]",
    rows: "Sequence[Artifact]",
    bonuses: "Sequence[artifact_optimizer.SetBonus]",
    hit: Hit,
    enemy: Enemy,
    character_level: int,
) -> "tuple[tuple[Contribution, ...], float]":
    """Contributions and damage for one set of pieces, through the one scoring path."""
    combination = build_assembler.candidates(rows)
    log, _ = artifact_optimizer.build_combination_log(
        base, combination, artifact_optimizer.bonuses_by_set(bonuses),
    )
    evaluator = BuildEvaluator(
        registry=log.registry, enemy=enemy, character_level=character_level,
    )
    return tuple(log.contributions), evaluator.evaluate(hit).expected


def _set_descriptions(rows: "Sequence[Artifact]") -> dict[str, str]:
    """Map a set contribution's note to the catalogue's published text.

    Keyed through `artifact_optimizer.set_bonus_note`, the **same function** that writes the
    note, so the two cannot drift. Building the key here by hand is what D.4 did first, and
    it silently matched nothing: the note was `"set 15025 2pc"` rather than the set's name.
    A set the catalogue has no affix text for simply has no entry, and the explanation
    reports it as uncited rather than inventing a sentence.
    """
    descriptions: dict[str, str] = {}
    for row in rows:
        artifact_set = row.artifact_set
        if artifact_set is None:
            continue
        for affix in artifact_set.affixes:
            if affix.description:
                key = artifact_optimizer.set_bonus_note(
                    artifact_set.nanoka_id, artifact_set.name, affix.pieces_required,
                )
                descriptions[key] = affix.description
    return descriptions


async def _retrieval(
    body: ExplainRequest, repo: SimRunRepository,
) -> "sim_retrieval.Retrieval | None":
    """The cached run for this context, when the caller supplied one to look for.

    Both `context_key` and `energy_recharge` or neither: a key with no ER cannot pick a
    bucket, and an ER with no key has no context to pick one from. Half of the pair is a
    caller mistake worth naming rather than silently ignoring.
    """
    if body.context_key is None and body.energy_recharge is None:
        return None
    if body.context_key is None or body.energy_recharge is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "context_key and energy_recharge go together: a key with no ER cannot pick "
                "a bucket, and an ER with no key has no context to pick one from."
            ),
        )
    runs = await repo.get_buckets(
        context_key=body.context_key, gcsim_pin=pinned_commit(),
    )
    return sim_retrieval.retrieve(runs, body.energy_recharge)


async def _require_build(repo: BuildRepository, build_id: str) -> "Build":
    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail=f"No build {build_id!r}")
    return build


async def _require_full_build(repo: BuildRepository, build_id: str) -> "Build":
    build = await repo.get_full(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail=f"No build {build_id!r}")
    return build


def _base_contributions(build: "Build") -> "tuple[Contribution, ...]":
    try:
        return build_assembler.base_contributions(build)
    except (BuildAssemblyError, StatInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _hit(spec: HitSpec) -> Hit:
    return Hit(
        multiplier=spec.multiplier,
        channel=spec.channel,
        scope=spec.scope,
        scaling_stat=spec.scaling_stat,
        amplifying=spec.amplifying,
        flat_damage=spec.flat_damage,
    )


async def _enemy(spec: EnemySpec, repo: EnemyProfileRepository) -> Enemy:
    """The target, from a stored profile when one is named.

    A profile's eight resistance columns are the whole of what a hit needs from it — its
    HP/ATK/DEF are curve bases and outgoing damage never reads them.
    """
    if spec.enemy_profile_id is not None:
        profile = await repo.get_by_id(spec.enemy_profile_id)
        if profile is None:
            raise HTTPException(
                status_code=404, detail=f"No enemy profile {spec.enemy_profile_id!r}",
            )
        return enemy_from_profile(
            level=profile.level,
            resistances={
                "physical": profile.physical_res, "anemo": profile.anemo_res,
                "cryo": profile.cryo_res, "dendro": profile.dendro_res,
                "electro": profile.electro_res, "geo": profile.geo_res,
                "hydro": profile.hydro_res, "pyro": profile.pyro_res,
            },
        )
    return enemy_from_profile(level=spec.level, resistances=spec.resolved_resistances())
