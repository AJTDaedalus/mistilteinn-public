"""Optimizer endpoints — async job submission + job management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import (
    DBSession,
    get_attack_repo,
    get_enemy_repo,
    get_job_runner,
    get_owned_build_repo,
    get_owned_combo_repo,
    get_owned_optimization_job_repo,
    get_owned_team_repo,
)
from app.middleware.rate_limit import JOB_LIMIT, WRITE_LIMIT, limiter
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.optimization_job import (
    MAX_ACTIVE_JOBS_PER_USER,
    OptimizationJobRepository,
)
from app.repositories.team import TeamRepository
from app.schemas.optimization_job import OptimizationJobRead, OptimizationJobSummary
from app.schemas.optimizer import DiscOptimizeRequest
from app.services.job_runner import JobRunner
from app.services.optimizer_pipeline import resolve_optimize_payload

router = APIRouter(prefix="/optimizer", tags=["optimizer"])


def _auto_prefilter_k_from_result(result: dict | list | None) -> int | None:
    """Extract the auto-prefilter K signal from a stored job result blob.

    ``auto_prefilter_k`` isn't its own DB column (OQ1: result-blob-only
    storage) — it rides inside the ``DiscOptimizeResponse`` JSONB already
    persisted as ``optimization_jobs.result``.
    """
    if isinstance(result, dict):
        return result.get("auto_prefilter_k")
    return None


@router.post("/discs", response_model=OptimizationJobSummary, status_code=202)
@limiter.limit(JOB_LIMIT)
async def submit_optimizer_job(
    request: Request,
    body: DiscOptimizeRequest,
    session: DBSession,
    combo_repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
    build_repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
    job_repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
    runner: Annotated[JobRunner, Depends(get_job_runner)],
    team_repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> OptimizationJobSummary:
    """Submit a disc optimization job; returns 202 + queued job summary."""
    active = await job_repo.count_active()
    if active >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You already have {active} active jobs "
                f"(max {MAX_ACTIVE_JOBS_PER_USER}). "
                "Cancel one or wait for it to finish before submitting another."
            ),
        )

    payload = await resolve_optimize_payload(
        session,
        body,
        combo_repo,
        build_repo,
        attack_repo,
        enemy_repo,
        team_repo=team_repo,
    )

    job = await job_repo.create(
        {
            "status": "queued",
            "request": body.model_dump(mode="json"),
            "agent_name": payload.agent_name,
            "enemy_name": payload.enemy_name,
            "combo_name": payload.combo_name,
        }
    )

    runner.submit_optimizer_job(str(job.id), payload)

    summary = OptimizationJobSummary.model_validate(job)
    summary.auto_prefilter_k = _auto_prefilter_k_from_result(job.result)
    return summary


@router.get("/jobs", response_model=list[OptimizationJobSummary])
async def list_jobs(
    job_repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
    status: str | None = None,
    job_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[OptimizationJobSummary]:
    """List optimizer jobs, newest first. Filter by status (comma-separated) or job_type."""
    status_list = [s.strip() for s in status.split(",")] if status else None
    jobs = await job_repo.list(
        status=status_list,
        job_type=job_type,
        limit=min(limit, 200),
        offset=offset,
    )
    summaries = []
    for j in jobs:
        summary = OptimizationJobSummary.model_validate(j)
        summary.auto_prefilter_k = _auto_prefilter_k_from_result(j.result)
        summaries.append(summary)
    return summaries


@router.get("/jobs/{job_id}", response_model=OptimizationJobRead)
async def get_job(
    job_id: str,
    job_repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
) -> OptimizationJobRead:
    """Return full job detail including result blob."""
    job = await job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    read = OptimizationJobRead.model_validate(job)
    read.auto_prefilter_k = _auto_prefilter_k_from_result(job.result)
    return read


@router.delete("/jobs/{job_id}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def delete_job(
    request: Request,
    job_id: str,
    job_repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
    runner: Annotated[JobRunner, Depends(get_job_runner)],
) -> None:
    """Cancel and delete an optimizer job."""
    job = await job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    runner.cancel(job_id)
    await job_repo.delete(job_id)
