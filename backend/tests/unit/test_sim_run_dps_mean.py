"""`dps_mean_of` — the one number the run corpus pulls out of a submitted payload.

**There were no tests for this function, and that is why it was wrong.** It read
`statistics.dps.mean`, taken from `tests/fixtures/crossval/ayaka_normal_1.json`, which is a
**native gcsim CLI** run. The only client that will ever submit to this cache is the browser,
and the browser's wasm build returns `{"stats": {…}}` — a different top-level key and nothing
else beside it.

So every submission would have been accepted and stored with `dps_mean = NULL`: a corpus that
filled up and still sorted nothing. It fails in the direction nobody checks, because the row is
there and the endpoint returns 201.

Found by building the producer, not by reading. These tests pin both shapes with the evidence
for each.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.sim_run import dps_mean_of

#: A native CLI run, committed. Its top level is `statistics`.
_NATIVE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "crossval" / "ayaka_normal_1.json"
)


def test_the_native_cli_shape_is_read() -> None:
    """Not a hand-written dict: the committed crossval fixture, which is what the native
    binary actually wrote. If gcsim ever moves this key, this fails against real output."""
    native = json.loads(_NATIVE.read_text())

    assert native["statistics"]["dps"]["mean"] == dps_mean_of(native)
    assert dps_mean_of(native) is not None


def test_the_browsers_shape_is_read() -> None:
    """**The shape that actually matters, because the browser is the only producer.**

    Transcribed from driving the committed `gcsim/gcsim.wasm` through
    `initializeAggregator → simulate → aggregate → flush`, which returns exactly one top-level
    key. The `dps` block inside is identical to the native one; only the root differs.
    """
    from_wasm = {
        "stats": {
            "dps": {
                "min": 21.706079870465302, "max": 21.706079870465302,
                "mean": 21.706079870465302, "sd": 0,
            },
            "character_actions": [
                {"sources": {"attack": {"min": 1, "max": 1, "mean": 1, "sd": 0}}},
            ],
        },
    }

    assert dps_mean_of(from_wasm) == 21.706079870465302


def test_a_payload_with_no_dps_block_is_none_rather_than_zero() -> None:
    """A context run is wanted for its uptimes and energy, and one reporting no DPS is still
    worth caching — but "no DPS reported" and "a DPS of zero" are different claims."""
    assert dps_mean_of({"stats": {"duration": {"mean": 90}}}) is None
    assert dps_mean_of({}) is None


def test_a_dps_of_zero_survives_as_zero() -> None:
    """The other half of the same distinction. A rotation that never connects is a real
    answer, and `or None`-style falsiness would erase it."""
    assert dps_mean_of({"stats": {"dps": {"mean": 0}}}) == 0.0


def test_a_boolean_is_not_a_number() -> None:
    """`isinstance(True, int)` is True in Python, so a payload carrying `"mean": true` would
    otherwise be stored as a DPS of 1.0 — a plausible figure invented from a type error."""
    assert dps_mean_of({"stats": {"dps": {"mean": True}}}) is None


def test_a_ragged_payload_does_not_raise() -> None:
    """Submissions cross a trust boundary: the browser produces them and a tampered client can
    send anything. Every one of these is a refusal, not a 500."""
    for ragged in (
        {"stats": "not a dict"},
        {"stats": {"dps": "not a dict"}},
        {"stats": {"dps": []}},
        {"statistics": None},
    ):
        assert dps_mean_of(ragged) is None
