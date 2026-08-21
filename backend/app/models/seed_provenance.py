"""What patch this database was seeded from, and how that run went.

One row per `python -m scripts.seed_db` run, append-only. The BRIEF's data-source rule is
that the database is the single source of truth for game data; this table is what makes the
follow-up question — *which patch's* game data — a query rather than a guess, and what makes
a stale seed visible instead of invisible.

Append-only rather than one mutable row on purpose: "when did the roster last change" and
"did the last run actually finish" are both history questions, and a row that gets
overwritten cannot answer either.
"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class SeedRun(TimestampMixin, Base):
    """One seed run: the version it pinned, what it wrote, and whether it succeeded."""

    __tablename__ = "seed_runs"

    id: Mapped[uuid_pk]

    #: Which upstream this run read. A constant today (`nanoka-gi`); a column because Chunk
    #: E adds committed YuanShenResources snapshots as a second source with its own version.
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="nanoka-gi")

    #: The pinned version, e.g. `7.0.51` — `manifest.json` → `gi.latest` at run time.
    version: Mapped[str] = mapped_column(String(32), nullable=False)

    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: False while a run is in flight, and **left** False if it dies. A run that crashed
    #: half way through leaves a row saying so; without one, a partially seeded database
    #: looks exactly like a complete one.
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: `{"character": {"total": 150, "imported": 150, "skipped": 0, "pruned": 0,
    #: "failed": []}, …}` — one entry per pass, including the ids that failed. Kept in full
    #: because "which 3 rows failed" is the question you have after reading "3 failed", and
    #: the log line that would have answered it has usually scrolled away.
    entity_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    def __repr__(self) -> str:
        state = "ok" if self.succeeded else "incomplete"
        return f"<SeedRun {self.source} {self.version} ({state})>"
