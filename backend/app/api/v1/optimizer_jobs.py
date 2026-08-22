"""Poll, list and cancel background artifact searches.

A search that will not finish inside `optimizer_job_service.SYNC_SECONDS` is answered with
202 and a job id (see `builds.optimize_build`); this is where the caller follows it.

**Owner-scoped.** A job holds a build's search result, so it is the owner's, and the
repository carries the caller's id — a foreign id is a 404 for the same reason a foreign
artifact is.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import get_job_runner, get_owned_optimization_job_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.optimization_job import OptimizationJobRepository
from app.schemas.common import PaginatedResponse
from app.schemas.optimization_job import OptimizationJobRead, OptimizationJobSummary
from app.services.job_runner import JobRunner

router = APIRouter(prefix="/optimizer-jobs", tags=["optimizer-jobs"])


@router.get("", response_model=PaginatedResponse[OptimizationJobSummary])
async def list_jobs(
    repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[OptimizationJobSummary]:
    """The caller's jobs, newest first.

    Summaries only: a finished job's `result` is a full optimize response, and a list of
    twenty of them is a payload nobody asked for.
    """
    rows = await repo.list(offset=offset, limit=limit)
    return PaginatedResponse(
        items=[OptimizationJobSummary.model_validate(row) for row in rows],
        total=await repo.count(),
        offset=offset,
        limit=limit,
    )


@router.get("/{job_id}", response_model=OptimizationJobRead)
async def get_job(
    job_id: str,
    repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
) -> OptimizationJobRead:
    """One job: its status, its progress, and its result once it has one.

    Progress is `combinations_done` against `combinations_total`, plus the counts of what
    was rejected before scoring — a search that is 90% done and rejecting almost everything
    is a constraint the caller should loosen, and that is readable here while it runs rather
    than only from the finished result.
    """
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No optimizer job {job_id!r}")
    return OptimizationJobRead.model_validate(job)


@router.post("/{job_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(WRITE_LIMIT)
async def cancel_job(
    request: Request,
    job_id: str,
    repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
    runner: Annotated[JobRunner, Depends(get_job_runner)],
) -> None:
    """Ask a queued or running job to stop.

    Cooperative: a queued job is dropped before it ever starts, and a running one stops at
    its next progress tick — a couple of seconds — because a synchronous CPU-bound loop
    offers no other way in. The row is marked `cancelled` by the worker as it unwinds, so a
    poll immediately after this may still read `running`.
    """
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No optimizer job {job_id!r}")
    if job.status in ("succeeded", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id} already finished as {job.status!r}; nothing to cancel",
        )
    runner.cancel(job_id)
