"""Saved optimization runs — `DESIGN_account_tracking.md` Track 2.

Owner: *"Users should also be able to save their optimization runs and see a list of previous
runs when first going to the optimization page. These should be sharable, like the gcsim
database sharing results."*

The sharing model is the rotation library's, deliberately. A second one would be a second set
of rules about who can see what, and the two would eventually disagree.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_optimization_run_repo
from app.models.enums import Visibility
from app.repositories.optimization_run import PAGE, OptimizationRunRepository
from app.schemas.optimization_run import (
    OptimizationRunCreate,
    OptimizationRunRead,
    OptimizationRunSummary,
    OptimizationRunUpdate,
)

router = APIRouter(prefix="/optimization-runs", tags=["optimization-runs"])

_Repo = Annotated[OptimizationRunRepository, Depends(get_optimization_run_repo)]


def _summary(run: object) -> dict:
    """The fields a list row needs, drawn from `objective` so no second fetch is required."""
    objective = getattr(run, "objective", None) or {}
    return {
        "sets": objective.get("artifact_set_ids") or [],
        "weapons": objective.get("weapon_ids") or [],
        "energy_model": "waiting" if objective.get("wait_for_energy") else "skipping",
        "enemy": objective.get("enemy"),
    }


def _read(run: object) -> OptimizationRunRead:
    return OptimizationRunRead(
        id=str(run.id), name=run.name, visibility=run.visibility,
        share_key=run.share_key, score=run.score, margin=run.margin,
        iterations=run.iterations, character_id=run.character_id,
        rotation_id=run.rotation_id, created_at=run.created_at.isoformat(),
        summary=_summary(run), objective=run.objective, snapshot=run.snapshot,
        result=run.result, elapsed_seconds=run.elapsed_seconds,
        gcsim_pin=run.gcsim_pin, rotation_signature=run.rotation_signature,
    )


def _row(run: object) -> OptimizationRunSummary:
    return OptimizationRunSummary(
        id=str(run.id), name=run.name, visibility=run.visibility,
        share_key=run.share_key, score=run.score, margin=run.margin,
        iterations=run.iterations, character_id=run.character_id,
        rotation_id=run.rotation_id, created_at=run.created_at.isoformat(),
        summary=_summary(run),
    )


@router.get("", response_model=list[OptimizationRunSummary])
async def list_runs(
    repo: _Repo,
    character_id: str | None = None,
    rotation_id: str | None = None,
    gcsim_pin: str | None = None,
    limit: int = Query(default=PAGE, ge=1, le=PAGE),
) -> list[OptimizationRunSummary]:
    """This user's saved runs, newest first.

    **Never ordered by score.** A score is a damage number for one character against one
    enemy, so ranking two runs for different characters by it would invent a comparison the
    data does not support.
    """
    runs = await repo.for_owner(
        repo.owner_id, limit=limit, character_id=character_id,
        rotation_id=rotation_id, gcsim_pin=gcsim_pin,
    )
    return [_row(run) for run in runs]


@router.get("/public", response_model=list[OptimizationRunSummary])
async def list_public(
    repo: _Repo,
    character_id: str | None = None,
    limit: int = Query(default=PAGE, ge=1, le=PAGE),
) -> list[OptimizationRunSummary]:
    """Everyone's published runs — the shared half of the owner's ask."""
    runs = await repo.public(limit=limit, character_id=character_id)
    return [_row(run) for run in runs]


@router.post("", response_model=OptimizationRunRead, status_code=201)
async def save_run(body: OptimizationRunCreate, repo: _Repo) -> OptimizationRunRead:
    """Save a completed search.

    **Private on creation**, always. Publishing is a separate PATCH, because a private thing
    becoming visible is not a mistake anyone can take back — the same reasoning `Visibility`
    records for rotations.
    """
    # `owner_id` is stamped by the repository, not passed here — the scoping belongs to the
    # object that enforces it, and a handler that also sets it is a second place to get wrong.
    run = await repo.create(
        {**body.model_dump(), "visibility": Visibility.PRIVATE},
    )
    return _read(run)


@router.get("/shared/{share_key}", response_model=OptimizationRunRead)
async def read_shared(share_key: str, repo: _Repo) -> OptimizationRunRead:
    """A published run by its key, readable without owning it.

    A private run **404s rather than 403s**: telling a caller that a key exists but is not
    theirs is telling them the key is worth guessing at.
    """
    run = await repo.by_share_key(share_key)
    if run is None:
        raise HTTPException(status_code=404, detail="no shared run with that key")
    return _read(run)


@router.get("/{run_id}", response_model=OptimizationRunRead)
async def read_run(run_id: str, repo: _Repo) -> OptimizationRunRead:
    """One of the caller's own runs, in full."""
    run = await repo.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    return _read(run)


@router.patch("/{run_id}", response_model=OptimizationRunRead)
async def update_run(
    run_id: str, body: OptimizationRunUpdate, repo: _Repo,
) -> OptimizationRunRead:
    """Rename a run, or publish it.

    **The result is not editable.** A saved run records what happened, and letting it be
    rewritten would make the library a place where numbers are asserted rather than measured.
    """
    run = await repo.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    changes = body.model_dump(exclude_none=True)
    if changes.get("visibility") == Visibility.PUBLISHED and not run.share_key:
        changes["share_key"] = repo.new_share_key()
    updated = await repo.update(run_id, changes)
    return _read(updated)


@router.delete("/{run_id}", status_code=204)
async def delete_run(run_id: str, repo: _Repo) -> None:
    """Delete a saved run."""
    if await repo.get_by_id(run_id) is None:
        raise HTTPException(status_code=404, detail="no such run")
    await repo.delete(run_id)
