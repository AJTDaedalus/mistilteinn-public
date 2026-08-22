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


class InventorySnapshot(BaseModel):
    """Every owned artifact in one response, plus the version that identifies it.

    **OQ-S3, answered: the browser holds the inventory and revalidates it.** The transfer is
    not the deciding factor — a 2,000-piece account is ~936 KB of JSON, ~234 KB gzipped, so
    fetching per search and holding across searches cost about the same. What differs is
    **staleness**: an inventory held across a GOOD re-import is an inventory containing
    artifacts the user no longer owns, and a search over it would recommend wearing them.

    So the payload carries a `version` and the route serves `304 Not Modified` against
    `If-None-Match`. The browser keeps the pieces and asks a cheap question before each
    search, which is the correctness of fetching at the cost of holding.

    Paging is deliberately not offered here. `GET /artifacts` pages for a UI list; a search
    needs the whole inventory at one instant, and four paged round-trips have no such
    instant — a concurrent import shifts every offset under the reader.
    """

    #: A digest over every piece's identity and stats. Changes when the inventory changes,
    #: and *only* then, so an unchanged account revalidates for free.
    version: str
    #: In the repository's game-slot order — slot, then level descending, then id. Fully
    #: determined, which is what the version depends on: a version that flipped because
    #: Postgres returned rows in another order would make every revalidation a full transfer.
    artifacts: list[ArtifactRead]
    total: int
    #: True when the account holds more pieces than one response will carry. The list is then
    #: a prefix of that order and the version covers only what was sent, so a search must
    #: treat it as "the server would not answer" rather than as a complete inventory.
    truncated: bool = False


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
