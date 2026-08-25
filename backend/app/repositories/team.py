"""Data access for the Team entity.

**Port state.** B.7 removed three bulk operations that belonged to fairy's scanner-import
flow, not to teams as such: ``snapshot_slots_for_owner`` and ``remap_slots`` (which keyed
team slots by ``Build.agent_id`` so a ``build_mode="clean"`` wipe could restore them
afterwards) and ``delete_all_null_teams_for_owner`` (which counted cascaded ``Combo`` rows).
All three referenced columns and models that B.4 deleted.

**The GOOD importer has its own wipe-and-restore now (N.3), and it is not this one.** The
marker here said to re-key these methods on ``Build.character_id``; that was aimed at the
wrong layer. A GOOD ``replace`` deletes **artifacts**, and teams point at *builds*, which the
wipe never touches — so team slots come through intact. What it destroys is every
``Artifact.build_id``.

``good_import_service`` therefore snapshots and restores *those*, matching a re-inserted piece
to a snapshotted one by stats rather than identity, because GOOD carries no stable
per-artifact id. The subtlety this note said to keep did carry over: only pieces **this owner
owns** are snapshotted, so a foreign build's slot is never re-pointed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.team import Team
from app.repositories.base import BaseRepository
from app.schemas.team import TEAM_SLOTS

if TYPE_CHECKING:
    from collections.abc import Sequence


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
        """Team with its three member builds eager-loaded.

        The eager-load stopped at ``Build`` in B.7. fairy also pulled
        ``Build.agent`` (plus core skills and mindscapes), ``Build.w_engine`` and
        ``Build.discs``->``disc_set`` in one round trip, because team evaluation needed
        all of it. Chunk C gives ``Build`` its Genshin relationships and Chunk F/G the
        evaluation that justifies loading them; until then loading three builds is the
        honest query.
        """
        stmt = select(Team).where(Team.id == entity_id)
        if self.owner_id is not None:
            stmt = stmt.where(Team.owner_id == self.owner_id)
        # Derived from TEAM_SLOTS, not listed: a slot missing from this eager load is a
        # `MissingGreenlet` the moment a route touches it, which is the shape Chunk G met
        # three times before `lazy="raise_on_sql"` was turned on.
        stmt = stmt.options(
            *(selectinload(getattr(Team, name.removesuffix("_id"))) for name in TEAM_SLOTS),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
