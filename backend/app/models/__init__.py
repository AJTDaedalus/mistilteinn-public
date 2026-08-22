"""Model package — re-exports every ORM entity and domain enum for `Base.metadata` discovery."""

from app.models.artifact import (
    MAIN_STAT_POOL,
    Artifact,
    ArtifactMainStatPoolUnavailableError,
    ArtifactSet,
    ArtifactSetAffix,
    main_stats_for,
)
from app.models.base import Base, TimestampMixin
from app.models.buff_preset import BuffPreset
from app.models.build import Build, EnemyProfile
from app.models.character import (
    AscensionPassive,
    Character,
    Constellation,
    Talent,
    TalentScaling,
)
from app.models.enums import (
    ArtifactSlot,
    DamageType,
    Element,
    Rarity,
    StatType,
    TalentType,
    UserStatus,
    WeaponType,
)
from app.models.optimization_job import OptimizationJob
from app.models.seed_provenance import SeedRun
from app.models.session import Session
from app.models.sim_run import SimRun
from app.models.team import Team
from app.models.user import User
from app.models.weapon import Weapon, WeaponRefinement

__all__ = [
    "MAIN_STAT_POOL",
    "Artifact",
    "ArtifactMainStatPoolUnavailableError",
    "ArtifactSet",
    "ArtifactSetAffix",
    "ArtifactSlot",
    "AscensionPassive",
    "Base",
    "BuffPreset",
    "Build",
    "Character",
    "Constellation",
    "DamageType",
    "Element",
    "EnemyProfile",
    "OptimizationJob",
    "Rarity",
    "SeedRun",
    "Session",
    "SimRun",
    "StatType",
    "Talent",
    "TalentScaling",
    "TalentType",
    "Team",
    "TimestampMixin",
    "User",
    "UserStatus",
    "Weapon",
    "WeaponRefinement",
    "WeaponType",
    "main_stats_for",
]
