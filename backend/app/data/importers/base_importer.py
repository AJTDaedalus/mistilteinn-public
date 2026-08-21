"""Abstract adapter interface shared by all data-source importers (nanoka, hakushin, scanner)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class AnomalyStats(NamedTuple):
    """Anomaly Mastery / Proficiency pair, named so call sites cannot swap them silently.

    These two were stored backwards on every agent until 2026-07-25 because both
    sources' field names are counter-intuitive and the assignment was positional.
    Accessing by attribute (``.mastery`` / ``.proficiency``) makes a re-swap visible
    at the call site — see docs/RESEARCH_batch32c_followups.md.
    """

    mastery: int
    proficiency: int


class BaseImporter(ABC):
    """Abstract base for data importers. Adapter pattern allows swapping sources."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @abstractmethod
    async def import_agents(self) -> int:
        """Import agent/character data. Returns count of imported agents."""

    @abstractmethod
    async def import_w_engines(self) -> int:
        """Import W-Engine/weapon data. Returns count of imported W-Engines."""

    @abstractmethod
    async def import_disc_sets(self) -> int:
        """Import disc set data. Returns count of imported disc sets."""

    @abstractmethod
    async def import_enemies(self) -> int:
        """Import enemy profile data. Returns count of imported enemies."""

    async def import_all(self) -> dict[str, int]:
        """Run all importers. Returns counts per entity type."""
        return {
            "agents": await self.import_agents(),
            "w_engines": await self.import_w_engines(),
            "disc_sets": await self.import_disc_sets(),
            "enemies": await self.import_enemies(),
        }
