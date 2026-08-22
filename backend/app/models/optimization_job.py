"""Background artifact-optimization job: request payload, progress counters, and result."""

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.user import User  # noqa: F401 — ensures FK target is registered


class OptimizationJob(TimestampMixin, Base):
    """Tracks one async optimizer run: search progress, ETA, and the winning build result."""

    __tablename__ = "optimization_jobs"

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: Display labels, denormalised so a job list needs no joins. Renamed from
    #: `agent_name` / `combo_name` in C.9 — they were the last ZZZ vocabulary left in
    #: `app/models`, and B.5 deferred the rename here rather than doing it mid-demolition.
    character_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    enemy_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    rotation_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: Renamed from `assignments_done` / `assignments_total` / `pruned_sets` /
    #: `pruned_stats` in G.10 — the last of fairy's ZZZ vocabulary in this table, after C.9
    #: took `agent_name` / `combo_name` and deferred these.
    #:
    #: "Assignments" were ZZZ **set-assignment frames**: the optimizer there enumerated
    #: declared set-count distributions over six slots and searched within each. This
    #: search has no such thing — it is a plain product over five slots — so the unit is a
    #: combination, and a column named for a concept this game does not have is exactly the
    #: leak the BRIEF names as the fork's main long-term hazard.
    combinations_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    combinations_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Combinations refused before scoring: by a `required_sets` constraint, and by a
    #: `min_stats` floor. Named for what the optimizer calls them.
    rejected_by_sets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_by_stats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    eta_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_damage: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="optimize")

    __table_args__ = (
        Index("ix_optimization_jobs_status", "status"),
        Index("ix_optimization_jobs_created_at_desc", "created_at"),
        Index("ix_optimization_jobs_job_type", "job_type"),
    )
