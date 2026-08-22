"""Genshin weapons: the catalogue row and its five refinement steps.

**New file, new class names** — nothing renamed from the deleted `w_engine.py`. W-Engines
were locked to a ZZZ `specialty`; weapons are locked to a `weapon_type`, and ZZZ's
"phases" become Genshin's refinements R1-R5 (DESIGN §2.5).

Field provenance: `tests/fixtures/nanoka_gi/weapon.json` (index) and
`tests/fixtures/nanoka_gi/detail/weapon_11501.json` (detail), nanoka 7.0.51.
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUARDED_LAZY, Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import Rarity, StatType, WeaponType


class Weapon(TimestampMixin, Base):
    """One weapon.

    Payload map:

    * index `type` / detail `weapon_type` → `weapon_type`, via `WeaponType.parse` — which
      folds `ITEM_TPS_WEAPON` into `CROSSBOW`, because the two indexes spell that class
      differently (C.1).
    * index `rank` (int) / detail `rarity` (int) → `rarity`, via `Rarity.parse`.
    * detail `weapon_prop[]` → `base_atk` (`FIGHT_PROP_BASE_ATTACK`) and the substat
      (`sub_stat_type` / `sub_stat_base_value`), each carrying its `GROW_CURVE_*` name so
      Chunk F can evaluate the level curve rather than storing a flattened table.
    * detail `ascension` → `ascension_atk`: `{phase: {"fight_prop_base_attack": value}}`.

    **`base_atk` and `sub_stat_type` are nullable on purpose.** The eight
    `ITEM_TPS_WEAPON` rows (ids 224001-224008: "Shatanaya's Frostsilver", the "Frag
    Crystal" family) carry `atk: null` and `sub: null` in the index — they are not ordinary
    weapons. C.1 recorded them; the model tolerates them so D.4 can import them visibly
    rather than dropping them on a NOT NULL violation, and whether they belong in the
    optimizer at all is a Chunk G question.
    """

    __tablename__ = "weapons"
    __table_args__ = (
        Index("ix_weapons_weapon_type", "weapon_type"),
        Index("ix_weapons_rarity", "rarity"),
    )

    id: Mapped[uuid_pk]
    nanoka_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)

    weapon_type: Mapped[WeaponType] = mapped_column(enum_column(WeaponType, 32), nullable=False)
    rarity: Mapped[Rarity] = mapped_column(enum_column(Rarity, 16), nullable=False)

    base_atk: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_atk_curve: Mapped[str | None] = mapped_column(String(48), nullable=True)

    sub_stat_type: Mapped[StatType | None] = mapped_column(
        enum_column(StatType, 48), nullable=True,
    )
    sub_stat_base_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sub_stat_curve: Mapped[str | None] = mapped_column(String(48), nullable=True)

    #: `ascension` verbatim — per-phase base-ATK bumps, read as one unit.
    ascension_atk: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    refinements: Mapped[list[WeaponRefinement]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="weapon",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WeaponRefinement.level",
    )

    def __repr__(self) -> str:
        return f"<Weapon {self.name} ({self.weapon_type} {self.rarity})>"


class WeaponRefinement(TimestampMixin, Base):
    """One refinement step, R1-R5.

    Source: the detail payload's `refinement` object, keyed `"1"`..`"5"`, each with the
    passive's `name`, `desc` and `param_list`. The text is stored as given — turning it into
    modifiers is Chunk H's job, not something to half-do here and redo against the kit
    schema — but `param_list` carries the numbers in structured form so that work starts
    from data rather than from `<color=#99FFFFFF>20%</color>`.
    """

    __tablename__ = "weapon_refinements"
    __table_args__ = (
        UniqueConstraint("weapon_id", "level", name="uq_weapon_refinements_weapon_id_level"),
    )

    id: Mapped[uuid_pk]
    weapon_id: Mapped[str] = mapped_column(
        ForeignKey("weapons.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: `refinement["<level>"].param_list`, e.g. `[0.2, 1, 2, 15, 0, 0, 0, 0]` — the numbers
    #: the description renders inside `<color=…>` markup. Kept so Chunk H reads data instead
    #: of regexing prose, and so the R1→R5 progression is queryable.
    param_list: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    weapon: Mapped[Weapon] = relationship(back_populates="refinements")

    def __repr__(self) -> str:
        return f"<WeaponRefinement R{self.level} of {self.weapon_id}>"
