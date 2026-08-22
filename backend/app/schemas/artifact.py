"""Schemas for a user's owned artifacts and for importing them from a GOOD export."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.good_import_service import APPEND, REPLACE


class ArtifactRead(BaseModel):
    """One owned artifact."""

    id: str
    slot: str
    rarity: str
    level: int
    main_stat_type: str
    #: Derived from the committed value table for this rarity, level and main stat — not a
    #: number a scanner read off a screen. See `good_import_service`.
    main_stat_value: float
    substats: list[Any] = []
    artifact_set_id: str | None = None
    #: Null when the piece is not equipped. Unequipping does not delete it.
    build_id: str | None = None

    model_config = {"from_attributes": True}


class GoodImportRequest(BaseModel):
    """Body for `POST /artifacts/import/good`.

    `mode` has **no default**, and that is the point. GOOD carries no stable per-artifact
    identifier, so `append` run twice duplicates a whole inventory — and a duplicated goblet
    is not clutter, it is a search that will happily recommend wearing the same piece twice.
    `replace` deletes. Neither is safe to reach by omission, so the request states which.
    """

    mode: Literal[REPLACE, APPEND]
    #: The export itself, verbatim. Validated by `app/data/importers/good_importer.py`,
    #: which refuses rather than coerces — see its docstring for why that differs from
    #: Genshin Optimizer's own reader.
    payload: dict[str, Any] = Field(..., description="A GOOD export, as exported.")


class ImportRejection(BaseModel):
    """One artifact that did not make it in, and why."""

    index: int
    reason: str


class GoodImportResponse(BaseModel):
    """What the import did.

    `rejected` lists both the artifacts the parser refused and the ones whose set this
    database does not know. A caller showing a user what happened should not have to tell
    those apart, and a partial import that reported only a count would be the thing this
    importer exists not to be.
    """

    inserted: int
    deleted: int
    rejected: list[ImportRejection] = []
    ok: bool
    source: str = ""
    version: int = 0
