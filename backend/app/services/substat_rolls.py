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

**Per-roll qualities are published wherever a count is,** which follows Genshin Optimizer:
where several combinations of the same length fit, it takes one and colours the bars. The
alternatives differ by a tier on a roll or two, so a *grey* bar — which reads as "this line
never rolled" — is further from the truth than a picked one. `tiers_exact` marks a reading
that is one of several, and the card says so on hover.

Where not even a count can be reached the answer is `None` and the UI shows nothing: null is
not zero, and this is the rule `UpgradePotentialRead` already follows.

**Roll value is separate, and always exact.** `roll_value` is the total as a multiple of the
stat's best single roll — 24.9% CRIT DMG against a 7.77% max roll is 3.20. It needs no
decomposition, so it is available on every substat including the ambiguous ones, and it is
the number that actually answers "is this a good line".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from itertools import combinations_with_replacement, product
from typing import TYPE_CHECKING

from app.data.snapshot import (
    SnapshotUnavailableError,
    artifact_upgrade_levels,
    substat_depots_for_rarity,
    substat_rolls,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    #: The value of each roll, or None unless exactly one decomposition fits. Unlike
    #: `roll_tiers` this is never a *reading* — a float claims more precision than a bar does.
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
    #: Every roll count the arithmetic allows, ascending. `rolls` is the single member when
    #: there is one; this is what lets `resolve_artifact` narrow the rest.
    candidates: tuple[int, ...] = ()
    #: One decomposition per candidate count, keyed by count, so a joint solve that picks a
    #: count also gets its tiers. **Every count is represented**, including those reachable
    #: several ways — `tied_counts` says which, and `tiers_exact` carries it to the caller.
    by_count: tuple[tuple[int, tuple[int, ...]], ...] = ()
    #: Counts reachable by more than one combination of that length.
    tied_counts: tuple[int, ...] = ()
    #: True when `rolls` is the *likeliest* count rather than the only possible one.
    #:
    #: Genshin Optimizer takes the same fallback — `ArtifactDataManager` prefers the shortest
    #: decomposition and, across a piece, the assignment with the fewest rolls — and it does
    #: so silently. This flag is the difference: the count is shown, and shown as an estimate,
    #: so a card can draw it without claiming more than it knows.
    estimated: bool = False
    #: True when `roll_tiers` is the *only* combination of its length; False when it is one
    #: reading of several the arithmetic allows equally well.
    #:
    #: Genshin Optimizer does not carry this distinction — `getSubstatRolls` returns every
    #: decomposition and `artifactMeta.ts` takes the first, treating a same-length tie as
    #: settled. This repo shows the same bars and keeps the caveat, because a tooltip is free
    #: and a silent pick is the one thing about GO's approach worth improving on.
    tiers_exact: bool = True


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


#: Enough places to erase float32 noise from the snapshot and nowhere near enough to change a
#: real value. The tables are stored as float32, so an exact 5.25% arrives as 5.249999836.
_NOISE_PLACES = 6


def _displayed(value: float, *, fraction: bool) -> float:
    """The number as an export writes it: a percentage to one decimal, a flat stat whole.

    **Half-up, and de-noised first.** Both matter, and together they were the whole of the
    grey-bar problem:

    - the tier tables are float32, so a true 5.25% ATK% roll is stored as `0.05249999836`;
    - Python's `round` is banker's, so `round(5.249999836, 1)` is `5.2`.

    The game displays `5.3` and the export writes `0.053`, so the comparison failed and the
    line was reported as matching no combination at all. Measured on a real 2,370-piece
    inventory, **the four commonest 5-star ATK% values in the export are 0.041 / 0.047 /
    0.053 / 0.058 against tiers of 0.0408 / 0.0466 / 0.0525 / 0.0583** — two of the four
    landed on a rounding boundary and never matched.

    This is what Genshin Optimizer does and why it has bars where we had gaps: it compares the
    **displayed** value, and the displayed value is the one the game rounded, not the one the
    table stores.
    """
    scaled = value * 100 if fraction else value
    # De-noise before rounding, or the boundary case rounds the wrong way.
    quantum = Decimal("0.1") if fraction else Decimal("1")
    return float(
        Decimal(repr(round(scaled, _NOISE_PLACES))).quantize(quantum, rounding=ROUND_HALF_UP),
    )


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

    counts = sorted({len(combo) for combo in fits})
    per_count: dict[int, list[tuple[float, ...]]] = {}
    for combo in fits:
        per_count.setdefault(len(combo), []).append(combo)

    # **One reading per count, including the counts reachable several ways.** This module used
    # to publish tiers only where a count had exactly one decomposition, and the effect was
    # invisible in aggregate but not on screen: unlevelled pieces decompose trivially and were
    # 100% coloured, while **at +20 — the only pieces anyone looks at — 44% were.** Averaged
    # over an inventory that reads as 87% coloured, which is why the gap survived a
    # measurement. Genshin Optimizer takes the first fitting combination and colours the bars;
    # the tie is real but the alternatives differ by a tier on one roll, and a grey bar
    # claims *less* than the truth rather than more. `tiers_exact` keeps the distinction.
    #
    # `combinations_with_replacement` walks a sorted ladder, so `combos[0]` is the
    # lexicographically smallest — a deterministic pick, not an incidental one.
    by_count = tuple(
        (count, tuple(_quality(tiers, v) for v in combos[0]))
        for count, combos in sorted(per_count.items())
    )
    tied = tuple(count for count, combos in sorted(per_count.items()) if len(combos) > 1)

    rolls = counts[0] if len(counts) == 1 else None
    tiers_out = dict(by_count).get(rolls) if rolls is not None else None
    exact = rolls is not None and rolls not in tied
    return SubstatAnalysis(
        rolls=rolls,
        # Still only when one decomposition fits: a float is a stronger claim than a bar.
        roll_values=per_count[rolls][0] if rolls is not None and exact else None,
        roll_tiers=tiers_out,
        roll_value=roll_value,
        candidates=tuple(counts),
        by_count=by_count,
        tied_counts=tied,
        tiers_exact=exact if tiers_out else True,
    )


def resolve_artifact(
    *, stars: int, level: int, substats: Sequence[tuple[str, float]],
) -> list[SubstatAnalysis]:
    """Analyse a whole piece, using the *artifact's* roll budget to narrow each line.

    **A substat is not independent of its neighbours.** A piece receives one roll per initial
    substat plus one per upgrade, and every one lands on some line — so the per-substat counts
    must sum to that budget. A 5-star at +20 has five upgrades and three or four initial
    substats: eight or nine rolls in total.

    That constraint resolves lines the value alone cannot. Measured on a real inventory,
    **about 30% of maxed 5-star pieces had at least one substat the per-line arithmetic left
    ambiguous** — which the card could only draw as a gap, and a missing bar reads as "this
    line has no rolls" rather than as "this cannot be determined". Solving the lines together
    recovers most of them, because the ambiguous one is usually the only remaining degree of
    freedom once the others are fixed.

    Where more than one assignment fits the budget, the fewest-rolls one is taken — Genshin
    Optimizer's rule — and every line it touched is marked `estimated`. Lines that were
    already unambiguous on their own stay exact; the solve cannot make a settled line less
    certain.
    """
    found = [
        analyse(stars=stars, stat=stat, value=value, level=level)
        for stat, value in substats
    ]
    candidates = [f.candidates for f in found]
    if not candidates or any(not c for c in candidates):
        return found

    budget = _budget(stars=stars, level=level, shown=len(list(substats)))
    if not budget:
        return found

    solutions = [combo for combo in product(*candidates) if sum(combo) in budget]
    if not solutions:
        return found

    # **Several assignments can satisfy the budget, and refusing them all was too strict.**
    # It left 15% of a real inventory with at least one bar-less line, which reads as "this
    # substat never rolled" rather than as "this cannot be pinned down". Genshin Optimizer
    # takes the fewest-rolls assignment here (`ArtifactDataManager`: it scores by
    # `-roll.length` and keeps the highest), and so does this — the difference is that the
    # result is flagged `estimated` rather than presented as fact.
    chosen = min(solutions, key=sum)
    estimated = len(solutions) > 1
    return [
        _with_count(analysis, count, estimated=estimated)
        for analysis, count in zip(found, chosen, strict=True)
    ]


#: How many substats a piece of each rarity is *created* with, low and high.
#:
#: Genshin Optimizer's `artSubstatRollData` (`libs/gi/consts/src/artifact.ts`, MIT), used
#: rather than derived. The first version of this module inferred the initial count from how
#: many substats a piece has *now*, minus one for "started a line short" — which is only
#: right at 5-star, where four-now happens to equal the high bound. A 4-star drops with two
#: or three lines and a 3-star with one or two, so a piece can gain several through upgrades:
#: the inferred budget for a 4-star `+16` was `{7, 8}` against a truth of `{6, 7}`, excluding
#: the real answer half the time and admitting one the rarity cannot reach.
#:
#: 1-star and 2-star do not follow the pattern at all, which is the other reason this is a
#: table and not arithmetic.
_INITIAL_SUBSTATS: dict[int, tuple[int, int]] = {
    1: (0, 0), 2: (0, 1), 3: (1, 2), 4: (2, 3), 5: (3, 4),
}


def _budget(*, stars: int, level: int, shown: int) -> set[int]:
    """Total rolls a piece of this rarity, level and substat count holds.

    `initial + upgrades` — but **not over both initial counts unconditionally.** The number of
    substats on the card is not merely a consequence of the initial count; it *constrains* it,
    and this function used to say the opposite in a docstring.

    A rarity starts with `low` or `high` substats, and a piece that started with `low` gains
    its extra line on the **first upgrade**. So:

    - showing `low` lines means it started with `low` **and has had no upgrades** — otherwise
      it would be showing `low + 1`;
    - showing `high` lines means either it started with `high`, or it started with `low` and
      has had at least one upgrade.

    **Measured against a real 2,370-piece inventory this is not a nicety.** Without it a `+0`
    five-star showing three substats got the budget `{3, 4}`, and a four-roll assignment over
    three lines — impossible at `+0`, where every line holds exactly one roll — stayed a
    live solution. The piece was reported undetermined and the card drew grey bars with no
    denominator. **230 of the 266 undetermined pieces were exactly that shape.**
    """
    bounds = _INITIAL_SUBSTATS.get(stars)
    if bounds is None:
        return set()
    try:
        upgrades = len([at for at in artifact_upgrade_levels(stars) if at <= level])
    except SnapshotUnavailableError:
        return set()

    low, high = bounds
    possible: set[int] = set()
    if shown == low and upgrades == 0:
        possible.add(low)
    if shown == high:
        if upgrades >= 1:
            possible.add(low + upgrades)
        possible.add(high + upgrades)
    # A count the rarity cannot produce — a hand-written row, or a rarity whose pattern this
    # table does not cover. Fall back to the unconstrained budget rather than returning
    # nothing: an empty budget refuses every assignment and reports the whole piece unknown,
    # which is a worse answer than a wide one.
    return possible or {low + upgrades, high + upgrades}


def _with_count(
    analysis: SubstatAnalysis, count: int, *, estimated: bool,
) -> SubstatAnalysis:
    """`analysis` narrowed to one roll count, keeping its tiers if that count has them.

    A line that was already unambiguous on its own stays exact even when the *piece* needed
    an estimate elsewhere: the budget solve cannot make a settled line less certain.
    """
    if analysis.rolls == count and len(analysis.candidates) == 1:
        return analysis
    is_estimate = estimated or len(analysis.candidates) > 1
    return SubstatAnalysis(
        rolls=count,
        roll_values=None,
        # **The reading is published even for an estimated count**, which reverses this
        # module's earlier rule. That rule was defensible on its own terms — bars painted as
        # fact on a guessed number — but it stripped tiers from lines that decomposed
        # uniquely, merely because some *other* line on the piece needed the budget solve. The
        # honest fix is the flag, not the withholding: `tiers_exact` is False here and the
        # card says so, where before the user simply saw grey and read it as "no rolls".
        roll_tiers=dict(analysis.by_count).get(count),
        roll_value=analysis.roll_value,
        candidates=analysis.candidates,
        by_count=analysis.by_count,
        tied_counts=analysis.tied_counts,
        estimated=is_estimate,
        tiers_exact=not is_estimate and count not in analysis.tied_counts,
    )
