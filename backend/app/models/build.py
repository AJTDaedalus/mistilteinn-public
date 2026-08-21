"""A user's saved Build (agent + gear), its attack Combo sequences, and EnemyProfile targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.user import User  # noqa: F401 — ensures FK target is registered

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.disc import Disc
    from app.models.team import Team
    from app.models.w_engine import WEngine


class Build(TimestampMixin, Base):
    """A character build: agent + W-Engine + mindscape level. Discs link back via Disc.build_id."""

    __tablename__ = "builds"
    __table_args__ = (
        Index(
            "uq_builds_owner_agent",
            "owner_id", "agent_id",
            unique=True,
            postgresql_where=text("owner_id IS NOT NULL"),
        ),
        CheckConstraint(
            "potential_rank BETWEEN 0 AND 6",
            name="ck_builds_potential_rank_range",
        ),
    )

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    w_engine_id: Mapped[str | None] = mapped_column(
        ForeignKey("w_engines.id", ondelete="SET NULL"), nullable=True, default=None
    )
    w_engine_level: Mapped[int] = mapped_column(Integer, default=60)  # 1-60
    mindscape_level: Mapped[int] = mapped_column(Integer, default=0)  # 0-6
    agent_level: Mapped[int] = mapped_column(Integer, default=60)
    skill_levels: Mapped[str] = mapped_column(String(100), default="12,12,12,12,12")
    # Format: "basic,dodge,special,chain,core" levels

    # Core *passive* upgrade tier (A=0, B=1, C=2, D=3, E=4, F=5). Drives
    # which row of ``Agent.core_stats`` is folded into the snapshot.
    # Distinct from the core *skill* attack level above, which scales the
    # passive's named hits.
    core_skill_level: Mapped[int] = mapped_column(Integer, default=5)

    # W-Engine refinement rank (1-5). Applied to both DPS and support builds.
    w_engine_refinement: Mapped[int] = mapped_column(Integer, default=1)

    # Potential Vision level owned: 0 = not unlocked, 1..6 = Level I..VI (#90).
    # Selects which kit and move set the calc resolves (>= 1 means the Potential
    # kit); Track 2 will index the per-level value ramps.
    #
    # 1..6 rather than 1..5: nanoka lists SIX separately-purchasable nodes per agent
    # (in-game "Shark's Rage I".."VI"). Level I buys the kit variant and NO value bonus;
    # Levels II-VI add the ramp. Track 2 therefore indexes `ramp[potential_rank - 1]`,
    # and rank 0 never indexes the ramp at all.
    #
    # Default 6 is load-bearing: it means "fully unlocked", so every pre-#90 build keeps
    # the numbers it had under #85's unconditional-unlocked import.
    potential_rank: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=6, server_default=text("6")
    )

    notes: Mapped[str] = mapped_column(String(1000), default="")

    optimizer_priority: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None, index=True
    )

    # Stable IDs (``<hakushin_id>:<slugified_source_label>``) of kit
    # modifiers the user has switched off for this build. Snapshot
    # construction filters them out before the buff resolver runs, so a
    # disabled buff contributes nothing to stats, attribution, or the
    # damage calc — same effect as if the modifier didn't exist for
    # this build.
    disabled_buffs: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    active_conditions: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    stack_counts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    agent: Mapped[Agent] = relationship(foreign_keys=[agent_id])
    w_engine: Mapped[WEngine | None] = relationship()
    discs: Mapped[list[Disc]] = relationship(
        foreign_keys="Disc.build_id",
        order_by="Disc.build_slot",
    )

    def __repr__(self) -> str:
        return f"<Build {self.agent_id} M{self.mindscape_level}>"


class Combo(TimestampMixin, Base):
    """An attack sequence for a single agent build."""

    __tablename__ = "combos"

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)

    # Sequence of attack references: [{"attack_id": "...", "label": "BA1"}, ...]
    sequence: Mapped[list | None] = mapped_column(JSONB, default=None)

    description: Mapped[str] = mapped_column(String(1000), default="")

    team: Mapped[Team] = relationship()

    def __repr__(self) -> str:
        return f"<Combo {self.name}>"


class EnemyProfile(TimestampMixin, Base):
    """Enemy stat profile for damage calculations."""

    __tablename__ = "enemy_profiles"

    id: Mapped[uuid_pk]
    hakushin_id: Mapped[int | None] = mapped_column(
        Integer,
        unique=True,
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[int] = mapped_column(Integer, default=60)

    # Base stats
    hp: Mapped[int] = mapped_column(Integer, default=0)
    atk: Mapped[int] = mapped_column(Integer, default=0)
    defense: Mapped[int] = mapped_column(Integer, default=50)  # base_def (hakushin: Defence)

    # Elemental RES (basis points, -2000 = -20% = weakness)
    physical_res: Mapped[int] = mapped_column(Integer, default=0)
    fire_res: Mapped[int] = mapped_column(Integer, default=0)
    ice_res: Mapped[int] = mapped_column(Integer, default=0)
    electric_res: Mapped[int] = mapped_column(Integer, default=0)
    ether_res: Mapped[int] = mapped_column(Integer, default=0)
    wind_res: Mapped[int] = mapped_column(Integer, default=0)

    # Anomaly Capacity per element
    anomaly_capacity_physical: Mapped[int] = mapped_column(Integer, default=100)
    anomaly_capacity_fire: Mapped[int] = mapped_column(Integer, default=100)
    anomaly_capacity_ice: Mapped[int] = mapped_column(Integer, default=100)
    anomaly_capacity_electric: Mapped[int] = mapped_column(Integer, default=100)
    anomaly_capacity_ether: Mapped[int] = mapped_column(Integer, default=100)
    anomaly_capacity_wind: Mapped[int] = mapped_column(Integer, default=100)

    # Anomaly RES (basis points, -2000 = -20% weakness, +2000 = +20% resistance)
    anomaly_res_physical: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_res_fire: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_res_ice: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_res_electric: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_res_ether: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_res_wind: Mapped[int] = mapped_column(Integer, default=0)

    # Anomaly Duration and Stun factors
    anomaly_duration_default: Mapped[float] = mapped_column(Float, default=10.0)
    stun_buildup_multiplier: Mapped[int] = mapped_column(Integer, default=10000)

    # Stun mechanics
    stun_threshold: Mapped[int] = mapped_column(Integer, default=0)
    stun_dmg_taken_ratio: Mapped[int] = mapped_column(Integer, default=5000)  # 50% = typical

    # Tags for filtering
    rarity: Mapped[int] = mapped_column(Integer, default=1)  # 1=common, 2=elite, 3=boss
    tags: Mapped[str] = mapped_column(String(500), default="")  # comma-separated

    def __repr__(self) -> str:
        return f"<EnemyProfile {self.name} lv{self.level}>"
