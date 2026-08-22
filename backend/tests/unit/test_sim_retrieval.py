"""D.2 — retrieval that reports its own error.

The dangerous shape here is not a missing run. It is a run that is returned confidently for a
build it does not describe, which is why almost every test below is about what the retrieval
*says about itself* rather than which row it picked.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.models.sim_run import SimRun
from app.services.sim_retrieval import MAX_NEIGHBOUR_BUCKETS, retrieve

SWEEP = Path(__file__).resolve().parents[1] / "fixtures" / "er_sweep" / "ayaka_er_sweep.json"


def _run(bucket: int, dps: float | None, *, sd: float = 0.0, iterations: int = 50) -> SimRun:
    result = {"statistics": {"iterations": iterations, "dps": {"mean": dps, "sd": sd}}}
    return SimRun(
        context_key="a" * 64, er_bucket=bucket, gcsim_pin="b" * 40,
        result=result, dps_mean=dps,
    )


# ── Which run comes back ──────────────────────────────────────────────────────


def test_an_exact_bucket_is_matched():
    got = retrieve([_run(175, 100.0), _run(180, 200.0)], 1.82)
    assert got is not None
    assert got.matched_bucket == 180
    assert got.is_exact_bucket
    assert got.bucket_distance == 0


def test_the_nearest_bucket_is_matched_when_the_exact_one_is_absent():
    got = retrieve([_run(175, 100.0), _run(190, 300.0)], 1.81)
    assert got is not None
    assert got.matched_bucket == 175, "180 is absent; 175 is one bucket away and 190 is two"
    assert got.bucket_distance == 1
    assert not got.is_exact_bucket


def test_a_distant_neighbour_is_refused_rather_than_offered():
    """DESIGN §3.5: never retrieve a distant neighbour and report it as though it were close."""
    assert retrieve([_run(100, 100.0)], 1.80) is None


def test_the_refusal_boundary_is_the_stated_constant():
    """One bucket away is offered; one further is not — pinned to the constant, not to 5."""
    from app.services.sim_context import ER_BUCKET_PERCENT

    allowed = 180 - ER_BUCKET_PERCENT * MAX_NEIGHBOUR_BUCKETS
    too_far = allowed - ER_BUCKET_PERCENT
    assert retrieve([_run(allowed, 100.0)], 1.80) is not None
    assert retrieve([_run(too_far, 100.0)], 1.80) is None


def test_an_empty_corpus_retrieves_nothing():
    assert retrieve([], 1.80) is None


def test_a_tie_between_neighbours_is_broken_toward_the_lower_bucket():
    """175 and 185 are both one bucket from 180, and the tie is not broken arbitrarily.

    Down, for the same reason `er_bucket` rounds down: the higher neighbour is a run that got
    its burst off when this build may not, so breaking the tie upward would hand out uptime
    the build has not earned.
    """
    picks = {retrieve([_run(185, 2.0), _run(175, 1.0)], 1.80).matched_bucket for _ in range(5)}
    assert picks == {175}


# ── What it says about itself ─────────────────────────────────────────────────


def test_an_exact_bucket_still_reports_a_divergence():
    """The key matched. The answer is still an approximation — RESEARCH_er_bucketing §1.

    A build at 182% ER and a run simulated at some point inside bucket 180 are not the same
    build, and inside the steepest bucket the research doc measured that is worth 13%.
    """
    got = retrieve([_run(180, 100.0), _run(185, 113.0)], 1.82)
    assert got.is_exact_bucket
    assert got.divergence is not None, "an exact key match is not an exact answer"
    assert got.divergence.reference_bucket == 185
    assert got.divergence.dps_delta == pytest.approx(13.0)
    assert got.divergence.dps_delta_pct == pytest.approx(13.0)


def test_only_immediate_neighbours_are_used_as_a_reference():
    """A bucket four away describes a different part of the curve.

    Letting it stand in for the local gradient would report the shape of the whole sweep as
    though it were this neighbourhood's uncertainty — a big, confident, irrelevant number.
    """
    got = retrieve([_run(180, 100.0), _run(185, 110.0), _run(200, 5000.0)], 1.80)
    assert got.divergence.reference_bucket == 185
    assert got.divergence.dps_delta == pytest.approx(10.0)


def test_a_context_with_no_immediate_neighbour_reports_no_divergence():
    got = retrieve([_run(180, 100.0), _run(195, 500.0)], 1.80)
    assert got is not None
    assert got.divergence is None, "195 is three buckets away and says nothing about 180"


def test_the_reference_is_the_neighbour_that_moved_most_not_the_nearest():
    """RESEARCH_er_bucketing — the nearest neighbour of bucket 120 sees a third of the truth.

    A build sits *above* its bucket floor, so the upward neighbour is usually the informative
    one. Taking the largest movement gets that without reasoning about which side it is on.
    """
    got = retrieve([_run(175, 96.3), _run(180, 100.0), _run(185, 108.2)], 1.80)
    assert got.divergence.reference_bucket == 185
    assert got.divergence.dps_delta_pct == pytest.approx(8.2)


def test_a_lone_run_reports_no_divergence_rather_than_zero():
    """"Nothing to compare against" and "the comparison came out at zero" are different.

    Merging them is precisely how an approximation stops reporting its own error.
    """
    got = retrieve([_run(180, 100.0)], 1.80)
    assert got is not None
    assert got.divergence is None


def test_the_noise_floor_combines_both_runs_in_quadrature():
    """Summing the errors linearly would overstate the floor and hide real divergences."""
    got = retrieve([_run(180, 100.0, sd=70.7), _run(185, 110.0, sd=70.7)], 1.80)
    each = 70.7 / math.sqrt(50)
    assert got.divergence.noise_floor == pytest.approx(math.hypot(each, each))
    assert got.divergence.noise_floor < each * 2


def test_a_divergence_under_the_noise_floor_is_flagged_as_such():
    got = retrieve([_run(180, 1000.0, sd=700.0), _run(185, 1001.0, sd=700.0)], 1.80)
    assert not got.divergence.exceeds_noise
    assert got.divergence.dps_delta == pytest.approx(1.0), "and it is still reported"


def test_a_run_that_reports_no_spread_gets_an_optimistic_floor():
    """Unknown noise must not read as "no divergence" — it sends the reader to look."""
    got = retrieve([_run(180, 100.0), _run(185, 110.0)], 1.80)
    assert got.divergence.noise_floor == 0.0
    assert got.divergence.exceeds_noise


def test_a_run_with_no_dps_yields_no_divergence():
    """A context run cached for its uptimes has no headline number to diverge."""
    assert retrieve([_run(180, None), _run(185, 110.0)], 1.80).divergence is None
    assert retrieve([_run(180, 100.0), _run(185, None)], 1.80).divergence is None


# ── Against the measured sweep ────────────────────────────────────────────────


def _sweep() -> list[dict]:
    return json.loads(SWEEP.read_text())["runs"]


def test_the_committed_sweep_is_from_the_pin():
    from app.services.gcsim_keys import pinned_commit

    assert json.loads(SWEEP.read_text())["sim_version"] == pinned_commit()


def test_the_sweep_shows_the_invariant_parts_of_context_are_exactly_invariant():
    """RESEARCH_er_bucketing §1 — skill casts and aura uptime do not move with ER at all.

    This is the part of the §3 assumption that holds outright, and the reason retrieving a
    neighbour is worth doing rather than always simulating.
    """
    runs = _sweep()
    assert len({r["skill_casts"] for r in runs}) == 1
    assert len({r["attack_casts"] for r in runs}) == 1
    assert len({round(r["cryo_aura_uptime"], 6) for r in runs}) == 1


def test_the_sweep_shows_a_five_percent_bucket_is_not_uniformly_safe():
    """RESEARCH_er_bucketing §3 — the counterexample that made this module report per-context.

    If this ever stops holding, the constant-error shortcut this module refuses to take
    becomes defensible, and that is a change worth noticing rather than inheriting.
    """
    runs = {r["er_percent"]: r for r in _sweep()}
    spreads = {}
    for low in range(100, 155, 5):
        inside = [runs[er]["dps_mean"] for er in range(low, low + 5) if er in runs]
        if len(inside) > 1:
            spreads[low] = max(inside) / min(inside) - 1.0

    assert max(spreads.values()) > 0.10, "no bucket is wide; a flat error would be defensible"
    assert min(spreads.values()) < 0.02, "every bucket is wide; the width itself is the bug"
    assert spreads[120] == max(spreads.values()), "the widest bucket is the burst-count climb"


def test_retrieval_over_the_real_sweep_reports_the_wide_bucket_as_wide():
    """The end-to-end claim: a build in bucket 120 is told its neighbourhood is uncertain."""
    runs = {r["er_percent"]: r for r in _sweep()}
    cached = [
        _run(bucket, runs[bucket]["dps_mean"], sd=runs[bucket]["dps_sd"],
             iterations=runs[bucket]["iterations"])
        for bucket in (115, 120, 125)
    ]

    wide = retrieve(cached, 1.22)
    assert wide.matched_bucket == 120
    assert wide.divergence.exceeds_noise
    assert abs(wide.divergence.dps_delta_pct) > 5.0

    settled = retrieve(
        [
            _run(b, runs[b]["dps_mean"], sd=runs[b]["dps_sd"], iterations=runs[b]["iterations"])
            for b in (145, 150)
        ],
        1.50,
    )
    assert abs(settled.divergence.dps_delta_pct) < abs(wide.divergence.dps_delta_pct), (
        "the settled part of the curve must look calmer than the transition band"
    )
