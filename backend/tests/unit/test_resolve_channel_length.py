"""`resolve_channel_length` -- Task 8 of docs/TASKS_channeled_moves.md.

Deliberately the same shape as `resolve_variant_selection`: returns
``(chosen, warning)`` rather than raising for the recoverable cases, because a combo
saved before a move was re-classified must not 400 the whole team-DPS request. An
outage is not a corrected number.

Where it differs from the variant resolver, and why: an unknown `variant_label` is a
hard 404 because no default can repair a step naming a variant that does not exist. An
out-of-range `channel_s` is *not* the same thing -- clamping it yields a real, meaningful
answer (the longest hold the move allows), so it warns instead.
"""

import pytest
from fastapi import HTTPException

from app.data.loaders.moves import ChannelSpec
from app.services.combo_step_resolver import resolve_channel_length

_SPEC = ChannelSpec(
    min_s=0.0, max_s=4.0, default_s=2.0, tick_s=0.5, roles={"Spray Per Sec": "tick"}
)


def test_explicit_value_in_range_passes_through() -> None:
    assert resolve_channel_length("EX", _SPEC, 3.0) == (3.0, None)


def test_missing_value_defaults_with_warning() -> None:
    chosen, warning = resolve_channel_length("EX Special: Spray", _SPEC, None)
    assert chosen == 2.0
    assert warning is not None
    assert "EX Special: Spray" in warning
    assert "2.0" in warning


def test_above_max_clamps_with_warning() -> None:
    chosen, warning = resolve_channel_length("EX", _SPEC, 99.0)
    assert chosen == 4.0
    assert warning is not None
    assert "4.0" in warning


def test_below_min_clamps_with_warning() -> None:
    spec = ChannelSpec(
        min_s=1.0, max_s=4.0, default_s=2.0, tick_s=0.5, roles={"A": "tick"}
    )
    chosen, warning = resolve_channel_length("EX", spec, 0.25)
    assert chosen == 1.0
    assert warning is not None


def test_zero_is_legal_when_min_is_zero() -> None:
    """A tap rather than a hold -- entry + release with no ticks. Not an error."""
    assert resolve_channel_length("EX", _SPEC, 0.0) == (0.0, None)


def test_negative_raises_422() -> None:
    """Unlike an over-long hold, a negative one has no meaningful clamp: it is a
    malformed request, not a stale one."""
    with pytest.raises(HTTPException) as exc:
        resolve_channel_length("EX", _SPEC, -1.0)
    assert exc.value.status_code == 422


def test_nan_raises_422() -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_channel_length("EX", _SPEC, float("nan"))
    assert exc.value.status_code == 422


def test_warning_names_the_move_and_the_substitution() -> None:
    """Matches the existing warning style -- a warning the user cannot act on is noise."""
    _, warning = resolve_channel_length("EX Special Attack: Stirring Method", _SPEC, 10.0)
    assert warning is not None
    assert "EX Special Attack: Stirring Method" in warning
    assert "10" in warning
