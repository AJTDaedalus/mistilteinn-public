"""Pydantic schemas for OptimizationJob — async optimizer/scorer job status and results."""

from __future__ import annotations

import datetime  # noqa: TC003
from typing import Literal

from pydantic import BaseModel

OptimizationJobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class OptimizationJobSummary(BaseModel):
    """Response for job list/status-polling endpoints — progress only, without the large result."""

    id: str
    status: OptimizationJobStatus
    job_type: str
    agent_name: str
    enemy_name: str
    combo_name: str
    assignments_done: int
    assignments_total: int
    evaluated: int
    elapsed_seconds: float
    eta_seconds: float | None
    top_damage: float | None
    error_message: str | None
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    auto_prefilter_k: int | None = None

    model_config = {"from_attributes": True}


class OptimizationJobRead(OptimizationJobSummary):
    """Response for a single job fetch — adds the original request and the full result payload."""

    request: dict
    result: dict | list | None
