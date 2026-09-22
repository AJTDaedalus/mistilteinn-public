"""Wish income per game version, at three spending tiers.

## Where the numbers come from

The community bookkeeping workbook the sister project `/root/hoyincome` reads — one tab per
patch, 1.0 through the next estimate. Each tab itemises the patch and totals it twice, so the
three tiers are **line items rather than a model**: `Total F2P`, plus `Welkin 42 Days`, plus
`Battle Pass - Paid Bonus`. A wish is `Primogems / 160 + Intertwined Fate`; **Acquaint Fate is
excluded** because it buys the standard banner (owner ruling, 2026-09-22).

`docs/RESEARCH_wish_planner.md` §10 has the extraction, the three invariants that gate a
refresh, and the reason this reads the Intertwined column by header rather than by index.

## Why a table and not a live fetch

`app/` has exactly one request-time fetch and E.6 argues the case for it. A third-party
spreadsheet on the request path would be a second, on a dependency nobody here controls. So
`scripts/refresh_wish_income.py` writes these rows on a timer and the API only ever reads
them. `app/data/wishes/income_snapshot.json` is the committed seed, so a fresh clone and the
test suite need no network at all — the same doctrine as `app/data/yuanshen/snapshot/`.

## The two columns that are not numbers

`is_estimate` carries the sheet's own `est.` marker. The workbook publishes a forward estimate
for the next patch, and a projection displayed as history is the same error as a mean
displayed as a certainty.

`fetched_at` exists because **stale projected income goes wrong invisibly** — the failure
mode `CLAUDE.md` records for the materials planner, where *"how many Teachings do I hold"*
goes stale within a day and says nothing. It ships in the API payload rather than staying a
bookkeeping column, so a page can say how old its numbers are.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy resolves Mapped[datetime] at runtime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class WishIncome(TimestampMixin, Base):
    """Wishes earned during one game version, at one spending tier."""

    __tablename__ = "wish_income"
    __table_args__ = (
        UniqueConstraint("version", "tier", name="uq_wish_income_version_tier"),
    )

    id: Mapped[uuid_pk]

    #: Game version as the workbook names it, normalised to "7.0" — never "7.0 est.".
    version: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: Sort key, so "7.10" would order after "7.9" rather than before it.
    major: Mapped[int] = mapped_column(Integer, nullable=False)
    minor: Mapped[int] = mapped_column(Integer, nullable=False)

    #: One of `f2p`, `welkin`, `welkin_bp`.
    tier: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Wishes earned in this version at this tier. Fractional: the workbook's own figures are.
    wishes: Mapped[float] = mapped_column(Float, nullable=False)

    #: Whether the workbook marked this version an estimate rather than a settled total.
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: When the refresher last read this row from the workbook.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<WishIncome {self.version} {self.tier}={self.wishes:.1f}>"
