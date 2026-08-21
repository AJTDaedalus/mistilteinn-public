"""Disc ranker service — shared progress/cancellation types for the rank pipeline.

`rank_inventory` (the legacy single-pass aggregator) was retired as dead code:
no production caller remained, only `job_runner.py` importing `RankCancelled` /
`RankProgress` and calling `rank_pipeline.run_rank_pipeline_with_progress` for
the actual work. See docs/DESIGN_ranker_discless.md task R1.
"""

from __future__ import annotations

from dataclasses import dataclass


class RankCancelled(Exception):  # noqa: N818
    """Raised by the rank pipeline's progress callback to cancel execution."""


@dataclass
class RankProgress:
    """Progress snapshot reported by the rank pipeline's callback for long-running ranks."""

    discs_done: int = 0
    discs_total: int = 0
    elapsed_seconds: float = 0.0
