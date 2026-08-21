"""Data-access layer: async repositories wrapping SQLAlchemy queries per entity.

Each repository is the sole data-access point for its model, extending
``BaseRepository[T]`` for common CRUD and adding entity-specific queries.
Services depend on these repositories rather than importing SQLAlchemy
directly, keeping persistence concerns out of business logic.
"""

from app.repositories.agent import AgentRepository
from app.repositories.base import BaseRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.disc import DiscRepository, DiscSetRepository
from app.repositories.team import TeamRepository
from app.repositories.w_engine import WEngineRepository

__all__ = [
    "AgentRepository",
    "BaseRepository",
    "BuildRepository",
    "ComboRepository",
    "DiscRepository",
    "DiscSetRepository",
    "EnemyProfileRepository",
    "TeamRepository",
    "WEngineRepository",
]
