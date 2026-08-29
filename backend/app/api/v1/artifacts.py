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
from app.models.enums import ArtifactSlot, Rarity, StatType
from app.repositories.artifact import ArtifactRepository
from app.repositories.build import BuildRepository
from app.schemas.artifact import (
    ArtifactEquip,
    ArtifactOptions,
    ArtifactRead,
    BuildImportSummary,
    GoodImportRequest,
    GoodImportResponse,
    ImportRejection,
    InventorySnapshot,
    KernelCandidate,
    RarityVocabularyEntry,
    SlotVocabularyEntry,
    StatVocabularyEntry,
    UnreadableArtifact,
)
from app.schemas.build import KernelSetBonus
from app.schemas.common import PaginatedResponse
from app.services import build_assembler
from app.services.good_build_service import rebuild_builds as rebuild_from_export
from app.services.good_import_service import ReplaceRefusedError, store_good_import
from app.services.good_weapon_service import store_owned_weapons
from app.services.stat_calculator import StatInputError, _quantity_for_prop

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
    #: Narrower than `equipped`: the pieces on **one** build, which is what a build's own five
    #: slots need. Fetching every equipped piece and filtering on the client scales with the
    #: whole inventory rather than with five.
    build_id: str | None = None,
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[ArtifactRead]:
    """The caller's artifacts, in game slot order — flower, plume, sands, goblet, circlet."""
    filters = {"slot": slot, "set_id": set_id, "equipped": equipped, "build_id": build_id}
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

    **Deliberately a superset of what the payload carries** (O.2). `rarity`, `level` and
    `build_id` are hashed and no longer emitted, so equipping a piece invalidates a snapshot
    whose bytes did not change. That is a spurious miss, and it is the safe direction: a
    digest narrower than the payload risks serving a **stale** inventory, and a search over
    one recommends artifacts the user no longer owns — the failure OQ-S3 chose this design to
    avoid. Widening costs a transfer; narrowing costs correctness.
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

    candidates, unreadable = _kernel_candidates(rows)

    response.headers["ETag"] = etag
    return InventorySnapshot(
        version=version,
        artifacts=candidates,
        # What was **returned**, not what was read: a count describing pieces the caller did
        # not receive is a count nobody can reconcile with the list beside it.
        total=len(candidates),
        truncated=truncated,
        unreadable=unreadable,
    )


def _kernel_candidates(
    rows: Sequence[Artifact],
) -> tuple[list[KernelCandidate], list[UnreadableArtifact]]:
    """Translate owned pieces into what `search.ts` reads, reporting what would not.

    O.2. `set_id` is the catalogue's **integer** `nanoka_id`, not the row's UUID: the kernel
    counts set pieces by id, and it counts numbers.

    A piece whose stats do not resolve is **reported and excluded** (OQ-O2). Excluded because
    the kernel cannot score a partial stat map and would rank the piece as weaker than it is —
    a wrong ordering, silently. Reported because a silently omitted piece is an inventory the
    user cannot see is incomplete.
    """
    candidates: list[KernelCandidate] = []
    unreadable: list[UnreadableArtifact] = []

    for row in rows:
        try:
            stats = _kernel_stats(row)
        except StatInputError as exc:
            unreadable.append(
                UnreadableArtifact(artifact_id=str(row.id), reason=str(exc)),
            )
            continue
        candidates.append(
            KernelCandidate(
                id=str(row.id),
                slot=row.slot.value,
                set_id=row.artifact_set.nanoka_id if row.artifact_set is not None else None,
                stats=stats,
                main_stat=row.main_stat_type.value,
            ),
        )
    return candidates, unreadable


def _kernel_stats(artifact: Artifact) -> dict[str, float]:
    """One piece's main stat and substats, summed per kernel quantity.

    Summed rather than assigned: a CRIT DMG circlet with a CRIT DMG substat has both, and the
    kernel takes one number per quantity — overwriting would drop whichever came second.

    `allow_absent` on the substats only. A substat may genuinely be absent — `FIGHT_PROP_NONE`
    is one of three spellings for it, and a piece with fewer than four is ordinary. A **main**
    stat that does not resolve is not an absent stat, it is a piece this build cannot read.
    """
    stats: dict[str, float] = {}
    main = _quantity_for_prop(artifact.main_stat_type)
    if main is not None:
        stats[main] = float(artifact.main_stat_value or 0.0)

    for substat in artifact.substats or []:
        if not isinstance(substat, dict):
            continue
        quantity = _quantity_for_prop(substat.get("stat"), allow_absent=True)
        if quantity is None:
            continue
        stats[quantity] = stats.get(quantity, 0.0) + float(substat.get("value", 0.0))
    return stats


