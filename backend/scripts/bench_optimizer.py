"""Measure what one scored combination costs, so the auto-budget is a number with a run behind it.

`artifact_prefilter.SECONDS_PER_COMBINATION` decides how large a search the optimizer will
attempt before it starts pruning lossily. The ZZZ pipeline this was ported from carried a
fitted constant for *its* hot loop; carrying that number over would have been a fabricated
measurement of code that has never been timed. So it is measured here instead.

    cd backend && python -m scripts.bench_optimizer

Prints the line to paste into `app/services/artifact_prefilter.py`. Re-run it whenever the
damage chain or the stat resolution changes shape — G.7 re-baselines `tests/perf` against
the same search and should re-run this at the same time.
"""

from __future__ import annotations

import argparse
import random
import time

from app.formula.genshin import tags
from app.formula.genshin.damage import Hit
from app.pando.calculator import NodeRegistry
from app.services import artifact_prefilter
from app.services.artifact_optimizer import (
    SLOTS,
    ArtifactCandidate,
    OptimizerConstraints,
    optimize,
)
from app.services.damage_calculator import Enemy
from app.services.stat_calculator import build_log

#: The five substats a piece rolls from, and a plausible per-roll value. Only the *shape*
#: matters for a timing — four substats per piece, values in the right order of magnitude —
#: so these are not presented as game data and nothing but this script reads them.
_SUBSTAT_POOL = (
    ("FIGHT_PROP_ATTACK_PERCENT", 0.0466),
    ("FIGHT_PROP_CRITICAL", 0.0311),
    ("FIGHT_PROP_CRITICAL_HURT", 0.0622),
    ("FIGHT_PROP_ELEMENT_MASTERY", 18.65),
    ("FIGHT_PROP_CHARGE_EFFICIENCY", 0.0518),
)

_MAIN_STATS = {
    "equip_bracer": "FIGHT_PROP_HP",
    "equip_necklace": "FIGHT_PROP_ATTACK",
    "equip_shoes": "FIGHT_PROP_ATTACK_PERCENT",
    "equip_ring": "FIGHT_PROP_ICE_ADD_HURT",
    "equip_dress": "FIGHT_PROP_CRITICAL_HURT",
}


def _inventory(per_slot: int, seed: int) -> list[ArtifactCandidate]:
    rng = random.Random(seed)  # noqa: S311 - a timing fixture, not a security decision
    out: list[ArtifactCandidate] = []
    for slot in SLOTS:
        for index in range(per_slot):
            rolls = rng.sample(_SUBSTAT_POOL, 4)
            out.append(ArtifactCandidate(
                artifact_id=f"{slot}-{index}",
                slot=slot,
                set_id=rng.choice((1, 2, 3)),
                rarity=5,
                level=20,
                main_stat=_MAIN_STATS[slot],
                substats=tuple(
                    {"stat": stat, "value": value * rng.uniform(1.0, 6.0)}
                    for stat, value in rolls
                ),
            ))
    return out


def _base_contributions() -> tuple:
    log = build_log(NodeRegistry())
    log.add(tags.Q_BASE_ATK, 800.0, tags.SRC_CHARACTER, "character")
    log.add(tags.Q_BASE_ATK, 500.0, tags.SRC_WEAPON, "weapon")
    log.add(tags.Q_CRIT_RATE, 0.05, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_CRIT_DMG, 0.5, tags.SRC_CHARACTER, "base")
    return tuple(log.contributions)


def main() -> None:
    """Time one exhaustive search and print the constant it implies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-slot", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20260821)
    args = parser.parse_args()

    inventory = _inventory(args.per_slot, args.seed)
    enemy = Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))
    hit = Hit(multiplier=2.0, channel="cryo", scope="burst")

    started = time.perf_counter()
    result = optimize(
        _base_contributions(), inventory, hit, enemy, character_level=90,
        # EXACT, because the point is to time the search, not to time the thing that
        # decides how much of the search to skip.
        constraints=OptimizerConstraints(prefilter_top_k=artifact_prefilter.EXACT),
    )
    elapsed = time.perf_counter() - started

    scored = result.evaluated + result.rejected_by_sets + result.rejected_by_stats
    per_combination = elapsed / scored if scored else float("nan")
    print(f"inventory:        {len(inventory)} pieces ({args.per_slot} per slot)")
    print(f"pareto removed:   {result.prefilter.pareto_removed}")
    print(f"combinations:     {scored:,} ({result.evaluated:,} scored to completion)")
    print(f"elapsed:          {elapsed:.3f}s")
    print()
    print(f"SECONDS_PER_COMBINATION: float = {per_combination:.3e}")
    budget = int(artifact_prefilter.COMBINATION_BUDGET_SECONDS / per_combination)
    print(f"# -> auto-budget {budget:,} combinations "
          f"at {artifact_prefilter.COMBINATION_BUDGET_SECONDS:.0f}s")


if __name__ == "__main__":
    main()
