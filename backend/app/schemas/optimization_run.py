"""Schemas for saved optimization runs.

`DESIGN_account_tracking.md` Track 2. The shape mirrors the rotation library's, because the
owner's framing is *"sharable, like the gcsim database"* and this repo already solved sharing
once — a second model would be a second set of rules about who can see what.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import Visibility


class OptimizationRunCreate(BaseModel):
    """Body for `POST /optimization-runs` — a search the client has just finished."""

    model_config = {"extra": "forbid"}

    name: str = Field(default="", max_length=120)
    #: What the search was asked. Required, because a result whose question is unknown cannot
    #: be interpreted — *"this scored 1.4 M"* means nothing without the enemy, the sets
    #: considered and the energy model.
    objective: dict = Field(...)
    #: What it ran against, frozen. See `OptimizationRun`'s module docstring on why this is a
    #: snapshot rather than a set of ids.
    snapshot: dict = Field(...)
    result: dict = Field(...)
    score: float
    margin: float | None = None
    iterations: int = Field(default=0, ge=0)
    elapsed_seconds: float | None = None
    gcsim_pin: str = Field(default="", max_length=64)
    character_id: str | None = None
    rotation_id: str | None = None
    rotation_signature: str = Field(default="", max_length=64)


class OptimizationRunUpdate(BaseModel):
    """Body for `PATCH /optimization-runs/{id}` — the two things a user changes afterwards.

    Not the result. A saved run records what happened, and editing that would make the
    library a place where numbers are asserted rather than measured.
    """

    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, max_length=120)
    visibility: Visibility | None = None


class OptimizationRunSummary(BaseModel):
    """One row of the list — enough to choose between runs without loading any of them."""

    id: str
    name: str
    visibility: Visibility
    share_key: str | None = None
    score: float
    margin: float | None = None
    iterations: int
    character_id: str | None = None
    rotation_id: str | None = None
    created_at: str
    #: Drawn from `objective`, so a list row can say what the run was without a second fetch.
    summary: dict = Field(default_factory=dict)


class OptimizationRunRead(OptimizationRunSummary):
    """One run in full."""

    objective: dict = Field(default_factory=dict)
    snapshot: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    elapsed_seconds: float | None = None
    gcsim_pin: str = ""
    rotation_signature: str = ""
