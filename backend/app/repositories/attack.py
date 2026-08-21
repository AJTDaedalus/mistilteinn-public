"""Attack repository."""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select, true

from app.models.agent import Attack
from app.models.enums import PotentialVariant
from app.repositories.base import BaseRepository


def visible_to(variant: PotentialVariant) -> ColumnElement[bool]:
    """Rows a caller in ``variant`` can see: shared rows, plus at most one variant.

    Since #90 the ``attacks`` table holds both Potential states, so a query with no
    variant predicate returns *both* — which on a calc path double-counts every hit the
    two kits disagree about and silently inflates damage. That is why every accessor
    below takes ``variant`` as a required argument rather than defaulting it: a call site
    that has not decided fails to import instead of quietly picking one
    (docs/DECISIONS.md 2026-08-09 (c), docs/DESIGN_potential_toggle.md §5.1).
    """
    if variant is PotentialVariant.BOTH:
        return true()
    wanted = "unlocked" if variant is PotentialVariant.UNLOCKED else "base"
    return or_(Attack.potential.is_(None), Attack.potential == wanted)


class AttackRepository(BaseRepository[Attack]):
    """Sole data-access point for per-hit Attack records belonging to an Agent."""

    model = Attack

    async def get_by_agent(
        self,
        agent_id: str,
        variant: PotentialVariant,
    ) -> list[Attack]:
        """All attack hits for an agent in ``variant``'s kit, ordered by skill and hit."""
        stmt = (
            select(Attack)
            .where(Attack.agent_id == agent_id)
            .where(visible_to(variant))
            .order_by(Attack.skill_key, Attack.hit_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_agent_and_name(
        self,
        agent_id: str,
        name: str,
        variant: PotentialVariant,
    ) -> list[Attack]:
        """All hits in a single move for an agent in ``variant``'s kit, by hit_index."""
        stmt = (
            select(Attack)
            .where(Attack.agent_id == agent_id)
            .where(Attack.name == name)
            .where(visible_to(variant))
            .order_by(Attack.skill_key, Attack.hit_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
