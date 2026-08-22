"""Retrieving a simulated run for a build, and saying how far the answer is from the truth.

DESIGN §3 sets the rule this module exists to keep:

> A score built on retrieved context ships with the measured error for its neighbourhood, or
> it does not ship. [...] A *retrieved* damage number must additionally be able to say what
> it was retrieved from and how far that neighbour was.

So `retrieve()` never returns a run on its own. It returns the run **together with** what was
asked for, what was matched, and how much the substitution appears to cost.

## An exact bucket hit is not an exact answer

The subtle part, and the one a distance counter alone would hide. Buckets are 5 % wide. A
build at 122 % ER matching the run cached at bucket 120 is a *distance-zero* match, and it is
still an approximation: the run was simulated at one point inside a 5 % band and the build
sits at another.

`docs/RESEARCH_er_bucketing.md` measured how much that is worth. Across 54 gcsim runs at the
pin, one per whole ER percent, DPS inside bucket 120 ranges **13.3 %** — that bucket straddles
the steepest part of the burst-count climb — while buckets away from the transition sit at
the noise floor. So the cost of a distance-zero match is anywhere from nothing to 13 %
depending on *which* bucket, which is why this reports a divergence even when the key matched
exactly.

## Where the error number comes from, and what it is *not*

**From the corpus, not from a constant.** The immediate neighbours of the matched bucket say
how fast the answer is moving in this part of the curve, measured in the user's own context
rather than read off the one character the research doc swept. It needs no extra simulation:
the runs are already there, because a search caches one per ER bucket anyway.

**It is a lower bound on the uncertainty, and the docstring has to say so**, because the
first version of this code quietly implied otherwise. Measured against the sweep, for a build
in bucket 120:

| | |
|---|---|
| true spread inside bucket 120 | **13.3 %** |
| delta to neighbour 115 | −3.7 % |
| delta to neighbour 125 | +8.2 % |

The nearest neighbour is 115 and it reports 3.7 % — a third of the real uncertainty, because
the curve is steep in the *upper* half of the bucket and the downward neighbour cannot see
that. So the reference is the **largest** movement among the immediate neighbours rather than
the nearest one: 8.2 % here, still short of 13.3 %, and the honest description of the number
is *"the fastest the answer is moving nearby"* — not *"the most this can be wrong"*.

Closing that remaining gap needs a run *inside* the bucket, which is a simulation the search
was trying to avoid. Reporting the bound that is affordable, and saying which bound it is, is
the alternative to reporting nothing.

## Why it reports two numbers and not a verdict

Every run carries Monte Carlo noise, and a divergence below that noise is not a divergence.
The obvious move is to threshold on the standard error and pronounce — and that is exactly
what the research doc caught being wrong. A 3.4×-se "significant" divergence appeared in a
bucket where the burst count was flat and no context change was possible, because burst casts
are discrete, so per-iteration DPS is a multi-modal mixture and `sd/√n` understates it.

A test that produced a false positive on the first dataset it saw is not a test to hide a
number behind. `Divergence` therefore carries both the delta and the noise floor and lets the
reader see them together.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.sim_context import ER_BUCKET_PERCENT, er_bucket

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.sim_run import SimRun

#: How many buckets away a run may be and still be offered. One bucket is already worth up to
#: the full within-bucket spread the research doc measured; two compounds it with nothing
#: bounding the middle. Beyond this, retrieval returns nothing and the caller simulates —
#: DESIGN §3.5: "It must never be to retrieve a distant neighbour and report its score as
#: though it were close."
MAX_NEIGHBOUR_BUCKETS = 1


@dataclass(frozen=True, slots=True)
class Divergence:
    """What substituting a neighbouring bucket appears to cost, and the noise under it."""

    #: The bucket this was measured against — the immediate neighbour that moved **most**,
    #: not the nearest one. See the module docstring: the nearest neighbour of bucket 120
    #: reports a third of the real within-bucket spread, because the curve is steep in the
    #: half of the bucket that neighbour cannot see.
    reference_bucket: int
    #: Signed, in DPS. Positive means the reference run scores higher than the matched one.
    dps_delta: float
    #: The same as a percentage of the matched run's DPS.
    dps_delta_pct: float
    #: Combined Monte Carlo standard error of the two runs, in DPS. A delta near or below
    #: this is not evidence of anything — see the module docstring on why there is no
    #: threshold here doing that judgement for the reader.
    noise_floor: float

    @property
    def exceeds_noise(self) -> bool:
        """True when the delta is larger than the two runs' combined standard error.

        Deliberately *not* a significance test, and deliberately not used to suppress the
        number. It is a hint that the reader should look, in a codebase where the same
        arithmetic already produced a false positive.
        """
        return abs(self.dps_delta) > self.noise_floor


@dataclass(frozen=True, slots=True)
class Retrieval:
    """One run, and everything needed to judge whether it should have been used."""

    run: SimRun
    #: The bucket the build actually falls in.
    requested_bucket: int
    #: The bucket that was found. Equal to `requested_bucket` on an exact match.
    matched_bucket: int
    #: `None` when the corpus holds only this one run for the context, so there is nothing to
    #: measure the error against. Absent, not zero: "no comparison was possible" and "the
    #: comparison came out at zero" are different claims and merging them is how an
    #: approximation stops reporting its own error.
    divergence: Divergence | None

    @property
    def bucket_distance(self) -> int:
        """How many whole buckets away the match is. Zero is still an approximation."""
        return abs(self.matched_bucket - self.requested_bucket) // ER_BUCKET_PERCENT

    @property
    def is_exact_bucket(self) -> bool:
        """The *key* matched. This is not the same as the answer being exact — see above."""
        return self.matched_bucket == self.requested_bucket


def _standard_error(run: SimRun) -> float:
    """`sd/√n` from what gcsim reported, or 0.0 when the run does not say.

    Zero for an unknown noise floor makes `exceeds_noise` optimistic rather than silently
    permissive-looking: a divergence then always reads as exceeding it, which sends the reader
    to look at a run that did not report its own spread.
    """
    stats = (run.result or {}).get("statistics")
    if not isinstance(stats, dict):
        return 0.0
    dps = stats.get("dps")
    iterations = stats.get("iterations")
    if not isinstance(dps, dict) or not isinstance(iterations, int) or iterations < 1:
        return 0.0
    sd = dps.get("sd")
    if not isinstance(sd, (int, float)) or isinstance(sd, bool):
        return 0.0
    return float(sd) / math.sqrt(iterations)


def _divergence(matched: SimRun, others: Sequence[SimRun]) -> Divergence | None:
    """Measure the matched run against whichever immediate neighbour moved most.

    Immediate only — a bucket four away describes a different part of the curve, and letting
    it stand in for the local gradient would report the shape of the whole sweep as though it
    were this neighbourhood's uncertainty.
    """
    if matched.dps_mean is None:
        return None
    neighbours = [
        run
        for run in others
        if run.er_bucket != matched.er_bucket
        and abs(run.er_bucket - matched.er_bucket) <= ER_BUCKET_PERCENT
        and run.dps_mean is not None
    ]
    if not neighbours:
        return None
    # The largest movement, not the nearest bucket. A build sits *above* its bucket floor, so
    # the upward neighbour is usually the informative one, and taking the max gets that
    # without having to reason about which side the build is on.
    nearest = max(neighbours, key=lambda run: abs(run.dps_mean - matched.dps_mean))

    delta = nearest.dps_mean - matched.dps_mean
    # Errors add in quadrature: two independent runs each carry their own, and summing them
    # linearly would overstate the floor and hide real divergences behind it.
    floor = math.hypot(_standard_error(matched), _standard_error(nearest))
    pct = (delta / matched.dps_mean * 100.0) if matched.dps_mean else 0.0
    return Divergence(
        reference_bucket=nearest.er_bucket,
        dps_delta=delta,
        dps_delta_pct=pct,
        noise_floor=floor,
    )


def retrieve(runs: Sequence[SimRun], energy_recharge: float) -> Retrieval | None:
    """The best cached run for a build at `energy_recharge`, or None if none is close enough.

    `runs` is every cached run for one context at one pin — what `SimRunRepository.get_buckets`
    returns. A pure function over them, so the decision can be tested without a database and
    reused by anything that already holds the runs.

    Returns `None` when the corpus is empty or its nearest bucket is further than
    `MAX_NEIGHBOUR_BUCKETS`. That is not an error and not a fallback: D.3 turns it into a
    stated outcome, and the caller simulates rather than being handed a distant neighbour.
    """
    if not runs:
        return None

    wanted = er_bucket(energy_recharge)
    # Nearest bucket, and on a tie the **lower** one. Same reasoning as `er_bucket` rounding
    # down: a build offered the higher neighbour is being shown a run that got its burst off
    # when this one may not, and a tie should not be broken toward the optimistic side.
    matched = min(runs, key=lambda run: (abs(run.er_bucket - wanted), run.er_bucket))
    distance = abs(matched.er_bucket - wanted) // ER_BUCKET_PERCENT
    if distance > MAX_NEIGHBOUR_BUCKETS:
        return None

    return Retrieval(
        run=matched,
        requested_bucket=wanted,
        matched_bucket=matched.er_bucket,
        divergence=_divergence(matched, runs),
    )
