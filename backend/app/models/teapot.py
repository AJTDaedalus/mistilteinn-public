"""Furnishing sets, who favours them, and which a user has finished.

`DESIGN_account_tracking.md` Track 3. Owner: *"a teapot set tracker, backed by the 'owned'
flag on user's builds, like seelie.me's teapot set calculator. This one should be sortable by
remaining primogems and lets users mark off which they've already done."*

The data is nanoka's, at the version this repo already pins: `suite.json` publishes 109 sets
with their constituent furnishings and, for 79 of them, the characters who favour them —
**by the same nanoka id `characters.nanoka_id` already holds**. So the question the tracker
exists to answer, *which sets does this roster unlock*, is a join rather than a scrape.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — a runtime annotation for SQLAlchemy

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk


class FurnishingSuite(TimestampMixin, Base):
    """One furnishing set, as the game publishes it."""

    __tablename__ = "furnishing_suites"

    id: Mapped[uuid_pk]
    #: nanoka's own key, so a re-capture updates rather than duplicates.
    nanoka_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: `"I"` indoor, `"O"` outdoor — nanoka's own spelling, uninterpreted.
    #:
    #: Stored rather than mapped to a friendlier enum because this repo's rule is to keep the
    #: source's own vocabulary and convert at the edge: a mapping written here would be a
    #: second place for a patch to disagree with.
    placement: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: `{furnishing_id: count}`, as published.
    units: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    favorites: Mapped[list[FurnishingSuiteFavorite]] = relationship(
        back_populates="suite", cascade="all, delete-orphan", lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<FurnishingSuite {self.name!r}>"


class FurnishingSuiteFavorite(Base):
    """A character who favours a suite — the row that turns a set into primogems."""

    __tablename__ = "furnishing_suite_favorites"
    __table_args__ = (
        Index("ix_suite_favorites_character", "character_nanoka_id"),
    )

    suite_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("furnishing_suites.id", ondelete="CASCADE"),
        primary_key=True,
    )
    #: The character's **nanoka** id, deliberately not a foreign key to `characters`.
    #:
    #: A suite can favour a character this database has not seeded yet — a set ships in the
    #: same patch as the character, and the two are captured separately. Losing the row would
    #: be worse than holding an id that resolves later, and the join still works the moment
    #: the character arrives.
    character_nanoka_id: Mapped[str] = mapped_column(String(32), primary_key=True)

    suite: Mapped[FurnishingSuite] = relationship(back_populates="favorites")


class TeapotProgress(Base):
    """A set this user has already done.

    Seelie's whole affordance: mark it off and it leaves the list. One row per finished set,
    and its absence is the default — nothing has to be written for a user who has done nothing.
    """

    __tablename__ = "teapot_progress"

    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    suite_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("furnishing_suites.id", ondelete="CASCADE"), primary_key=True,
    )
    done_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
