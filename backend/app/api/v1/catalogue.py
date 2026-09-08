"""Catalogue read endpoints — the seeded game data, over HTTP at last.

Chunk D filled 18 tables and Chunk E supplied what nanoka does not publish; until now
nothing exposed any of it and the API served seven paths. These are the read routes for
characters, weapons, artifact sets and enemy profiles.

**Public, and read-only.** The catalogue is the game's data, not a user's: there is nothing
to scope to an owner and nothing here writes. The rows come from
`python -m scripts.seed_db`, and a route that let a request edit them would put fabricated
game data behind an API whose only value is that it is not fabricated.

**A `total` counts the filter.** Every list envelope's `total` is computed with the same
`WHERE` the page used. A bare table count next to a filtered page tells a client there are
150 results and then hands it three, which reads as a broken page rather than a broken
count.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import (
    get_artifact_set_repo,
    get_character_repo,
    get_enemy_profile_repo,
    get_owned_weapon_repo,
    get_weapon_repo,
)
from app.models.enums import Element, Rarity, WeaponType
from app.repositories.artifact_set import ArtifactSetRepository
from app.repositories.character import CharacterRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.owned_weapon import OwnedWeaponRepository
from app.repositories.weapon import WeaponRepository
from app.schemas.catalogue import (
    ArtifactSetRead,
    CharacterRead,
    CharacterSummary,
    CharacterWeaponGuideRead,
    ElementRead,
    EnemyProfileRead,
    OwnedWeaponRead,
    ReactionRead,
    SetRecommendationRead,
    WeaponClassRead,
    WeaponRead,
    WeaponRecommendationRead,
    WeaponSummary,
)
from app.schemas.common import PaginatedResponse
from app.services import gcsim_keys, kqm_weapons
from app.services.element_symbols import all_visions
from app.services.reactions import offered
from app.services.unreleased import is_unreleased_class
from app.services.weapon_symbols import all_classes

router = APIRouter(tags=["catalogue"])

_Offset = Annotated[int, Query(ge=0)]
_Limit = Annotated[int, Query(ge=1, le=200)]


@router.get("/characters", response_model=PaginatedResponse[CharacterSummary])
async def list_characters(
    repo: Annotated[CharacterRepository, Depends(get_character_repo)],
    element: Element | None = None,
    weapon_type: WeaponType | None = None,
    rarity: Rarity | None = None,
    name: str | None = None,
    include_beta: bool = False,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[CharacterSummary]:
    """List characters, filtered by element, weapon type, rarity or name substring.

    **`include_beta` defaults to false, and that default is the feature.** Characters the
    manifest names as unreleased are seeded and marked rather than withheld (owner, 2026-09-07)
    so `/planner` can price an upcoming one. Every other caller keeps the old list without
    changing a line — and because the build editor never lists them, a beta character cannot
    reach a build and so cannot reach the optimizer, which is the exclusion that was asked for.
    """
    filters = {
        "element": element, "weapon_type": weapon_type, "rarity": rarity, "name": name,
        "include_beta": include_beta,
    }
    rows = await repo.search(**filters, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[CharacterSummary.model_validate(row) for row in rows],
        total=await repo.count_filtered(**filters),
        offset=offset,
        limit=limit,
    )


@router.get("/characters/{nanoka_id}", response_model=CharacterRead)
async def get_character(
    nanoka_id: str,
    repo: Annotated[CharacterRepository, Depends(get_character_repo)],
) -> CharacterRead:
    """One character with its talents, constellations and ascension passives.

    The path parameter is a **string**: 28 of the 150 characters are keyed `10000005-2` …
    `10000005-8`, and they are **14 Traveler variants plus 14 practice mannequins**
    (`10000117`/`10000118` are Manekin and Manekina, not Traveler bodies). Typing it as an int
    would 422 on all of them.
    """
    character = await repo.get_by_nanoka_id(nanoka_id)
    if character is None:
        raise HTTPException(status_code=404, detail=f"No character {nanoka_id!r}")
    return CharacterRead.model_validate(character)


@router.get("/weapons", response_model=PaginatedResponse[WeaponSummary])
async def list_weapons(
    repo: Annotated[WeaponRepository, Depends(get_weapon_repo)],
    weapon_type: WeaponType | None = None,
    rarity: Rarity | None = None,
    name: str | None = None,
    include_beta: bool = False,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[WeaponSummary]:
    """List weapons, filtered by type, rarity or name substring.

    **`include_beta` defaults to false**, the twin of the character list's. Only `/planner`
    asks, so the build editor never offers a beta weapon and no build can hold one.

    It does **not** reach the eight rows carrying an unshipped weapon class: those are a
    different exclusion and no flag turns them on.
    """
    filters = {
        "weapon_type": weapon_type, "rarity": rarity, "name": name,
        "include_beta": include_beta,
    }
    rows = await repo.search(**filters, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[WeaponSummary.model_validate(row) for row in rows],
        total=await repo.count_filtered(**filters),
        offset=offset,
        limit=limit,
    )


# **Declared before `/weapons/{nanoka_id}`, and it has to be.** FastAPI matches in declaration
# order, so with this below the parameterised route, `owned` was parsed as a nanoka id and the
# endpoint answered `422 int_parsing` — a route that exists and is unreachable. Found by calling
# it rather than by reading it.
@router.get("/weapons/owned", response_model=PaginatedResponse[OwnedWeaponRead])
async def list_owned_weapons(
    repo: Annotated[OwnedWeaponRepository, Depends(get_owned_weapon_repo)],
    equipped: bool | None = None,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[OwnedWeaponRead]:
    """The caller's own weapons — **equipped first**, then by refinement and level.

    Distinct from `/weapons`, which is the 260-row catalogue of every weapon in the game. This
    is what you have, and until now nothing published it: a GOOD export lists 320 weapons and
    the importer used 68 of them to set `builds.weapon_id`, discarding the rest.

    Equipped-first is the **default order rather than a sort option**, because it answers
    "what am I actually using" without the user having to ask.
    """
    rows = await repo.search(equipped=equipped, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[OwnedWeaponRead.of(row) for row in rows],
        total=await repo.count_filtered(equipped=equipped),
        offset=offset,
        limit=limit,
    )


@router.get("/weapons/{nanoka_id}", response_model=WeaponRead)
async def get_weapon(
    nanoka_id: int,
    repo: Annotated[WeaponRepository, Depends(get_weapon_repo)],
) -> WeaponRead:
    """One weapon with its refinement rows and growth curves.

    A row whose class the game has not shipped answers 404 like a row that is not there. The
    list hides these eight because their **names** are datamine-only (`services/unreleased.py`,
    #271), and a detail route that still serves the name on request publishes exactly what
    hiding the list was for — a guessable id is not a meaningful barrier.
    """
    weapon = await repo.get_by_nanoka_id(nanoka_id)
    if weapon is None or is_unreleased_class(weapon.weapon_type):
        raise HTTPException(status_code=404, detail=f"No weapon {nanoka_id}")
    return WeaponRead.model_validate(weapon)


@router.get("/artifact-sets", response_model=PaginatedResponse[ArtifactSetRead])
async def list_artifact_sets(
    repo: Annotated[ArtifactSetRepository, Depends(get_artifact_set_repo)],
    name: str | None = None,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[ArtifactSetRead]:
    """List artifact sets with their bonus affixes, and whether gcsim can simulate each."""
    rows = await repo.search(name=name, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[_set_read(row) for row in rows],
        total=await repo.count_filtered(name=name),
        offset=offset,
        limit=limit,
    )


def _set_read(row: object) -> ArtifactSetRead:
    """One set, with `simulable` answered by the same lookup a run would use.

    **Asked here rather than inferred by a client.** The optimizer offered every set the
    inventory could field four of, gcsim has no key for some of them, and one such set fails
    the whole calibration with a 422 — so a run over a mixed selection returned nothing rather
    than the sets it could have done. The picker can only offer what runs if the server says
    which those are.
    """
    read = ArtifactSetRead.model_validate(row)
    try:
        gcsim_keys.artifact_set_key(read.name)
    except gcsim_keys.GcsimKeyError:
        read.simulable = False
    else:
        read.simulable = True
    return read


@router.get("/artifact-sets/{nanoka_id}", response_model=ArtifactSetRead)
async def get_artifact_set(
    nanoka_id: int,
    repo: Annotated[ArtifactSetRepository, Depends(get_artifact_set_repo)],
) -> ArtifactSetRead:
    """One artifact set with its affixes."""
    artifact_set = await repo.get_by_nanoka_id(nanoka_id)
    if artifact_set is None:
        raise HTTPException(status_code=404, detail=f"No artifact set {nanoka_id}")
    return _set_read(artifact_set)


@router.get("/enemies", response_model=PaginatedResponse[EnemyProfileRead])
async def list_enemies(
    repo: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
    name: str | None = None,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[EnemyProfileRead]:
    """List enemy profiles.

    The stats in each row are **curve bases**, not level-90 numbers; `stat_curves` names
    the curve each one grows on. See `EnemyProfileRead`.
    """
    rows = await repo.search(name=name, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[EnemyProfileRead.model_validate(row) for row in rows],
        total=await repo.count_filtered(name=name),
        offset=offset,
        limit=limit,
    )


@router.get("/enemies/{profile_id}", response_model=EnemyProfileRead)
async def get_enemy(
    profile_id: str,
    repo: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
) -> EnemyProfileRead:
    """One enemy profile by row id.

    By row id, not `nanoka_id`, because `nanoka_id` is **nullable**: a hand-authored
    profile — a test dummy, a crossval target — is a legitimate row that no importer owns
    and would be unreachable through a source-keyed route.
    """
    profile = await repo.get_by_id(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No enemy profile {profile_id!r}")
    return EnemyProfileRead.model_validate(profile)


@router.get(
    "/characters/{nanoka_id}/weapons",
    response_model=CharacterWeaponGuideRead,
)
async def character_weapon_guide(
    nanoka_id: str,
    weapons: Annotated[WeaponRepository, Depends(get_weapon_repo)],
    sets: Annotated[ArtifactSetRepository, Depends(get_artifact_set_repo)],
) -> CharacterWeaponGuideRead:
    """What KeqingMains lists as this character's weapons, in the order KQM lists them.

    **404 when no guide has been captured**, which is not the same as "KQM recommends nothing" —
    a caller showing an empty panel for an uncaptured character would be making a claim about
    KQM that nobody made.

    Static and committed, never a live fetch: a guide is somebody else's page and it changes.
    `scripts/capture_kqm_weapons.py` re-captures deliberately, and the diff is the review.

    **The snapshot holds the game's ids and this resolves them here.** It held *row* ids until
    2026-09-04, which meant it only worked against the one database it was captured from —
    zero of them existed in production, so every recommendation silently missed and both
    pickers looked like pickers with no guide. Resolving at read time keeps the published
    `weapon_id` a row id, so no client had to change.

    Declared **above** `/characters/{nanoka_id}` is unnecessary — the paths differ by a
    segment — but it is declared beside it so the two are read together.
    """
    guide = kqm_weapons.for_character(nanoka_id)
    if guide is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no KeqingMains guide captured for character {nanoka_id!r}. "
                f"That is not a claim that none exists — see scripts/capture_kqm_weapons.py."
            ),
        )

    weapon_rows = await weapons.ids_by_nanoka_ids(
        w.weapon_nanoka_id for w in guide.weapons
    )
    set_rows = await sets.ids_by_nanoka_ids(
        e.set_nanoka_id for e in guide.sets if e.set_nanoka_id is not None
    )

    return CharacterWeaponGuideRead(
        character=guide.character,
        url=guide.url,
        retrieved_at=guide.retrieved_at,
        weapons=[
            WeaponRecommendationRead(
                position=w.position,
                # **Null rather than dropped** when this pin does not have the weapon. KQM's
                # sentence and their ordering are still true; what is missing is a card to
                # attach them to, and that is a fact about the pin. Dropping the row would
                # quietly shorten a cited list.
                weapon_id=weapon_rows.get(w.weapon_nanoka_id),
                weapon_nanoka_id=w.weapon_nanoka_id,
                weapon_name=w.weapon_name,
                note=w.note,
                playstyle=w.playstyle,
                relative_dps=w.relative_dps,
            )
            for w in guide.weapons
        ],
        sets=[
            SetRecommendationRead(
                position=e.position,
                kind=e.kind,
                as_written=e.as_written,
                note=e.note,
                set_id=(
                    set_rows.get(e.set_nanoka_id) if e.set_nanoka_id is not None else None
                ),
                set_nanoka_id=e.set_nanoka_id,
                set_name=e.set_name,
                pieces=e.pieces,
                playstyle=e.playstyle,
                relative_dps=e.relative_dps,
            )
            for e in guide.sets
        ],
    )


@router.get("/elements", response_model=list[ElementRead])
async def list_elements() -> list[ElementRead]:
    """The seven visions and their emblems, in the order the game lists them.

    A filter bar needs both. Served rather than restated so the client never builds an icon
    basename out of an element name — `app/services/element_symbols.py` explains at length why
    that string is an allowlist and not an f-string.

    Unauthenticated like the rest of the catalogue: it describes the game, not the caller.
    """
    return [ElementRead(value=value, icon=icon) for value, icon in all_visions()]


@router.get("/weapon-classes", response_model=list[WeaponClassRead])
async def list_weapon_classes() -> list[WeaponClassRead]:
    """The five weapon classes that have a mark, for a filter bar.

    The crossbow class is absent and `app/services/weapon_symbols.py` says why: no mark exists
    to draw, and the two characters carrying it are unreleased Traveler variants with no
    talents seeded.

    Unauthenticated like the rest of the catalogue: it describes the game, not the caller.
    """
    return [
        WeaponClassRead(value=value, display=display, icon=icon)
        for value, display, icon in all_classes()
    ]


@router.get("/reactions", response_model=list[ReactionRead])
async def list_reactions() -> list[ReactionRead]:
    """Every elemental reaction a team filter can offer.

    **Static, committed and cited** — `docs/RESEARCH_elemental_reactions.md` records the source
    URL, the retrieval date and the wiki's own wording per reaction. No database, because this
    is not seeded game data: the catalogue importer has no notion of a reaction, and
    `app/formula/genshin/damage.py` carries only the four *amplifying* ones by design.

    Unauthenticated like the rest of the catalogue: it describes the game, not the caller.
    """
    return [
        ReactionRead(
            id=reaction.id,
            name=reaction.name,
            required=list(reaction.required),
            one_of=list(reaction.one_of),
        )
        for reaction in offered()
    ]