# The import route is declared **before** `/{artifact_id}`. The two do not collide today —
# one is a POST and the other a GET — but a future `GET /artifacts/import/...` would be
# swallowed by the path parameter, and finding that out from a 404 is a bad afternoon.
@router.get("/set-bonuses", response_model=list[KernelSetBonus])
async def get_set_bonuses(
    repo: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
) -> list[KernelSetBonus]:
    """Every tier of every set the caller owns a piece of, in kernel terms.

    **Why this exists rather than reusing `/builds/{id}/search-context`.** That endpoint
    already returns these, but it requires a *hit* — and the rotation objective has none: it
    scores a whole gcsim run, not one Cutting DMG. Passing a hit purely to reach the bonuses
    would couple the rotation path to the single-hit path's requirements.

    **Why not derived in the browser.** `/artifact-sets` already publishes each affix's
    `add_props`, so a client could translate them itself — and would then own a second copy of
    the `FIGHT_PROP_*` → kernel-quantity mapping. `OptimizeService` says why that is refused:
    the mapping decides what every stat means, and O.1/O.2 exist so it happens once, here.

    **Only static `add_props` become stats**, the same rule `artifact_optimizer` documents: a
    conditional bonus has `FIGHT_PROP_NONE` for every prop and its numbers live in
    `param_list`. Nine of the sixty 2-piece affixes at 7.0.51 are conditional, six of them
    ability-scoped DMG bonuses a flat stat pool cannot express. They arrive here with empty
    `stats`, and a caller that means to score them has to say so — `TASKS_optimizer_reach.md`
    B.2 and B.3.

    Asked as a set question rather than by reading the inventory, for the reason
    `owned_sets` gives: `search`'s cap would silently omit a set from a large account, and a
    ranking missing an option looks exactly like a ranking.
    """
    return [
        KernelSetBonus(
            set_id=bonus.set_id,
            pieces_required=bonus.pieces_required,
            stats=build_assembler.bonus_stats(bonus),
        )
        for bonus in build_assembler.set_bonuses(await repo.owned_sets())
    ]


@router.get("/options", response_model=ArtifactOptions)
async def artifact_options(_: CurrentUser) -> ArtifactOptions:
    """The vocabulary an inventory needs to draw a row.

    A.3. `slot` and `main_stat_type` carry the source's internal spellings — `equip_bracer`,
    `FIGHT_PROP_HP_PERCENT` — which are keys, not labels. And the stored values are
    units-dependent: `4780.0` for flat HP, `0.466` for HP%. A page with neither fact prints
    "0.466 HP%" or "478000% HP", and neither looks obviously wrong at a glance.

    Published **once** rather than decorated onto every row: 26 stats and 5 slots repeated
    across 800 pieces is the same table 800 times.

    Declared above `/{artifact_id}` — FastAPI matches in declaration order, and below it this
    is an artifact whose id is the word "options", which 404s and looks like an empty
    inventory rather than a routing mistake.
    """
    return ArtifactOptions(
        stats=[
            StatVocabularyEntry(
                key=stat.value, display=stat.display, percentage=stat.is_percentage,
            )
            for stat in StatType
        ],
        slots=[
            SlotVocabularyEntry(key=slot.value, display=slot.display)
            for slot in sorted(ArtifactSlot, key=lambda s: s.sort_index)
        ],
        rarities=[
            RarityVocabularyEntry(key=rarity.value, stars=rarity.stars)
            for rarity in Rarity
        ],
    )


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
    builds = None
    if body.rebuild_builds:
        report = await rebuild_from_export(
            session,
            owner_id=str(current_user.id),
            parsed=parsed,
            stored=stored.rows_by_source,
        )
        builds = BuildImportSummary(
            created=report.created,
            skipped_existing=sorted(report.skipped_existing),
            unresolved=sorted(report.unresolved),
            unplaced=sorted(report.unplaced),
            unresolved_weapons=sorted(report.unresolved_weapons),
            no_weapon_in_export=sorted(report.no_weapon_in_export),
            reassigned=sorted(report.reassigned),
        )

    # **After the builds**, because the equip link is made through them — and unconditionally,
    # because owning a weapon is not contingent on wanting builds rebuilt. Before this, 252 of
    # the owner's 320 weapons were parsed and discarded (`good_weapon_service`).
    weapons_stored, weapons_unresolved = await store_owned_weapons(
        session, owner_id=str(current_user.id), parsed=parsed,
    )

    return GoodImportResponse(
        weapons_stored=weapons_stored,
        weapons_unresolved=weapons_unresolved,
        inserted=stored.inserted,
        deleted=stored.deleted,
        builds=builds,
        rejected=[
            ImportRejection(index=index, reason=reason) for index, reason in stored.rejected
        ],
        ok=stored.ok,
        unequipped=list(stored.unequipped),
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
    # Eager, and this is the load the **response** depends on too. `ArtifactRead` publishes
    # `set_name`, which reads `artifact_set`; `lazy` is `raise_on_sql`, so fetching with
    # `get_by_id` here is a `MissingGreenlet` at serialisation time — the trap T.2 and A.1
    # both met. Weakening this line breaks the write path's response, not just its 404.
    artifact = await repo.get_with_set(artifact_id)
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
        # `update` re-reads through `get_by_id`, which returns the **same instance** this
        # handler already loaded eagerly — so `set_name` stays resolvable without a second
        # eager fetch. Injecting that fetch away changed no test, which is what says it was
        # redundant rather than untested.
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
