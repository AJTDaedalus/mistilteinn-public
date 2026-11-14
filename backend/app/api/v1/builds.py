"""Saved builds, and explaining and comparing them.

## The hit is supplied, not derived

`POST /builds/{id}/explain` takes a `hit` — multiplier, scaling stat, damage channel,
scope — or **names a talent**, and the multiplier is resolved from the build's own character
at its own talent level (M.2). That was the kit corpus's job and there is no kit corpus, so it
waited: parsing a multiplier out of a `desc` string and serving the result would have been
presenting a guess as the game's own number. It is not a guess now — `talent_scaling` parses
the published table and M.4 checked that parse against gcsim across 105 characters and 18,611
hits before anything read it.

**The channel is still the caller's.** The table gives a multiplier and says nothing about
which element the hit lands as.

## The search is not here any more

C.6 deleted `/optimize` and `/rank-artifacts`. Searching runs in the browser (DESIGN §3.5:
nothing combinatorial lands on the server), and what is left here is the part that reads the
database — explaining one build, and comparing candidate weapons in it. Both reach the damage
chain through `build_combination_log`, which stays the single definition of what five
artifacts are worth.
"""

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.artifacts import _kernel_stats
from app.dependencies import (
    CurrentUser,
    SettingsDep,
    get_artifact_set_repo,
    get_character_repo,
    get_enemy_profile_repo,
    get_owned_artifact_repo,
    get_owned_build_repo,
    get_owned_rotation_repo,
    get_owned_sim_run_repo,
    get_weapon_repo,
)
from app.formula.genshin import tags
from app.formula.genshin.damage import Hit, ScalingStat, ScalingTerm
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.enums import LEVELLED_TALENTS, MAX_STORED_TALENT_LEVEL
from app.repositories.artifact import ArtifactRepository
from app.repositories.artifact_set import ArtifactSetRepository
from app.repositories.build import BuildRepository
from app.repositories.character import CharacterRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.rotation import RotationRepository
from app.repositories.sim_run import SimRunRepository
from app.repositories.weapon import WeaponRepository
from app.schemas.build import (
    AvailableHitRead,
    BuildCreate,
    BuildOptions,
    BuildPriorityOrder,
    BuildPriorityRead,
    BuildRead,
    BuildUpdate,
    CalibrationConfigs,
    CalibrationRequest,
    CompareWeaponsRequest,
    CompareWeaponsResponse,
    ContributionRead,
    EnemySpec,
    EquippedStatsRead,
    ExplainRequest,
    ExplainResponse,
    GcsimCandidateConfig,
    GcsimComparisonConfigs,
    GcsimComparisonRequest,
    HitSpec,
    KernelHit,
    KernelSetBonus,
    KernelTarget,
    RefusedCandidate,
    RefusedHitRead,
    ScalingTermRead,
    SearchContextRead,
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
    gcsim_keys,
    sim_retrieval,
    weapon_comparison,
)
from app.services.build_assembler import BuildAssemblyError
from app.services.damage_calculator import BuildEvaluator, Enemy, enemy_from_profile
from app.services.gcsim_config import (
    Calibration,
    GcsimConfigError,
    SubstituteWeapon,
    build_config,
    character_order,
)
from app.services.gcsim_keys import GcsimKeyError, pinned_commit
from app.services.quotas import enforce_quota
from app.services.rotation_compiler import RotationCompileError, compile_rotation
from app.services.stat_calculator import StatInputError
from app.services.talent_boosts import TalentBoostError, effective_talent_levels
from app.services.talent_hits import (
    TalentHitUnavailableError,
    available_hits,
    refused_hits,
    resolve_talent_hit,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.formula.genshin.explain import Contribution
    from app.models.artifact import Artifact, ArtifactSet
    from app.models.build import Build
    from app.models.weapon import Weapon

router = APIRouter(prefix="/builds", tags=["builds"])

_Offset = Annotated[int, Query(ge=0)]
_Limit = Annotated[int, Query(ge=1, le=200)]


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


@router.put("/priority", response_model=BuildPriorityRead)
@limiter.limit(WRITE_LIMIT)
async def set_build_priority(
    request: Request,  # slowapi reads the client address off it
    body: BuildPriorityOrder,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildPriorityRead:
    """Set the owner's build ranking, best first.

    `BACKLOG_frontend.md` §3. The ranking answers "who gets the piece" when two builds want
    the same artifact — see the optimizer's equip path, which until now refused outright.

    **Declared before `/{build_id}` on purpose.** FastAPI matches in declaration order, so a
    literal path registered after a parameterised one is unreachable: `/priority` would arrive
    as `build_id="priority"` and 404 as a missing build. That is a silent routing bug, not an
    error, which is why it is stated here rather than left to path order to imply.
    """
    ranked = await repo.set_priority_order(body.build_ids)
    return BuildPriorityRead(ranked=ranked)


@router.get("/options", response_model=BuildOptions)
async def build_options(_: CurrentUser) -> BuildOptions:
    """The talent keys a build may carry, and the level cap.

    Declared **above** `/{build_id}` — FastAPI matches in declaration order, and below it this
    path is a build whose id is the word "options", which 404s and looks like an empty form
    rather than a routing mistake. Same trap R.5 met.

    No database, no owner: this is the vocabulary, not the caller's data. It still requires a
    bearer token, because everything under `/builds` does and an exception would be a hole
    someone has to remember.
    """
    return BuildOptions(
        talents=[str(talent) for talent in LEVELLED_TALENTS],
        max_talent_level=MAX_STORED_TALENT_LEVEL,
    )


@router.post("", response_model=BuildRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_build(
    request: Request,
    body: BuildCreate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    characters: _Characters,
    weapons: _Weapons,
    settings: SettingsDep,
) -> BuildRead:
    """Save a build, having checked it is one that could exist."""
    # The layer that assumes every bot defence failed. `DESIGN_open_registration.md` §3.3.
    await enforce_quota(repo, settings.MAX_BUILDS_PER_USER, "Build")
    await _validated_pairing(
        characters, weapons,
        character_id=body.character_id, weapon_id=body.weapon_id,
    )
    build = await repo.create({**body.model_dump(), "owner_id": repo.owner_id})
    # Re-read eagerly. The instance just created has no relationships loaded, and
    # `GUARDED_LAZY` is `raise_on_sql`, so `BuildRead` reading `.character` off it is a
    # `MissingGreenlet` in production — invisible in a test, whose session already holds the
    # catalogue rows it made moments earlier (T.1a).
    return BuildRead.model_validate(await repo.get_with_catalogue(str(build.id)))


@router.get("/{build_id}", response_model=BuildRead)
async def get_build(
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """One of the caller's builds, with the catalogue rows a page draws it from."""
    build = await repo.get_with_catalogue(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found")
    return BuildRead.model_validate(build)


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
        return BuildRead.model_validate(await repo.get_with_catalogue(build_id))

    merged_character = patch.get("character_id", existing.character_id)
    # `.get` with a default is right here only because `exclude_unset` already dropped the
    # keys that were not sent: an explicit `"weapon_id": null` means *unequip* and must
    # survive as None rather than falling back to the stored weapon.
    merged_weapon = patch.get("weapon_id", existing.weapon_id)
    await _validated_pairing(
        characters, weapons,
        character_id=merged_character, weapon_id=merged_weapon,
    )

    await repo.update(build_id, patch)
    return BuildRead.model_validate(await repo.get_with_catalogue(build_id))


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


@router.get("/{build_id}/hits", response_model=list[AvailableHitRead])
async def build_hits(
    build_id: str,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> list[AvailableHitRead]:
    """Every hit this build can be asked about, at its own talent levels.

    M.2. What `HitSpec.talent` will accept, from the same parse that resolves it — so a page
    offering these cannot name one the resolver refuses.

    A talent the build has no level for is **absent rather than offered**: offering it would
    produce a refusal the moment it was picked. A build with no character returns nothing,
    which is the truthful answer rather than a 404 about a build that exists.
    """
    build = await _require_full_build(builds, build_id)
    if build.character is None:
        return []
    return [
        AvailableHitRead(
            talent=hit.talent, label=hit.label, index=hit.index,
            multiplier=hit.multiplier, hits=hit.hits, exclusive=hit.exclusive,
            scaling_stat=hit.scaling_stat,
            extra_terms=[
                ScalingTermRead(stat=term.stat, multiplier=term.multiplier)
                for term in hit.extra_terms
            ],
        )
        for hit in available_hits(build.character, _hit_levels(build))
    ]


@router.get("/{build_id}/hits/refused", response_model=list[RefusedHitRead])
async def build_refused_hits(
    build_id: str,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> list[RefusedHitRead]:
    """The damage rows this build's talents carry that cannot be scored, each with its reason.

    **A sibling of `/hits`, not entries in it.** `/hits` promises that everything it lists is
    something `HitSpec` accepts, and every consumer relies on that — the search context, the
    explain call, the kernels. Folding refusals into it would break that promise for every
    client that does not know to skip them. Here they are published for the pickers to show
    greyed out (owner, 2026-11-13), from the same rows at the same levels.
    """
    build = await _require_full_build(builds, build_id)
    if build.character is None:
        return []
    return [
        RefusedHitRead(talent=r.talent, label=r.label, spec=r.spec, reason=r.reason)
        for r in refused_hits(build.character, _hit_levels(build))
    ]


@router.post("/{build_id}/search-context", response_model=SearchContextRead)
@limiter.limit(WRITE_LIMIT)
async def search_context(
    request: Request,  # slowapi reads the client address off it
    build_id: str,
    body: ExplainRequest,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    artifacts: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    enemies: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
) -> SearchContextRead:
    """Everything the browser kernel needs to search, except the inventory.

    O.1. `frontend/src/app/sim/search.ts` has been a working optimizer that nothing could
    reach, because `SearchContext` needs a hit and a base — and the base is keyed by **kernel
    quantity** while the API speaks `FIGHT_PROP_*`. That mapping is
    `stat_calculator._quantity_for_prop`; it decides what every stat means and refuses rather
    than guessing, so a TypeScript copy of it would be a second definition of the vocabulary
    with a silent failure mode.

    Takes the same body as `/explain` deliberately: a caller asking "what should I wear for
    this hit" and one asking "why does this score what it does" are describing the same hit,
    and two request shapes for one description is how they drift apart.

    The inventory is **not** here. `/artifacts/inventory` carries it, ETag'd, because the
    browser holds it across searches and revalidates cheaply (OQ-S3).
    """
    build = await _require_full_build(builds, build_id)
    hit = _hit(body.hit, build)
    enemy = await _enemy(body.enemy, enemies)

    # **Summed per quantity.** `base_atk` has several contributors (the character's curve, the
    # weapon's, the weapon's ascension) and so does `base_hp`. This was a dict comprehension,
    # which kept only the last contribution to each quantity — the kernel scored Neuvillette
    # on his ascension HP bonus alone, 4,697.8 of 14,695. Found driving math-fallback P0.
    base: dict[str, float] = {}
    for contribution in _base_contributions(build):
        base[contribution.quantity] = base.get(contribution.quantity, 0.0) + contribution.value

    # Every set the caller owns a piece of, not only the sets currently worn: the search is
    # free to propose a build using pieces from a set this build is not wearing, and a bonus
    # the kernel was never told about is one it cannot score.
    #
    # Asked as a set question, not by reading the inventory: `search`'s cap is 20,000, and
    # deriving sets from a capped read would silently omit one from a larger account.
    bonuses = build_assembler.set_bonuses(await artifacts.owned_sets())

    return SearchContextRead(
        base=base,
        hit=KernelHit(
            multiplier=hit.multiplier,
            channel=hit.channel,
            scaling_stat=str(hit.scaling_stat),
            amplifying=str(hit.amplifying) if hit.amplifying is not None else None,
            extra_terms=[
                ScalingTermRead(stat=term.stat, multiplier=term.multiplier)
                for term in hit.extra_terms
            ],
        ),
        target=KernelTarget(
            level=enemy.level,
            # One number, because the kernel scores one channel. Taken from the hit's own
            # channel rather than averaged — an average is a resistance no enemy has.
            resistance=enemy.resistances[hit.channel],
        ),
        character_level=build.character_level,
        dmg_bonus_quantity=tags.dmg_bonus_q(hit.channel),
        set_bonuses=[
            KernelSetBonus(
                set_id=tier.set_id,
                pieces_required=tier.pieces_required,
                stats=build_assembler.bonus_stats(tier),
            )
            for tier in bonuses
        ],
    )


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
    hit, enemy = _hit(body.hit, build), await _enemy(body.enemy, enemies)

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
        proposed, proposed_damage, proposed_totals = _scored(
            base, proposed_rows, bonuses, hit, enemy, build.character_level,
        )
        equipped = proposed
        equipped_damage = proposed_damage
        if body.compare_to_equipped and body.artifact_ids is not None:
            equipped, equipped_damage, _ = _scored(
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
        # The **proposed** build's totals, matching `damage` and `stats` above. The equipped
        # build's are deliberately not published: this response describes one build, and a
        # second stat block under the same keys is how a reader ends up reading the wrong one.
        totals=proposed_totals,
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

    - **Weapon passives are not applied here.** They are imported into `weapon_refinements`,
      and 242 of 260 weapons carry one while 5 are expressible in this chain — so the gap is
      frequently the entire reason to equip a weapon. `unmodelled_passives` names every
      candidate that has a passive and the response's `caveat` says the ordering may be wrong.
      **`POST /compare-weapons/gcsim` is the tier that does apply them** (W.6): it costs
      minutes rather than milliseconds, so this endpoint stays rather than being replaced.
    - **Artifacts are held fixed.** DESIGN §3.5's fuller version searches per weapon and
      compares the winners, but searches belong on the client. This answers "which weapon is
      better in the build I have", which is a cheaper and different question — a weapon
      wanting a different artifact set loses a comparison it would win with its own pieces.

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
            _hit(body.hit, build),
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
) -> "tuple[tuple[Contribution, ...], float, dict[str, float]]":
    """Contributions, damage, and the resolved stat totals for one set of pieces.

    The totals come from the **same evaluator** that produced the damage, under the same
    scope. Resolving them separately would let the printed stats and the printed number
    describe two different builds — which is the drift the contribution log's own
    tag/quantity check exists to make impossible one layer down.
    """
    combination = build_assembler.candidates(rows)
    log, _ = artifact_optimizer.build_combination_log(
        base, combination, artifact_optimizer.bonuses_by_set(bonuses),
    )
    evaluator = BuildEvaluator(
        registry=log.registry, enemy=enemy, character_level=character_level,
    )
    return tuple(log.contributions), evaluator.evaluate(hit).expected, evaluator.totals(hit.scope)


def _burst_energy_costs(
    keys: "Sequence[str]", builds: "Sequence[Build]",
) -> list[int | None]:
    """Each key's burst energy cost, or `None` where the burst does not use energy.

    Paired the same way `_display_names` pairs — through `gcsim_keys.character_key` rather than
    by position — so a reordering upstream cannot attach one character's cost to another.
    """
    by_key: dict[str, int | None] = {}
    for build in builds:
        character = build.character
        if character is None:
            continue
        try:
            key = gcsim_keys.character_key(
                str(character.nanoka_id), character.name, character.element,
            )
        except gcsim_keys.GcsimKeyError:
            continue
        by_key[key] = character.burst_energy_cost
    return [by_key.get(key) for key in keys]


def _display_names(keys: "Sequence[str]", builds: "Sequence[Build]") -> list[str]:
    """Display names for gcsim keys, in the order the keys are given.

    Keyed by `gcsim_keys.character_key` — the same function that produced the config's names —
    so the pairing cannot drift. A key nothing matches keeps the key: a wrong name is worse
    than a raw one, because only one of them looks wrong.
    """
    by_key: dict[str, str] = {}
    for build in builds:
        character = getattr(build, "character", None)
        if character is None:
            continue
        try:
            # `nanoka_id` first: every Traveler variant is named "Traveler" and only the id
            # says which body it is, so the name alone cannot resolve one.
            key = gcsim_keys.character_key(
                str(character.nanoka_id), character.name, character.element,
            )
        except GcsimKeyError:
            continue
        by_key[key] = character.name
    return [by_key.get(key, key) for key in keys]


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


def _hit_levels(build: "Build") -> dict[str, int]:
    """The talent levels this build's own hits are read at: stored, plus C3/C5 boosts.

    Math-fallback 9b. Every reader of a hit here — `/hits`, `/hits/refused`, `/explain`,
    `/search-context` — goes through this, so the picker, the explanation and the kernel see
    the same multiplier. The gcsim config does **not**: gcsim adds the boost itself
    (`app/services/talent_boosts.py` lists who adds it and why).
    """
    if build.character is None:
        return dict(build.talent_levels or {})
    try:
        return effective_talent_levels(
            build.character, build.constellation_level, build.talent_levels or {},
        )
    except TalentBoostError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _hit(spec: HitSpec, build: "Build") -> Hit:
    """The hit to score, with a named talent resolved against the build's own character.

    M.2. `HitSpec` takes exactly one of `multiplier` or `talent`; a named talent is looked up
    at the level *this build* has it, because a talent-9 burst reported at talent 1 is 59% of
    its real multiplier and the result still looks like a damage figure.
    """
    multiplier = spec.multiplier
    scaling_stat = spec.scaling_stat or ScalingStat.ATK
    extra_terms: tuple[ScalingTerm, ...] = ()
    if spec.talent is not None:
        if build.character is None:
            raise HTTPException(
                status_code=422,
                detail="this build has no character, so a talent cannot be resolved.",
            )
        try:
            resolved = resolve_talent_hit(
                build.character,
                _hit_levels(build),
                spec.talent.talent,
                spec.talent.label,
                index=spec.talent.index,
            )
        except TalentHitUnavailableError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Math-fallback P0: the talent's row names its stat. A body that says otherwise is
        # stating two stats for one hit, refused for the reason `multiplier`-and-`talent` is.
        if spec.scaling_stat is not None and spec.scaling_stat != resolved.scaling_stat:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{spec.talent.label!r} scales off {resolved.scaling_stat}, and the "
                    f"request says {spec.scaling_stat}. Omit `scaling_stat` with a named "
                    f"talent: its own row says what it scales off."
                ),
            )
        multiplier = resolved.multiplier
        scaling_stat = resolved.scaling_stat
        extra_terms = resolved.extra_terms

    return Hit(
        multiplier=multiplier,
        channel=spec.channel,
        scope=spec.scope,
        scaling_stat=scaling_stat,
        amplifying=spec.amplifying,
        flat_damage=spec.flat_damage,
        extra_terms=extra_terms,
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


@router.post(
    "/{build_id}/compare-weapons/gcsim", response_model=GcsimComparisonConfigs,
)
@limiter.limit(WRITE_LIMIT)
async def compare_weapons_gcsim_configs(
    request: Request,
    build_id: str,
    body: GcsimComparisonRequest,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    rotations: Annotated[RotationRepository, Depends(get_owned_rotation_repo)],
    weapons: Annotated[WeaponRepository, Depends(get_weapon_repo)],
    enemies: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
) -> GcsimComparisonConfigs:
    """The gcsim configs for a weapon comparison — one per candidate (W.6).

    **This is the tier that knows weapon passives.** `POST /compare-weapons` ranks on base ATK
    and the substat and reports `unmodelled_passives`, which is not a precision caveat: 242 of
    260 weapons carry a passive and 5 are expressible in the Chunk F chain, so a stat-stick can
    outrank the weapon whose passive is the entire reason to equip it. gcsim implements them.

    **The server emits configs and does not simulate.** `RESEARCH_gcsim_embed.md` §6 put gcsim
    in the browser, and W.4 measured a full sword pool at ~96 s across four workers — a job on
    the user's machine, not a request a server holds open. The browser runs these through
    `sim/gcsim.ts` and ranks them with `sim/weapon-ranking.ts`, which reports which pairs the
    run could **not** separate.

    **A candidate gcsim cannot key is refused by name, never dropped.** A silently omitted
    candidate produces a ranking missing a weapon the user asked about, and the omission is
    invisible because the result still looks like a complete answer.
    """
    build = await _require_full_build(builds, build_id)
    if build.character is None:
        raise HTTPException(
            status_code=422, detail="this build has no character; there is nothing to simulate",
        )

    rotation = await rotations.get_by_id(body.rotation_id)
    if rotation is None:
        raise HTTPException(status_code=404, detail="rotation not found")
    roster = await rotations.character_rows(rotation.team_id)
    if build.character.nanoka_id not in roster:
        # The rotation never acts on this build's character, so every candidate would score
        # the same team damage with this build standing still — a flat ranking that reads as
        # "these weapons are equivalent".
        raise HTTPException(
            status_code=422,
            detail=(
                f"rotation {body.rotation_id} is for a team that does not include "
                f"{build.character.name}, so it never acts on this build. Comparing weapons "
                f"against it would rank them all identically."
            ),
        )
    try:
        action_block = compile_rotation(rotation.steps or [], roster)
    except RotationCompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # **The whole team, not just this build.** The action block is the *team's* rotation, so a
    # config declaring one character names three it never introduces — and gcsim does not
    # reject that. It simulates nobody: empty log, zero damage, returned as valid JSON. Every
    # recipe calibrated to zeros and `/optimize` ranked ten builds at 0 while reporting
    # `isExact` (`AUDIT_fribbels_parity.md` §9a).
    #
    # Loaded fully, because a teammate's buffs depend on their own gear — a Furina at her real
    # HP is a different Furina — which is also the point of calibrating "in this team" at all.
    teammates = [
        await _require_full_build(builds, other_id)
        for other_id in await rotations.team_build_ids(rotation.team_id)
        if other_id != str(build.id)
    ]

    # A rotation carries no enemy — it is a team's action list, not a scenario — so the
    # caller names one or gcsim's default target is used. The first draft reached for
    # `rotation.enemy_profile_id` behind a `getattr` default, which would have been dead code
    # silently choosing the default forever.
    enemy = await enemies.get_by_id(body.enemy_id) if body.enemy_id else None
    if body.enemy_id and enemy is None:
        raise HTTPException(status_code=404, detail=f"enemy profile {body.enemy_id} not found")

    def _config(substitute: SubstituteWeapon | None) -> str:
        return build_config(
            build,
            teammates=teammates,
            substitute_weapon=substitute,
            action_block=action_block,
            enemy=enemy,
            iterations=body.iterations,
        )

    equipped = None
    if build.weapon is not None:
        try:
            equipped = GcsimCandidateConfig(
                weapon_id=build.weapon.id, name=build.weapon.name, config=_config(None),
            )
        except (GcsimKeyError, GcsimConfigError) as exc:
            # The worn weapon failing is not a candidate failing: there is no baseline, and a
            # comparison with no baseline is a list of numbers.
            raise HTTPException(
                status_code=422,
                detail=f"the equipped weapon cannot be simulated at the pin: {exc}",
            ) from exc

    candidates: list[GcsimCandidateConfig] = []
    refused: list[RefusedCandidate] = []
    for weapon_id in body.weapon_ids:
        weapon = await weapons.get_by_id(weapon_id)
        if weapon is None:
            refused.append(RefusedCandidate(weapon_id=weapon_id, reason="not in the catalogue"))
            continue
        try:
            config = _config(
                SubstituteWeapon(weapon=weapon, level=build.weapon_level, refinement=1),
            )
        except (GcsimKeyError, GcsimConfigError) as exc:
            refused.append(RefusedCandidate(weapon_id=weapon_id, reason=str(exc)))
            continue
        candidates.append(
            GcsimCandidateConfig(weapon_id=weapon_id, name=weapon.name, config=config),
        )

    return GcsimComparisonConfigs(
        equipped=equipped,
        candidates=candidates,
        refused=refused,
        iterations=body.iterations,
    )


@router.post("/{build_id}/calibrate", response_model=CalibrationConfigs)
@limiter.limit(WRITE_LIMIT)
async def calibrate_recipe(
    request: Request,
    build_id: str,
    body: CalibrationRequest,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    rotations: Annotated[RotationRepository, Depends(get_owned_rotation_repo)],
    sets: Annotated[ArtifactSetRepository, Depends(get_artifact_set_repo)],
    enemies: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
    weapons: Annotated[WeaponRepository, Depends(get_weapon_repo)],
) -> CalibrationConfigs:
    """The two gcsim configs a damage recipe is built from (R.3).

    **The server emits; the browser runs.** `RESEARCH_gcsim_embed.md` §6 put gcsim in the
    browser, and a calibration is ~3.2 s of work per set — a job on the user's machine, not a
    request a server holds open.

    **One calibration per 4-piece state.** Every 4-piece bonus in the game is conditional
    (`RESEARCH_conditional_sets.md`), so only a run with the set equipped can hold it, and R.2
    measured the cost of not doing so at **15–25 % understated**. A five-slot combination
    reaches at most one 4-piece, which is what keeps this `S + 1` rather than a product.

    **The probe moves exactly one stat.** `resolveConversions` identifies what a frozen term
    converts from by comparing the two runs; a probe that moved two stats by the same factor
    could not separate them, and the recipe would rather report a conversion unresolved than
    guess between them.
    """
    build = await _require_full_build(builds, build_id)
    if build.character is None:
        raise HTTPException(
            status_code=422, detail="this build has no character; there is nothing to simulate",
        )

    rotation = await rotations.get_by_id(body.rotation_id)
    if rotation is None:
        raise HTTPException(status_code=404, detail="rotation not found")
    roster = await rotations.character_rows(rotation.team_id)
    if build.character.nanoka_id not in roster:
        raise HTTPException(
            status_code=422,
            detail=(
                f"rotation {body.rotation_id} is for a team that does not include "
                f"{build.character.name}, so it never acts on this build. A calibration "
                f"against it would describe a rotation this build does not perform."
            ),
        )
    try:
        action_block = compile_rotation(
            rotation.steps or [], roster, wait_for_energy=body.wait_for_energy,
        )
    except RotationCompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # The whole team — see the identical note on the weapon-comparison endpoint above. This is
    # the one where it caused the zero-damage bug.
    teammates = [
        await _require_full_build(builds, other_id)
        for other_id in await rotations.team_build_ids(rotation.team_id)
        if other_id != str(build.id)
    ]

    async def _key_for(set_id: str) -> str:
        """The gcsim key for a catalogue set id, refusing rather than dropping.

        Calibrating without the set would produce a recipe that silently understates it by
        the whole bonus the caller asked to have scored.
        """
        artifact_set = await sets.get_by_id(set_id)
        if artifact_set is None:
            raise HTTPException(status_code=404, detail=f"artifact set {set_id} not found")
        try:
            return gcsim_keys.artifact_set_key(artifact_set.name)
        except GcsimKeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"gcsim does not implement {artifact_set.name} at the pin: {exc}",
            ) from exc

    set_key = (
        await _key_for(body.artifact_set_id) if body.artifact_set_id is not None else None
    )
    # B.3 — a 2+2 state. Equipped rather than added as stats because nine of the sixty
    # 2-piece bonuses are conditional, six of them ability-scoped in a way no flat stat pool
    # can express (owner ruling 1, `docs/DECISIONS.md`).
    two_piece_keys = tuple([await _key_for(set_id) for set_id in body.two_piece_set_ids])

    enemy = await enemies.get_by_id(body.enemy_id) if body.enemy_id else None
    if body.enemy_id and enemy is None:
        raise HTTPException(status_code=404, detail=f"enemy profile {body.enemy_id} not found")

    # **The weapon comparison's own calibration.** `body.weapon_id` names a weapon to emit in
    # place of the build's, and it is resolved here rather than trusted: a substitution that
    # silently did nothing would produce a *flat ranking* — every weapon scoring the worn
    # weapon's number — which reads as "these are equivalent" rather than as a bug, and is a
    # conclusion a user would believe. `SubstituteWeapon` states the same argument at length.
    #
    # The refinement is the build's own, and the level is too: ranking a level-90 worn weapon
    # against a level-1 candidate measures levelling rather than weapons.
    substitute: SubstituteWeapon | None = None
    if body.weapon_id is not None and body.weapon_id != str(
        build.weapon.id if build.weapon else "",
    ):
        candidate = await weapons.get_by_id(body.weapon_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"weapon {body.weapon_id} not found")
        substitute = SubstituteWeapon(
            weapon=candidate,
            level=build.weapon_level,
            refinement=build.refinement,
        )

    def _config(calibration: Calibration, extra: str | None = None) -> str:
        text = build_config(
            build,
            teammates=teammates,
            calibration=calibration,
            substitute_weapon=substitute,
            action_block=action_block,
            enemy=enemy,
            iterations=body.iterations,
            energy_drip=body.wait_for_energy,
        )
        if extra is None:
            return text
        # The probe's stat rides on the calibration's own `add stats` line, so the two configs
        # differ in exactly one place. A second line would also work and would make the diff
        # harder for a human to check, which is the thing that matters when a number is wrong.
        return text.replace(
            f"add stats er={calibration.energy_recharge:g};",
            f"add stats er={calibration.energy_recharge:g} {extra};",
        )

    try:
        calibration = Calibration(
            set_key=set_key,
            energy_recharge=body.energy_recharge,
            two_piece_set_keys=two_piece_keys,
        )
    except ValueError as exc:
        # Five slots cannot hold a 4-piece and a 2+2 at once.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        baseline = _config(calibration)
        # Sorted, so two runs of the same request produce byte-identical configs — the
        # recipe cache keys on the config's content downstream, and a dict's order is not a
        # promise worth resting that on.
        probe = _config(
            calibration,
            " ".join(f"{stat}={delta:g}" for stat, delta in sorted(body.probe_deltas.items())),
        )
    except (GcsimKeyError, GcsimConfigError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CalibrationConfigs(
        baseline=baseline,
        probe=probe,
        characters=character_order(baseline),
        # The same order, as a player reads them. `character_order` returns gcsim keys, and
        # `kaedeharakazuha` on a damage-share row is the raw-key ugliness this repo keeps
        # fixing one field at a time. Mapped through `character_key` rather than by position,
        # so a reordering upstream cannot silently pair a name with the wrong character.
        character_names=_display_names(character_order(baseline), [build, *teammates]),
        # Positional against `characters`, and **`None` where the burst costs no energy** —
        # Skirk spends Serpent's Subtlety. A caller comparing burst counts across a
        # free-energy counterfactual must not read her as starved: the counterfactual moves
        # the whole team's timing, so her count changes for reasons that are not hers.
        burst_energy_costs=_burst_energy_costs(
            character_order(baseline), [build, *teammates],
        ),
        artifact_set_id=body.artifact_set_id,
        two_piece_set_ids=body.two_piece_set_ids,
        energy_recharge=body.energy_recharge,
        probe_deltas=body.probe_deltas,
    )


@router.get("/{build_id}/equipped-stats", response_model=EquippedStatsRead)
async def equipped_stats(
    build_id: str,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> EquippedStatsRead:
    """The build's equipped artifacts, summed in the kernel's quantities.

    What `/calculate` needs to evaluate a calibrated recipe at a build's *real* gear — the
    recipe is calibrated at a reference set of stats, and this is what replaces them.

    Deliberately not part of `/artifacts/inventory`: that payload is fetched across a whole
    inventory, and a field added to it is paid for once per artifact. This answers a question
    about five.
    """
    build = await _require_full_build(builds, build_id)
    totals: dict[str, float] = {}
    pieces = 0
    for artifact in build.artifacts:
        pieces += 1
        for quantity, value in _kernel_stats(artifact).items():
            totals[quantity] = totals.get(quantity, 0.0) + value
    return EquippedStatsRead(stats=totals, pieces=pieces)
