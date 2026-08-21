"""Disc Drive sets and individual disc instances, the 6-slot equippable gear system."""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.enums import DiscSlot, Rarity, StatType
from app.models.user import User  # noqa: F401 — ensures FK target is registered


class DiscSet(TimestampMixin, Base):
    """A Disc Drive set definition (2pc/4pc bonuses) that individual `Disc` rows belong to."""

    __tablename__ = "disc_sets"

    id: Mapped[uuid_pk]
    hakushin_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))

    # Set bonus descriptions (raw text from hakushin)
    two_piece_text: Mapped[str] = mapped_column(String(1000), default="")
    four_piece_text: Mapped[str] = mapped_column(String(2000), default="")

    # Parsed structured bonuses for calculation engine
    # Each entry: stat name, value in basis points, conditional flag
    two_piece_effects: Mapped[list | None] = mapped_column(JSONB, default=None)
    four_piece_effects: Mapped[list | None] = mapped_column(JSONB, default=None)

    icon_path: Mapped[str] = mapped_column(String(500), default="")

    discs: Mapped[list["Disc"]] = relationship(back_populates="disc_set")

    def __repr__(self) -> str:
        return f"<DiscSet {self.name}>"


class Disc(TimestampMixin, Base):
    """Individual disc instance (user inventory item)."""

    __tablename__ = "discs"

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    disc_set_id: Mapped[str] = mapped_column(
        ForeignKey("disc_sets.id", ondelete="CASCADE"), index=True
    )
    slot: Mapped[DiscSlot] = mapped_column(Integer)
    rarity: Mapped[Rarity] = mapped_column(String(5))
    level: Mapped[int] = mapped_column(Integer, default=0)  # 0-15 for S-rank

    # Main stat
    main_stat_type: Mapped[StatType] = mapped_column(String(30))
    main_stat_value: Mapped[int] = mapped_column(Integer, default=0)  # Basis points

    # Substats as JSONB: each entry has stat name, value in basis points, roll count
    substats: Mapped[list | None] = mapped_column(JSONB, default=None)

    # Optional: track which build this disc is equipped in
    build_id: Mapped[str | None] = mapped_column(
        ForeignKey("builds.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # Which slot in the build (1-6)
    build_slot: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    disc_set: Mapped["DiscSet"] = relationship(back_populates="discs")

    def __repr__(self) -> str:
        return f"<Disc {self.slot.name} {self.main_stat_type.value} lv{self.level}>"
