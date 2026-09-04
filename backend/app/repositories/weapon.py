"""Data access for the Weapon catalogue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.weapon import Weapon
from app.repositories.base import BaseRepository, ilike_contains

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy import Select

    from app.models.enums import Rarity, WeaponType


class WeaponRepository(BaseRepository[Weapon]):
    """Sole data-access point for the Weapon catalogue."""

    model = Weapon

    def _filtered(
        self,
        *,
        weapon_type: WeaponType | None,
        rarity: Rarity | None,
        name: str | None,
    ) -> Select[tuple[Weapon]]:
        stmt = select(Weapon)
        if weapon_type is not None:
            stmt = stmt.where(Weapon.weapon_type == weapon_type)
        if rarity is not None:
            stmt = stmt.where(Weapon.rarity == rarity)
        if name:
            stmt = stmt.where(ilike_contains(Weapon.name, name))
        return stmt

    async def search(
        self,
        *,
        weapon_type: WeaponType | None = None,
        rarity: Rarity | None = None,
        name: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Weapon]:
        """Filtered, paginated list."""
        stmt = (
            self._filtered(weapon_type=weapon_type, rarity=rarity, name=name)
            .order_by(Weapon.name, Weapon.nanoka_id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_filtered(
        self,
        *,
        weapon_type: WeaponType | None = None,
        rarity: Rarity | None = None,
        name: str | None = None,
    ) -> int:
        """Total matching `search`'s filters — see `CharacterRepository.count_filtered`."""
        stmt = self._filtered(weapon_type=weapon_type, rarity=rarity, name=name)
        result = await self.session.execute(
            select(func.count()).select_from(stmt.subquery()),
        )
        return int(result.scalar_one())

    async def get_many_with_refinements(self, weapon_ids: Sequence[str]) -> list[Weapon]:
        """Several weapons by primary key, each with its refinement rows.

        Refinements eagerly, because the caller reads them to *name what it cannot model* —
        and a lazy relationship touched inside an async request is the `MissingGreenlet`
        shape Chunk G met three times before `lazy="raise_on_sql"` was turned on.
        """
        if not weapon_ids:
            return []
        stmt = (
            select(Weapon)
            .where(Weapon.id.in_(list(weapon_ids)))
            .options(selectinload(Weapon.refinements))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def ids_by_nanoka_ids(self, nanoka_ids: Iterable[int]) -> dict[int, str]:
        """`{nanoka id: row id}` for the ids this pin has, silently omitting the ones it lacks.

        **A batch lookup, because the caller has a list.** `kqm_weapons` holds 1,353
        recommendations keyed by the game's ids, and resolving them one `get_by_nanoka_id` at a
        time would be a query per row on a page load.

        A missing id is an absent key rather than an error: a weapon released after the pinned
        patch is a fact about the pin, and the caller decides what to do about it.
        """
        ids = list(dict.fromkeys(nanoka_ids))
        if not ids:
            return {}
        result = await self.session.execute(
            select(Weapon.nanoka_id, Weapon.id).where(Weapon.nanoka_id.in_(ids)),
        )
        return dict(result.all())  # type: ignore[arg-type]

    async def get_by_nanoka_id(self, nanoka_id: int) -> Weapon | None:
        """One weapon by its source id, with its five refinement rows."""
        stmt = (
            select(Weapon)
            .where(Weapon.nanoka_id == nanoka_id)
            .options(selectinload(Weapon.refinements))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
