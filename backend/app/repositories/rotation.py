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


class DuplicateTeamMemberError(RuntimeError):
    """A team row holds two builds of one character — impossible through the API (T.1a)."""


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

    def _teams(self) -> Select[tuple[Team]]:
        """Teams, owner-scoped, eager-loaded down to each build's character.

        Eager, because a lazy hop here is a `MissingGreenlet` inside a request — the shape
        Chunk G met three times before `lazy="raise_on_sql"` made it loud.
        """
        stmt = select(Team)
        if self.owner_id is not None:
            stmt = stmt.where(Team.owner_id == self.owner_id)
        return stmt.options(
            *(
                selectinload(getattr(Team, name.removesuffix("_id"))).selectinload(
                    Build.character,
                )
                for name in TEAM_SLOTS
            ),
        )

    @staticmethod
    def _roster(team: Team) -> dict[str, Character]:
        """`nanoka_id -> Character` for one already-loaded team.

        **Refuses a team holding one character twice rather than collapsing it.** Keying by
        `nanoka_id` means a duplicate would silently become a single entry, and a four-build
        team would compile a rotation against three characters — a wrong answer that looks
        like a right one, with nothing anywhere reporting a problem.

        `app/api/v1/teams.py` refuses such a team on write, so this is not reachable through
        the API (T.1a). It stays because the rule lives in the application and not in the
        schema: a row written by a script, a fixture or a future code path would arrive here
        with no other check in its way.
        """
        found: dict[str, Character] = {}
        for slot in TEAM_SLOTS:
            build = getattr(team, slot.removesuffix("_id"))
            if build is None or build.character is None:
                continue
            nanoka_id = str(build.character.nanoka_id)
            if nanoka_id in found:
                msg = (
                    f"team {team.id} holds {build.character.name} twice. A party cannot "
                    f"field the same character twice — gcsim refuses one outright — and "
                    f"keying the roster by character would have hidden the duplicate rather "
                    f"than reported it."
                )
                raise DuplicateTeamMemberError(msg)
            found[nanoka_id] = build.character
        return found

    async def character_rows(self, team_id: str) -> dict[str, Character]:
        """`nanoka_id -> Character` for every build on a team.

        Rows rather than ids, because the compiler needs a character's name and element to
        reach its gcsim key. `team_characters` derives its set from this, so the two cannot
        disagree about who is on a team — which they would if each ran its own query and one
        forgot a slot.
        """
        team = (
            await self.session.execute(self._teams().where(Team.id == team_id))
        ).scalar_one_or_none()
        return {} if team is None else self._roster(team)

    async def team_build_ids(self, team_id: str) -> list[str]:
        """Every build id on a team, in slot order.

        Ids rather than rows: a calibration needs each teammate's **weapon and artifacts**,
        which `_teams()` does not eager-load, so the caller re-reads them through
        `BuildRepository`. Returning half-loaded rows here would be the `MissingGreenlet`
        shape the eager-loading comment above is about.
        """
        team = (
            await self.session.execute(self._teams().where(Team.id == team_id))
        ).scalar_one_or_none()
        if team is None:
            return []
        return [
            str(getattr(team, name))
            for name in TEAM_SLOTS
            if getattr(team, name) is not None
        ]

    async def rosters(self) -> list[tuple[Team, dict[str, Character]]]:
        """Every team the caller owns, with who is on it.

        This is what the editor offers as step options, and it comes through `_roster` —
        the same extraction the write path validates against. Two implementations would
        eventually offer a character the validator then refused, and the user would be told
        their own selection was invalid.
        """
        teams = (
            (await self.session.execute(self._teams().order_by(Team.created_at.desc())))
            .scalars()
            .unique()
            .all()
        )
        return [(team, self._roster(team)) for team in teams]
