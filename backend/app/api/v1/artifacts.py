"""A user's artifact inventory, and the GOOD import that fills it.

The first **write** surface over Chunk G's work. Everything here is owner-scoped: an
artifact belongs to someone, unlike the catalogue, and every route reaches the database
through a repository already carrying the caller's id.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.exc import IntegrityError

from app.data.importers.good_importer import GoodImportError, parse_good
from app.dependencies import (
    CurrentUser,
    DBSession,
    get_owned_artifact_repo,
    get_owned_build_repo,
)
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.enums import ArtifactSlot
from app.repositories.artifact import ArtifactRepository
from app.repositories.build import BuildRepository
from app.schemas.artifact import (
    ArtifactEquip,
    ArtifactRead,
    GoodImportRequest,
    GoodImportResponse,
    ImportRejection,
    InventorySnapshot,
)
from app.schemas.common import PaginatedResponse
from app.services.good_import_service import ReplaceRefusedError, store_good_import

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.artifact import Artifact

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


#: Pieces one inventory response will carry. Above this the response says so rather than
#: silently sending a prefix: a search told it has the whole inventory when it has 20,000 of
#: 25,000 pieces would report a best build that is only the best of what it was shown.
INVENTORY_CAP = 20_000


def _inventory_version(rows: Sequence[Artifact]) -> str:
    """A digest over what a search would actually read.

    Over the *stats*, not `updated_at`: levelling a piece changes the search, and a touched
    timestamp on a piece whose numbers did not move does not. A version that changed for
    bookkeeping would make every revalidation a full transfer, which is the cost this exists
    to avoid.
    """
    parts = [
        f"{row.id}:{row.slot}:{row.rarity}:{row.level}:{row.main_stat_type}:"
        f"{row.main_stat_value!r}:{row.artifact_set_id}:{row.build_id}:{row.substats!r}"
        for row in rows
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:32]


# Declared before `/{artifact_id}` for the same reason the GOOD import is: a path parameter
# would otherwise swallow it.
@router.get("/inventory", response_model=InventorySnapshot)
async def get_inventory(
    repo: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> InventorySnapshot | Response:
    """The caller's whole inventory at one instant, for the client-side search.

    Answers `304` when the caller already holds this version. See `InventorySnapshot` for
    why the browser holds it at all (OQ-S3).
    """
    rows = await repo.search(offset=0, limit=INVENTORY_CAP + 1)
    truncated = len(rows) > INVENTORY_CAP
    rows = rows[:INVENTORY_CAP]

    version = _inventory_version(rows)
    etag = f'"{version}"'
    # Weak-comparison-free on purpose: this is a strong ETag over exact bytes of meaning, and
    # a `W/` prefix from a proxy should miss rather than be normalised into a hit here.
    if if_none_match is not None and etag in [t.strip() for t in if_none_match.split(",")]:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    response.headers["ETag"] = etag
    return InventorySnapshot(
        version=version,
        artifacts=[ArtifactRead.model_validate(row) for row in rows],
        total=len(rows),
        truncated=truncated,
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


@router.patch("/{artifact_id}", response_model=ArtifactRead)
@limiter.limit(WRITE_LIMIT)
async def equip_artifact(
    request: Request,  # slowapi reads the client address off it
    artifact_id: str,
    body: ArtifactEquip,
    repo: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> ArtifactRead:
    """Attach a piece to a build, or take it off.

    A.1. `Artifact.build_id` has existed since Chunk C and nothing set it, so an imported
    inventory could not be attached to anything.

    **A filled slot is refused, naming the piece that holds it** (OQ-A2). Swapping is a
    reasonable thing to want and a terrible thing to do unasked: the displaced piece is still
    equipped in the user's head, and they would find out later, from a damage number.
    `uq_artifacts_build_slot` would otherwise make this a 500 — the shape
    `uq_builds_owner_character` had before T.1a.
    """
    artifact = await repo.get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"No artifact {artifact_id!r}")

    if body.build_id is not None:
        # Owner-scoped, so a stranger's build reads as absent. That is the right answer:
        # confirming it exists would disclose that it does.
        if await builds.get_by_id(body.build_id) is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no build {body.build_id!r} of yours. A piece is equipped to one of "
                    f"your own builds."
                ),
            )
        holder = await repo.equipped_in_slot(body.build_id, artifact.slot)
        if holder is not None and str(holder.id) != artifact_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"that build already has a {artifact.slot.display} equipped ({holder.id}). "
                    f"Take it off first — swapping without being asked would leave you with "
                    f"a piece you still think is equipped."
                ),
            )

    # Read **before** the write. A failed flush expires the instance, so touching
    # `artifact.slot` afterwards emits SQL from inside the exception handler — which is a
    # `MissingGreenlet`, and turns the 422 below into the 500 it exists to prevent.
    slot_name = artifact.slot.display
    try:
        updated = await repo.update(artifact_id, {"build_id": body.build_id})
    except IntegrityError as exc:
        # The check above and this write are not one operation, so two requests equipping the
        # same slot can both pass it. `uq_artifacts_build_slot` is the backstop that keeps the
        # data right — and without this it surfaces as a 500 for an ordinary race, which is
        # the failure mode this endpoint exists to remove rather than relocate.
        #
        # No rollback here: `get_db` rolls back on any exception leaving the handler.
        raise HTTPException(
            status_code=422,
            detail=(
                f"that build already has a {slot_name} equipped. Something filled the slot "
                f"while this request was in flight — take it off and try again."
            ),
        ) from exc
    return ArtifactRead.model_validate(updated)


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
