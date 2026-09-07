"""Genshin characters: the roster row plus its talents, constellations and passives.

**New file, new class names.** Nothing here is renamed from the deleted `agent.py`. The
BRIEF names leaked ZZZ shapes in the Genshin domain model as this fork's main long-term
hazard, so a column exists here because the Genshin payload has it — not because its ZZZ
counterpart did. `specialty`, `faction`, `base_impact`, `base_anomaly_mastery`,
`base_anomaly_proficiency` and `ex_energy_cost` have no successor.

Field provenance is `backend/tests/fixtures/nanoka_gi/detail/character_10000002.json`
(nanoka 7.0.51). D.3 writes the mapping; the notes below say where each value lives so D.3
does not have to re-derive it.
"""

from __future__ import annotations

from sqlalchemy import (
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

from app.models.base import GUARDED_LAZY, Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import Element, Rarity, StatType, TalentType, WeaponType


class Character(TimestampMixin, Base):
    """One playable character.

    Payload map (`.../en/character/{nanoka_id}.json`):

    * The payload key → `nanoka_id`, **verbatim and as a string**. 28 of the 150 entries in
      the 7.0.51 index are `"{body}-{element}"` — `10000005-2` … `10000005-8`, and the same
      for 10000007, 10000117 and 10000118: four Traveler bodies × seven elements, each a
      genuinely different kit, and the bare `10000005` is not in the index at all. This
      column was `Integer` until D.3; `int(key)` raises on the first Traveler and
      skip-on-parse-failure loses all 28. See `_index_keys` in the nanoka importer.
    * `element` → `element`, via `Element.parse` — **nullable**, because two of the 150
      entries carry the literal `"None"`.
    * `weapon` → `weapon_type`; `rarity` → `rarity` via `Rarity.parse`.
    * `base_hp` / `base_atk` / `base_def` are the level-1 values; the per-phase table is
      `stats_modifier.ascension` (6 rows) and lands in `ascension_stats`, and the growth
      curve each one follows is `stats_modifier.prop_grow_curves` → `prop_curves`. All
      three are needed to get a stat at a level; F.3 found that out by having two of them.
    * `ascension_stat_type` is derived, not given: it is the key in an
      `stats_modifier.ascension` row that is not one of the three base stats.
    * `chara_info.region` → `region`; `chara_info.release_date` → `release_date`.
    * `burst_energy_cost` is **not** a top-level field. It appears inside the burst
      talent's `promote[].desc` as an `Energy Cost` row. Nullable until D.3 parses it, and
      deliberately not defaulted to a number that would look like real data.
    """

    __tablename__ = "characters"
    __table_args__ = (
        Index("ix_characters_element", "element"),
        Index("ix_characters_weapon_type", "weapon_type"),
    )

    id: Mapped[uuid_pk]
    #: The source key verbatim: `"10000002"`, or `"10000005-2"` for a Traveler variant.
    #: A string, not an integer — see the class docstring.
    nanoka_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    #: Null for the two unaligned entries whose payload element is the literal "None".
    element: Mapped[Element | None] = mapped_column(enum_column(Element, 16), nullable=True)
    weapon_type: Mapped[WeaponType] = mapped_column(enum_column(WeaponType, 32), nullable=False)
    rarity: Mapped[Rarity] = mapped_column(enum_column(Rarity, 16), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    base_hp: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_atk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_def: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    #: The stat a character gains on ascension (Crit DMG for Ayaka, EM, ATK%, …). Derived
    #: from `stats_modifier.ascension`; see the class docstring.
    ascension_stat_type: Mapped[StatType | None] = mapped_column(
        enum_column(StatType, 48), nullable=True,
    )

    #: `stats_modifier.prop_grow_curves` as `{FIGHT_PROP_BASE_*: GROW_CURVE_*}`. **Without
    #: this the three base stats above cannot be evaluated at any level** — they are level-1
    #: values that grow on a named curve, and F.3 found the gap by trying.
    #:
    #: Read from the payload, never derived from the stat: **every one of the 150 characters
    #: grows DEF on an HP curve** (`GROW_CURVE_HP_S4`/`_S5`), so "the DEF curve" is not a
    #: thing. Project Amber publishes the same pairing independently.
    prop_curves: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    #: The three per-character base values the payload publishes beside the scaling stats.
    #: gcsim hardcodes `CR += 0.05` / `CD += 0.5` (`basestat.go:82-84`) and reads EM from
    #: the character data — and the payloads show why the last one matters and the first
    #: does not quite hold: **Lauma publishes 200 base EM and Nefer 100**, while the two
    #: unreleased Traveler bodies publish `crit_rate: 0` rather than 0.05. Storing what the
    #: payload says costs three columns and removes three assumptions.
    base_elemental_mastery: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_crit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_crit_dmg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    #: `stats_modifier.ascension` verbatim: six rows of `{prop_key: value}`. Stored as JSONB
    #: rather than a sixth table because it is always read as one unit and nothing queries an
    #: individual phase. The prop keys are **lower_case** in this payload, unlike everywhere
    #: else — `enums.stat_type_for` is case-insensitive for exactly this reason.
    ascension_stats: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: `level_exp` verbatim: 89 usable entries, **per level and not cumulative** — entry `i`
    #: is the EXP to go from level `i+1` to `i+2`, and the first 89 sum to 8,362,650, the
    #: published total to level 90. The 90th entry exists in the payload and is unreachable.
    #: Read whole by the planner, so JSONB rather than a row per level.
    level_exp: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
    )

    burst_energy_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)

    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(32), nullable=True)

    talents: Mapped[list[Talent]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    constellations: Mapped[list[Constellation]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Constellation.position",
    )
    ascension_passives: Mapped[list[AscensionPassive]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # NULLs sort last in Postgres ASC, which puts the condition-gated passives after
        # the phase-gated ones; `nanoka_id` breaks the tie so the order is total.
        order_by="AscensionPassive.unlock_ascension, AscensionPassive.nanoka_id",
    )

    def __repr__(self) -> str:
        return f"<Character {self.name} ({self.element or 'no vision'})>"


class Talent(TimestampMixin, Base):
    """One entry of a character's `skills[]` — a normal attack, skill, burst, or sprint.

    `talent_type` is classified from `promote[].icon` (`enums.TalentType.from_skill_icon`),
    **never from list position**: Ayaka has four entries where most characters have three,
    so position means nothing.
    """

    __tablename__ = "talents"
    __table_args__ = (
        UniqueConstraint("character_id", "nanoka_id", name="uq_talents_character_id_nanoka_id"),
    )

    id: Mapped[uuid_pk]
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    nanoka_id: Mapped[int] = mapped_column(Integer, nullable=False)
    talent_type: Mapped[TalentType] = mapped_column(enum_column(TalentType, 24), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)

    character: Mapped[Character] = relationship(back_populates="talents")
    scalings: Mapped[list[TalentScaling]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="talent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TalentScaling.level",
    )

    def __repr__(self) -> str:
        return f"<Talent {self.name} [{self.talent_type}]>"


class TalentScaling(TimestampMixin, Base):
    """One talent level's published multiplier table.

    Genshin publishes an **explicit table per level**, not a base-plus-growth pair — which
    is why this replaces ZZZ's `attacks.base`/`growth` columns rather than renaming them
    (DESIGN §2.5).

    `labels` and `params` come straight from `skills[].promote[<level>]`: `desc` is the list
    of `"1-Hit DMG|{param1:F1P}"` format strings and `param` the parallel numeric list.
    Both are kept verbatim so the formatting directives survive for the UI, and so a
    mis-parse in Chunk F is a bug in the parser rather than lost data.
    """

    __tablename__ = "talent_scalings"
    __table_args__ = (
        UniqueConstraint("talent_id", "level", name="uq_talent_scalings_talent_id_level"),
    )

    id: Mapped[uuid_pk]
    talent_id: Mapped[str] = mapped_column(
        ForeignKey("talents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    labels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    params: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    talent: Mapped[Talent] = relationship(back_populates="scalings")

    def __repr__(self) -> str:
        return f"<TalentScaling lv{self.level} of {self.talent_id}>"


class Constellation(TimestampMixin, Base):
    """One of a character's six constellations (C1-C6).

    `position` is 1-6 and is the ordinal, not the payload id: the payload's
    `constellations[].id` values are contiguous but arbitrary (21-26 for Ayaka), so ordering
    on them would be a coincidence rather than a guarantee.
    """

    __tablename__ = "constellations"
    __table_args__ = (
        UniqueConstraint(
            "character_id", "position", name="uq_constellations_character_id_position",
        ),
    )

    id: Mapped[uuid_pk]
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    nanoka_id: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)

    character: Mapped[Character] = relationship(back_populates="constellations")

    def __repr__(self) -> str:
        return f"<Constellation C{self.position} {self.name}>"


class AscensionPassive(TimestampMixin, Base):
    """A passive talent: 1st-ascension, 4th-ascension, or the always-on utility one.

    **`passives[].unlock` has two shapes, and C.3 only knew about one.** Swept across all
    150 character payloads at 7.0.51 (D.2): it is an integer 460 times — `0` (164), `1`
    (148) and `4` (148), the utility passive and the two ascension gates — and a **list**
    33 times, always a single id: `[603101]` on the Traveler's "Foreign Starfire",
    `[7469304]` on Cyno's "A Star With Which to Start the Journey", `[7469604]` on Qiqi's
    "Seven Sacred Treasures". Assigning that list to an `Integer NOT NULL` column is a
    crash on 33 of ~460 passives.

    So the two shapes get two columns. `unlock_ascension` keeps the integer gate and is
    **nullable**, null meaning "the payload expressed the unlock as a condition instead";
    `unlock_condition_ids` holds the list verbatim. The payload does not say what those ids
    refer to and nothing here guesses — the name says what it is (an id list gating the
    unlock), not what it means.
    """

    __tablename__ = "ascension_passives"
    __table_args__ = (
        UniqueConstraint(
            "character_id", "nanoka_id", name="uq_ascension_passives_character_id_nanoka_id",
        ),
    )

    id: Mapped[uuid_pk]
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    nanoka_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The ascension phase that unlocks this passive (`0`, `1` or `4`), or NULL when the
    #: payload gave a condition list instead. Not an enum: a future kit with a different
    #: gate should be data, not a crash.
    unlock_ascension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: `passives[].unlock` in its list form, verbatim; `[]` when the unlock is an integer
    #: gate. Kept rather than dropped so the 33 affected passives stay distinguishable
    #: from a genuinely ungated one.
    unlock_condition_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)

    character: Mapped[Character] = relationship(back_populates="ascension_passives")

    def __repr__(self) -> str:
        gate = f"A{self.unlock_ascension}" if self.unlock_ascension is not None else "cond"
        return f"<AscensionPassive {self.name} ({gate})>"
