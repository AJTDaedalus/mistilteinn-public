"""Saved builds, and the optimizer and ranker over them.

This is where Chunks F and G become reachable. Until now the damage chain and the artifact
search existed and nothing could call them.

## The hit is supplied, not derived

`POST /builds/{id}/optimize` takes a `hit` — multiplier, scaling stat, damage channel,
scope. It does **not** work one out from the build's character. Deriving a talent's numbers
from its stored rows is the kit corpus's job (Chunk H) and this repo has no kit corpus;
parsing a multiplier out of a `desc` string and serving the result would be presenting a
guess as though it came from the game. `TODO(chunk-H)`.

## The search reports what it skipped

Every optimize response carries `search`, including `is_exact`. A near-answer presented as
an answer is worse than a slow search, and the caller is the one who can decide to re-run
exhaustively.
"""

from functools import partial
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.dependencies import (
    get_enemy_profile_repo,
    get_job_runner,
    get_owned_artifact_repo,
    get_owned_build_repo,
    get_owned_optimization_job_repo,
)
from app.formula.genshin.damage import Hit
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.artifact import ArtifactRepository
from app.repositories.build import BuildRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.optimization_job import OptimizationJobRepository
from app.schemas.build import (
    BuildCreate,
    BuildRead,
    BuildUpdate,
    EnemySpec,
    HitSpec,
    JobAccepted,
    OptimizedBuildRead,
    OptimizeRequest,
    OptimizeResponse,
    RankedArtifactRead,
    RankRequest,
    RankResponse,
    SearchTransparency,
)
from app.schemas.common import PaginatedResponse
from app.services import (
    artifact_optimizer,
    artifact_ranker,
    build_assembler,
    optimizer_job_service,
)
from app.services.build_assembler import BuildAssemblyError
from app.services.damage_calculator import Enemy, enemy_from_profile
from app.services.job_runner import JobRunner
from app.services.stat_calculator import StatInputError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from app.formula.genshin.explain import Contribution
    from app.models.artifact import Artifact, ArtifactSet
    from app.models.build import Build

router = APIRouter(prefix="/builds", tags=["builds"])

_Offset = Annotated[int, Query(ge=0)]
_Limit = Annotated[int, Query(ge=1, le=200)]


