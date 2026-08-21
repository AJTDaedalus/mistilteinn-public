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

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import Element, Rarity, StatType, TalentType, WeaponType


class Character(TimestampMixin, Base):
    """One playable character.

    Payload map (`.../en/character/{nanoka_id}.json`):

    * `element` → `element`, via `Element.parse` — **nullable**, because two of the 150
      entries carry the literal `"None"`.
    * `weapon` → `weapon_type`; `rarity` → `rarity` via `Rarity.parse`.
    * `base_hp` / `base_atk` / `base_def` are the level-1 values; the per-phase table is
      `stats_modifier.ascension` (6 rows) and lands in `ascension_stats`.
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
    nanoka_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
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

    #: `stats_modifier.ascension` verbatim: six rows of `{prop_key: value}`. Stored as JSONB
    #: rather than a sixth table because it is always read as one unit and nothing queries an
    #: individual phase. The prop keys are **lower_case** in this payload, unlike everywhere
    #: else — `enums.stat_type_for` is case-insensitive for exactly this reason.
    ascension_stats: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    burst_energy_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)

    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(32), nullable=True)

    talents: Mapped[list[Talent]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    constellations: Mapped[list[Constellation]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Constellation.position",
    )
    ascension_passives: Mapped[list[AscensionPassive]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AscensionPassive.unlock_ascension",
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

    `unlock_ascension` is the payload's `passives[].unlock`, observed as `1`, `4` and `0` —
    the two ascension gates and the utility passive that is never gated. Stored as the raw
    number rather than an enum so a future kit with a different gate is data, not a crash.
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
    unlock_ascension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)

    character: Mapped[Character] = relationship(back_populates="ascension_passives")

    def __repr__(self) -> str:
        return f"<AscensionPassive {self.name} (A{self.unlock_ascension})>"
