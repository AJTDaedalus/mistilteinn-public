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
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


def _full_build() -> tuple:
    """Everything an evaluation touches, in one round trip."""
    return (
        selectinload(Build.character),
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

    async def get_full(self, build_id: str) -> Build | None:
        """One build with everything an evaluation reads."""
        stmt = select(Build).where(Build.id == build_id)
        if self.owner_id is not None:
            stmt = stmt.where(Build.owner_id == self.owner_id)
        stmt = stmt.options(*_full_build())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
