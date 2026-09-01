"""The window a rotation is simulated over is stated once.

`build_config` runs a calibration for `duration` seconds, defaulting to 90. `/calculate`
divides by that window to show DPS beside gcsim's own figure — so the number lives in two
places, and **a DPS figure divided by the wrong window is wrong in a way nothing on screen
would show**: it is a plausible number, in the right units, off by a ratio.

This is the same shape as the gcsim pin living in a build script (`test_gcsim_pin_is_single`)
and the Go toolchain living in a Dockerfile (`test_prod_go_satisfies_the_gcsim_pin`). Both of
those drifted and were found by something breaking.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from app.services.gcsim_config import build_config

REPO = Path(__file__).resolve().parents[3]
CALCULATE = REPO / "frontend" / "src" / "app" / "pages" / "calculate" / "calculate.ts"


def _default_duration() -> int:
    """`build_config`'s own default, read off the signature rather than repeated."""
    default = inspect.signature(build_config).parameters["duration"].default
    assert isinstance(default, int), "build_config no longer defaults its duration"
    return default


def _frontend_seconds() -> int:
    match = re.search(r"^const ROTATION_SECONDS = (\d+);", CALCULATE.read_text(), re.M)
    assert match, "calculate.ts no longer declares ROTATION_SECONDS"
    return int(match.group(1))


def test_the_page_divides_by_the_window_the_config_uses() -> None:
    assert _frontend_seconds() == _default_duration(), (
        f"/calculate divides by {_frontend_seconds()}s but calibrations run for "
        f"{_default_duration()}s. The DPS shown would be off by that ratio, and it would look "
        f"like an ordinary number."
    )
