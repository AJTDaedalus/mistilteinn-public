"""Data access for user-authored rotations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.models.build import Build
from app.models.rotation import Rotation
from app.models.team import Team
from app.repositories.base import BaseRepository
from app.schemas.team import TEAM_SLOTS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.character import Character


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

    def _for_team(self, team_id: str) -> Select[tuple[Rotation]]:
        """The one WHERE both the page and its count are built from.

        Two hand-written filters would be two chances to forget the owner scope, and the
        half that forgot it would be the one reporting `total` — the exact shape the base
        repository's unscoped `count` had before the Chunk A+B review.
        """
        stmt = select(Rotation).where(Rotation.team_id == team_id)
        if self.owner_id is not None:
            stmt = stmt.where(Rotation.owner_id == self.owner_id)
        return stmt

    async def list_for_team(
        self, team_id: str, *, offset: int = 0, limit: int = 50,
    ) -> Sequence[Rotation]:
        """One page of the rotations saved against a team, newest first."""
        stmt = self._for_team(team_id).order_by(Rotation.created_at.desc())
        return (await self.session.execute(stmt.offset(offset).limit(limit))).scalars().all()

    async def count_for_team(self, team_id: str) -> int:
        """How many there are in total, so the page envelope is not guesswork."""
        stmt = select(func.count()).select_from(self._for_team(team_id).subquery())
        return int((await self.session.execute(stmt)).scalar_one())

    async def team_characters(self, team_id: str) -> set[str]:
        """The nanoka ids of every character on a team — for validating steps on write."""
        return set(await self.character_rows(team_id))

    async def character_rows(self, team_id: str) -> dict[str, Character]:
        """`nanoka_id -> Character` for every build on a team.

        Rows rather than ids, because the compiler needs a character's name and element to
        reach its gcsim key. `team_characters` derives its set from this, so the two cannot
        disagree about who is on a team — which they would if each ran its own query and one
        forgot a slot.

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
            return {}
        found: dict[str, Character] = {}
        for slot in TEAM_SLOTS:
            build = getattr(team, slot.removesuffix("_id"))
            if build is not None and build.character is not None:
                found[str(build.character.nanoka_id)] = build.character
        return found
