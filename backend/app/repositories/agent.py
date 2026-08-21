"""Agent repository with eager loading of sub-resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class AgentRepository(BaseRepository[Agent]):
    """Sole data-access point for the Agent aggregate (kit sub-resources included)."""

    model = Agent

    def _eager_options(self) -> list:
        """Loader options that pull an agent's full kit in one round trip."""
        return [
            selectinload(Agent.skills),
            selectinload(Agent.attacks),
            selectinload(Agent.core_skills),
            selectinload(Agent.mindscapes),
            selectinload(Agent.resource_costs),
        ]

    async def get_by_id(self, entity_id: str) -> Agent | None:
        """Fetch an agent by ID with its full kit eager-loaded."""
        stmt = select(Agent).where(Agent.id == entity_id).options(*self._eager_options())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_hakushin_id(self, hakushin_id: int) -> Agent | None:
        """Fetch an agent by its hakushin.gg source ID, used by the importer."""
        stmt = (
            select(Agent).where(Agent.hakushin_id == hakushin_id).options(*self._eager_options())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        element: str | None = None,
        specialty: str | None = None,
        rarity: str | None = None,
    ) -> Sequence[Agent]:
        """List agents, paginated and optionally filtered by element/specialty/rarity."""
        stmt = select(Agent)
        if element:
            stmt = stmt.where(Agent.element == element)
        if specialty:
            stmt = stmt.where(Agent.specialty == specialty)
        if rarity:
            stmt = stmt.where(Agent.rarity == rarity)
        stmt = stmt.order_by(Agent.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        *,
        element: str | None = None,
        specialty: str | None = None,
        rarity: str | None = None,
    ) -> int:
        """Count agents matching the same element/specialty/rarity filters as ``get_all``."""
        stmt = select(func.count()).select_from(Agent)
        if element:
            stmt = stmt.where(Agent.element == element)
        if specialty:
            stmt = stmt.where(Agent.specialty == specialty)
        if rarity:
            stmt = stmt.where(Agent.rarity == rarity)
        result = await self.session.execute(stmt)
        return result.scalar_one()
