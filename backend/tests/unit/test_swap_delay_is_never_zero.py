"""A gcsim config must never say `swap_delay=0`, and this is why.

`docs/RESEARCH_recipe_cost.md` §2. gcsim queues a character swap to land `Delays.Swap` frames
later (`pkg/core/player/exec.go:156`). At **0 the swap never lands** before the next action is
requested, and the run dies with *"requested next char X is not active and next action is not
swap"* — the sanity check at `pkg/simulation/run.go:155`.

`build_config` emitted `swap_delay=0` unconditionally, so **every multi-character rotation this
repo produced was unrunnable**, natively and in the browser alike. Solo rotations never swap,
which is why the sample configs, the crossval fixtures and the compare page all looked healthy
while the feature was broken for every team.

The failure is also **silent in the shape that matters**: it surfaces as an error from
`simulate()`'s *return value*, not as a thrown exception, so a caller that does not check gets
`index out of range [0] with length 0` from `flush()` instead of the real message.
"""

from __future__ import annotations

import types

import pytest

from app.services.gcsim_config import build_config


def _build():
    return types.SimpleNamespace(
        id="b1",
        character=types.SimpleNamespace(
            nanoka_id="10000002", name="Kamisato Ayaka", element="Cryo",
        ),
        weapon=types.SimpleNamespace(name="Mistsplitter Reforged"),
        artifacts=[], character_level=90, constellation_level=0,
        weapon_level=90, refinement=1,
        talent_levels={"normal_attack": 9, "elemental_skill": 9, "elemental_burst": 9},
    )


def test_the_emitted_config_has_an_options_line():
    """Guards the assertions below from passing because nothing was emitted."""
    assert build_config(_build(), actions=["burst"]).startswith("options iteration=")


def test_it_never_emits_swap_delay_zero():
    """The bug. Any explicit zero here makes every team rotation unrunnable."""
    assert "swap_delay=0" not in build_config(_build(), actions=["burst"])


def test_it_does_not_pin_a_swap_delay_at_all():
    """Omitted rather than set to 1.

    gcsim's default is gcsim's answer (`pkg/gcs/parser/parser.go:55`, "default swap timer of
    1"), and a frame count restated here is one this repo would have to defend as game data —
    the same reasoning `PROVENANCE.md` gives for never restating the pin.
    """
    assert "swap_delay" not in build_config(_build(), actions=["burst"])


@pytest.mark.parametrize("iterations", [1, 100, 500])
def test_the_options_line_still_carries_what_it_should(iterations):
    config = build_config(_build(), actions=["burst"], iterations=iterations)

    assert f"iteration={iterations}" in config


def test_the_options_line_pins_no_duration():
    """**`duration` is gone, and its absence is the point.**

    It defaulted to 90 and nothing ever passed anything else, so every rotation this app
    simulated was truncated at ninety seconds by a constant nobody chose — and every DPS figure
    was divided by it. The target now carries `hp=`, which puts gcsim in the mode where a run
    ends when its *actions* do.

    Emitting it anyway would be worse than harmless: in HP mode gcsim **ignores** it, so the
    line would read as a decision and be inert. Measured on the owner's rotation, which reports
    the same 189.3 s whether the config says `duration=90`, `duration=3600` or nothing.
    """
    config = build_config(_build(), actions=["burst"])

    assert "duration" not in config
    assert "hp=999999999" in config
