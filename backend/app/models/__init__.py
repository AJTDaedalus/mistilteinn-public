"""Model package — re-exports every ORM entity and domain enum for `Base.metadata` discovery."""

from app.models.artifact import (
    MAIN_STAT_POOL,
    Artifact,
    ArtifactMainStatPoolUnavailableError,
    ArtifactSet,
    ArtifactSetAffix,
    main_stats_for,
)
from app.models.auth_token import AuthToken
from app.models.base import Base, TimestampMixin
from app.models.buff_preset import BuffPreset
from app.models.build import Build, EnemyProfile
from app.models.character import (
    AscensionPassive,
    Character,
    CharacterAttack,
    CharacterEnergyDrop,
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
from app.models.optimization_run import OptimizationRun
from app.models.planner import (
    CharacterAscensionCost,
    CharacterTalentCost,
    Material,
    UserMaterial,
    WeaponAscensionCost,
)
from app.models.roster import CharacterRosterEntry
from app.models.rotation import Rotation
from app.models.seed_provenance import SeedRun
from app.models.session import Session
from app.models.sim_run import SimRun
from app.models.team import Team
from app.models.teapot import (
    FurnishingSuite,
    FurnishingSuiteFavorite,
    TeapotBuilt,
    TeapotProgress,
)
from app.models.user import User
from app.models.weapon import OwnedWeapon, Weapon, WeaponRefinement
from app.models.wish_banner import WishBanner
from app.models.wish_income import WishIncome

__all__ = [
    "MAIN_STAT_POOL",
    "Artifact",
    "ArtifactMainStatPoolUnavailableError",
    "ArtifactSet",
    "ArtifactSetAffix",
    "ArtifactSlot",
    "AscensionPassive",
    "AuthToken",
    "Base",
    "BuffPreset",
    "Build",
    "Character",
    "CharacterAscensionCost",
    "CharacterAttack",
    "CharacterEnergyDrop",
    "CharacterRosterEntry",
    "CharacterTalentCost",
    "Constellation",
    "DamageType",
    "Element",
    "EnemyProfile",
    "FurnishingSuite",
    "FurnishingSuiteFavorite",
    "Material",
    "OptimizationRun",
    "OwnedWeapon",
    "Rarity",
    "Rotation",
    "SeedRun",
    "Session",
    "SimRun",
    "StatType",
    "Talent",
    "TalentScaling",
    "TalentType",
    "Team",
    "TeapotBuilt",
    "TeapotProgress",
    "TimestampMixin",
    "User",
    "UserMaterial",
    "UserStatus",
    "Weapon",
    "WeaponAscensionCost",
    "WeaponRefinement",
    "WeaponType",
    "WishBanner",
    "WishIncome",
    "main_stats_for",
]
