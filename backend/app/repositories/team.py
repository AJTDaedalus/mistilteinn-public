"""Data access for the Team entity.

**Port state.** B.7 removed three bulk operations that belonged to fairy's scanner-import
flow, not to teams as such: ``snapshot_slots_for_owner`` and ``remap_slots`` (which keyed
team slots by ``Build.agent_id`` so a ``build_mode="clean"`` wipe could restore them
afterwards) and ``delete_all_null_teams_for_owner`` (which counted cascaded ``Combo`` rows).
All three referenced columns and models that B.4 deleted.

TODO(chunk-G, G.5): the GOOD importer needs the same wipe-and-restore guarantee, re-keyed
on ``Build.character_id``. Recover the originals from
fairy@76909c4:backend/app/repositories/team.py rather than re-deriving them — the subtlety
worth keeping is that only slots pointing at a build *this owner owns* were snapshotted, so
a foreign build's slot is never clobbered. The ``_SLOT_COLUMNS`` map and the
``_require_owner`` guard that made those methods safe went with them; both are one line and
both are in that file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.team import Team
from app.repositories.base import BaseRepository

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
        stmt = stmt.options(
            selectinload(Team.build1),
            selectinload(Team.build2),
            selectinload(Team.build3),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
