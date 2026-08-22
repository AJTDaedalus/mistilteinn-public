"""Schemas for the run corpus — the browser's simulated runs, and what is already cached.

The browser produces these numbers (DESIGN §3.5: nothing combinatorial lands on the server),
so every field here crosses a trust boundary. The validation below is not politeness about
shapes; each rule closes a way the corpus could go on looking healthy while holding runs that
do not describe what their key claims.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.sim_context import ER_BUCKET_PERCENT

#: A context key is a sha256 hex digest and nothing else. A client that computed its key some
#: other way would write rows nobody can look up and would never hit its own cache.
_CONTEXT_KEY = re.compile(r"^[0-9a-f]{64}$")

#: Bytes of serialised `result` accepted from a client. A gcsim summary is a few KB; this is
#: room for an order of magnitude more, and a refusal for anything using the corpus as
#: storage. JSONB has no natural ceiling of its own, which is the problem.
MAX_RESULT_BYTES = 256 * 1024


class SimRunSubmit(BaseModel):
    """One run the browser finished, offered to the cache."""

    context_key: str
    #: Whole percent, and it must be a bucket boundary — see the validator.
    er_bucket: int = Field(..., ge=0, le=10_000)
    #: What gcsim reported, verbatim. Not interpreted here; §3's error measurement reads it.
    result: dict[str, Any]
    #: Pulled out for the common read. Null is allowed: a context run is wanted for its
    #: uptimes and energy, and one that reports no DPS is still worth caching.
    dps_mean: float | None = None

    @field_validator("context_key")
    @classmethod
    def _is_a_digest(cls, value: str) -> str:
        if not _CONTEXT_KEY.match(value):
            msg = (
                "context_key must be a 64-character lowercase sha256 digest, as produced by "
                "sim_context.context_key. A key computed another way cannot be looked up."
            )
            raise ValueError(msg)
        return value

    @field_validator("er_bucket")
    @classmethod
    def _is_a_bucket_boundary(cls, value: int) -> int:
        """Refuse an ER value that was never bucketed.

        `er_bucket()` rounds **down** on purpose, so a build at 179% is never told about a
        run at 180% that got its burst off. Accepting 179 here would store a row whose key no
        reader ever generates: the writer would fill a cache it could not hit, and the miss
        would look like a cold context rather than a bug.
        """
        if value % ER_BUCKET_PERCENT != 0:
            msg = (
                f"er_bucket must be a multiple of {ER_BUCKET_PERCENT} (whole percent), and "
                f"{value} is not. Bucket the ER with sim_context.er_bucket() rather than "
                f"sending the raw value — it rounds down, and rounding some other way would "
                f"claim burst uptime the build has not earned."
            )
            raise ValueError(msg)
        return value

    @field_validator("result")
    @classmethod
    def _fits(cls, value: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(value, separators=(",", ":")).encode())
        if size > MAX_RESULT_BYTES:
            msg = (
                f"result is {size} bytes; the cache accepts {MAX_RESULT_BYTES}. Submit the "
                f"aggregated statistics, not a per-frame log."
            )
            raise ValueError(msg)
        return value


class SimRunRead(BaseModel):
    """One cached run."""

    id: str
    context_key: str
    er_bucket: int
    gcsim_pin: str
    result: dict[str, Any]
    dps_mean: float | None

    model_config = {"from_attributes": True}


class SimRunCoverage(BaseModel):
    """Which ER buckets this context already has, so a search knows what it must simulate.

    Buckets rather than whole runs: the browser asks this before deciding how much work to
    do, and shipping it every cached `result` to answer "how many" would make the cheap
    question as expensive as the answer it is trying to avoid.
    """

    context_key: str
    gcsim_pin: str
    #: Ascending. `[]` is the honest answer for a cold context and is not an error.
    er_buckets: list[int]
    #: `dps_mean` per cached bucket, aligned with `er_buckets`. Null where the run recorded
    #: none. Enough to see the shape of the ER cliff without fetching every run.
    dps_means: list[float | None]


class SimRunStored(BaseModel):
    """What the write did."""

    run: SimRunRead
    #: False means the same key was already cached and its result was replaced. Two tabs
    #: finishing the same context run is ordinary, so this reports rather than complains.
    created: bool

