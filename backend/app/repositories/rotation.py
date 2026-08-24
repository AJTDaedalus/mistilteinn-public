"""Data access for user-authored rotations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.build import Build
from app.models.rotation import Rotation
from app.models.team import Team
from app.repositories.base import BaseRepository
from app.schemas.team import TEAM_SLOTS

if TYPE_CHECKING:
    from collections.abc import Sequence


class RotationStaleError(RuntimeError):
    """A rotation names characters its team no longer has.

    Raised rather than repaired. The alternatives are to drop the offending steps — deleting
    a user's authored work so an operation can succeed — or to reinterpret them against
    whoever now occupies the position, which is the silent-wrong-answer this repo refuses
    everywhere else. Saying no, and naming exactly which steps, leaves the user in control of
    their own rotation.
    """


class RotationRepository(BaseRepository[Rotation]):
    """Sole data-access point for rotations."""

    model = Rotation

    async def list_for_team(self, team_id: str) -> Sequence[Rotation]:
        """Every rotation saved against one team, newest first."""
        stmt = select(Rotation).where(Rotation.team_id == team_id)
        if self.owner_id is not None:
            stmt = stmt.where(Rotation.owner_id == self.owner_id)
        stmt = stmt.order_by(Rotation.created_at.desc())
        return (await self.session.execute(stmt)).scalars().all()

    async def team_characters(self, team_id: str) -> set[str]:
        """The nanoka ids of every character on a team.

        Eager-loaded down to each build's character, because a lazy hop here is a
        `MissingGreenlet` inside a request — the shape Chunk G met three times before
        `lazy="raise_on_sql"` made it loud.
        """
        stmt = select(Team).where(Team.id == team_id)
        if self.owner_id is not None:
            stmt = stmt.where(Team.owner_id == self.owner_id)
        stmt = stmt.options(
            *(
                selectinload(getattr(Team, name.removesuffix("_id"))).selectinload(
                    Build.character,
                )
                for name in TEAM_SLOTS
            ),
        )
        team = (await self.session.execute(stmt)).scalar_one_or_none()
        if team is None:
            return set()
        found = set()
        for slot in TEAM_SLOTS:
            build = getattr(team, slot.removesuffix("_id"))
            if build is not None and build.character is not None:
                found.add(str(build.character.nanoka_id))
        return found
