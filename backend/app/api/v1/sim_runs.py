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

from app.dependencies import get_owned_sim_run_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.repositories.sim_run import SimRunRepository
from app.schemas.sim_run import (
    SimRunCoverage,
    SimRunRead,
    SimRunStored,
    SimRunSubmit,
    dps_mean_of,
)
from app.services.gcsim_keys import pinned_commit
from app.services.sim_context import ER_BUCKET_PERCENT

router = APIRouter(prefix="/sim-runs", tags=["sim-runs"])

_Repo = Annotated[SimRunRepository, Depends(get_owned_sim_run_repo)]
#: The same shape in both places it appears, because a key that is valid as a query
#: parameter and rejected as a path one would be a route-dependent definition of a digest.
_DIGEST = r"^[0-9a-f]{64}$"
_ContextKeyQuery = Annotated[str, Query(min_length=64, max_length=64, pattern=_DIGEST)]
_ContextKeyPath = Annotated[str, Path(min_length=64, max_length=64, pattern=_DIGEST)]
_ERBucket = Annotated[int, Path(ge=0, le=10_000)]


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
) -> SimRunStored:
    """Cache a run the browser finished.

    The pin is a query parameter rather than a body field so that a client which omits it
    gets a 422 naming it, instead of a body validated against a default nobody chose.
    """
    pin = _require_our_pin(gcsim_pin)
    run, created = await repo.store(
        context_key=body.context_key,
        er_bucket=body.er_bucket,
        gcsim_pin=pin,
        result=body.result,
        dps_mean=dps_mean_of(body.result),
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return SimRunStored(run=SimRunRead.model_validate(run), created=created)
