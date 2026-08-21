"""A saved Team: up to 3 `Build`s grouped for combo simulation and comparison."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.build import Build


class Team(TimestampMixin, Base):
    """A team of 3 agent builds."""

    __tablename__ = "teams"

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")

    build1_id: Mapped[str | None] = mapped_column(
        ForeignKey("builds.id", ondelete="SET NULL"), nullable=True, default=None
    )
    build2_id: Mapped[str | None] = mapped_column(
        ForeignKey("builds.id", ondelete="SET NULL"), nullable=True, default=None
    )
    build3_id: Mapped[str | None] = mapped_column(
        ForeignKey("builds.id", ondelete="SET NULL"), nullable=True, default=None
    )

    build1: Mapped[Build | None] = relationship(foreign_keys=[build1_id])
    build2: Mapped[Build | None] = relationship(foreign_keys=[build2_id])
    build3: Mapped[Build | None] = relationship(foreign_keys=[build3_id])

    def __repr__(self) -> str:
        return f"<Team {self.name}>"
