"""Abstract adapter interface shared by all data-source importers.

**Port state.** B.8 deleted every concrete importer (nanoka, the three hakushin
adapters, ezod, dimbreath resource costs, and the ZO scanner) and the
``AnomalyStats`` NamedTuple, which existed to keep ZZZ's Anomaly Mastery and
Proficiency from being swapped positionally — a bug fairy actually shipped. Neither
stat exists in Genshin.

The abstract method names were retargeted at the same time, which B.8 did not ask
for but the BRIEF's "delete ZZZ concepts rather than aliasing them" requires: a kept
base class advertising ``import_disc_sets()`` is an instruction to the next person
who implements it. Per DESIGN §2.5 the entity mapping is agents→characters,
w_engines→weapons, disc_sets→artifact_sets, enemies→enemies.

Chunk D writes the concrete implementation against this interface
(`nanoka_gi_importer.py`, D.1); the transport layer it ports —  manifest pin, index
fetch, detail fetch, upsert, stale prune — is in
/root/fairy/backend/app/data/importers/nanoka_importer.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class BaseImporter(ABC):
    """Abstract base for data importers. Adapter pattern allows swapping sources."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @abstractmethod
    async def import_characters(self) -> int:
        """Import character data. Returns count of imported characters."""

    @abstractmethod
    async def import_weapons(self) -> int:
        """Import weapon data. Returns count of imported weapons."""

    @abstractmethod
    async def import_artifact_sets(self) -> int:
        """Import artifact-set data. Returns count of imported sets."""

    @abstractmethod
    async def import_enemies(self) -> int:
        """Import enemy profile data. Returns count of imported enemies."""

    async def import_all(self) -> dict[str, int]:
        """Run all importers. Returns counts per entity type."""
        return {
            "characters": await self.import_characters(),
            "weapons": await self.import_weapons(),
            "artifact_sets": await self.import_artifact_sets(),
            "enemies": await self.import_enemies(),
        }
