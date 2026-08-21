"""Disc endpoints — full CRUD for user inventory."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.data.importers.ezod_importer import import_ezod_payload
from app.data.importers.scanner_importer import import_zod_payload
from app.dependencies import CurrentUser, DBSession, get_owned_disc_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.disc import DiscRepository
from app.schemas.common import PaginatedResponse
from app.schemas.disc import DiscCreate, DiscRead, DiscUpdate

router = APIRouter(prefix="/discs", tags=["discs"])


class DiscImportResponse(BaseModel):
    """Result summary for ``POST /discs/import``."""

    imported: int
    skipped_duplicate: int
    skipped_unknown_set: int
    skipped_invalid: int
    errors: list[str]
    # Advisory findings that did not stop the import (stale mindscape, skill levels
    # inconsistent with mindscape). Separate from `errors` so the UI can label them
    # honestly — see EzodImportResult.notices.
    notices: list[str] = []
    builds_created: int = 0
    builds_overwritten: int = 0
    builds_skipped: int = 0
    discs_deleted: int = 0
    builds_deleted: int = 0
    teams_deleted: int = 0
    combos_deleted: int = 0
    team_slots_remapped: int = 0


_IMPORT_MODES = ("merge", "clean")


def _validate_mode(name: str, value: str) -> None:
    """Reject an import mode outside ``{"merge", "clean"}`` with a 422."""
    if value not in _IMPORT_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {name} {value!r}; expected 'merge' or 'clean'.",
        )


@router.get("", response_model=PaginatedResponse[DiscRead])
async def list_discs(
    repo: Annotated[DiscRepository, Depends(get_owned_disc_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=3000),
    slot: int | None = Query(None, ge=1, le=6, description="Filter by disc slot (1-6)"),
    set_id: str | None = Query(None, description="Filter by disc set ID"),
    rarity: str | None = Query(None, description="Filter by rarity (S, A, B)"),
    equipped: str | None = Query(
        None,
        description=(
            "Filter by equipped status: "
            "'any' (default), 'unequipped', or a build ID "
            "(returns unequipped + equipped to that build)"
        ),
    ),
) -> PaginatedResponse[DiscRead]:
    """List the caller's disc inventory, with optional slot/set/rarity/equip filters."""
    if any(p is not None for p in (slot, set_id, rarity, equipped)):
        discs = await repo.list_filtered(
            offset=offset,
            limit=limit,
            slot=slot,
            set_id=set_id,
            rarity=rarity,
            equipped=equipped,
        )
        total = await repo.count_filtered(
            slot=slot,
            set_id=set_id,
            rarity=rarity,
            equipped=equipped,
        )
    else:
        discs = await repo.get_all(offset=offset, limit=limit)
        total = await repo.count()
    return PaginatedResponse(
        items=[DiscRead.model_validate(d) for d in discs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=DiscRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_disc(
    request: Request,
    body: DiscCreate,
    repo: Annotated[DiscRepository, Depends(get_owned_disc_repo)],
) -> DiscRead:
    """Add a disc to the caller's inventory."""
    data = body.model_dump()
    if data.get("substats"):
        data["substats"] = [
            s.model_dump() if hasattr(s, "model_dump") else s for s in body.substats
        ]
    disc = await repo.create(data)
    return DiscRead.model_validate(disc)


@router.get("/{disc_id}", response_model=DiscRead)
async def get_disc(
    disc_id: str,
    repo: Annotated[DiscRepository, Depends(get_owned_disc_repo)],
) -> DiscRead:
    """Fetch a single disc from the caller's inventory by id."""
    disc = await repo.get_by_id(disc_id)
    if disc is None:
        raise HTTPException(status_code=404, detail="Disc not found")
    return DiscRead.model_validate(disc)


@router.patch("/{disc_id}", response_model=DiscRead)
@limiter.limit(WRITE_LIMIT)
async def update_disc(
    request: Request,
    disc_id: str,
    body: DiscUpdate,
    repo: Annotated[DiscRepository, Depends(get_owned_disc_repo)],
) -> DiscRead:
    """Partially update a disc (main/substats, slot, equip state)."""
    data = body.model_dump(exclude_unset=True)
    if "substats" in data and data["substats"] is not None:
        data["substats"] = [
            s.model_dump() if hasattr(s, "model_dump") else s for s in body.substats
        ]
    disc = await repo.update(disc_id, data)
    if disc is None:
        raise HTTPException(status_code=404, detail="Disc not found")
    return DiscRead.model_validate(disc)


@router.delete("/{disc_id}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def delete_disc(
    request: Request,
    disc_id: str,
    repo: Annotated[DiscRepository, Depends(get_owned_disc_repo)],
) -> None:
    """Delete a disc from the caller's inventory."""
    deleted = await repo.delete(disc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Disc not found")


@router.post("/import", response_model=DiscImportResponse)
@limiter.limit(WRITE_LIMIT)
async def import_discs(
    request: Request,
    body: dict,
    session: DBSession,
    current_user: CurrentUser,
    build_conflict: str = Query(
        "overwrite", description="eZOD conflict mode: 'skip' or 'overwrite'"
    ),
    disc_mode: str = Query(
        "merge",
        description="'merge' keeps existing discs; 'clean' wipes the inventory first",
    ),
    build_mode: str = Query(
        "merge",
        description=(
            "eZOD only: 'merge' keeps existing builds; 'clean' wipes them first "
            "(re-pointing team slots, deleting teams left with no members). "
            "Ignored for ZOD payloads, which carry no builds."
        ),
    ),
) -> DiscImportResponse:
    """Import a ZOD or eZOD scanner payload.

    For ZOD: imports discs as unequipped inventory (idempotent via content hash).
    For eZOD: imports discs + creates one Build per equipped character.
    ``build_conflict`` controls behaviour when a build for that agent already
    exists; it only applies under ``build_mode="merge"``, since a clean leaves
    no build to conflict with.
    """
    if build_conflict not in ("skip", "overwrite"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid build_conflict {build_conflict!r}; expected 'skip' or 'overwrite'.",
        )
    _validate_mode("disc_mode", disc_mode)
    _validate_mode("build_mode", build_mode)
    fmt = body.get("format", "")
    try:
        if fmt == "eZOD":
            result = await import_ezod_payload(
                body,
                session,
                owner_id=str(current_user.id),
                build_conflict=build_conflict,
                disc_mode=disc_mode,
                build_mode=build_mode,
            )
            return DiscImportResponse(
                imported=result.imported,
                skipped_duplicate=result.skipped_duplicate,
                skipped_unknown_set=result.skipped_unknown_set,
                skipped_invalid=result.skipped_invalid,
                errors=result.errors,
                notices=result.notices,
                builds_created=result.builds_created,
                builds_overwritten=result.builds_overwritten,
                builds_skipped=result.builds_skipped,
                discs_deleted=result.discs_deleted,
                builds_deleted=result.builds_deleted,
                teams_deleted=result.teams_deleted,
                combos_deleted=result.combos_deleted,
                team_slots_remapped=result.team_slots_remapped,
            )
        if fmt == "ZOD":
            zod_result = await import_zod_payload(
                body, session, owner_id=str(current_user.id), disc_mode=disc_mode
            )
            return DiscImportResponse(
                imported=zod_result.imported,
                skipped_duplicate=zod_result.skipped_duplicate,
                skipped_unknown_set=zod_result.skipped_unknown_set,
                skipped_invalid=zod_result.skipped_invalid,
                errors=zod_result.errors,
                discs_deleted=zod_result.discs_deleted,
            )
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported format {fmt!r}. Expected ZOD or eZOD.",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
