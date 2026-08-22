"""OptimizationJobRepository — data access for async optimize/rank job tracking."""

from __future__ import annotations

import datetime

from sqlalchemy import func, select, update

from app.models.optimization_job import OptimizationJob
from app.repositories.base import BaseRepository

#: Max concurrent (queued or running) jobs a single user may hold at once,
#: combined across optimize and rank. New submissions past this are rejected.
MAX_ACTIVE_JOBS_PER_USER = 3

#: Statuses that count as "active" (occupying a queue/processing slot).
_ACTIVE_STATUSES = ("queued", "running")


class OptimizationJobRepository(BaseRepository[OptimizationJob]):
    """Sole data-access point for background OptimizationJob records."""

    model = OptimizationJob

    async def count_active(self) -> int:
        """Count the owner's active (queued or running) jobs across all job types."""
        stmt = (
            select(func.count())
            .select_from(OptimizationJob)
            .where(OptimizationJob.status.in_(_ACTIVE_STATUSES))
        )
        if self.owner_id is not None:
            stmt = stmt.where(OptimizationJob.owner_id == self.owner_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list(
        self,
        *,
        status: list[str] | None = None,
        job_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OptimizationJob]:
        """List jobs, newest first, optionally filtered by status and job type."""
        stmt = select(OptimizationJob)
        if self.owner_id is not None:
            stmt = stmt.where(OptimizationJob.owner_id == self.owner_id)
        if status:
            stmt = stmt.where(OptimizationJob.status.in_(status))
        if job_type is not None:
            stmt = stmt.where(OptimizationJob.job_type == job_type)
        stmt = stmt.order_by(OptimizationJob.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_progress(
        self,
        job_id: str,
        *,
        combinations_done: int,
        combinations_total: int,
        evaluated: int,
        rejected_by_sets: int,
        rejected_by_stats: int,
        elapsed_seconds: float,
        eta_seconds: float | None,
    ) -> None:
        """Persist incremental progress counters for a running job (self-commits)."""
        await self.session.execute(
            update(OptimizationJob)
            .where(OptimizationJob.id == job_id)
            .values(
                combinations_done=combinations_done,
                combinations_total=combinations_total,
                evaluated=evaluated,
                rejected_by_sets=rejected_by_sets,
                rejected_by_stats=rejected_by_stats,
                elapsed_seconds=elapsed_seconds,
                eta_seconds=eta_seconds,
                updated_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        await self.session.commit()

    async def mark_running(self, job_id: str) -> None:
        """Transition a job to ``running`` and stamp its start time (self-commits)."""
        await self.session.execute(
            update(OptimizationJob)
            .where(OptimizationJob.id == job_id)
            .values(
                status="running",
                started_at=datetime.datetime.now(tz=datetime.UTC),
                updated_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        await self.session.commit()

    async def mark_succeeded(self, job_id: str, *, result: dict, top_damage: float | None) -> None:
        """Transition a job to ``succeeded``, storing its result payload (self-commits)."""
        await self.session.execute(
            update(OptimizationJob)
            .where(OptimizationJob.id == job_id)
            .values(
                status="succeeded",
                result=result,
                top_damage=top_damage,
                finished_at=datetime.datetime.now(tz=datetime.UTC),
                updated_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        await self.session.commit()

    async def mark_failed(self, job_id: str, *, error_message: str) -> None:
        """Transition a job to ``failed``, truncating the error message (self-commits)."""
        await self.session.execute(
            update(OptimizationJob)
            .where(OptimizationJob.id == job_id)
            .values(
                status="failed",
                error_message=error_message[:2000],
                finished_at=datetime.datetime.now(tz=datetime.UTC),
                updated_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        await self.session.commit()

    async def mark_cancelled(self, job_id: str) -> None:
        """Transition a job to ``cancelled`` on user request (self-commits)."""
        await self.session.execute(
            update(OptimizationJob)
            .where(OptimizationJob.id == job_id)
            .values(
                status="cancelled",
                error_message="Cancelled by user",
                finished_at=datetime.datetime.now(tz=datetime.UTC),
                updated_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        await self.session.commit()

    async def sweep_orphans(self) -> int:
        """Mark queued/running jobs as failed on startup (process restart recovery)."""
        result = await self.session.execute(
            update(OptimizationJob)
            .where(OptimizationJob.status.in_(["queued", "running"]))
            .values(
                status="failed",
                error_message="Backend restarted while job was running",
                finished_at=datetime.datetime.now(tz=datetime.UTC),
                updated_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        await self.session.commit()
        return result.rowcount
