"""Data access for a user's owned artifacts.

Owner-scoped, unlike the catalogue repositories: an artifact belongs to someone. Every
query here goes through `BaseRepository`'s `owner_id`, so a missing scope is a missing
filter rather than a silently global read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.artifact import Artifact, ArtifactSet, artifact_slot_sort_order
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select
    from sqlalchemy.orm.strategy_options import _AbstractLoad

    from app.models.enums import ArtifactSlot


def _with_set() -> _AbstractLoad:
    """Load each piece's set **and that set's affixes**.

    Down to the affixes, not just to the set. `build_assembler.set_bonuses` reads
    `ArtifactSet.affixes`, so stopping at the set leaves a lazy relationship to be touched
    inside an async request — `MissingGreenlet`, a 500. This is the third instance of that
    exact shape in Chunk G (`Talent.scalings` in G.6a was the first), and every one of them
    looked correct until a route actually ran.
    """
    return selectinload(Artifact.artifact_set).selectinload(ArtifactSet.affixes)


class ArtifactRepository(BaseRepository[Artifact]):
    """Sole data-access point for owned artifacts."""

    model = Artifact

    def _filtered(
        self,
        *,
        slot: ArtifactSlot | None,
        set_id: str | None,
        equipped: bool | None,
        build_id: str | None = None,
        ids: Sequence[str] | None = None,
    ) -> Select[tuple[Artifact]]:
        stmt = select(Artifact)
        if self.owner_id is not None:
            stmt = stmt.where(Artifact.owner_id == self.owner_id)
        if slot is not None:
            stmt = stmt.where(Artifact.slot == slot)
        if set_id is not None:
            stmt = stmt.where(Artifact.artifact_set_id == set_id)
        if equipped is not None:
            stmt = (
                stmt.where(Artifact.build_id.isnot(None)) if equipped
                else stmt.where(Artifact.build_id.is_(None))
            )
        # Narrower than `equipped`, not a duplicate of it: "equipped to *this* build" is what
        # a build's own five slots need, and answering it by fetching every equipped piece
        # and filtering on the client scales with the whole inventory rather than with five.
        if build_id is not None:
            stmt = stmt.where(Artifact.build_id == build_id)
        # **`is not None`, not truthiness.** An empty list is a real filter meaning "none of
        # them", and `if ids:` would read it as "no filter" and answer with the whole
        # inventory — the caller asking for nothing getting everything, which is the worst
        # available direction for a filter to fail in.
        if ids is not None:
            stmt = stmt.where(Artifact.id.in_(ids))
        return stmt

    async def search(
        self,
        *,
        slot: ArtifactSlot | None = None,
        set_id: str | None = None,
        equipped: bool | None = None,
        build_id: str | None = None,
        ids: Sequence[str] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Artifact]:
        """Filtered, paginated list in **game slot order**, with each piece's set.

        Ordered by `artifact_slot_sort_order()`, not by `slot`: sorting on the column sorts
        the payload keys alphabetically — flower, circlet, plume, goblet, sands — which
        looks deliberate and is wrong for anything that iterates the result.
        """
        stmt = (
            self._filtered(
                slot=slot, set_id=set_id, equipped=equipped, build_id=build_id, ids=ids,
            )
            .options(_with_set())
            .order_by(artifact_slot_sort_order(), Artifact.level.desc(), Artifact.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_filtered(
        self,
        *,
        slot: ArtifactSlot | None = None,
        set_id: str | None = None,
        equipped: bool | None = None,
        build_id: str | None = None,
        ids: Sequence[str] | None = None,
    ) -> int:
        """Total matching `search`'s filters, so a filtered page's `total` is its own."""
        stmt = self._filtered(
            slot=slot, set_id=set_id, equipped=equipped, build_id=build_id, ids=ids,
        )
        result = await self.session.execute(
            select(func.count()).select_from(stmt.subquery()),
        )
        return int(result.scalar_one())

    async def owned_sets(self) -> Sequence[ArtifactSet]:
        """Every distinct catalogue set the caller owns a piece of, with its affixes.

        Asked as a set question rather than by reading every artifact and collecting the
        distinct ones. Two reasons, and the second is the one that matters:

        * there are 65 sets and a large account has thousands of pieces, so the join answers
          in the size of the answer rather than the size of the inventory;
        * `search`'s `_FETCH_CAP` is 20,000, and deriving sets from a capped read would
          **silently omit a set** from a larger account — the search would then rank without
          a bonus it should have scored, and prefer whatever it did know about. A ranking
          missing an option looks exactly like a ranking.
        """
        stmt = (
            select(ArtifactSet)
            .join(Artifact, Artifact.artifact_set_id == ArtifactSet.id)
            .options(selectinload(ArtifactSet.affixes))
            .distinct()
        )
        if self.owner_id is not None:
            stmt = stmt.where(Artifact.owner_id == self.owner_id)
        return (await self.session.execute(stmt)).scalars().unique().all()

    async def get_with_set(self, artifact_id: str) -> Artifact | None:
        """One owned artifact with its set eager-loaded."""
        stmt = select(Artifact).where(Artifact.id == artifact_id)
        if self.owner_id is not None:
            stmt = stmt.where(Artifact.owner_id == self.owner_id)
        stmt = stmt.options(_with_set())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def equipped_in_slot(self, build_id: str, slot: ArtifactSlot) -> Artifact | None:
        """The piece a build already holds in `slot`, if any.

        **Scoped by the build, deliberately not by `owner_id` as well.** Every other read here
        carries the owner filter, and adding it looked like consistency until the mutation
        harness showed it changed no test — because the caller has already established that
        the build is the caller's, so no reachable row can differ on owner.

        Where it *would* differ is a corrupt row: a stranger's artifact attached to my build.
        The owner filter would hide it, this would report the slot as free, and
        `uq_artifacts_build_slot` would then reject the insert as a **500**. Unfiltered, the
        same row produces the ordinary 422. So the filter cannot help and can only turn a
        clean refusal into a server error — which is why it is absent rather than untested.
        """
        stmt = select(Artifact).where(
            Artifact.build_id == build_id, Artifact.slot == slot,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
