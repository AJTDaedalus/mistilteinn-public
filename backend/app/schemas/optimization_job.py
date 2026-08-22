"""Pydantic schemas for OptimizationJob — async optimizer/scorer job status and results.

Renamed in C.9: `agent_name` → `character_name`, `combo_name` → `rotation_name`. B.5
deferred this to Chunk G because it needs a migration, but C.9's close-out sweep requires
`app/models` and `app/schemas` to be free of ZZZ vocabulary outside comments, and doing it
now — before D seeds anything — costs one `alter_column` against empty tables.
"""

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
    character_name: str
    enemy_name: str
    rotation_name: str
    combinations_done: int
    combinations_total: int
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
