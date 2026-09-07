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
import math
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "yuanshen" / "snapshot"
_CURATED = Path(__file__).resolve().parents[2] / "data" / "planner"


def _weighted(record: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    """`{"values": [...], "weights": [...]}` as `((value, probability), ...)`."""
    values = [float(v) for v in record["values"]]
    weights = [float(w) for w in record["weights"]]
    total = sum(weights)
    return tuple(zip(values, [w / total for w in weights], strict=True))


def _compound(
    guaranteed: tuple[tuple[float, float], ...],
    packs: tuple[tuple[float, float], ...],
    pack_value: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    """One domain run's yield in base-tier equivalents.

    The guaranteed 2-star roll, plus a random number of drop packs, each worth a random tier.
    A compound distribution rather than a mean, so the histogram reflects that a single 4-star
    book is worth nine 2-star ones and lands rarely.
    """
    outcomes: dict[float, float] = {}
    for base, base_p in guaranteed:
        for count, count_p in packs:
            totals: dict[float, float] = {base: base_p * count_p}
            for _ in range(int(count)):
                nxt: dict[float, float] = {}
                for total, probability in totals.items():
                    for value, value_p in pack_value:
                        key = total + value
                        nxt[key] = nxt.get(key, 0.0) + probability * value_p
                totals = nxt
            for total, probability in totals.items():
                outcomes[total] = outcomes.get(total, 0.0) + probability
    return tuple(sorted(outcomes.items()))


def _per_run_distribution(
    record: dict[str, Any], exp_value: Callable[[int], int],
) -> tuple[tuple[float, float], ...] | None:
    """The per-run shape a curated source declares, or `None` if it declares only a mean.

    Two shapes, because the two sources that have one are genuinely different:

    * **`yields`** — a run hands you several things at once, each within its own range. A ley
      line gives *"6-7 blue xp books and 4-5 purple"*, so the run's EXP is the sum over the
      cartesian product of those ranges, uniform within each. Written as components rather
      than as four pre-multiplied totals so the file says what the owner said, and the
      arithmetic is the code's job rather than a transcription anyone has to re-check.
    * **`per_run` + `split_across`** — a run hands you `n` items and each is uniformly one of
      `split_across` kinds, so a *named* kind follows `Binomial(n, 1/split_across)`. A trounce
      domain gives *"2 or 3, randomly selected between 3 options"*.

    Both derive a mean, and `_source_default` refuses the entry if that mean disagrees with
    the stated `expected_per_run`.
    """
    if "yields" in record:
        outcomes: dict[float, float] = {0.0: 1.0}
        for component in record["yields"]:
            per_item = exp_value(int(component["item"])) if component.get("as_exp") else 1
            counts = [int(count) for count in component["counts"]]
            share = 1.0 / len(counts)
            nxt: dict[float, float] = {}
            for total, probability in outcomes.items():
                for count in counts:
                    key = total + count * per_item
                    nxt[key] = nxt.get(key, 0.0) + probability * share
            outcomes = nxt
        return tuple(sorted(outcomes.items()))

    if "per_run" in record:
        values = [int(v) for v in record["per_run"]["values"]]
        weights = [float(w) for w in record["per_run"]["weights"]]
        kinds = int(record.get("split_across", 1))
        outcomes = {}
        for count, weight in zip(values, weights, strict=True):
            for hits in range(count + 1):
                probability = (
                    math.comb(count, hits)
                    * (1.0 / kinds) ** hits
                    * (1.0 - 1.0 / kinds) ** (count - hits)
                )
                outcomes[float(hits)] = outcomes.get(float(hits), 0.0) + weight * probability
        # A zero-probability outcome is not an outcome. `split_across: 1` produces three of
        # them for a world boss, because Binomial(n, 1) puts all its mass on n.
        return tuple(sorted((v, p) for v, p in outcomes.items() if p > 0))

    return None


class MaterialSource(StrEnum):
    """Where a material is actually obtained, and therefore whether it costs resin.

    Owner, 2026-09-07: *"Mora, talent books, weapon ascension mats, world boss drops,
    character xp books, and weekly boss mats are the only things that should have a
    [resin] cost"*, and separately *"gems and overworld drops don't have a resin cost, same
    with the local specialties like flowers"*.

    **The gem rule is not an omission, it is a double-counting fix.** Elemental gems drop from
    a world boss *alongside* the boss's own material, in the same 40-resin run. Pricing both
    would bill that run twice, so the resin is attributed to the boss material and the gems
    ride along free. A first pass charged for both.

    Classification is by material family, derived from which cost table each family appears in
    (`docs/RESEARCH_leveling_planner_data.md` §10) rather than from whether some reward preview
    happens to mention it. That distinction caught a real bug: an elite enemy's preview lists
    Spectral Husk, Heart and Nucleus with expected counts, so they were being priced at 40
    resin a run — but Specters are ordinary overworld mobs and cost nothing.
    """

    DOMAIN = "domain"
    WORLD_BOSS = "world_boss"
    WEEKLY_BOSS = "weekly_boss"
    LEY_LINE_EXP = "ley_line_exp"
    LEY_LINE_MORA = "ley_line_mora"
    #: Free of resin: elemental gems, common enemy drops, local specialties, the Enhancement
    #: Ores, and Crown of Insight.
    NONE = "none"


#: Material id families, measured against the seeded catalogue at 7.0.54. Each is a prefix of
#: the game's own item id, and the counts behind them are in the research doc:
#: `1041` is 32 elemental gems (8 elements x 4 tiers), `1043` is 72 talent books plus the
#: Crown, `1140` is 96 weapon ascension materials, `1130` is 89 boss drops, `112x` are common
#: enemy drops, and `1000`/`1012` are local specialties.
_GEMS = "1041"
_TALENT_BOOKS = "1043"
_WEAPON_MATERIALS = "114"
_BOSS_DROPS = "113"

#: Crown of Insight. In the talent-book family by id and **not** a domain drop — it comes from
#: events, the Battle Pass and Offerings. The only member of `1043` that is not a book.
CROWN_OF_INSIGHT = 104319


@dataclass(frozen=True)
class ExpItem:
    """One EXP denomination — Hero's Wit, Mystic Enhancement Ore, and their smaller siblings."""

    id: int
    exp: int
    rarity: int


@dataclass(frozen=True)
class DropRate:
    """What one resin run yields of a material.

    `expected_per_run` is a **mean**. `distribution` is the per-run *shape* when one is
    known — `((value, probability), ...)` — and `None` when only the mean is.

    **The two are not interchangeable and the difference is visible on screen.** A mean alone
    forces the histogram to assume a shape; a source that publishes 6-7 of one book and 4-5 of
    another has a real spread, and collapsing it to 122,500 EXP made the run count a point
    mass — nine runs, probability 1.0, no distribution at all. The game's own reward previews
    give only means, so `distribution` is populated from `curated_rates.json` where a human
    knew the shape.
    """

    material_id: int
    source_type: str
    resin: int
    expected_per_run: float
    curated: bool
    distribution: tuple[tuple[float, float], ...] | None = None


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
        #: Ids the game itself published an expected drop for. Used to split world bosses
        #: (which have previews) from trounce domains (which do not).
        self._published_rates: set[int] = {int(k) for k in derived["drop_rates"]}
        self._rates: dict[int, DropRate] = {}
        for key, rec in derived["drop_rates"].items():
            self._rates[int(key)] = DropRate(
                material_id=int(key),
                source_type=rec["source"],
                resin=rec["resin"],
                expected_per_run=rec["expected_per_run"],
                curated=False,
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

    def name(self, material_id: int) -> str | None:
        """The material's English display name, from the TextMap.

        Carried because **the EXP denominations are named nowhere else** — Hero's Wit and
        Mystic Enhancement Ore never appear in an ascension bill, so nanoka never names them,
        and without a name they cannot bind to a GOOD export's `HerosWit` key.
        """
        meta = self._meta.get(material_id)
        return meta.get("name") or None if meta else None

    def exp_material_ids(self) -> tuple[int, ...]:
        """Every EXP denomination, character and weapon.

        These are materials the planner *spends* but no bill *names*, so the seed has to
        create their rows explicitly or a user's 204 Hero's Wit are invisible to it.
        """
        return tuple(
            item.id for item in (*self.character_exp_items, *self.weapon_exp_items)
        )

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

    def reduce_to_root(
        self, material_id: int, count: int, *, craft_multiplier: float = 1.0,
    ) -> tuple[int, int, int]:
        """`(root id, count in root units, mora spent crafting)` for `count` of a material.

        Ratios come from `CombineExcelConfigData`, never assumed to be 3:1 — a few recipes
        are not.

        `craft_multiplier` is what a double-product passive is worth per batch: a 10% chance
        of a double batch makes each batch worth 1.1, so the inputs fall by that factor.

        **It applies here, at every rung, rather than to the requirement.** Shrinking the
        requirement made `required` a number the game does not agree with — a plan needing 6
        Philosophies reported 5, so a user holding exactly 5 was told they were done and could
        not reach the talent level. Applying it to the inputs also compounds across a
        three-tier family for free, which shrinking one rung did not.
        """
        mora = 0
        current, needed = material_id, count
        seen: set[int] = set()
        while current in self._combine and current not in seen:
            seen.add(current)
            step = self._combine[current]
            batches = -(-needed // step.output_count)
            if craft_multiplier > 1.0:
                batches = max(1, math.ceil(batches / craft_multiplier))
            mora += batches * step.mora
            needed = batches * step.input_count
            current = step.input
        return current, needed, mora

    # -- resin ----------------------------------------------------------------------

    def source_of(self, material_id: int) -> MaterialSource:
        """Which resin activity yields this material, if any.

        Read the enum's docstring before changing a rule here — every branch is a decision
        about whether a run gets billed once or twice.
        """
        singles = {
            self.mora_item_id: MaterialSource.LEY_LINE_MORA,
            # Rides along with the world-boss run its boss material already pays for.
            CROWN_OF_INSIGHT: MaterialSource.NONE,
        }
        if material_id in singles:
            return singles[material_id]
        if material_id in {item.id for item in self.character_exp_items}:
            return MaterialSource.LEY_LINE_EXP
        text = str(material_id)
        if text.startswith(_GEMS):
            return MaterialSource.NONE
        if text.startswith((_TALENT_BOOKS, _WEAPON_MATERIALS)):
            return MaterialSource.DOMAIN
        if text.startswith(_BOSS_DROPS):
            # A published expected drop means the game's own preview priced it, which it does
            # for world bosses and not for trounce domains. That split is the classifier.
            return (
                MaterialSource.WORLD_BOSS
                if material_id in self._published_rates
                else MaterialSource.WEEKLY_BOSS
            )
        return MaterialSource.NONE

    def family_multipliers(self, root_id: int) -> dict[int, int]:
        """`{tier above the root: how many roots it is worth}`, from the crafting tree.

        `{0: 1, 1: 3, 2: 9}` for a talent book family. Read from
        `CombineExcelConfigData` rather than assumed to be 3:1, because a few recipes are not.
        """
        out = {0: 1}
        for material_id in self._combine:
            if self.craft_root(material_id) != root_id:
                continue
            depth, current = 0, material_id
            seen: set[int] = set()
            while current in self._combine and current not in seen:
                seen.add(current)
                depth += 1
                current = self._combine[current].input
            out[depth] = self.reduce_to_root(material_id, 1)[1]
        return out

    def _domain_rate(self, root_id: int) -> DropRate | None:
        """A domain's yield in base-tier equivalents, from the curated two-roll model.

        The game publishes only the guaranteed 2-star roll, so a rate built from the reward
        preview alone counts that and ignores every drop pack. See
        `curated_rates.json:domain_yields._why`.
        """
        for record in self._curated.get("domain_yields", {}).values():
            if not isinstance(record, dict) or not str(root_id).startswith(record["prefix"]):
                continue
            multipliers = self.family_multipliers(root_id)
            pack_value = tuple(
                (float(multipliers.get(int(entry["tier"]), 0)), float(entry["probability"]))
                for entry in record["pack_tiers"]
            )
            distribution = _compound(
                _weighted(record["guaranteed"]), _weighted(record["packs"]), pack_value,
            )
            mean = sum(value * probability for value, probability in distribution)
            stated = float(record["expected_per_run"])
            if abs(mean - stated) > max(1e-6, abs(stated) * 1e-4):
                msg = (
                    f"domain yield for {root_id} states expected_per_run={stated} but its "
                    f"declared rolls average {mean}."
                )
                raise ValueError(msg)
            return DropRate(
                material_id=root_id,
                source_type=MaterialSource.DOMAIN.value,
                resin=int(record["resin"]),
                expected_per_run=mean,
                curated=True,
                distribution=distribution,
            )
        return None

    def rate(self, material_id: int) -> DropRate | None:
        """The drop rate for a material, or `None` when nothing prices it.

        `None` has two meanings and `source_of` tells them apart: a material with source
        `NONE` costs no resin at all, and one with a real source but no rate is a gap in the
        data. A caller that folds them together tells the user their local specialties are an
        unknown farming cost and their weekly bosses are free.
        """
        source = self.source_of(material_id)
        if source is MaterialSource.NONE:
            return None
        if source is MaterialSource.DOMAIN:
            curated = self._domain_rate(material_id)
            if curated is not None:
                return curated
        # **A curated source default outranks the published one.** The game's own preview is
        # not always current: it gives 2.556 for every world boss, which is the World Level 8
        # figure — one value across all 101 previews, no world-level variants, because the
        # scaling is server-side. An entry here is a human saying the published number is
        # stale, and `overrides_published` records that intent in the file.
        curated_default = self._source_default(material_id)
        if curated_default is not None:
            return curated_default
        return self._rates.get(material_id)

    def _source_default(self, material_id: int) -> DropRate | None:
        """A rate curated per *source* rather than per material.

        Every trounce domain yields its materials the same way, so one number prices all 47
        weekly-boss drops instead of 47 hand-typed entries. The same shape carries the ley
        lines, whose yields no preview publishes either.
        """
        source = self.source_of(material_id)
        record = self._curated.get("source_defaults", {}).get(source.value)
        if not record or record.get("expected_per_run") is None:
            return None
        distribution = _per_run_distribution(record, self._exp_value)
        if distribution is not None:
            mean = sum(value * probability for value, probability in distribution)
            stated = float(record["expected_per_run"])
            if abs(mean - stated) > max(1e-6, abs(stated) * 1e-6):
                msg = (
                    f"curated source {source.value!r} states expected_per_run={stated} but its "
                    f"declared shape averages {mean}. One of the two is wrong, and the mean is "
                    "what every resin figure is built on."
                )
                raise ValueError(msg)
        return DropRate(
            material_id=material_id,
            source_type=source.value,
            resin=int(record["resin"]),
            expected_per_run=float(record["expected_per_run"]),
            curated=True,
            distribution=distribution,
        )

    def _exp_value(self, material_id: int) -> int:
        """A denomination's EXP, so a ley-line yield in *books* becomes one in points."""
        for item in (*self.character_exp_items, *self.weapon_exp_items):
            if item.id == material_id:
                return item.exp
        msg = f"material {material_id} is not an EXP denomination"
        raise ValueError(msg)

    def source_resin(self, source: MaterialSource) -> int | None:
        """Resin per run at a source, from the curated defaults."""
        record = self._curated.get("source_defaults", {}).get(source.value)
        return None if record is None else int(record["resin"])

    def uncurated_sources(self) -> list[str]:
        """Sources that cost resin at a rate nobody has supplied yet."""
        defaults = self._curated.get("source_defaults", {})
        return sorted(
            name for name, rec in defaults.items() if rec.get("expected_per_run") is None
        )

    def mora_per_exp(self, target: str) -> float | None:
        """Mora charged per point of EXP fed, or `None` if the rate is missing.

        **This is zero, and zero is a fact rather than a gap.** Owner, 2026-09-07: *"there is
        no more per exp point conversion"* — Genshin stopped charging mora for feeding EXP
        material. Ascension and talent levels still charge it, from the payload's own `cost`
        fields, so a plan is very far from mora-free; only the levelling half is.
        """
        rate = self._curated["mora_per_exp"][target].get("mora_per_point")
        return None if rate is None else float(rate)


@lru_cache(maxsize=1)
def economy() -> Economy:
    """The process-wide price list. Read from disk once."""
    derived = json.loads((_SNAPSHOT / "planner_economy.json").read_text(encoding="utf-8"))
    curated = json.loads((_CURATED / "curated_rates.json").read_text(encoding="utf-8"))
    return Economy(derived, curated)
