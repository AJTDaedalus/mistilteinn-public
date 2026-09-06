"""Measure substat line frequencies in a GOOD export against the published draw weights.

    cd backend && python -m scripts.measure_substat_frequencies
    cd backend && python -m scripts.measure_substat_frequencies --export ../references/x.json
    cd backend && python -m scripts.measure_substat_frequencies --slot flower --max-level 0

`docs/TASKS_artifact_ranking.md` A.3; findings in `docs/RESEARCH_substat_draw_weights.md`.

## Why this exists

`app/data/external/artifact_draw_model.json` carries the substat appearance weights, and they
are **cited rather than derived** — no primary source publishes them (`app/data/external.py`).
The obvious way to put that right is to measure them from a real inventory, and the owner has a
2,370-piece export. **This is the script that tried, and the answer is that it cannot be done
from this corpus.** It is committed so the next person reads the result instead of repeating the
attempt.

## The test this performs, and why the naive one is wrong

A first cut compared each stat's observed share against `weight / total_weight`. That comparison
is **not** the model's prediction: substats are drawn *without replacement*, so a stat's marginal
probability of appearing is not proportional to its weight. The right quantity is

    P(s appears) = 1 - P(s is missed in all k draws)

computed exactly by enumerating ordered draws over the eligible pool, renormalising the
denominator after each — which is what `_marginals` does, and what GO's `substatProb` does at the
same problem.

Two things make the comparison honest:

- **The pool is conditioned.** A stat cannot roll as a substat if it is the piece's main stat, so
  every cell is grouped by `(slot, main stat, number of substat lines)` and its expectation
  computed for that pool and that many draws. A flower's `hp` is not eligible; a Crit DMG
  circlet's `critDMG_` is not either.
- **Only the ordering is asserted.** Exact marginals depend on the weights being right, which is
  the thing under test. But inclusion probability under this scheme is **monotone in weight**
  regardless of what the weights are, so `P(appears)` must rank the stats the same way the weight
  table does. That ordering is falsifiable without assuming the numbers.

## `--fit`, which is the part that settles it

Reporting a disagreement would leave two live explanations — a selected inventory, or a wrong
published table — and an obvious next move: fit the weights to the export and use those instead.
`--fit` does exactly that, and the result is why nobody should.

The model has ten weights, free up to scale, so **nine** parameters. The corpus supplies ten
marginals that sum to the line count, so **nine** independent observations. A fit therefore
generically exists, and it does: 25 iterations to a maximum marginal error of 9.3e-6. Whatever
selection is present in a kept inventory is absorbed into the fitted weights and becomes
invisible.

**So the corpus cannot distinguish the two explanations, and that is a fact about identifiability
rather than about which one is true.** It is the reason `app/data/external/` cites the table
instead of deriving it.

## What it does not do

It does not adjust anything. `--fit` prints a table and writes nothing; no shipped number is
fitted to this corpus.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from itertools import permutations
from pathlib import Path

from app.data.external import main_stat_probabilities, substat_weights

REPO = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT = REPO / "references" / "genshin_export_2026-08-28_11-07.json"

#: A GOOD export names slots exactly like this, which is also `app.data.external.SLOTS`.
SLOT_ORDER = ("flower", "plume", "sands", "goblet", "circlet")


def _marginals(pool: dict[str, float], draws: int) -> dict[str, float]:
    """P(stat appears) for each stat, under a weighted draw of `draws` without replacement.

    Enumerated rather than approximated. The pool is at most ten stats and `draws` at most four,
    so the exact answer costs a few thousand terms — an independent-weights approximation would
    be cheaper and would be the very thing this script exists to avoid asserting.
    """
    if draws >= len(pool):
        return dict.fromkeys(pool, 1.0)
    total = sum(pool.values())
    out: dict[str, float] = {}
    for stat in pool:
        rest = {k: v for k, v in pool.items() if k != stat}
        missed = 0.0
        for order in permutations(rest, draws):
            p, remaining = 1.0, float(total)
            for drawn in order:
                p *= pool[drawn] / remaining
                remaining -= pool[drawn]
            missed += p
        out[stat] = 1.0 - missed
    return out


#: Convergence tolerance for `_fit`, as a maximum absolute error on any stat's marginal share.
#: 1e-5 is two orders below the smallest difference the report prints, so a "converged" fit is
#: converged at the resolution anybody reads it at.
FIT_TOLERANCE = 1e-5

#: Damping on the multiplicative update. Undamped (1.0) the iteration oscillates.
FIT_STEP = 0.35


def _fit(
    sizes: Counter, obs: Counter, start: dict[str, int],
) -> tuple[dict[str, float], int, float]:
    """Weights whose predicted marginals reproduce `obs`, by multiplicative update.

    Not an inference — a demonstration. See the module docstring: a fit exists because the
    parameter count matches the observation count, so its existence says nothing about whether
    the fitted numbers are the game's.
    """
    total_obs = sum(obs.values())
    weights = {k: float(v) for k, v in start.items()}
    err = float("inf")
    for iteration in range(400):
        expected = _expected(sizes, weights)
        total_exp = sum(expected.values())
        err = max(abs(obs[s] / total_obs - expected[s] / total_exp) for s in weights)
        if err < FIT_TOLERANCE:
            return weights, iteration, err
        for stat in weights:
            ratio = max(obs[stat] / total_obs, 1e-9) / max(expected[stat] / total_exp, 1e-9)
            weights[stat] *= ratio**FIT_STEP
        floor = min(weights.values())
        weights = {k: v / floor * 3 for k, v in weights.items()}
    return weights, 400, err


def _expected(sizes: Counter, weights: dict[str, float]) -> dict[str, float]:
    """Expected line counts per stat, summed over every conditioned cell."""
    out: dict[str, float] = defaultdict(float)
    for (main, lines), n in sizes.items():
        pool = {k: v for k, v in weights.items() if k != main}
        for stat, p in _marginals(pool, lines).items():
            out[stat] += p * n
    return out


def _cells(
    artifacts: list[dict], *, rarity: int, max_level: int | None, slot: str | None,
) -> tuple[Counter, Counter]:
    """Group pieces by `(main stat, line count)` — one homogeneous draw per cell.

    The main stat is in the key because it is out of the substat pool, and the line count
    because it is how many draws happened. Slot is a filter rather than a key: two slots that
    rolled the same main stat drew from the same pool.
    """
    sizes: Counter = Counter()
    observed: Counter = Counter()
    for art in artifacts:
        if art.get("rarity") != rarity:
            continue
        if max_level is not None and art.get("level", 0) > max_level:
            continue
        if slot and art.get("slotKey") != slot:
            continue
        subs = [s["key"] for s in art.get("substats", []) if s.get("key")]
        if not subs:
            continue
        sizes[(art["mainStatKey"], len(subs))] += 1
        observed.update(subs)
    return sizes, observed


def _report(
    export: Path, *, rarity: int, max_level: int | None, slot: str | None, fit: bool,
) -> int:
    data = json.loads(export.read_text(encoding="utf-8"))
    weights = substat_weights()
    sizes, observed = _cells(
        data.get("artifacts", []), rarity=rarity, max_level=max_level, slot=slot,
    )
    if not sizes:
        print("no pieces matched the filters")
        return 1

    expected = _expected(sizes, {k: float(v) for k, v in weights.items()})
    total_obs = sum(observed.values())
    total_exp = sum(expected.values())
    pieces = sum(sizes.values())

    scope = slot or "all slots"
    lvl = "any level" if max_level is None else f"level <= {max_level}"
    print(f"\n{rarity}-star, {scope}, {lvl}: {pieces} pieces, {total_obs} substat lines\n")
    print(f"{'stat':12s} {'w':>2s} {'observed':>9s} {'expected':>9s} {'obs/exp':>8s}")
    rows = sorted(observed, key=lambda s: -observed[s] / total_obs)
    for stat in rows:
        obs = observed[stat] / total_obs
        exp = expected[stat] / total_exp
        print(f"{stat:12s} {weights[stat]:2d} {obs:8.2%} {exp:8.2%} {obs / exp:8.2f}")

    # The falsifiable claim: inclusion probability is monotone in weight, so ordering by
    # observed frequency must not put a lighter stat above a heavier one.
    order = [weights[s] for s in rows]
    inversions = [
        (rows[i], rows[j])
        for i in range(len(order))
        for j in range(i + 1, len(order))
        if order[i] < order[j]
    ]
    print(f"\nweight-order inversions: {len(inversions)}")
    for lighter, heavier in inversions[:12]:
        print(f"  {lighter} (w={weights[lighter]}) ranks above {heavier} (w={weights[heavier]})")
    if inversions:
        print(
            "\nMonotonicity is violated. Under a weighted draw without replacement a heavier "
            "stat is always at least as likely to appear, whatever the weights are, so this "
            "corpus does not agree with the published table.",
        )

    if fit:
        fitted, iterations, err = _fit(sizes, observed, weights)
        refit = _expected(sizes, fitted)
        total_refit = sum(refit.values())
        print(f"\n--fit: converged in {iterations} iterations, max marginal error {err:.1e}\n")
        header = f"{'stat':12s} {'published':>9s} {'fitted':>7s} {'observed':>9s} {'fit exp':>9s}"
        print(header)
        for stat in sorted(fitted, key=lambda s: -fitted[s]):
            print(
                f"{stat:12s} {weights[stat]:9d} {fitted[stat]:7.2f} "
                f"{observed[stat] / total_obs:8.2%} {refit[stat] / total_refit:10.2%}",
            )
        print(
            "\nA fitted table exists because the model has nine free parameters and the corpus "
            "nine independent marginals, so whatever selection a kept inventory carries is "
            "absorbed into the fit and becomes invisible. **This corpus therefore cannot tell a "
            "wrong published table from a selected sample**, which is why nothing is derived "
            "from it. docs/RESEARCH_substat_draw_weights.md.",
        )
    return 0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--rarity", type=int, default=5)
    parser.add_argument(
        "--max-level",
        type=int,
        default=None,
        help="Only pieces at or below this level. 0 is the least-selected cut available.",
    )
    parser.add_argument("--slot", choices=SLOT_ORDER, default=None)
    parser.add_argument(
        "--fit",
        action="store_true",
        help="Also fit weights to this corpus, to show that a fit exists and settles nothing.",
    )
    args = parser.parse_args()
    if not args.export.exists():
        raise SystemExit(
            f"no export at {args.export} — references/ is gitignored, so this is expected on a "
            "machine that has none",
        )
    # Touching this asserts the draw model loads before any measurement is printed.
    main_stat_probabilities("flower")
    raise SystemExit(
        _report(
            args.export,
            rarity=args.rarity,
            max_level=args.max_level,
            slot=args.slot,
            fit=args.fit,
        ),
    )


if __name__ == "__main__":
    main()
