"""What levelling costs: the material bills, and the stock a user holds against them.

Every number in these tables is imported from a nanoka detail payload this repository
already pins — `materials.ascensions`, `materials.talents` and the weapon's `materials` map.
None of it was read before the planner; `docs/RESEARCH_leveling_planner_data.md` §1 records
that the costs had been sitting in the fixtures unread since Chunk D.

**Costs are stored, not computed.** §"Data Source of Truth" makes the database the single
source for game data, and the importer that fills the catalogue fills these in the same pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUARDED_LAZY, Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.character import Character, Talent
    from app.models.weapon import Weapon


class Material(TimestampMixin, Base):
    """One ascension, talent or weapon material.

    The primary key is the **game's own item id** rather than a surrogate, because that id is
    what every cost row, every GOOD export key and every icon basename is keyed by. 508 of
    these are reachable from the catalogue; the table holds every one the importer meets.

    `icon` comes from `MaterialExcelConfigData.icon` via the snapshot — cited, not assembled
    from the id. `rarity` is nanoka's `rank`, and the seed cross-checks it against YuanShen's
    `rankLevel`: at 7.0.51 all 508 agree, which is what makes the two sources safe to join.
    """

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    #: Icon basename, e.g. `UI_ItemIcon_104161`. Nullable because a material the catalogue
    #: names but the snapshot does not carry is a *seeding* gap, and papering over it here
    #: would hide it — the same rule `download_icons.py` follows for a null `icon` column.
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rarity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Material {self.id} {self.name}>"


class CharacterAscensionCost(TimestampMixin, Base):
    """The bill for one of a character's six ascension phases.

    `items` is `[{"id": 104161, "count": 1}, ...]` — the material list verbatim from
    `materials.ascensions[phase].mats`, kept as JSONB rather than a child table because it is
    always read whole and never queried into.
    """

    __tablename__ = "character_ascension_costs"
    __table_args__ = (
        UniqueConstraint(
            "character_id", "phase", name="uq_character_ascension_costs_character_id",
        ),
        CheckConstraint("phase BETWEEN 1 AND 6", name="phase_range"),
    )

    id: Mapped[uuid_pk]
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    phase: Mapped[int] = mapped_column(Integer, nullable=False)
    mora: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    character: Mapped[Character] = relationship(lazy=GUARDED_LAZY)


class CharacterTalentCost(TimestampMixin, Base):
    """The bill for taking one talent from `level` to `level + 1`.

    **Keyed per talent, not per character**, and that is load-bearing. Ayaka's payload holds
    four talent cost lists carrying **two distinct** sets, so a single per-character row would
    price three of her talents off the fourth's bill. Rosaria's and Venti's are uniform, which
    is exactly why assuming uniformity would have survived a spot check.

    `level` runs 1..9 — the nine steps to talent level 10. Levels 11-15 come free from C3/C5
    and have no material rows at all, which the planner states rather than rendering empty.
    """

    __tablename__ = "character_talent_costs"
    __table_args__ = (
        UniqueConstraint("talent_id", "level", name="uq_character_talent_costs_talent_id"),
        CheckConstraint("level BETWEEN 1 AND 9", name="level_range"),
        Index("ix_character_talent_costs_character", "character_id"),
    )

    id: Mapped[uuid_pk]
    character_id: Mapped[str] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False,
    )
    talent_id: Mapped[str] = mapped_column(
        ForeignKey("talents.id", ondelete="CASCADE"), nullable=False,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    mora: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    talent: Mapped[Talent] = relationship(lazy=GUARDED_LAZY)


class WeaponAscensionCost(TimestampMixin, Base):
    """The bill for one of a weapon's six ascension phases."""

    __tablename__ = "weapon_ascension_costs"
    __table_args__ = (
        UniqueConstraint("weapon_id", "phase", name="uq_weapon_ascension_costs_weapon_id"),
        CheckConstraint("phase BETWEEN 1 AND 6", name="phase_range"),
    )

    id: Mapped[uuid_pk]
    weapon_id: Mapped[str] = mapped_column(
        ForeignKey("weapons.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    phase: Mapped[int] = mapped_column(Integer, nullable=False)
    mora: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    weapon: Mapped[Weapon] = relationship(lazy=GUARDED_LAZY)


class UserMaterial(TimestampMixin, Base):
    """How many of a material this account holds, as its last GOOD export said.

    **An absent row means zero, and that is what the export means too** — measured on a real
    Irminsul export, which carries 1,384 entries and *no* zero-valued one (min 1, max 11,250).
    So a material the export omits is one the user has none of, not one the scanner missed.

    Mora is deliberately absent: GOOD has no currency field, so the planner totals mora and
    never claims to know whether you can afford it.
    """

    __tablename__ = "user_materials"

    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), primary_key=True,
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<UserMaterial {self.material_id} x{self.count}>"
