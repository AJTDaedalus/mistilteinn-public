"""A user's artifact inventory, and the GOOD import that fills it.

The first **write** surface over Chunk G's work. Everything here is owner-scoped: an
artifact belongs to someone, unlike the catalogue, and every route reaches the database
through a repository already carrying the caller's id.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.data.importers.good_importer import GoodImportError, parse_good
from app.dependencies import CurrentUser, DBSession, get_owned_artifact_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.enums import ArtifactSlot
from app.repositories.artifact import ArtifactRepository
from app.schemas.artifact import (
    ArtifactRead,
    GoodImportRequest,
    GoodImportResponse,
    ImportRejection,
)
from app.schemas.common import PaginatedResponse
from app.services.good_import_service import ReplaceRefusedError, store_good_import

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

#: Bounded the same way the catalogue's lists are, through `Query` rather than a hand-rolled
#: check — one mechanism, and FastAPI's 422 body instead of a second shape for the same
#: error. The ceiling is higher because an inventory is: a scanned account runs to thousands
#: of pieces where the catalogue tops out at 360.
_Offset = Annotated[int, Query(ge=0)]
_Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("", response_model=PaginatedResponse[ArtifactRead])
async def list_artifacts(
    repo: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    slot: ArtifactSlot | None = None,
    set_id: str | None = None,
    equipped: bool | None = None,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[ArtifactRead]:
    """The caller's artifacts, in game slot order — flower, plume, sands, goblet, circlet."""
    filters = {"slot": slot, "set_id": set_id, "equipped": equipped}
    rows = await repo.search(**filters, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[ArtifactRead.model_validate(row) for row in rows],
        total=await repo.count_filtered(**filters),
        offset=offset,
        limit=limit,
    )


# The import route is declared **before** `/{artifact_id}`. The two do not collide today —
# one is a POST and the other a GET — but a future `GET /artifacts/import/...` would be
# swallowed by the path parameter, and finding that out from a 404 is a bad afternoon.
@router.post("/import/good", response_model=GoodImportResponse)
@limiter.limit(WRITE_LIMIT)
async def import_good(
    request: Request,
    body: GoodImportRequest,
    session: DBSession,
    current_user: CurrentUser,
) -> GoodImportResponse:
    """Import a GOOD export into the caller's inventory.

    `mode` is required — see `GoodImportRequest`. A malformed *envelope* is a 400, because
    the file is not a GOOD export at all and nothing about it can be salvaged. A malformed
    *artifact* is not: it lands in `rejected` and the rest of the inventory imports, because
    someone with 800 artifacts and two odd ones wants the 798.

    A `replace` that resolved **nothing** is a 409 and deletes nothing — see
    `ReplaceRefusedError`.
    """
    try:
        parsed = parse_good(body.payload)
    except GoodImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        stored = await store_good_import(
            session, str(current_user.id), parsed, body.mode,
        )
    except ReplaceRefusedError as exc:
        # 409, not 400: the request is well-formed and the refusal is about the state it
        # would leave behind.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GoodImportResponse(
        inserted=stored.inserted,
        deleted=stored.deleted,
        rejected=[
            ImportRejection(index=index, reason=reason) for index, reason in stored.rejected
        ],
        ok=stored.ok,
        source=parsed.source,
        version=parsed.version,
    )


@router.get("/{artifact_id}", response_model=ArtifactRead)
async def get_artifact(
    artifact_id: str,
    repo: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
) -> ArtifactRead:
    """One of the caller's artifacts."""
    artifact = await repo.get_with_set(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"No artifact {artifact_id!r}")
    return ArtifactRead.model_validate(artifact)


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(WRITE_LIMIT)
async def delete_artifact(
    request: Request,
    artifact_id: str,
    repo: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
) -> None:
    """Delete one of the caller's artifacts.

    404 rather than 403 for a piece owned by someone else: the repository is scoped, so a
    foreign id is indistinguishable from a missing one here — and telling a caller which of
    the two it was would confirm that some other user owns that id.
    """
    artifact = await repo.get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"No artifact {artifact_id!r}")
    await repo.delete(artifact_id)