@router.get("", response_model=PaginatedResponse[BuildRead])
async def list_builds(
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    offset: _Offset = 0,
    limit: _Limit = 50,
) -> PaginatedResponse[BuildRead]:
    """The caller's saved builds, newest first."""
    rows = await repo.search(offset=offset, limit=limit)
    return PaginatedResponse(
        items=[BuildRead.model_validate(row) for row in rows],
        total=await repo.count_filtered(),
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=BuildRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_build(
    request: Request,
    body: BuildCreate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """Save a build."""
    build = await repo.create({**body.model_dump(), "owner_id": repo.owner_id})
    return BuildRead.model_validate(build)


@router.get("/{build_id}", response_model=BuildRead)
async def get_build(
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """One of the caller's builds."""
    return BuildRead.model_validate(await _require_build(repo, build_id))


@router.patch("/{build_id}", response_model=BuildRead)
@limiter.limit(WRITE_LIMIT)
async def update_build(
    request: Request,
    build_id: str,
    body: BuildUpdate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """Partially update one of the caller's builds."""
    await _require_build(repo, build_id)
    patch = body.model_dump(exclude_unset=True)
    updated = await repo.update(build_id, patch) if patch else await repo.get_by_id(build_id)
    return BuildRead.model_validate(updated)


@router.delete("/{build_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(WRITE_LIMIT)
async def delete_build(
    request: Request,
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> None:
    """Delete one of the caller's builds. Its artifacts are unequipped, not deleted."""
    await _require_build(repo, build_id)
    await repo.delete(build_id)


@router.post(
    "/{build_id}/optimize",
    response_model=OptimizeResponse | JobAccepted,
    responses={202: {"model": JobAccepted}},
)
@limiter.limit(WRITE_LIMIT)
async def optimize_build(
    request: Request,
    build_id: str,
    body: OptimizeRequest,
    response: Response,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    artifacts: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    enemies: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
    jobs: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
    runner: Annotated[JobRunner, Depends(get_job_runner)],
) -> OptimizeResponse | JobAccepted:
    """Search the caller's inventory for the best five pieces for this build.

    **200 with the answer, or 202 with a job id.** A search that fits inside
    `optimizer_job_service.SYNC_SECONDS` runs here and returns its result; a larger one is
    queued and answered with a `poll_url`. A contract that always returned a job id would
    make the ordinary case worse in order to serve the rare one.
    """
    build = await _require_full_build(builds, build_id)
    base = _base_contributions(build)
    # One fetch. Equipped pieces are owned pieces, so this already covers the build's own
    # five. Querying twice and concatenating passed each equipped set in a second time, and
    # `set_bonuses` expands every affix of every row it is handed — see `_sets_of`.
    owned = await artifacts.search(limit=_FETCH_CAP)
    owned_total = await artifacts.count_filtered()
    inventory = build_assembler.candidates(_capped_per_slot(owned))
    bonuses = build_assembler.set_bonuses(_sets_of(owned))

    constraints = artifact_optimizer.OptimizerConstraints(
        locked_slots=body.locked_slots,
        required_sets=body.required_sets,
        min_stats=body.min_stats,
        top_n=body.top_n,
        prefilter_top_k=body.prefilter_top_k,
    )
    payload = optimizer_job_service.SearchPayload(
        base_contributions=tuple(base),
        candidates=tuple(inventory),
        hit=_hit(body.hit),
        enemy=await _enemy(body.enemy, enemies),
        character_level=build.character_level,
        set_bonuses=tuple(bonuses),
        constraints=constraints,
    )

    estimate = optimizer_job_service.estimated_combinations(payload.candidates)
    limit = optimizer_job_service.sync_combination_limit()
    if estimate > limit:
        # Too big to answer inside the request. Everything above already validated, so a
        # job is only ever created for a search that would actually have run.
        return await _accept_job(
            response, jobs, runner, build, payload, estimate, limit,
            partial(_to_response, owned_total=owned_total),
        )

    try:
        result = artifact_optimizer.optimize(
            payload.base_contributions,
            payload.candidates,
            payload.hit,
            payload.enemy,
            character_level=payload.character_level,
            set_bonuses=payload.set_bonuses,
            constraints=payload.constraints,
        )
    except (artifact_optimizer.OptimizerInputError, StatInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return OptimizeResponse.model_validate(
        _to_response(result, considered=len(inventory), owned_total=owned_total),
    )


def _to_response(
    result: artifact_optimizer.OptimizerResult, *, considered: int, owned_total: int,
) -> dict:
    """One shape for both paths.

    A job persists this dict and a synchronous request returns it, so "what an optimize
    answer looks like" has one definition. Two of them would drift, and the one that drifted
    would be whichever path the tests exercised less.
    """
    return OptimizeResponse(
        builds=[
            OptimizedBuildRead(
                damage=entry.damage,
                artifact_ids=list(entry.artifact_ids),
                set_counts=entry.set_counts,
                contributions=[
                    {
                        "quantity": c.quantity, "value": c.value,
                        "source": c.source, "note": c.note,
                    }
                    for c in entry.contributions
                ],
            )
            for entry in result.builds
        ],
        search=SearchTransparency(
            evaluated=result.evaluated,
            total_space=result.prefilter.total_space,
            rejected_by_sets=result.rejected_by_sets,
            rejected_by_stats=result.rejected_by_stats,
            pareto_removed=result.prefilter.pareto_removed,
            prefiltered=result.prefilter.prefiltered,
            effective_k=result.prefilter.effective_k,
            is_exact=result.is_exact,
            summary=result.summary(),
            skipped_conditional_bonuses=result.skipped_conditional_bonuses,
            inventory_considered=considered,
            inventory_total=owned_total,
        ),
    ).model_dump()


async def _accept_job(
    response: Response,
    jobs: OptimizationJobRepository,
    runner: JobRunner,
    build: "Build",
    payload: optimizer_job_service.SearchPayload,
    estimate: int,
    limit: int,
    to_response: "Callable[[artifact_optimizer.OptimizerResult], dict]",
) -> JobAccepted:
    """Persist a queued job, hand the search to the runner, and answer 202."""
    job = await jobs.create({
        "owner_id": jobs.owner_id,
        "job_type": "optimizer",
        "status": "queued",
        "request": {"build_id": str(build.id), "estimated_combinations": estimate},
        "character_name": build.character.name if build.character else "",
        "combinations_total": estimate,
    })
    # **Commit before submitting.** `get_db` commits when the handler returns, which is
    # after this line — and the worker's very first act is `_mark_running`, an UPDATE from a
    # *separate* session. Against an uncommitted row that matches nothing, so the job would
    # sit `queued` for ever and its result would be discarded silently. Nothing would raise,
    # and the route tests could not see it because they mock the runner.
    await jobs.session.commit()
    runner.submit_search(
        str(job.id), optimizer_job_service.search_fn(payload, to_response),
    )
    response.status_code = status.HTTP_202_ACCEPTED
    return JobAccepted(
        job_id=str(job.id),
        poll_url=f"/api/v1/optimizer-jobs/{job.id}",
        estimated_combinations=estimate,
        sync_limit=limit,
    )


@router.post("/{build_id}/rank-artifacts", response_model=RankResponse)
@limiter.limit(WRITE_LIMIT)
async def rank_artifacts(
    request: Request,
    build_id: str,
    body: RankRequest,
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    artifacts: Annotated[ArtifactRepository, Depends(get_owned_artifact_repo)],
    enemies: Annotated[EnemyProfileRepository, Depends(get_enemy_profile_repo)],
) -> RankResponse:
    """Rank the caller's artifacts by what each is worth *instead of* what is equipped.

    Needs all five slots filled: a ranking measures a swap, and with an empty slot every
    candidate for it would score as a free upgrade.
    """
    build = await _require_full_build(builds, build_id)
    equipped = build_assembler.candidates(build.artifacts)
    owned = await artifacts.search(limit=_FETCH_CAP)
    inventory = build_assembler.candidates(
        [row for row in owned if body.slot is None or row.slot == body.slot][: body.limit],
    )
    bonuses = build_assembler.set_bonuses(_sets_of(owned))

    try:
        context = artifact_ranker.RankContext(
            name=_CONTEXT,
            base_contributions=_base_contributions(build),
            equipped=tuple(equipped),
            hit=_hit(body.hit),
            enemy=await _enemy(body.enemy, enemies),
            character_level=build.character_level,
        )
        result = artifact_ranker.rank(inventory, [context], set_bonuses=bonuses)
    except (artifact_optimizer.OptimizerInputError, StatInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RankResponse(
        baseline_damage=result.baselines[_CONTEXT],
        artifacts=[
            RankedArtifactRead(
                artifact_id=entry.artifact_id,
                slot=entry.slot,
                improvement_pct=entry.mean_improvement_pct,
                # By name, not by position. One context today, and `artifact_ranker` takes a
                # list precisely because that changes — an index would keep working and stop
                # meaning this build.
                damage=next(s.damage for s in entry.scores if s.context == _CONTEXT),
            )
            for entry in result.artifacts
        ],
        skipped_conditional_bonuses=result.skipped_conditional_bonuses,
    )


#: How many owned pieces one request will read out of the database.
_FETCH_CAP = 20_000

#: How many pieces **per slot** a single request will search over, best-levelled first.
#:
#: Per slot, not overall. A global cap truncates the inventory in slot order — flower,
#: plume, sands, goblet, circlet — so it removes whole *slots* from the tail rather than
#: trimming each one, and the search then refuses with "no candidates for
#: ['equip_dress']". A cap that turns a large inventory into an impossible search is worse
#: than no cap at all.
#:
#: **And it is reported, never silent.** `SearchTransparency.inventory_considered` and
#: `inventory_total` differ exactly when it bit. A bound on coverage the response does not
#: mention reads as "searched everything" — the rule the prefilter already follows for its
#: own pruning, with no reason this one is exempt.
_SLOT_CAP = 500

#: The single ranking context this route builds. Named, because `artifact_ranker` reports
#: per-context results by name and `RankRequest` will grow a multi-build form (G.6c-multi).
_CONTEXT = "build"


def _capped_per_slot(artifacts: "Sequence[Artifact]") -> list["Artifact"]:
    """At most `_SLOT_CAP` pieces per slot, keeping the best-levelled.

    Relies on the repository's ordering — slot order, then level descending — so "the first
    N of this slot" is "the N most upgraded".
    """
    kept: list[Artifact] = []
    seen: dict[str, int] = {}
    for artifact in artifacts:
        slot = artifact.slot.value
        if seen.get(slot, 0) >= _SLOT_CAP:
            continue
        seen[slot] = seen.get(slot, 0) + 1
        kept.append(artifact)
    return kept


def _sets_of(artifacts: "Sequence[Artifact]") -> list["ArtifactSet"]:
    """Each distinct catalogue set among these pieces, once.

    Once, because `set_bonuses` expands every affix of every set it is given: handing it the
    same set five times would register a 2-piece bonus five times over on any build wearing
    five of it. The optimizer would then report a build worth several times what it is.
    """
    seen: dict[int, ArtifactSet] = {}
    for artifact in artifacts:
        if artifact.artifact_set is not None:
            seen.setdefault(artifact.artifact_set.nanoka_id, artifact.artifact_set)
    return list(seen.values())


async def _require_build(repo: BuildRepository, build_id: str) -> "Build":
    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail=f"No build {build_id!r}")
    return build


async def _require_full_build(repo: BuildRepository, build_id: str) -> "Build":
    build = await repo.get_full(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail=f"No build {build_id!r}")
    return build


def _base_contributions(build: "Build") -> "tuple[Contribution, ...]":
    try:
        return build_assembler.base_contributions(build)
    except (BuildAssemblyError, StatInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _hit(spec: HitSpec) -> Hit:
    return Hit(
        multiplier=spec.multiplier,
        channel=spec.channel,
        scope=spec.scope,
        scaling_stat=spec.scaling_stat,
        amplifying=spec.amplifying,
        flat_damage=spec.flat_damage,
    )


async def _enemy(spec: EnemySpec, repo: EnemyProfileRepository) -> Enemy:
    """The target, from a stored profile when one is named.

    A profile's eight resistance columns are the whole of what a hit needs from it — its
    HP/ATK/DEF are curve bases and outgoing damage never reads them.
    """
    if spec.enemy_profile_id is not None:
        profile = await repo.get_by_id(spec.enemy_profile_id)
        if profile is None:
            raise HTTPException(
                status_code=404, detail=f"No enemy profile {spec.enemy_profile_id!r}",
            )
        return enemy_from_profile(
            level=profile.level,
            resistances={
                "physical": profile.physical_res, "anemo": profile.anemo_res,
                "cryo": profile.cryo_res, "dendro": profile.dendro_res,
                "electro": profile.electro_res, "geo": profile.geo_res,
                "hydro": profile.hydro_res, "pyro": profile.pyro_res,
            },
        )
    return enemy_from_profile(level=spec.level, resistances=spec.resolved_resistances())
