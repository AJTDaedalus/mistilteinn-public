"""A user's saved Build and the EnemyProfile it is calculated against.

Rewritten for Genshin in C.6. B.4 left both as skeletons carrying only identity and owner
scoping; this gives them their real columns. Nothing is renamed from the ZZZ versions —
`mindscape_level`, `w_engine_refinement`, `potential_rank`, the disc relationships, and
every anomaly/stun/daze column on `EnemyProfile` are gone rather than re-pointed.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.artifact import Artifact, artifact_slot_sort_order
from app.models.base import GUARDED_LAZY, Base, TimestampMixin, uuid_pk
from app.models.character import Character
from app.models.user import User  # noqa: F401 — ensures FK target is registered
from app.models.weapon import Weapon


class Build(TimestampMixin, Base):
    """A character build: character + weapon + five artifacts + talent and constellation levels.

    Artifacts point *here* (`Artifact.build_id`) rather than being five FK columns on this
    row. That is the shape fairy used for discs and the reason still holds: a piece is
    equipped by at most one build, unequipping must not delete it, and the alternative is
    five nullable FKs plus a constraint that they are distinct.

    **A user may own several builds of one character.** `uq_builds_owner_character` —
    inherited verbatim from fairy's `uq_builds_owner_agent` — forbade it, and was dropped by
    owner decision (2026-08-24, T.1a): comparing a C0 against a C6, or a Physical Eula
    against a Cryo one, is an ordinary thing to want in this game.

    **The rule moved rather than vanished.** gcsim refuses a party holding the same character
    twice — `pkg/simulation/setup.go:94` at pin `3647a07` returns
    `duplicated character %v` — so two builds of one character can coexist in a collection
    and cannot coexist on a **team**. `app/api/v1/teams.py` enforces that, which is where it
    belongs: the collection is a shelf, the team is the thing being simulated.

    `talent_levels` is JSONB keyed by `TalentType` value — normal attack, elemental skill
    and elemental burst each level 1-10 independently. These are **base** levels, without
    the +3 a C3/C5 adds (owner ruling, 2026-11-14 — `MAX_STORED_TALENT_LEVEL`); the boosted
    level is derived on read (`BuildRead.effective_talent_levels`). The bound is enforced by
    every write path's validator rather than a `CheckConstraint`, because a JSONB value has
    no column to constrain. Stored as one unit because it is always read as one.
    """

    __tablename__ = "builds"
    __table_args__ = (
        CheckConstraint(
            "constellation_level BETWEEN 0 AND 6",
            name="constellation_level_range",
        ),
        CheckConstraint(
            "refinement BETWEEN 1 AND 5",
            name="refinement_range",
        ),
        # The other three bounded integers. Grounded in the committed 7.0.51 payloads
        # rather than assumed: `level_exp` has 90 entries and `xp_requirements` is keyed
        # 1..90, so both level caps are 90; `stats_modifier.ascension` has 6 rows, so
        # phase 0 (unascended) through 6.
        CheckConstraint(
            "ascension_phase BETWEEN 0 AND 6",
            name="ascension_phase_range",
        ),
        CheckConstraint(
            "character_level BETWEEN 1 AND 90",
            name="character_level_range",
        ),
        CheckConstraint(
            "weapon_level BETWEEN 1 AND 90",
            name="weapon_level_range",
        ),
    )

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    character_id: Mapped[str | None] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    weapon_id: Mapped[str | None] = mapped_column(
        ForeignKey("weapons.id", ondelete="SET NULL"), nullable=True, default=None,
    )

    character_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default=text("90"),
    )
    #: 0-6 ascension phases; distinct from level because two builds at level 80 can differ.
    ascension_phase: Mapped[int] = mapped_column(
        Integer, nullable=False, default=6, server_default=text("6"),
    )
    weapon_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default=text("90"),
    )
    refinement: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
    )
    constellation_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )

    #: `{"normal_attack": 10, "elemental_skill": 10, "elemental_burst": 10}`
    talent_levels: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    #: The user's own name for this build.
    #:
    #: Without one, two builds for the same character are told apart by their gear — which
    #: means reading five artifacts to answer "which of these is this?".
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    notes: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    optimizer_priority: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None, index=True,
    )

    character: Mapped[Character | None] = relationship(
        foreign_keys=[character_id], lazy=GUARDED_LAZY,
    )
    weapon: Mapped[Weapon | None] = relationship(lazy=GUARDED_LAZY)
    artifacts: Mapped[list[Artifact]] = relationship(
        lazy=GUARDED_LAZY,
        foreign_keys="Artifact.build_id",
        # NOT `order_by="Artifact.slot"`. The column holds the payload's internal keys, so
        # sorting on it gives flower, **circlet**, plume, goblet, sands. This orders by the
        # conventional slot sequence instead; `ArtifactSlot.sort_index` is the same order in
        # Python.
        order_by=artifact_slot_sort_order(),
        # The FK is ON DELETE SET NULL and that is the whole intent: deleting a build
        # unequips its pieces, it does not destroy them. `passive_deletes` lets the database
        # do the nulling — without it SQLAlchemy loads every artifact to null it in Python,
        # which under asyncio raises MissingGreenlet during flush rather than lazily loading.
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Build {self.character_id} C{self.constellation_level}>"


class EnemyProfile(TimestampMixin, Base):
    """Enemy stat profile for damage calculations.

    **No daze, anomaly, stun or capacity columns** — those mechanics do not exist in this
    game, and DESIGN §2.5 names re-pointing them as the leak to avoid.

    Resistances are per damage channel: the seven visions plus physical, eight columns
    rather than a JSONB blob, because the damage chain reads exactly one of them per hit
    and a typo'd key in JSONB would resolve to "no resistance" instead of failing.

    Values are fractions (`0.10` = 10% RES), matching how the source expresses them.
    Negative means a weakness. **The RES-to-multiplier formula is not here** — it is Chunk
    F's, and it has to arrive with a gcsim/KQM citation at the line that introduces it.

    **`base_hp` / `base_atk` / `base_def` are curve bases, not level-90 stats.** A Hilichurl's
    `base_hp` is `13.584`. The number a damage calculation needs is that base scaled by the
    growth curve named in `stat_curves` at `level`, and those curve tables
    (`MonsterCurveExcelConfigData`) are **YuanShenResources data, i.e. Chunk E** — nanoka
    does not publish them. `level` therefore describes what the profile is *for*; it is not
    a level these stats have already been evaluated at. Anything that multiplies these
    numbers by a crit multiplier and calls the result damage is wrong.

    **One row is one monster family, not one spawn.** A nanoka monster payload holds a
    `child` map of 1-17 spawn configurations, and 189 of the 360 families with children have
    children that differ in base stats (85 differ in resistances). D.6 stores the canonical
    child — the one whose id equals the family id, else the lowest — and records which in
    `variant_nanoka_id` with `variant_count` beside it, so "these are one of N configs" is a
    query rather than a thing you have to know.

    `nanoka_id` stays nullable: a hand-authored profile (a test dummy, a Chunk F crossval
    target) is a legitimate row that no importer owns, and `_prune` leaves NULLs alone.
    """

    __tablename__ = "enemy_profiles"

    id: Mapped[uuid_pk]
    nanoka_id: Mapped[int | None] = mapped_column(
        Integer, unique=True, nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The monster's art basename, e.g. `UI_MonsterIcon_Hili_None_01`. Same shape and same
    #: `String(128)` as `characters.icon` and `weapons.icon`, and vendored by the same script.
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=90)

    base_hp: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_atk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_def: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    physical_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    anemo_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cryo_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dendro_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    electro_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    geo_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hydro_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pyro_res: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    tags: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    #: The `child` entry these stats came from, and how many that family had. Provenance
    #: for a choice the payload does not make for us — see the class docstring.
    variant_nanoka_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variant_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )

    #: `{FIGHT_PROP_BASE_HP: "GROW_CURVE_HP_2", …}` from the child's `prop[]`. Without it
    #: the three base columns cannot be evaluated at any level at all, and Chunk F would
    #: have to re-fetch the payload to find out how they scale.
    stat_curves: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    def __repr__(self) -> str:
        return f"<EnemyProfile {self.name} lv{self.level}>"
