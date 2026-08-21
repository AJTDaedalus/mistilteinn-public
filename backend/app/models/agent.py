"""The playable Agent entity and its owned skills, attacks, core passives, and mindscapes."""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.enums import (
    Element,
    HitMode,
    PotentialTag,
    Rarity,
    RowCondition,
    Specialty,
)


class Agent(TimestampMixin, Base):
    """A ZZZ playable character: element/specialty/rarity metadata plus base stats and growth."""

    __tablename__ = "agents"

    id: Mapped[uuid_pk]
    hakushin_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    element: Mapped[Element] = mapped_column(String(20))
    specialty: Mapped[Specialty] = mapped_column(String(20))
    rarity: Mapped[Rarity] = mapped_column(String(5))
    faction: Mapped[str] = mapped_column(String(200), default="")
    faction_id: Mapped[int] = mapped_column(Integer, default=0)
    icon_path: Mapped[str] = mapped_column(String(500), default="", server_default="")

    # Base stats at level 1. ``*_growth`` is per-level scaling in basis
    # points (decimal × 10000); ``promotion_stats`` carries the discrete
    # ZZZ promotion bonuses applied at lv11 / 21 / 31 / 41 / 51 / 60. The
    # snapshot builder combines these with the build's ``agent_level`` to
    # compute the actual stat total at calc time.
    base_hp: Mapped[int] = mapped_column(Integer, default=0)
    base_atk: Mapped[int] = mapped_column(Integer, default=0)
    base_def: Mapped[int] = mapped_column(Integer, default=0)
    hp_growth: Mapped[int] = mapped_column(Integer, default=0)
    atk_growth: Mapped[int] = mapped_column(Integer, default=0)
    def_growth: Mapped[int] = mapped_column(Integer, default=0)

    # Six entries (promotions 0..5) — each {hp, atk, def} bonus added at
    # the corresponding promotion. ``None`` for legacy rows without this
    # data; treated as zeros at calc time.
    promotion_stats: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )

    # Six entries (core upgrade tiers A..F = index 0..5) — flat / pct
    # bonuses unlocked as the user invests cores. Field names follow ZO's
    # ``coreStats`` shape (``atk``, ``crit_``, ``crit_dmg_``, ``pen_``,
    # ``atk_``, ``hp``, ``hp_``, ``anomMas``, ``anomProf``, ``impact``,
    # ``enerRegen``); ``_``-suffixed values are decimal pcts in ZO and
    # converted to basis points at snapshot time. ``None`` for legacy
    # rows; treated as zeros at calc time.
    core_stats: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )

    # Combat stats (basis points)
    base_crit_rate: Mapped[int] = mapped_column(Integer, default=500)  # 5.00%
    base_crit_dmg: Mapped[int] = mapped_column(Integer, default=5000)  # 50.00%
    base_anomaly_mastery: Mapped[int] = mapped_column(Integer, default=0)
    base_anomaly_proficiency: Mapped[int] = mapped_column(Integer, default=0)
    base_impact: Mapped[int] = mapped_column(Integer, default=0)
    base_energy_regen: Mapped[int] = mapped_column(Integer, default=0)
    base_pen_flat: Mapped[int] = mapped_column(Integer, default=0)
    base_pen_ratio: Mapped[int] = mapped_column(Integer, default=0)

    # EX Special energy cost (integer units, e.g. 60, 45). None for agents
    # whose primary is not energy-gated (stance charges, etc.).
    ex_energy_cost: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    # Per-level value ramps for this agent's Potential Vision (#90 Track 2).
    #
    # A list of params, each a SIX-element ramp indexed by `builds.potential_rank - 1`:
    #   index 0 -> Level I   (node <aid>00) — the kit variant, and no value bonus, so this
    #              entry is 0 for every param by construction
    #   index 1..5 -> Levels II..VI
    # `potential_rank == 0` (not unlocked) never indexes this at all.
    #
    # Derived by the importer from `potential_detail[<aid>01..05].desc` — see
    # `_parse_potential_ramps`. That derivation reproduces ZO's `potentialParams` for 27 of
    # 28 params across all 10 agents that have them; the 28th is ZO's own defect (Jane's
    # 25-for-0.25). docs/RESEARCH_potential_ramps.md.
    #
    # None for the 49 agents with no Potential tree. Koleda DOES populate, despite her
    # Potential being unreleased — the importer reads nanoka's `latest` by policy and her
    # nodes already carry text, so hers are pre-release values.
    #
    # Percentages are stored as DECIMALS (0.016), matching ZO's convention and the source
    # text, NOT as basis points — the modifier layer converts at bind time.
    potential_params: Mapped[list | None] = mapped_column(
        # `none_as_null=True` matters: without it SQLAlchemy stores Python None as the
        # JSON scalar `'null'` rather than SQL NULL, so "this agent has no ramps" becomes
        # a value that `IS NOT NULL` matches and `jsonb_array_length` chokes on. It only
        # bites rows INSERTED with None — for a row already NULL, assigning None emits no
        # UPDATE — so it stayed invisible locally and appeared on prod the moment two new
        # agents were inserted by a re-seed.
        JSONB(none_as_null=True),
        nullable=True,
        default=None,
    )

    # Whether this agent has a Potential tree at all (#90). 11 of 60 do. Set by the
    # importer from nanoka's root `potential` list. The UI needs it to decide whether
    # to offer the Potential toggle: an inert control on the other 49 agents is a
    # support question waiting to happen.
    has_potential: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Relationships
    skills: Mapped[list["AgentSkill"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    attacks: Mapped[list["Attack"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    core_skills: Mapped[list["CoreSkill"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    mindscapes: Mapped[list["Mindscape"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    resource_costs: Mapped[list["AgentResourceCost"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Agent {self.name} ({self.element.value}/{self.specialty.value})>"


class AgentSkill(Base):
    """Skill type grouping (Basic, Dodge, Special, Ultimate, etc.) with material costs."""

    __tablename__ = "agent_skills"

    id: Mapped[uuid_pk]
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    skill_key: Mapped[str] = mapped_column(String(50))  # "Basic", "Dodge", "Special", etc.
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    # See Attack.potential. Skill *descriptions* differ between the two states for 25
    # moves across 9 agents, and for several the base text omits the whole mechanic.
    potential: Mapped[PotentialTag | None] = mapped_column(String(16), nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="skills")

    def __repr__(self) -> str:
        return f"<AgentSkill {self.skill_key}: {self.name}>"


class Attack(Base):
    """Individual attack hit with damage multipliers."""

    __tablename__ = "attacks"

    id: Mapped[uuid_pk]
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    hakushin_skill_id: Mapped[int] = mapped_column(Integer, index=True)
    skill_key: Mapped[str] = mapped_column(String(50))  # "Basic", "Dodge", "Special", etc.
    name: Mapped[str] = mapped_column(String(200))
    hit_index: Mapped[int] = mapped_column(Integer, default=0)  # For multi-hit combos

    # Element for this specific attack (may differ from agent element)
    element: Mapped[Element] = mapped_column(String(20))

    # Damage values (basis points, from hakushin DamagePercentage fields)
    damage_base: Mapped[int] = mapped_column(Integer, default=0)  # Base multiplier at skill lv1
    damage_growth: Mapped[int] = mapped_column(Integer, default=0)  # Per-level growth
    stun_base: Mapped[int] = mapped_column(Integer, default=0)  # Daze/stun value
    stun_growth: Mapped[int] = mapped_column(Integer, default=0)
    # Decibel generation (SpRecovery)
    energy_gain: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_buildup: Mapped[int] = mapped_column(Integer, default=0)  # AttributeInfliction

    hit_mode: Mapped[HitMode] = mapped_column(
        String(20), default="atomic", server_default="atomic"
    )
    variant_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # nanoka's per-hit ``param`` label, e.g. "Enhanced Basic Attack 5th-Hit DMG
    # Multiplier". The discriminating datum for press-chain vs. variant rows. Rows may
    # legitimately share one (a single param expands to several rows), and a DB migrated
    # but not re-seeded has it NULL everywhere — treat all-NULL as "cannot check".
    param_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Which Potential state this row belongs to (#90). NULL = present in both; "base" =
    # base kit only; "unlocked" = Potential only. Assigned by the importer, so a DB that
    # was migrated but not re-seeded has it NULL everywhere — which reads as "every row
    # is shared" and makes the toggle silently inert. `validate_kits --require-db` treats
    # that as "cannot check", never as clean (DESIGN_potential_toggle.md §7).
    potential: Mapped[PotentialTag | None] = mapped_column(String(16), nullable=True)

    # Runtime game state this row is gated on (D-CH5). NULL = unconditional, deliberately
    # the same shape as `potential` above. Unlike `potential` it is NOT filtered at query
    # time: `potential` is fixed for a build, while stun flips on the rotation's own
    # `stun_trigger` / `stun_end` markers, so this is re-checked at every hit inside
    # `anomaly_simulator`. Assigned by the skill-override seeder, so a migrated-but-not-
    # re-seeded DB has it NULL everywhere — which reads as "every row is unconditional"
    # and makes a gated row fire when it should not.
    select_when: Mapped[RowCondition | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        # `potential` joins this index because both variants now coexist: without it,
        # the two rows of a base/unlocked pair collide under the same
        # (agent, name, variant_label) prefix (DESIGN_potential_toggle.md §4.2).
        Index(
            "ix_attacks_agent_name_variant",
            "agent_id",
            "name",
            "variant_label",
            "potential",
        ),
    )

    agent: Mapped["Agent"] = relationship(back_populates="attacks")

    @property
    def damage_at_level(self) -> "callable":
        """Return a function that computes damage multiplier at a given skill level."""
        base = self.damage_base
        growth = self.damage_growth

        def calc(level: int) -> float:
            return (base + growth * (level - 1)) / 10000

        return calc

    def __repr__(self) -> str:
        return f"<Attack {self.name} hit={self.hit_index} dmg={self.damage_base}>"


class CoreSkill(Base):
    """Core passive skill with upgrade levels."""

    __tablename__ = "core_skills"

    id: Mapped[uuid_pk]
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    hakushin_id: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    # See Attack.potential. 6 of the 11 agents restate their whole core passive under
    # Potential, giving 14 rows with `level` 1..7 appearing twice — identical `name`s, so
    # `potential` is the only thing that tells the two halves apart.
    potential: Mapped[PotentialTag | None] = mapped_column(String(16), nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="core_skills")

    def __repr__(self) -> str:
        return f"<CoreSkill {self.name} lv{self.level}>"


class Mindscape(Base):
    """Mindscape Cinema level (constellation equivalent)."""

    __tablename__ = "mindscapes"

    id: Mapped[uuid_pk]
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer)  # 1-6
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    agent: Mapped["Agent"] = relationship(back_populates="mindscapes")

    def __repr__(self) -> str:
        return f"<Mindscape M{self.level}: {self.name}>"


class AgentResourceCost(Base):
    """One priced action of one agent: what it costs, out of which bank, per press or per second.

    ``Agent.ex_energy_cost`` is a single scalar for a single mode, and that is not the shape of
    the data: Burnice's EX has two modes and each is billed three ways (40 to activate, 12.5 per
    second of spray, 5 for the blast; then 10 / 25 per sec / 10 again). A one-scalar column can
    only ever hold one of those six, and which one it holds is a judgement the importer has to
    make -- ``ex_energy_ambiguous`` in ``resource_costs.json`` marks the agents where it guessed.

    Rows are keyed by the upstream TextMap property key (``Burnice_Property_ExSpecial_01_
    SpCostValue_02``) because that is what a move spec binds to (``ChannelSpec.drain_cost_key``
    and friends). The binding lives in the move JSON, the **values live here**, per the
    source-of-truth rule: a curator may say *which* cost a move pays, never *how much* it is.

    ``ex_energy_cost`` is deliberately NOT removed. ~50 single-mode agents are served correctly
    by it, and it is the simulator's fallback for every agent with no cost-key binding
    (docs/DESIGN_channeled_moves.md 4.5).
    """

    __tablename__ = "agent_resource_costs"
    __table_args__ = (
        # The key is how a move spec binds to a row. Two rows sharing one key make that bind
        # ambiguous, and the ambiguity would surface as a silently-wrong energy bill rather
        # than an error, so it is a constraint rather than a convention.
        UniqueConstraint("agent_id", "cost_key", name="uq_agent_resource_costs_agent_key"),
    )

    id: Mapped[uuid_pk]
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    # Upstream TextMap property key, e.g. "Burnice_Property_ExSpecial_01_SpCostValue_02".
    cost_key: Mapped[str] = mapped_column(String(200))
    # Float, not Integer: 12.5 Energy/sec is a real upstream value and an Integer column
    # floors it to 12 -- a 4% under-bill that no test would notice.
    value: Mapped[float] = mapped_column(Float)
    # Is `value` charged once, or once per second held? NOT nullable: a NULL would read as
    # "not a drain", which is a wrong answer wearing the costume of a default.
    per_sec: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Which bank pays: "Energy" for most, but Velina's Windbloom and Starlight-Billy's
    # Heat/Rp share this table. An unnamed bank cannot be debited, so this is required.
    resource: Mapped[str] = mapped_column(String(50), default="Energy", server_default="Energy")

    agent: Mapped["Agent"] = relationship(back_populates="resource_costs")

    def __repr__(self) -> str:
        rate = "/s" if self.per_sec else ""
        return f"<AgentResourceCost {self.cost_key}={self.value}{rate} {self.resource}>"
