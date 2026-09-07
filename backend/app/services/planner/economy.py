"""The planner's price list: what things cost, and what a resin run yields.

Two files back this module and the split between them is the point.

* `app/data/yuanshen/snapshot/planner_economy.json` is **derived** from the pinned dump by
  `scripts/yuanshen/build_snapshot.py` — material icons and rarities, the ascension level
  caps, the EXP denominations, the crafting tree, resin cost per source, the domain weekday
  rotation, and the expected drops the game actually publishes.
* `app/data/planner/curated_rates.json` is **hand-maintained** — the twelve drop rates no
  table publishes plus the two mora-per-EXP divisors, each required to cite a source.

**A missing rate is reported, never invented.** `resin_for` returns `None` when nothing
prices a material, and every caller carries that `None` through to the UI. The alternative —
substituting an average — would produce a resin figure indistinguishable from a real one,
which is the failure this repository keeps a whole section of `CLAUDE.md` about.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "yuanshen" / "snapshot"
_CURATED = Path(__file__).resolve().parents[2] / "data" / "planner"


@dataclass(frozen=True)
class ExpItem:
    """One EXP denomination — Hero's Wit, Mystic Enhancement Ore, and their smaller siblings."""

    id: int
    exp: int
    rarity: int


@dataclass(frozen=True)
class DropRate:
    """What one resin run is expected to yield of a material.

    `expected_per_run` is a **mean**, never a guarantee: nothing in the pinned dump resolves
    a `drop_id`, so the true distribution is not available at any price. `curated` says
    whether the number came from the game's own reward preview or from a human.
    """

    material_id: int
    source_type: str
    resin: int
    expected_per_run: float
    curated: bool


@dataclass(frozen=True)
class CraftStep:
    """One rung of the crafting ladder.

    `input_count` of `input` makes `output_count`, and costs `mora`.
    """

    input: int
    input_count: int
    output_count: int
    mora: int


class Economy:
    """The loaded price list. Built once and cached; nothing here touches the network."""

    def __init__(self, derived: dict[str, Any], curated: dict[str, Any]) -> None:
        self._derived = derived
        self._curated = curated
        self.mora_item_id: int = derived["mora_item_id"]
        self.resin_item_id: int = derived["resin_item_id"]
        self.character_level_caps: dict[int, int] = {
            int(k): v for k, v in derived["level_caps"]["character"].items()
        }
        self.weapon_level_caps: dict[int, int] = {
            int(k): v for k, v in derived["level_caps"]["weapon"].items()
        }
        self.character_exp_items: tuple[ExpItem, ...] = tuple(
            ExpItem(**item) for item in derived["exp_items"]["character"]
        )
        self.weapon_exp_items: tuple[ExpItem, ...] = tuple(
            ExpItem(**item) for item in derived["exp_items"]["weapon"]
        )
        self._meta: dict[int, dict[str, Any]] = {
            int(k): v for k, v in derived["material_meta"].items()
        }
        self._combine: dict[int, CraftStep] = {
            int(k): CraftStep(**v) for k, v in derived["combine"].items()
        }
        self._domain_days: dict[int, list[str]] = {
            int(k): v for k, v in derived["domain_days"].items()
        }
        self._rates: dict[int, DropRate] = {}
        for key, rec in derived["drop_rates"].items():
            self._rates[int(key)] = DropRate(
                material_id=int(key),
                source_type=rec["source"],
                resin=rec["resin"],
                expected_per_run=rec["expected_per_run"],
                curated=False,
            )
        for key, rec in curated["drop_rates"].items():
            if rec.get("expected_per_run") is None:
                continue
            self._rates.setdefault(
                int(key),
                DropRate(
                    material_id=int(key),
                    source_type=rec["source_type"],
                    resin=rec["resin"],
                    expected_per_run=float(rec["expected_per_run"]),
                    curated=True,
                ),
            )

    # -- materials ------------------------------------------------------------------

    def icon(self, material_id: int) -> str | None:
        """The material's icon basename, e.g. `UI_ItemIcon_104161`.

        Cited to `MaterialExcelConfigData.icon` rather than assembled from the id — the
        convention holds for every material checked, but `download_icons.py`'s rule is that
        this code does not invent a basename.
        """
        meta = self._meta.get(material_id)
        return meta["icon"] if meta else None

    def rarity(self, material_id: int) -> int | None:
        """The material's star rating, cross-checked against nanoka's `rank` at seed time."""
        meta = self._meta.get(material_id)
        return meta["rarity"] if meta else None

    def domain_days(self, material_id: int) -> list[str]:
        """The weekdays this material's domain is open, or `[]` if it is not a domain drop."""
        return list(self._domain_days.get(material_id, ()))

    # -- crafting -------------------------------------------------------------------

    def craft_step(self, material_id: int) -> CraftStep | None:
        """How this material is crafted from the tier below, if it is."""
        return self._combine.get(material_id)

    def craft_root(self, material_id: int) -> int:
        """Walk down the crafting ladder to the tier that is actually farmed.

        A domain drops several tiers of one family and you convert upward, so pricing resin
        against the base tier is what matches how the material is really obtained. Cycle-safe
        because a malformed tree must not hang the request.
        """
        seen: set[int] = set()
        current = material_id
        while current in self._combine and current not in seen:
            seen.add(current)
            current = self._combine[current].input
        return current

    def reduce_to_root(self, material_id: int, count: int) -> tuple[int, int, int]:
        """`(root id, count in root units, mora spent crafting)` for `count` of a material.

        Ratios come from `CombineExcelConfigData`, never assumed to be 3:1 — a few recipes
        are not.
        """
        mora = 0
        current, needed = material_id, count
        seen: set[int] = set()
        while current in self._combine and current not in seen:
            seen.add(current)
            step = self._combine[current]
            batches = -(-needed // step.output_count)
            mora += batches * step.mora
            needed = batches * step.input_count
            current = step.input
        return current, needed, mora

    # -- resin ----------------------------------------------------------------------

    def rate(self, material_id: int) -> DropRate | None:
        """The drop rate for a material, or `None` when nothing prices it."""
        return self._rates.get(material_id)

    def uncurated(self) -> list[int]:
        """Material ids the curated file lists but has not been given a number for."""
        return sorted(
            int(k)
            for k, v in self._curated["drop_rates"].items()
            if v.get("expected_per_run") is None
        )

    def mora_per_exp(self, target: str) -> float | None:
        """Mora charged per point of EXP fed, or `None` while the divisor is uncurated."""
        divisor = self._curated["mora_per_exp"][target].get("divisor")
        return None if divisor is None else 1.0 / float(divisor)


@lru_cache(maxsize=1)
def economy() -> Economy:
    """The process-wide price list. Read from disk once."""
    derived = json.loads((_SNAPSHOT / "planner_economy.json").read_text(encoding="utf-8"))
    curated = json.loads((_CURATED / "curated_rates.json").read_text(encoding="utf-8"))
    return Economy(derived, curated)
