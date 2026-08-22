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
    get_weapon_repo,
)
from app.models.enums import Element, Rarity, WeaponType
from app.repositories.artifact_set import ArtifactSetRepository
from app.repositories.character import CharacterRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.weapon import WeaponRepository
from app.schemas.catalogue import (
    ArtifactSetRead,
    CharacterRead,
    CharacterSummary,
    EnemyProfileRead,
    WeaponRead,
    WeaponSummary,
)
from app.schemas.common import PaginatedResponse

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
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[CharacterSummary]:
    """List characters, filtered by element, weapon type, rarity or name substring."""
    filters = {
        "element": element, "weapon_type": weapon_type, "rarity": rarity, "name": name,
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

    The path parameter is a **string**: 28 of the 150 characters are Traveler variants
    keyed `10000005-2` … `10000005-8`. Typing it as an int would 422 on all of them.
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
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[WeaponSummary]:
    """List weapons, filtered by type, rarity or name substring."""
    filters = {"weapon_type": weapon_type, "rarity": rarity, "name": name}
    rows = await repo.search(**filters, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[WeaponSummary.model_validate(row) for row in rows],
        total=await repo.count_filtered(**filters),
        offset=offset,
        limit=limit,
    )


@router.get("/weapons/{nanoka_id}", response_model=WeaponRead)
async def get_weapon(
    nanoka_id: int,
    repo: Annotated[WeaponRepository, Depends(get_weapon_repo)],
) -> WeaponRead:
    """One weapon with its refinement rows and growth curves."""
    weapon = await repo.get_by_nanoka_id(nanoka_id)
    if weapon is None:
        raise HTTPException(status_code=404, detail=f"No weapon {nanoka_id}")
    return WeaponRead.model_validate(weapon)


@router.get("/artifact-sets", response_model=PaginatedResponse[ArtifactSetRead])
async def list_artifact_sets(
    repo: Annotated[ArtifactSetRepository, Depends(get_artifact_set_repo)],
    name: str | None = None,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[ArtifactSetRead]:
    """List artifact sets with their bonus affixes."""
    rows = await repo.search(name=name, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[ArtifactSetRead.model_validate(row) for row in rows],
        total=await repo.count_filtered(name=name),
        offset=offset,
        limit=limit,
    )


@router.get("/artifact-sets/{nanoka_id}", response_model=ArtifactSetRead)
async def get_artifact_set(
    nanoka_id: int,
    repo: Annotated[ArtifactSetRepository, Depends(get_artifact_set_repo)],
) -> ArtifactSetRead:
    """One artifact set with its affixes."""
    artifact_set = await repo.get_by_nanoka_id(nanoka_id)
    if artifact_set is None:
        raise HTTPException(status_code=404, detail=f"No artifact set {nanoka_id}")
    return ArtifactSetRead.model_validate(artifact_set)


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
