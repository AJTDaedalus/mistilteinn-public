"""The W-Engine (weapon) entity: specialty-locked stat stick with a leveled passive ability."""

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.enums import Rarity, Specialty


class WEngine(TimestampMixin, Base):
    """A W-Engine (weapon) equipped per `Build`; grants ATK plus a refinable passive ability."""

    __tablename__ = "w_engines"

    id: Mapped[uuid_pk]
    hakushin_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    rarity: Mapped[Rarity] = mapped_column(String(5))
    specialty: Mapped[Specialty] = mapped_column(String(20))
    icon_path: Mapped[str] = mapped_column(String(500), default="", server_default="")

    # Base stat
    base_atk: Mapped[int] = mapped_column(Integer, default=0)

    # Secondary stat
    secondary_stat_type: Mapped[str] = mapped_column(String(30), default="")
    secondary_stat_value: Mapped[int] = mapped_column(Integer, default=0)

    # Level scaling (basis points: StarRate for ATK, RandRate for secondary)
    # List of {level: {star_rate, rand_rate}} — allows computing stats at any level
    level_scaling: Mapped[dict | None] = mapped_column(JSONB, default=None)

    # Passive ability (R1-R5 descriptions with values)
    passive_name: Mapped[str] = mapped_column(String(200), default="")
    passive_descriptions: Mapped[dict | None] = mapped_column(JSONB, default=None)
    # Structured: {"1": {"desc": "...", "values": [...]}, ...}

    description: Mapped[str] = mapped_column(String(2000), default="")

    def __repr__(self) -> str:
        return f"<WEngine {self.name} ({self.rarity.value})>"
