"""Which characters and weapons each wish has featured.

The banner roster the starglitter refund needs. The three featured 4-stars are **two thirds of
every 4-star pulled** (`docs/DESIGN_wish_planner.md` §9.2), so the refund cannot be computed
without knowing who they are — and a player picking a banner is also the shortest path to
filling in the character, the weapon and the pity that the planner otherwise asks for by hand.

## Why a table and not a live fetch

The same rule as `wish_income`: `app/` has one request-time fetch and a wiki on the request
path would be a second. `scripts/refresh_banners.py` writes these rows;
`app/data/wishes/banners.json` is the committed seed so a fresh clone and CI need no network.

## The names are stored, and the ids are resolved at read time

A banner names *Vesna*, not a uuid. Storing the catalogue id instead would repeat the failure
`#263` shipped — a snapshot that stored `str(weapon.id)` from whichever database the capture
ran against, so **zero of 205 ids resolved in production** and every recommendation missed
silently. A name that does not resolve is visible; a stale uuid is not.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy resolves Mapped[datetime] at runtime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class WishBanner(TimestampMixin, Base):
    """One run of one event wish."""

    __tablename__ = "wish_banners"
    __table_args__ = (UniqueConstraint("slug", name="uq_wish_banners_slug"),)

    id: Mapped[uuid_pk]

    #: The wiki's own page title, `<Banner>/<YYYY-MM-DD>`. Unique per run, so a banner that
    #: reruns is two rows rather than one row that forgets its first outing.
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: `character` or `weapon`.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    #: The banner's own start, as the source spells it. Sorted on, never arithmetic'd.
    starts_at: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ends_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Names, in the source's order. One 5-star on a character banner, two on a weapon one.
    featured_five: Mapped[list] = mapped_column(JSONB, nullable=False)
    #: Three 4-star characters, or five 4-star weapons.
    featured_four: Mapped[list] = mapped_column(JSONB, nullable=False)
    #: The banners running at the same time — what makes a weapon somebody's "signature".
    alongside: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<WishBanner {self.slug} {self.featured_five}>"
