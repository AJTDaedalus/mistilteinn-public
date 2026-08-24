"""Data-access layer: async repositories wrapping SQLAlchemy queries per entity.

Each repository is the sole data-access point for its model, extending
``BaseRepository[T]`` for common CRUD and adding entity-specific queries.
Services depend on these repositories rather than importing SQLAlchemy
directly, keeping persistence concerns out of business logic.

**Port state.** B.7 deleted the ZZZ repositories — ``agent``, ``attack``, ``disc``,
``w_engine``, ``buff_preset`` and ``build`` (which also carried ``ComboRepository`` and
``EnemyProfileRepository``). ``base``, ``optimization_job``, ``session``, ``user`` and a
trimmed ``team`` survive; all five are game-agnostic.

``BuffPreset`` and ``Build`` keep their models but lose their repositories for now, which
is deliberate: nothing reads them while the routes are gone, and a repository written
against a skeleton model would only have to be rewritten in C.6.
"""

from app.repositories.base import BaseRepository
from app.repositories.rotation import RotationRepository
from app.repositories.session import SessionRepository
from app.repositories.team import TeamRepository
from app.repositories.user import UserRepository

__all__ = [
    "BaseRepository",
    "RotationRepository",
    "SessionRepository",
    "TeamRepository",
    "UserRepository",
]
