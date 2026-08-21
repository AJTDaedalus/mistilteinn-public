"""Build, Combo, EnemyProfile repositories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.build import Build, Combo, EnemyProfile
from app.models.disc import Disc
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class BuildRepository(BaseRepository[Build]):
    """Sole data-access point for the Build aggregate (agent + w-engine + 6 discs)."""

    model = Build

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Build]:
        """List builds, paginated and scoped to ``owner_id`` when set."""
        stmt = select(Build).options(selectinload(Build.agent))
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        stmt = stmt.order_by(Build.id).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, entity_id: str) -> Build | None:
        """Fetch a build by ID with agent kit, w-engine, and equipped discs eager-loaded."""
        stmt = select(Build).where(Build.id == entity_id)
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        stmt = stmt.options(
            selectinload(Build.discs).selectinload(Disc.disc_set),
            selectinload(Build.agent).selectinload(Agent.core_skills),
            selectinload(Build.agent).selectinload(Agent.mindscapes),
            selectinload(Build.agent).selectinload(Agent.resource_costs),
            selectinload(Build.w_engine),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def equip_all(
        self,
        build_id: str,
        discs: dict[int, str],
    ) -> Build:
        """Atomically replace all six disc slots on a build.

        ``discs`` must map slot (1-6) → disc_id. Each disc's stored slot must
        match the dict key (422 raised otherwise). Discs currently equipped on
        this build but absent from the payload are detached. Discs in the
        payload that belong to another build are stolen (re-attached here).

        Raises ``ValueError`` for unknown disc IDs or wrong-slot disc IDs.
        The caller is responsible for committing or rolling back the session.
        """
        disc_ids = list(discs.values())
        disc_q = await self.session.execute(
            select(Disc).where(Disc.id.in_(disc_ids)),
        )
        found = {str(d.id): d for d in disc_q.scalars().all()}

        missing_ids = [did for did in disc_ids if did not in found]
        if missing_ids:
            raise ValueError(f"Disc(s) not found: {missing_ids}")

        for slot, disc_id in discs.items():
            disc = found[disc_id]
            disc_slot = disc.slot.value if hasattr(disc.slot, "value") else disc.slot
            if int(disc_slot) != slot:
                raise ValueError(
                    f"Disc {disc_id} is for slot {disc_slot}, assigned to slot {slot}",
                )

        # Detach all discs currently equipped on this build.
        await self.session.execute(
            update(Disc).where(Disc.build_id == build_id).values(build_id=None, build_slot=None),
        )

        # Attach each requested disc (steals from other builds automatically
        # because we just write build_id/build_slot unconditionally).
        for slot, disc_id in discs.items():
            disc = found[disc_id]
            disc.build_id = build_id
            disc.build_slot = slot

        # Flush so the build's discs relationship is up-to-date, then reload.
        await self.session.flush()
        build = await self.get_by_id(build_id)
        if build is None:
            raise ValueError(f"Build not found: {build_id}")
        return build

    async def get_by_agent(
        self,
        agent_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Build]:
        """List builds for a given agent, paginated and scoped to ``owner_id`` when set."""
        stmt = select(Build).where(Build.agent_id == agent_id)
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def set_priority_order(self, ordered_build_ids: list[str]) -> Sequence[Build]:
        """Assign optimizer_priority = i+1 in list order; NULL all other builds.

        Raises ValueError for unknown build IDs. Caller is responsible for committing.
        """
        if ordered_build_ids:
            result = await self.session.execute(
                select(Build.id).where(Build.id.in_(ordered_build_ids))
            )
            found_ids = {str(row[0]) for row in result.all()}
            unknown = [bid for bid in ordered_build_ids if bid not in found_ids]
            if unknown:
                raise ValueError(f"Unknown build IDs: {unknown}")

        # NULL all builds (full replace)
        await self.session.execute(update(Build).values(optimizer_priority=None))

        if not ordered_build_ids:
            await self.session.flush()
            return []

        for i, build_id in enumerate(ordered_build_ids):
            await self.session.execute(
                update(Build).where(Build.id == build_id).values(optimizer_priority=i + 1)
            )

        await self.session.flush()

        result = await self.session.execute(
            select(Build).where(Build.id.in_(ordered_build_ids)).order_by(Build.optimizer_priority)
        )
        return result.scalars().all()

    async def delete_all_for_owner(self) -> int:
        """Delete every build owned by ``self.owner_id``; returns the row count deleted.

        Discs equipped on the deleted builds auto-detach (``Disc.build_id``
        ``ondelete="SET NULL"``); they are not themselves deleted.

        Raises ``ValueError`` when ``owner_id`` is unset, so an unscoped repo
        can never mass-delete the whole table.
        """
        if self.owner_id is None:
            raise ValueError("delete_all_for_owner requires an owner_id")
        result = await self.session.execute(delete(Build).where(Build.owner_id == self.owner_id))
        await self.session.flush()
        return result.rowcount

    async def higher_priority_equipped_disc_ids(self, build: Build) -> set[str]:
        """Return IDs of discs equipped on builds ranked strictly above `build`.

        Unranked target (optimizer_priority IS NULL) → all ranked builds count as higher.
        The target build itself is always excluded from the result.
        """
        p = build.optimizer_priority

        stmt = (
            select(Disc.id)
            .join(Build, Disc.build_id == Build.id)
            .where(
                Build.optimizer_priority.is_not(None),
                Build.id != str(build.id),
            )
        )

        if p is not None:
            # Ranked target: only builds with strictly lower priority number (higher rank)
            stmt = stmt.where(Build.optimizer_priority < p)
        # Unranked target: all ranked builds are higher → no additional filter

        result = await self.session.execute(stmt)
        return {str(row[0]) for row in result.all()}


class ComboRepository(BaseRepository[Combo]):
    """Sole data-access point for saved Combo rotations."""

    model = Combo

    async def get_by_team(
        self,
        team_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Combo]:
        """List combos saved against a given team, paginated and scoped to ``owner_id``."""
        stmt = select(Combo).where(Combo.team_id == team_id)
        if self.owner_id is not None:
            stmt = stmt.where(Combo.owner_id == self.owner_id)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class EnemyProfileRepository(BaseRepository[EnemyProfile]):
    """Sole data-access point for enemy defense/RES profiles used in damage calc."""

    model = EnemyProfile

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        rarity: int | None = None,
    ) -> Sequence[EnemyProfile]:
        """List enemy profiles, paginated and optionally filtered by rarity."""
        stmt = select(EnemyProfile)
        if rarity is not None:
            stmt = stmt.where(EnemyProfile.rarity == rarity)
        stmt = stmt.order_by(EnemyProfile.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, *, rarity: int | None = None) -> int:
        """Count enemy profiles, optionally filtered by rarity."""
        stmt = select(func.count()).select_from(EnemyProfile)
        if rarity is not None:
            stmt = stmt.where(EnemyProfile.rarity == rarity)
        result = await self.session.execute(stmt)
        return result.scalar_one()
