"""Disc and DiscSet repositories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select

from app.models.disc import Disc, DiscSet
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class DiscSetRepository(BaseRepository[DiscSet]):
    """Sole data-access point for DiscSet metadata (2pc/4pc set bonuses)."""

    model = DiscSet

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[DiscSet]:
        """List disc sets, paginated and ordered by name."""
        stmt = select(DiscSet).order_by(DiscSet.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class DiscRepository(BaseRepository[Disc]):
    """Sole data-access point for the Disc entity (owned drives, equipped or in inventory)."""

    model = Disc

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Disc]:
        """List discs, paginated and scoped to ``owner_id`` when set."""
        stmt = select(Disc)
        if self.owner_id is not None:
            stmt = stmt.where(Disc.owner_id == self.owner_id)
        stmt = stmt.order_by(Disc.id).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_unequipped(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Disc]:
        """List discs not currently equipped on any build."""
        stmt = select(Disc).where(Disc.build_id.is_(None))
        if self.owner_id is not None:
            stmt = stmt.where(Disc.owner_id == self.owner_id)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_build(self, build_id: str) -> Sequence[Disc]:
        """List the discs equipped on a given build, ordered by slot."""
        stmt = select(Disc).where(Disc.build_id == build_id)
        if self.owner_id is not None:
            stmt = stmt.where(Disc.owner_id == self.owner_id)
        stmt = stmt.order_by(Disc.build_slot)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_filtered(
        self,
        *,
        offset: int = 0,
        limit: int = 200,
        slot: int | None = None,
        set_id: str | None = None,
        rarity: str | None = None,
        equipped: str | None = None,
    ) -> Sequence[Disc]:
        """Filter discs by slot, set, rarity, and equipped status.

        ``equipped`` semantics:
        - None / "any"   → no filter (all discs returned)
        - "unequipped"   → only discs with build_id IS NULL
        - <build_id>     → discs unequipped OR equipped to that specific build
        """
        stmt = select(Disc)

        if self.owner_id is not None:
            stmt = stmt.where(Disc.owner_id == self.owner_id)

        if slot is not None:
            stmt = stmt.where(Disc.slot == slot)

        if set_id is not None:
            stmt = stmt.where(Disc.disc_set_id == set_id)

        if rarity is not None:
            stmt = stmt.where(Disc.rarity == rarity)

        if equipped == "unequipped":
            stmt = stmt.where(Disc.build_id.is_(None))
        elif equipped and equipped != "any":
            # Show unequipped + equipped to the given build (picker semantics).
            stmt = stmt.where(or_(Disc.build_id.is_(None), Disc.build_id == equipped))

        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_filtered(
        self,
        *,
        slot: int | None = None,
        set_id: str | None = None,
        rarity: str | None = None,
        equipped: str | None = None,
    ) -> int:
        """Count discs matching the same slot/set/rarity/equipped filters as ``list_filtered``."""
        stmt = select(func.count()).select_from(Disc)

        if self.owner_id is not None:
            stmt = stmt.where(Disc.owner_id == self.owner_id)

        if slot is not None:
            stmt = stmt.where(Disc.slot == slot)
        if set_id is not None:
            stmt = stmt.where(Disc.disc_set_id == set_id)
        if rarity is not None:
            stmt = stmt.where(Disc.rarity == rarity)
        if equipped == "unequipped":
            stmt = stmt.where(Disc.build_id.is_(None))
        elif equipped and equipped != "any":
            stmt = stmt.where(or_(Disc.build_id.is_(None), Disc.build_id == equipped))

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def delete_all_for_owner(self) -> int:
        """Delete every disc owned by ``self.owner_id``; returns the row count deleted.

        Raises ``ValueError`` when ``owner_id`` is unset, so an unscoped repo
        can never mass-delete the whole table.
        """
        if self.owner_id is None:
            raise ValueError("delete_all_for_owner requires an owner_id")
        result = await self.session.execute(delete(Disc).where(Disc.owner_id == self.owner_id))
        await self.session.flush()
        return result.rowcount

    async def get_by_set(
        self,
        disc_set_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Disc]:
        """List discs belonging to a given disc set, paginated."""
        stmt = select(Disc).where(Disc.disc_set_id == disc_set_id).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
