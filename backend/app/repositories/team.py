"""TeamRepository — data access for the Team entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.build import Build, Combo
from app.models.disc import Disc
from app.models.team import Team
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

# Slot number → the Team column holding that slot's build FK.
_SLOT_COLUMNS = {1: Team.build1_id, 2: Team.build2_id, 3: Team.build3_id}


class TeamRepository(BaseRepository[Team]):
    """Sole data-access point for the Team entity (3-build compositions)."""

    model = Team

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Team]:
        """List teams, paginated and scoped to ``owner_id`` when set."""
        stmt = select(Team)
        if self.owner_id is not None:
            stmt = stmt.where(Team.owner_id == self.owner_id)
        stmt = stmt.order_by(Team.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, entity_id: str) -> Team | None:
        """Team with all 3 member builds eager-loaded for team evaluation."""
        stmt = select(Team).where(Team.id == entity_id)
        if self.owner_id is not None:
            stmt = stmt.where(Team.owner_id == self.owner_id)
        member_opts = lambda rel: [  # noqa: E731
            selectinload(rel).selectinload(Build.agent).selectinload(Agent.core_skills),
            selectinload(rel).selectinload(Build.agent).selectinload(Agent.mindscapes),
            selectinload(rel).selectinload(Build.w_engine),
            selectinload(rel).selectinload(Build.discs).selectinload(Disc.disc_set),
        ]
        stmt = stmt.options(
            *member_opts(Team.build1),
            *member_opts(Team.build2),
            *member_opts(Team.build3),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def _require_owner(self) -> str:
        """Owner id, or raise — these bulk operations must never run unscoped."""
        if self.owner_id is None:
            raise ValueError("team slot re-mapping requires an owner_id")
        return self.owner_id

    async def snapshot_slots_for_owner(self) -> list[tuple[str, int, str]]:
        """Record every owner team slot as ``(team_id, slot, agent_id)`` (D-IM3).

        Taken *before* a ``build_mode="clean"`` wipe: the wipe nulls these slots
        (``Team.buildN_id`` is ``ondelete="SET NULL"``), and ``remap_slots``
        restores them by agent once the new builds exist.

        Only slots pointing at a build this owner owns are recorded — a foreign
        build survives ``BuildRepository.delete_all_for_owner`` and its slot is
        never nulled, so re-mapping over it would clobber untouched data.
        """
        owner_id = self._require_owner()
        snapshot: list[tuple[str, int, str]] = []
        for slot, column in _SLOT_COLUMNS.items():
            stmt = (
                select(Team.id, Build.agent_id)
                .join(Build, column == Build.id)
                .where(Team.owner_id == owner_id, Build.owner_id == owner_id)
            )
            rows = await self.session.execute(stmt)
            snapshot.extend((team_id, slot, agent_id) for team_id, agent_id in rows.all())
        return snapshot

    async def remap_slots(self, snapshot: Collection[tuple[str, int, str]]) -> int:
        """Re-point snapshotted slots at this owner's current build per agent.

        Returns the number of slots re-pointed. A slot whose agent has no build
        anymore (its agent was absent from the imported file) is left ``NULL``.
        ``uq_builds_owner_agent`` guarantees at most one candidate per agent, so
        the mapping is unambiguous.
        """
        owner_id = self._require_owner()
        if not snapshot:
            return 0

        rows = await self.session.execute(
            select(Build.id, Build.agent_id).where(Build.owner_id == owner_id)
        )
        build_by_agent = {agent_id: build_id for build_id, agent_id in rows.all()}

        remapped = 0
        for team_id, slot, agent_id in snapshot:
            build_id = build_by_agent.get(agent_id)
            column = _SLOT_COLUMNS.get(slot)
            if build_id is None or column is None:
                continue
            result = await self.session.execute(
                update(Team)
                .where(Team.id == team_id, Team.owner_id == owner_id)
                .values({column: build_id})
            )
            remapped += result.rowcount
        await self.session.flush()
        return remapped

    async def delete_all_null_teams_for_owner(
        self, team_ids: Collection[str] | None = None
    ) -> tuple[int, int]:
        """Delete owner teams left with all three slots ``NULL``; cascade combos.

        Returns ``(teams_deleted, combos_deleted)``. ``team_ids`` narrows the
        sweep to the teams a caller actually emptied — an import must not delete
        a team that was already all-``NULL`` before it ran. ``None`` sweeps every
        team this owner has.
        """
        owner_id = self._require_owner()
        if team_ids is not None and not team_ids:
            return (0, 0)

        stmt = select(Team.id).where(
            Team.owner_id == owner_id,
            Team.build1_id.is_(None),
            Team.build2_id.is_(None),
            Team.build3_id.is_(None),
        )
        if team_ids is not None:
            stmt = stmt.where(Team.id.in_(team_ids))
        doomed = list((await self.session.execute(stmt)).scalars().all())
        if not doomed:
            return (0, 0)

        # Count combos before the delete; the FK cascades them at the DB level.
        combos_deleted = (
            await self.session.execute(
                select(func.count()).select_from(Combo).where(Combo.team_id.in_(doomed))
            )
        ).scalar_one()

        result = await self.session.execute(delete(Team).where(Team.id.in_(doomed)))
        await self.session.flush()
        return (result.rowcount, combos_deleted)
