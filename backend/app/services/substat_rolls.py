"""What a substat is made of: how many rolls, and — usually — the value of each one.

Genshin publishes no roll count. A substat is a *sum* of rolls, one when the piece was
created and one per upgrade, and an export carries only the total. The count is therefore
reconstructed by decomposing that total over the four values the stat can roll, which
`app/data/yuanshen/snapshot/artifact_substat_values.json` publishes per rarity.

## Matching on the displayed value, not with a tolerance

The first version of this module compared floats within a tolerance, because GOOD rounds
percentages to one decimal and an exact match never succeeds against the raw tier values.
That slack was itself enough to make five bottom-tier rolls indistinguishable from three
mixed ones, and it refused far more than it had to.

Genshin Optimizer does something better, and this now matches it: **round the candidate sum
to the same precision the export uses, and compare exactly.** `getSubstatRolls`
(`libs/gi/util/src/artifact/artifact.ts`) looks the displayed value up in a precomputed table
keyed by that rounded string and returns every decomposition. Same idea, computed on demand
rather than precomputed.

Measured over a real 2,370-artifact export (7,878 substats): **85.0%** of substats decompose
exactly one way — so every roll value and its quality is known — **10.2%** more admit several
decompositions that agree on the *count*, and **4.8%** match nothing in the table.
These are the numbers from **after** the depot and rarity-cap fixes; an earlier pass
reported 84.9/8.9/2.8/3.4 against the same corpus and is superseded — two measurements of
one file that a reader cannot tell apart is worse than one.

## What it still refuses to do

**A count is reported only when every decomposition agrees on one**, and per-roll values only
when there is exactly one decomposition. Where they disagree the answer is `None` and the UI
shows nothing, which is the rule `UpgradePotentialRead` already follows: null is not zero,
and a confident wrong roll count is worse than an absent one.

**Roll value is separate, and always exact.** `roll_value` is the total as a multiple of the
stat's best single roll — 24.9% CRIT DMG against a 7.77% max roll is 3.20. It needs no
decomposition, so it is available on every substat including the ambiguous ones, and it is
the number that actually answers "is this a good line".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations_with_replacement

from app.data.snapshot import (
    SnapshotUnavailableError,
    artifact_upgrade_levels,
    substat_depots_for_rarity,
    substat_rolls,
)

#: Quality is reported on this scale — `0` worst, `TOP_QUALITY` best — whatever the ladder's
#: own length, so a maximum roll looks like one at every rarity.
TOP_QUALITY = 3

#: Below this a stat is a fraction (`0.0389` CRIT rate) and GOOD shows it as a percentage to
#: one decimal; at or above it the stat is flat (`23.31` EM) and is shown whole. Read off the
#: table's own top tier rather than kept as a second list of which stats are percentages.
_FRACTION_CEILING = 1.0


@dataclass(frozen=True)
class SubstatAnalysis:
    """What could be established about one substat."""

    #: Rolls behind it, or None when the decompositions disagree about how many.
    rolls: int | None
    #: The value of each roll, or None unless exactly one decomposition fits.
    roll_values: tuple[float, ...] | None
    #: Each roll's quality as `0` (worst) to `3` (best), aligned with `roll_values`.
    #:
    #: **Normalised across rarities, not a raw ladder index.** 1★ and 2★ ladders hold two and
    #: three values, so a raw index would top out at 1 and 2 there — and a *maximum* roll on a
    #: 2★ piece would be coloured as a mid-tier one. Scaled, `3` always means "the best this
    #: stat can roll at this rarity".
    roll_tiers: tuple[int, ...] | None
    #: The total as a multiple of one best-case roll. Always available — no decomposition
    #: needed — and None only when the stat is not in the table at all.
    roll_value: float | None


_UNKNOWN = SubstatAnalysis(rolls=None, roll_values=None, roll_tiers=None, roll_value=None)


@lru_cache(maxsize=16)
def _tiers_for(stars: int) -> dict[str, tuple[float, ...]]:
    """`{FIGHT_PROP_*: the values that stat can roll}` at this rarity.

    Read through `app/data/snapshot.py`, which DESIGN §1 A6 makes **the one reader** of
    `app/data/yuanshen/snapshot/*.json`. Opening the file here instead worked and had a
    different failure mode: a missing snapshot raised `FileNotFoundError` out of a computed
    field and 500'd `GET /api/v1/artifacts`, where every other consumer turns it into
    `SnapshotUnavailableError` and one unreadable row degrades to null.

    **Only depots that offer a ladder count.** `depot_ranks` maps `961`-`965` to rarities 4
    *and* 5, and those publish a single fixed value per prop — the unupgradable artifacts the
    snapshot's own `excluded_unupgradable` counts, not rolls. Merging them put `0.1943`
    beside 5★ CRIT DMG's real `0.0544-0.0777` ladder, which divided `roll_value` by the wrong
    maximum (24.9% CRIT DMG scored 1.28 instead of 3.20) and invented decompositions that
    made sound substats look ambiguous.

    A depot is a roll depot when it offers **more than one value for the prop in question** —
    a property of the data, not a hardcoded id list. The snapshot's own note warns against
    inferring `501 == 5-star` from the id pattern, and this does not have to.
    """
    table: dict[str, list[float]] = defaultdict(list)
    for depot_id in substat_depots_for_rarity(stars):
        per_prop: dict[str, list[float]] = defaultdict(list)
        for row in substat_rolls(depot_id):
            per_prop[str(row["prop"])].append(float(row["value"]))
        for prop, values in per_prop.items():
            if len(set(values)) > 1:
                table[prop].extend(values)
    return {prop: tuple(sorted(set(values))) for prop, values in table.items()}


@lru_cache(maxsize=64)
def _max_rolls(stars: int, level: int | None) -> int:
    """The most rolls one substat can hold on a piece of this rarity at this level.

    **One roll plus the upgrades the piece has actually had.** A 5★ gains a roll at
    +4/+8/+12/+16/+20, so a maxed one tops out at six on a single line — but a 4★ has four
    upgrades, a 3★ three, and a 1★ one. Enumerating to six regardless admitted decompositions
    the game cannot produce, and where a phantom count sat beside the true one the two
    disagreed and the answer collapsed to "ambiguous": **92 reachable 4★ substat values and
    58 3★ values lost a count that was perfectly determined.**

    `level` narrows it further where the caller knows it — a +8 5★ has had two upgrades, so
    no line on it can hold more than three rolls.
    """
    upgrades = artifact_upgrade_levels(stars)
    if level is not None:
        upgrades = tuple(at for at in upgrades if at <= level)
    return 1 + len(upgrades)


def _quality(tiers: tuple[float, ...], value: float) -> int:
    """Where `value` sits in `tiers`, rescaled to `0..3` so rarities are comparable."""
    if len(tiers) < TOP_QUALITY - 1:
        return TOP_QUALITY
    return round(tiers.index(value) * TOP_QUALITY / (len(tiers) - 1))


def _displayed(value: float, *, fraction: bool) -> float:
    """The number as an export writes it: a percentage to one decimal, a flat stat whole."""
    return round(value * 100, 1) if fraction else round(value, 0)


def analyse(
    *, stars: int, stat: str, value: float, level: int | None = None,
) -> SubstatAnalysis:
    """Decompose `value` into rolls. See the module docstring for what is and is not known.

    `level` is optional and worth passing: it bounds how many upgrades the piece has had, so
    counts the game could not have produced are never considered.
    """
    try:
        tiers = _tiers_for(stars).get(stat)
        cap = _max_rolls(stars, level)
    except SnapshotUnavailableError:
        # The same degradation `UpgradePotentialRead` makes: a snapshot this deployment does
        # not have must not take down a list of eight hundred artifacts.
        return _UNKNOWN
    if not tiers or value <= 0:
        return _UNKNOWN

    fraction = tiers[-1] < _FRACTION_CEILING
    target = _displayed(value, fraction=fraction)
    roll_value = value / tiers[-1]

    fits: list[tuple[float, ...]] = []
    for n in range(1, cap + 1):
        # Bounds first, on the displayed scale so the comparison is the same one that decides
        # a match. Skips almost every count without enumerating its combinations.
        if _displayed(n * tiers[0], fraction=fraction) > target:
            continue
        if _displayed(n * tiers[-1], fraction=fraction) < target:
            continue
        fits.extend(
            combo
            for combo in combinations_with_replacement(tiers, n)
            if _displayed(sum(combo), fraction=fraction) == target
        )

    if not fits:
        # The value matches no combination the table can produce. Reported as unknown rather
        # than rounded toward the nearest — a stat this table does not describe is not one to
        # answer questions about.
        return SubstatAnalysis(
            rolls=None, roll_values=None, roll_tiers=None, roll_value=roll_value,
        )

    counts = {len(combo) for combo in fits}
    rolls = next(iter(counts)) if len(counts) == 1 else None
    if len(fits) == 1:
        only = fits[0]
        return SubstatAnalysis(
            rolls=rolls,
            roll_values=only,
            roll_tiers=tuple(_quality(tiers, v) for v in only),
            roll_value=roll_value,
        )
    # Several decompositions. The count may still be agreed even where the values are not,
    # which is the common case — 10.2% of a real inventory.
    return SubstatAnalysis(
        rolls=rolls, roll_values=None, roll_tiers=None, roll_value=roll_value,
    )
