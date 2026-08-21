"""Enemy profile endpoints — read-only (seeded) + custom profile creation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_enemy_repo
from app.repositories.build import EnemyProfileRepository
from app.schemas.build import EnemyProfileCreate, EnemyProfileRead, EnemyProfileUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/enemies", tags=["enemies"])


@router.get("", response_model=PaginatedResponse[EnemyProfileRead])
async def list_enemies(
    repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    rarity: int | None = None,
) -> PaginatedResponse[EnemyProfileRead]:
    """List enemy profiles available as damage-calculation targets."""
    enemies = await repo.get_all(offset=offset, limit=limit, rarity=rarity)
    total = await repo.count(rarity=rarity)
    return PaginatedResponse(
        items=[EnemyProfileRead.model_validate(e) for e in enemies],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=EnemyProfileRead, status_code=201)
async def create_enemy(
    body: EnemyProfileCreate,
    repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> EnemyProfileRead:
    """Create a custom enemy profile (DEF, RES, stun state, etc.)."""
    enemy = await repo.create(body.model_dump())
    return EnemyProfileRead.model_validate(enemy)


@router.get("/{enemy_id}", response_model=EnemyProfileRead)
async def get_enemy(
    enemy_id: str,
    repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> EnemyProfileRead:
    """Fetch a single enemy profile by id."""
    enemy = await repo.get_by_id(enemy_id)
    if enemy is None:
        raise HTTPException(status_code=404, detail="Enemy profile not found")
    return EnemyProfileRead.model_validate(enemy)


@router.patch("/{enemy_id}", response_model=EnemyProfileRead)
async def update_enemy(
    enemy_id: str,
    body: EnemyProfileUpdate,
    repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> EnemyProfileRead:
    """Partially update a custom enemy profile."""
    enemy = await repo.update(enemy_id, body.model_dump(exclude_unset=True))
    if enemy is None:
        raise HTTPException(status_code=404, detail="Enemy profile not found")
    return EnemyProfileRead.model_validate(enemy)


@router.delete("/{enemy_id}", status_code=204)
async def delete_enemy(
    enemy_id: str,
    repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> None:
    """Delete a custom enemy profile."""
    deleted = await repo.delete(enemy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Enemy profile not found")
