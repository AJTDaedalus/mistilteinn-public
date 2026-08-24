"""Data access for saved builds.

Owner-scoped. Every read that feeds the damage chain eager-loads the *whole* build —
character, weapon, artifacts and each artifact's set — because the alternative is a lazy
load inside an async request, which is a `MissingGreenlet` and a 500 rather than a slow
page. G.6a shipped that bug once already, one relationship deeper than the eager-load went.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.artifact import Artifact, ArtifactSet
from app.models.build import Build
from app.models.character import Character, Talent
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


def _full_build() -> tuple:
    """Everything an evaluation touches, in one round trip."""
    return (
        # Down to the talent scalings, because `HitSpec.talent` resolves a multiplier from
        # them (M.2) and `lazy` is `raise_on_sql` — the same reasoning as the affixes below,
        # and the fourth instance of this shape in the repo.
        selectinload(Build.character).selectinload(Character.talents).selectinload(
            Talent.scalings,
        ),
        selectinload(Build.weapon),
        selectinload(Build.artifacts)
        .selectinload(Artifact.artifact_set)
        .selectinload(ArtifactSet.affixes),
    )


class BuildRepository(BaseRepository[Build]):
    """Sole data-access point for saved builds."""

    model = Build

    async def search(self, *, offset: int = 0, limit: int = 100) -> Sequence[Build]:
        """The caller's builds, newest first, each with its character and weapon."""
        stmt = select(Build)
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        stmt = (
            stmt.options(selectinload(Build.character), selectinload(Build.weapon))
            .order_by(Build.created_at.desc(), Build.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_filtered(self) -> int:
        """Total in the caller's scope, matching `search`."""
        stmt = select(Build)
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        result = await self.session.execute(
            select(func.count()).select_from(stmt.subquery()),
        )
        return int(result.scalar_one())

    async def with_catalogue(self, build_ids: Sequence[str]) -> dict[str, Build]:
        """The named builds, owner-scoped, each with its character and weapon loaded.

        One round trip rather than one per slot, and **eager** because `GUARDED_LAZY` is
        `raise_on_sql`: reading `build.character` off a row this did not load is a
        `MissingGreenlet` inside a request. The T.1a team check did exactly that and its test
        passed anyway — the session still held the Character in its identity map, so the hop
        emitted no SQL. Found by expiring the session in the test, which is what
        `test_genshin_models.py`'s `_reload` exists for.

        Missing ids are simply absent from the result, including builds owned by someone
        else: the caller turns that into "no build of yours", which is the right answer to
        give, since confirming it exists would disclose that it does.
        """
        if not build_ids:
            return {}
        stmt = select(Build).where(Build.id.in_(list(build_ids)))
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        stmt = stmt.options(selectinload(Build.character), selectinload(Build.weapon))
        rows = (await self.session.execute(stmt)).scalars().all()
        return {str(row.id): row for row in rows}

    async def get_with_catalogue(self, build_id: str) -> Build | None:
        """One build with the catalogue rows `BuildRead` publishes.

        `get_by_id` does not eager-load and `GUARDED_LAZY` is `raise_on_sql`, so returning a
        row from it as a `BuildRead` is a `MissingGreenlet` the moment the schema reads
        `.character`. Lighter than `get_full`, which also pulls artifacts, their sets and
        those sets' affixes — none of which a build row displays.
        """
        return (await self.with_catalogue([build_id])).get(build_id)

    async def get_full(self, build_id: str) -> Build | None:
        """One build with everything an evaluation reads."""
        stmt = select(Build).where(Build.id == build_id)
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        stmt = stmt.options(*_full_build())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
