"""Banner pity curves and featured-item rates, read from the cited data file.

`app/data/wishes/banner_rates.json` is hand-maintained and every numeric entry there is
required to carry a `source`. Nothing in this module invents a rate: a banner this file does
not describe raises rather than falling back to a plausible default, which is the same rule
`app/services/planner/economy.py` follows for resin.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parents[2] / "data" / "wishes" / "banner_rates.json"


class BannerKind(StrEnum):
    """Which limited banner is being planned for."""

    CHARACTER = "character"
    WEAPON = "weapon"


@dataclass(frozen=True, slots=True)
class BannerRates:
    """One banner's pity curve and featured-item rate.

    `soft_pity_start` and `increase_rate` are jointly fitted to the published consolidated
    rate and are **not** separately identified — see the note in the data file. They pin the
    centre of the distribution exactly and the far tail not at all, so `published_worst_case`
    rather than this curve answers "how bad can it get".
    """

    hard_pity: int
    soft_pity_start: int
    base_rate: float
    increase_rate: float
    #: Chance a 5-star is the one wanted, with no guarantee and no radiance banked.
    featured_rate: float
    #: Whether Capturing Radiance replaces `featured_rate` at radiance 0. Character only.
    capturing_radiance: bool
    #: The largest number of wishes HoYoverse advertises may be needed.
    published_worst_case: int

    def drop_curve(self) -> list[float]:
        """Per-pull 5-star rate for pity 1..hard_pity, ending in 1.0.

        Flat at `base_rate` below `soft_pity_start`, then `base_rate + n * increase_rate`
        clamped to 1.0. The clamp can reach certainty before `hard_pity` — the weapon curve
        does, at pity 77 — and that is the fitted curve rather than the game.
        """
        curve: list[float] = []
        for pity in range(1, self.hard_pity + 1):
            if pity >= self.hard_pity:
                curve.append(1.0)
            elif pity < self.soft_pity_start:
                curve.append(self.base_rate)
            else:
                steps = pity - self.soft_pity_start + 1
                curve.append(min(1.0, self.base_rate + steps * self.increase_rate))
        return curve


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


@cache
def rates_for(banner: BannerKind) -> BannerRates:
    """Return the cited rates for `banner`.

    Raises:
        KeyError: If the data file does not describe this banner. Deliberately not a
            fallback: an uncited curve would produce a number indistinguishable from a
            real one.
    """
    entry = _raw()[banner.value]
    return BannerRates(
        hard_pity=int(entry["hard_pity"]),
        soft_pity_start=int(entry["soft_pity_start"]),
        base_rate=float(entry["base_rate"]),
        increase_rate=float(entry["increase_rate"]),
        featured_rate=float(entry["featured_rate"]),
        capturing_radiance=bool(entry["capturing_radiance"]),
        published_worst_case=int(entry["published_worst_case"]),
    )


@lru_cache(maxsize=1)
def radiance_win_rates() -> tuple[float, ...]:
    """50/50 win rate indexed by 50/50s lost since the last *won* one.

    The last entry is 1.0: four consecutive losses are impossible, which is also what makes
    the counter terminate.
    """
    return tuple(float(v) for v in _raw()["capturing_radiance_win_rates"]["values"])


@lru_cache(maxsize=1)
def primogems_per_wish() -> int:
    """Primogems in one wish. Acquaint Fate is not counted — it buys the standard banner."""
    return int(_raw()["primogems_per_wish"]["value"])
