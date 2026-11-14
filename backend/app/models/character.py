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
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    case,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUARDED_LAZY, Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import Element, Rarity, StatType, TalentType, WeaponType

#: The order the game lists a character's talents in: normal attack, skill, an alternate sprint
#: where the kit has one, then burst.
_TALENT_ORDER = {
    TalentType.NORMAL_ATTACK: 0,
    TalentType.ELEMENTAL_SKILL: 1,
    TalentType.ALTERNATE_SPRINT: 2,
    TalentType.ELEMENTAL_BURST: 3,
}


class Character(TimestampMixin, Base):
    """One playable character.

    Payload map (`.../en/character/{nanoka_id}.json`):

    * The payload key → `nanoka_id`, **verbatim and as a string**. 28 of the 150 entries in
      the 7.0.51 index are `"{body}-{element}"` — `10000005-2` … `10000005-8`, and the same
      for 10000007, 10000117 and 10000118 — but those are **not** four Traveler bodies.
      `10000005` and `10000007` are Aether and Lumine; `10000117` and `10000118` are
      **Manekin and Manekina**, the practice mannequins. Two bodies x seven elements each,
      twice over, and the bare `10000005` is not in the index at all. This column was
      `Integer` until D.3; `int(key)` raises on the first of them and skip-on-parse-failure
      loses all 28. See `_index_keys` in the nanoka importer.
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

    #: Datamined ahead of release — in the manifest's `gi.new` at seed time.
    #:
    #: **These rows used to be refused entry**, under a standing ruling that beta content must
    #: not reach the app. The owner reopened it (2026-09-07) for the planner specifically: what
    #: an upcoming character will cost to level is exactly what a player wants before they pull,
    #: and it is the one surface where being wrong is cheap — nothing is simulated, nothing is
    #: ranked, and the numbers are a shopping list you check against your own inventory.
    #:
    #: **It stays opt-in per query, not per page.** `CharacterRepository.list` hides these
    #: unless asked, so every existing caller — the catalogue browser, the build editor, and
    #: through it the optimizer — keeps the old behaviour without knowing this column exists.
    #: The planner asks. That is also what keeps a beta character out of a build and therefore
    #: out of the optimizer, which is the exclusion the owner asked for.
    is_beta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                          server_default="false")

    talents: Mapped[list[Talent]] = relationship(
        lazy=GUARDED_LAZY,
        # **Ordered, like every sibling relationship here.** It was the one that was not, so
        # Postgres returned talents in whatever order it liked: the API, the rotation abilities
        # and `test_children_land_with_their_parent` saw it change between runs. `nanoka_id`
        # cannot be the key — Ayaka's ids put her sprint first — so the game's own order is
        # spelled out, with `nanoka_id` breaking ties.
        order_by=lambda: [
            case(_TALENT_ORDER, value=Talent.talent_type, else_=len(_TALENT_ORDER)),
            Talent.nanoka_id,
        ],
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
    attacks: Mapped[list[CharacterAttack]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CharacterAttack.position",
    )
    energy_drops: Mapped[list[CharacterEnergyDrop]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CharacterEnergyDrop.position",
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
    #: The numbers the description renders inside `<color=…>` markup, verbatim from the
    #: payload's `param_list` — trailing zeros included, because the payload pads every list
    #: to a fixed width and trimming would be a reading of the data rather than the data.
    #: Imported for the formula fallback (`TASKS_team_math_fallback.md` task 4); it was the
    #: one numeric field the importer dropped while keeping the text that renders it.
    param_list: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
    )

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
    #: The numbers the description renders inside `<color=…>` markup, verbatim from the
    #: payload's `param_list` — trailing zeros included, because the payload pads every list
    #: to a fixed width and trimming would be a reading of the data rather than the data.
    #: Imported for the formula fallback (`TASKS_team_math_fallback.md` task 4); it was the
    #: one numeric field the importer dropped while keeping the text that renders it.
    param_list: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
    )

    character: Mapped[Character] = relationship(back_populates="ascension_passives")

    def __repr__(self) -> str:
        gate = f"A{self.unlock_ascension}" if self.unlock_ascension is not None else "cond"
        return f"<AscensionPassive {self.name} ({gate})>"


class CharacterAttack(TimestampMixin, Base):
    """One entry of the payload's `attack[]`: a damage instance and how it applies.

    **Per character, not per talent.** The payload lists them flat and names no talent; the
    only link is `damage_param`, which is sometimes the internal name of a talent row
    (`"Ayaka_ExtraAttack_Damage"`), sometimes a bare multiplier, sometimes a list and
    sometimes null. Nothing here resolves that link, so it is stored as published (JSONB)
    and the reading of it is left to whoever needs it (DESIGN_team_math_fallback.md P3).

    **`element` is the game's internal spelling, not `Element`.** The payload says `Fire`,
    `Ice`, `Electric`, `None`, and spellings that are not a vision at all (`AntiFire`).
    Mapping them here would be a decision about what `AntiFire` means made in an importer;
    absent a cited mapping it stays verbatim, the same rule `Data Values` sets for fractions.
    """

    __tablename__ = "character_attacks"
    __table_args__ = (
        UniqueConstraint(
            "character_id", "position", name="uq_character_attacks_character_id_position",
        ),
    )

    id: Mapped[uuid_pk]
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    #: The entry's index in `attack[]`, from 0. The payload repeats identical entries
    #: (Ayaka's charged attack is three), so position is the only identity a row has.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    element: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icd_tag: Mapped[str | None] = mapped_column(String(120), nullable=True)
    icd_group: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Elemental gauge units, as published. Null when the payload says null.
    gauge: Mapped[float | None] = mapped_column(Float, nullable=True)
    poise_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    poise_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    attack_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strike_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: A string, a number, a list or null in the payload, and kept as whichever it was.
    damage_param: Mapped[object | None] = mapped_column(JSONB, nullable=True)

    character: Mapped[Character] = relationship(back_populates="attacks")

    def __repr__(self) -> str:
        return f"<CharacterAttack #{self.position} {self.name} [{self.element}]>"


class CharacterEnergyDrop(TimestampMixin, Base):
    """One entry of the payload's `energy[]`: a particle drop a skill can produce.

    The basis for a closed-form Energy Recharge estimate (G13), which nothing computes yet.
    `per_drop` and `chance` are kept exactly as published — `chance` is a **percent** in the
    payload (`50.0`), not a fraction, and it is not converted: converting on the way in would
    make every later citation check a converted number (`backend/CLAUDE.md`, Data Values).
    """

    __tablename__ = "character_energy_drops"
    __table_args__ = (
        UniqueConstraint(
            "character_id", "position", name="uq_character_energy_drops_character_id_position",
        ),
    )

    id: Mapped[uuid_pk]
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: The internal name of the skill that drops it (`Icespine_Strike_New`), verbatim.
    skill: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: A vision name here (`Cryo`), unlike `CharacterAttack.element`; still stored verbatim.
    element: Mapped[str | None] = mapped_column(String(32), nullable=True)
    per_drop: Mapped[float | None] = mapped_column(Float, nullable=True)
    lifetime: Mapped[float | None] = mapped_column(Float, nullable=True)
    chance: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Seconds between drops. **Eight entries at 7.2.51 publish a name here instead** (`CD`,
    #: `CDTime`, `DropBall_CD`) — a reference into a skill's own parameters, like
    #: `CharacterAttack.damage_param`. That goes to `cd_ref` and leaves this null, rather than
    #: one column holding two kinds of thing.
    cd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cd_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applications: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drop_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    character: Mapped[Character] = relationship(back_populates="energy_drops")

    def __repr__(self) -> str:
        return f"<CharacterEnergyDrop #{self.position} {self.skill} {self.per_drop}>"
