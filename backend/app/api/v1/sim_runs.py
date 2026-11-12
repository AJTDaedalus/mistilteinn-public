"""The run corpus — where the browser's simulated runs are kept, and what it already has.

DESIGN §3.5 puts every combinatorial cost on the client: the browser runs gcsim for its own
context, one run per ER bucket, and the search scores candidates against those. This is the
only server-side part of that loop, and it is deliberately small — three routes that store,
read, and report coverage. Nothing here simulates anything.

## Why the pin is checked rather than trusted

The submitter says which gcsim produced the run. If the server took its word, a browser
serving a stale WASM build would fill the corpus with runs from a different simulator, and
every one of them would look like a hit. `sim_run.py`'s key exists to prevent exactly that,
and a key is only as good as the value written into it — so a submission at any pin other
than this server's is refused, naming both.

That makes a re-pin loud. It should be: the pin is what "correct" means here, and a client
that disagrees about it is not a client whose numbers should be cached.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)

from app.dependencies import SettingsDep, get_owned_sim_run_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.sim_run import SimRunRepository
from app.schemas.sim_run import (
    NOT_RETRIEVED_COLD,
    NOT_RETRIEVED_TOO_FAR,
    DivergenceRead,
    RetrievalOutcome,
    RetrievalRead,
    SimRunCoverage,
    SimRunRead,
    SimRunStored,
    SimRunSubmit,
    dps_mean_of,
)
from app.services.gcsim_keys import pinned_commit
from app.services.quotas import enforce_daily
from app.services.sim_context import ER_BUCKET_PERCENT, er_bucket
from app.services.sim_retrieval import MAX_NEIGHBOUR_BUCKETS, retrieve

router = APIRouter(prefix="/sim-runs", tags=["sim-runs"])

_Repo = Annotated[SimRunRepository, Depends(get_owned_sim_run_repo)]
#: The same shape in both places it appears, because a key that is valid as a query
#: parameter and rejected as a path one would be a route-dependent definition of a digest.
_DIGEST = r"^[0-9a-f]{64}$"
_ContextKeyQuery = Annotated[str, Query(min_length=64, max_length=64, pattern=_DIGEST)]
_ContextKeyPath = Annotated[str, Path(min_length=64, max_length=64, pattern=_DIGEST)]
_ERBucket = Annotated[int, Path(ge=0, le=10_000)]

#: Energy recharge as a **fraction** — `1.8` is 180 %, the way every stat in this codebase is
#: expressed (`backend/CLAUDE.md`, "Fractions, not percents or basis points").
#:
#: The ceiling exists to catch the unit error rather than to model the game. A caller that
#: sends `180` meaning 180 % would otherwise be bucketed at 18000, miss every time, and be
#: told it has a cold context — forever, with no symptom other than never getting a hit. That
#: is the same shape as the unbucketed read D.1's review caught, arriving from the other
#: direction. Ten is far above any real build and far below a plausible unit slip.
_MAX_ENERGY_RECHARGE = 10.0
_EnergyRecharge = Annotated[float, Query(ge=0.0, le=_MAX_ENERGY_RECHARGE)]


def _require_our_pin(submitted: str) -> str:
    """Refuse a run from a gcsim this server does not mean."""
    ours = pinned_commit()
    if submitted != ours:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"this run was produced by gcsim {submitted[:12]} and this server is pinned "
                f"to {ours[:12]}. Rebuild the browser gcsim from the pin in "
                f"docs/CROSSVAL_gcsim.md — caching a run from another simulator would serve "
                f"a confident number for a different game version."
            ),
        )
    return ours


@router.get("", response_model=SimRunCoverage)
async def get_coverage(repo: _Repo, context_key: _ContextKeyQuery) -> SimRunCoverage:
    """Which ER buckets this context already has at the server's pin.

    The browser asks this **first**, and simulates only the gap. A cold context answers with
    an empty list rather than a 404: "nothing cached yet" is the ordinary state of a corpus
    that fills on demand, and it is not an error to be in it.
    """
    pin = pinned_commit()
    rows = await repo.get_buckets(context_key=context_key, gcsim_pin=pin)
    return SimRunCoverage(
        context_key=context_key,
        gcsim_pin=pin,
        er_buckets=[row.er_bucket for row in rows],
        dps_means=[row.dps_mean for row in rows],
    )


# Declared before `/{context_key}/{er_bucket}` — the two do not collide today, since this
# has one path segment where that has two, but a future `/retrieve/{something}` would be
# swallowed and finding that out from a 404 is a bad afternoon.
@router.get("/retrieve", response_model=RetrievalOutcome)
async def retrieve_run(
    repo: _Repo,
    context_key: _ContextKeyQuery,
    energy_recharge: _EnergyRecharge,
) -> RetrievalOutcome:
    """The cached run for a build at this ER — **or a stated reason there is none**.

    Always 200. `retrieved` is either present or explicitly null with `not_retrieved_because`
    beside it, and never a distant neighbour dressed up as a close one. See
    `RetrievalOutcome` for why "nothing close enough is cached" is an answer rather than a
    404: an error invites a retry or a swallowed exception, and the second is the silent
    fallback DESIGN §3.5 forbids by name.
    """
    pin = pinned_commit()
    runs = await repo.get_buckets(context_key=context_key, gcsim_pin=pin)
    wanted = er_bucket(energy_recharge)
    found = retrieve(runs, energy_recharge)

    if found is None:
        cold = not runs
        # Lower bucket on a tie, matching `sim_retrieval.retrieve` — a message that named
        # a different bucket than the one the decision was about would be its own bug.
        nearest = None if cold else min(
            runs, key=lambda r: (abs(r.er_bucket - wanted), r.er_bucket)
        )
        detail = (
            f"nothing is cached for this context at pin {pin[:12]}. Simulate the buckets this "
            f"search needs, starting with {wanted}."
            if cold
            else (
                f"the nearest cached run is bucket {nearest.er_bucket}, "
                f"{abs(nearest.er_bucket - wanted) // ER_BUCKET_PERCENT} buckets from "
                f"{wanted}, and at most {MAX_NEIGHBOUR_BUCKETS} away is offered. Simulate "
                f"{wanted}; a run that far away describes a different part of the ER curve."
            )
        )
        return RetrievalOutcome(
            context_key=context_key,
            gcsim_pin=pin,
            requested_bucket=wanted,
            retrieved=None,
            not_retrieved_because=NOT_RETRIEVED_COLD if cold else NOT_RETRIEVED_TOO_FAR,
            detail=detail,
        )

    divergence = found.divergence
    return RetrievalOutcome(
        context_key=context_key,
        gcsim_pin=pin,
        requested_bucket=found.requested_bucket,
        retrieved=RetrievalRead(
            run=SimRunRead.model_validate(found.run),
            requested_bucket=found.requested_bucket,
            matched_bucket=found.matched_bucket,
            bucket_distance=found.bucket_distance,
            is_exact_bucket=found.is_exact_bucket,
            divergence=None
            if divergence is None
            else DivergenceRead(
                reference_bucket=divergence.reference_bucket,
                dps_delta=divergence.dps_delta,
                dps_delta_pct=divergence.dps_delta_pct,
                noise_floor=divergence.noise_floor,
                exceeds_noise=divergence.exceeds_noise,
            ),
        ),
    )


@router.get("/{context_key}/{er_bucket}", response_model=SimRunRead)
async def get_run(repo: _Repo, context_key: _ContextKeyPath, er_bucket: _ERBucket) -> SimRunRead:
    """One cached run, or a 404 that says which bucket was missing.

    The 404 is the outcome D.3 turns into a stated one: a caller that gets it must simulate
    or say so, and must never widen its search to a neighbouring bucket and report the score
    as though it were this one's.
    """
    if er_bucket % ER_BUCKET_PERCENT != 0:
        # The same value the writer refuses. Letting the reader ask for it would 404 forever:
        # the caller would simulate, store under the bucketed key, ask again with the raw
        # value, miss again, and never see anything but a cold context.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{er_bucket} is not a bucket boundary; buckets are multiples of "
                f"{ER_BUCKET_PERCENT}. Bucket the ER with sim_context.er_bucket() — asking "
                f"for a raw value would miss every time, and look like a cold context."
            ),
        )
    run = await repo.get(
        context_key=context_key, er_bucket=er_bucket, gcsim_pin=pinned_commit(),
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no cached run for ER bucket {er_bucket} of context {context_key[:12]}… at "
                f"pin {pinned_commit()[:12]}. Simulate it; do not substitute another bucket."
            ),
        )
    return SimRunRead.model_validate(run)


@router.post("", response_model=SimRunStored)
@limiter.limit(WRITE_LIMIT)
async def store_run(
    request: Request,  # slowapi reads the client address off it
    repo: _Repo,
    body: SimRunSubmit,
    response: Response,
    gcsim_pin: Annotated[str, Query(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")],
    settings: SettingsDep,
) -> SimRunStored:
    """Cache a run the browser finished.

    The pin is a query parameter rather than a body field so that a client which omits it
    gets a 422 naming it, instead of a body validated against a default nobody chose.
    """
    pin = _require_our_pin(gcsim_pin)
    # **`MAX_SIM_RUNS_PER_DAY` bounds new rows** (security audit F3). Re-storing a run already
    # held replaces it in place, writes no new row, and so is not counted against it.
    held = await repo.get(context_key=body.context_key, er_bucket=body.er_bucket, gcsim_pin=pin)
    if held is None:
        enforce_daily(
            await repo.count_created_since(datetime.now(UTC) - timedelta(days=1)),
            settings.MAX_SIM_RUNS_PER_DAY,
            "Sim run",
        )
    run, created = await repo.store(
        context_key=body.context_key,
        er_bucket=body.er_bucket,
        gcsim_pin=pin,
        result=body.result,
        dps_mean=dps_mean_of(body.result),
        rotation_id=body.rotation_id,
        rotation_signature=body.rotation_signature,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return SimRunStored(run=SimRunRead.model_validate(run), created=created)
