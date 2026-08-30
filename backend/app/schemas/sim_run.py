"""Schemas for the run corpus — the browser's simulated runs, and what is already cached.

The browser produces these numbers (DESIGN §3.5: nothing combinatorial lands on the server),
so every field here crosses a trust boundary. The validation below is not politeness about
shapes; each rule closes a way the corpus could go on looking healthy while holding runs that
do not describe what their key claims.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    #: What gcsim reported, verbatim. §3's error measurement reads it.
    #:
    #: There is deliberately **no `dps_mean` field here**. The headline number is *derived*
    #: from this payload by `dps_mean_of()`, not submitted alongside it: a client that sent
    #: both could send a mean that disagrees with the run it claims to summarise, and a
    #: cache whose headline figure refers to something other than its body is the precise
    #: failure this project keeps meeting. Two fields that can disagree are worse than one
    #: field that can be absent.
    result: dict[str, Any]
    #: Which rotation this run simulated, when the client knows. **Optional and unverified**,
    #: which is safe because it is a label and not key material: a client that lies about it
    #: mislabels its *own* rows, in its own owner-scoped cache, and the worst outcome is a
    #: number sorted under the wrong rotation for the person who sent it.
    #:
    #: The server does not derive it, because it cannot: `context_key` is a hash and the
    #: rotation is the client's to name.
    rotation_id: str | None = None
    #: The rotation as it was, hashed. Sent with `rotation_id` or not at all — a label saying
    #: *which* rotation without saying *which version* is the one that would let a stale
    #: number be shown as current.
    rotation_signature: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _labels_travel_together(self) -> SimRunSubmit:
        """Both or neither.

        A `rotation_id` with no signature is precisely the state that lets an edited
        rotation be sorted by a number computed for its previous version — the failure the
        second column exists to prevent. Refusing the pair is cheaper than teaching every
        reader to check for it.
        """
        if (self.rotation_id is None) != (self.rotation_signature is None):
            msg = (
                "rotation_id and rotation_signature travel together. One without the other "
                "labels a run with a rotation but not with which version of it, which is how "
                "a stale number gets shown as current."
            )
            raise ValueError(msg)
        return self

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


#: Where gcsim's summary puts the mean DPS — **under either of two different top-level keys.**
#:
#: The native CLI writes `statistics`; the browser's wasm build writes `stats`, and nothing
#: else at the top level. That is not a guess: `tests/fixtures/crossval/ayaka_normal_1.json` is
#: a native run and carries `statistics`, and driving the committed `gcsim.wasm` through
#: `flush()` returns `{"stats": {…}}` with the identical `dps` block inside.
#:
#: **This mattered, and it was found by building the producer rather than by reading.** The
#: only client that will ever write to this cache is the browser, so a path that reads only
#: `statistics` would have accepted every submission and stored `dps_mean = NULL` on all of
#: them — a corpus that filled up and still sorted nothing, failing in the one direction
#: nobody would look.
_DPS_MEAN_ROOTS = ("statistics", "stats")
_DPS_MEAN_TAIL = ("dps", "mean")


def dps_mean_of(result: dict[str, Any]) -> float | None:
    """The run's headline DPS, or None when the payload does not carry one.

    None rather than zero. A context run is wanted for its uptimes and energy, and one that
    reports no DPS is still worth caching — but "no DPS reported" and "a DPS of zero" are
    different claims and a cache should not merge them.

    Both roots are read rather than one being normalised on the way in, because the payload is
    stored **verbatim** — §3's error measurement reads it, and rewriting a client's submission
    to fit a reader would make the stored artifact something gcsim never produced.
    """
    for root in _DPS_MEAN_ROOTS:
        node: Any = result.get(root)
        for step in _DPS_MEAN_TAIL:
            if not isinstance(node, dict) or step not in node:
                node = None
                break
            node = node[step]
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return float(node)
    return None


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


class DivergenceRead(BaseModel):
    """How much substituting a neighbouring bucket appears to cost, and the noise under it.

    Both numbers, never one verdict. `docs/RESEARCH_er_bucketing.md` records the significance
    test that flagged a bucket where no context change was possible — burst casts are
    discrete, so per-iteration DPS is a multi-modal mixture and `sd/√n` understates it. A test
    that misfired on its first dataset is not a test to hide a number behind.
    """

    reference_bucket: int
    dps_delta: float
    dps_delta_pct: float
    noise_floor: float
    #: A hint that the delta is larger than the two runs' combined standard error. **Not** a
    #: significance test — see above.
    exceeds_noise: bool


class RetrievalRead(BaseModel):
    """A run, and everything needed to judge whether it should have been used."""

    run: SimRunRead
    requested_bucket: int
    matched_bucket: int
    bucket_distance: int
    #: The *key* matched. Not the same as the answer being exact: the run was simulated at one
    #: point inside a 5% band and the build sits at another, which
    #: `docs/RESEARCH_er_bucketing.md` measured at up to 13.3% in the steepest bucket.
    is_exact_bucket: bool
    #: Null when the corpus holds no immediate neighbour to measure against. Absent, not
    #: zero — "no comparison was possible" and "the comparison came out at zero" are
    #: different claims, and merging them is how an approximation stops reporting its error.
    divergence: DivergenceRead | None


#: Why nothing was retrieved. Two values rather than one because they call for **different
#: actions**: `cold` means simulate the buckets this search needs, `too_far` means simulate
#: this one. Collapsing them would leave the caller guessing how much work it is in for.
NOT_RETRIEVED_COLD = "cold"
NOT_RETRIEVED_TOO_FAR = "too_far"


class RetrievalOutcome(BaseModel):
    """What retrieval found, **or did not** — always a 200, never a 404.

    DESIGN §3.5: *"A search can still arrive with no cached context. That must be a stated
    outcome, not a silent fallback: simulate it now (a second or two), or say so. It must
    never be to retrieve a distant neighbour and report its score as though it were close."*

    A 404 would be the wrong shape for the second half of that. "Nothing close enough is
    cached" is an **answer** — the caller acts on it by simulating — and dressing it as an
    error invites the two reflexes an error provokes: retry it, or catch it and carry on with
    whatever value was already in hand. The first wastes a round trip; the second is the
    silent fallback this rule exists to forbid.

    So the outcome is always 200 and `retrieved` is either present or explicitly null with a
    reason beside it. A client cannot read this response and fail to notice which it got.
    """

    context_key: str
    gcsim_pin: str
    #: The bucket the build falls in — reported whether or not anything was found, because it
    #: is what the caller must simulate if nothing was.
    requested_bucket: int
    retrieved: RetrievalRead | None
    #: `None` when something was retrieved. One of the two constants above otherwise.
    not_retrieved_because: Literal["cold", "too_far"] | None = None
    #: Prose for a human reading a log or a UI. Null when something was retrieved.
    detail: str | None = None


class SimRunStored(BaseModel):
    """What the write did."""

    run: SimRunRead
    #: False means the same key was already cached and its result was replaced. Two tabs
    #: finishing the same context run is ordinary, so this reports rather than complains.
    created: bool

