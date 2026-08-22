"""Generate search fixtures: an inventory, a context, and the Python optimizer's answer.

    cd backend && python -m scripts.kernel.generate_search_cases

C.3's harness pins the kernel's *arithmetic*. This pins its **search**: the same inventory
through `artifact_optimizer.optimize` and through the browser kernel must pick the same
build.

## The near-tie problem, and how the comparison handles it

The Python optimizer computes in float64 and the kernel in float32, diverging by up to
3.4e-07 (C.2). **Two builds closer than that can therefore swap places.** That is not a bug —
it is the tolerance doing exactly what C.2 argued it does — so the gate compares the winning
*damage* within tolerance rather than demanding identical ids, and reports a tie band when
the top builds are within it.

Inventories are randomised with distinct stat rolls, which makes exact ties vanishingly
unlikely; the tie handling is there because "unlikely" is not "impossible" and a gate that
fails once a month on a coin flip gets disabled.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from app.data.snapshot import artifact_main_stat_value, main_stat_pools
from app.formula.genshin import tags
from app.formula.genshin.damage import Hit
from app.pando.calculator import NodeRegistry
from app.services.artifact_optimizer import (
    SLOTS,
    ArtifactCandidate,
    OptimizerConstraints,
    SetBonus,
    optimize,
)
from app.services.damage_calculator import Enemy
from app.services.stat_calculator import _quantity_for_prop, build_log

OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "kernel" / "search_cases.json"
SEED = 20260822

#: How often a generated piece also carries the hit's damage bonus.
_P_DMG_BONUS = 0.4

#: Substat-ish quantities a generated piece can carry.
_ROLLABLE = (
    tags.Q_ATK_PCT, tags.Q_FLAT_ATK, tags.Q_HP_PCT, tags.Q_FLAT_HP,
    tags.Q_DEF_PCT, tags.Q_FLAT_DEF, tags.Q_CRIT_RATE, tags.Q_CRIT_DMG,
    tags.Q_ELEMENTAL_MASTERY,
)


def _piece(rng: random.Random, slot: str, index: int, channel: str) -> dict[str, Any]:
    """One synthetic artifact with a **legal** main stat for its slot.

    The first version invented main stats and the optimizer refused every one —
    `equip_necklace cannot roll FIGHT_PROP_HP`. That is G.1's validation doing its job, and
    the *fixture* was wrong rather than the check: a generator exempted from the rules would
    be testing a search over pieces the game cannot produce.

    The kernel's `stats` map is derived from the same path `add_artifact` uses, so both sides
    see the same totals — including the main stat's value from the committed snapshot, which
    the kernel does not model and must be handed.
    """
    pool = main_stat_pools()[slot]
    main_stat = rng.choice(sorted(pool))
    substats: dict[str, float] = {}
    for quantity in rng.sample(_ROLLABLE, k=rng.randint(2, 4)):
        substats[quantity] = round(rng.uniform(0.02, 0.35), 5)
    if rng.random() < _P_DMG_BONUS:
        substats[tags.dmg_bonus_q(channel)] = round(rng.uniform(0.05, 0.47), 5)

    stats = dict(substats)
    main_quantity = _quantity_for_prop(main_stat, allow_absent=True)
    if main_quantity is not None:
        value = artifact_main_stat_value(5, 20, main_stat)
        stats[main_quantity] = round(stats.get(main_quantity, 0.0) + value, 6)

    return {
        "id": f"{slot}-{index}",
        "slot": slot,
        "set_id": rng.choice([1, 2, 3]),
        "main_stat": main_stat,
        "substats": substats,
        "stats": stats,
    }


def _case(rng: random.Random, index: int, per_slot: int) -> dict[str, Any]:
    channel = rng.choice(tags.DAMAGE_CHANNELS)
    inventory = [
        _piece(rng, slot, i, channel)
        for slot in SLOTS
        for i in range(per_slot)
    ]

    base = {
        tags.Q_BASE_ATK: round(rng.uniform(700, 1100), 4),
        tags.Q_BASE_HP: round(rng.uniform(12000, 30000), 4),
        tags.Q_BASE_DEF: round(rng.uniform(600, 900), 4),
        tags.Q_CRIT_RATE: 0.05,
        tags.Q_CRIT_DMG: 0.5,
    }
    hit = {
        "multiplier": round(rng.uniform(1.0, 6.0), 4),
        "channel": channel,
        "scaling_stat": rng.choice(["atk", "hp", "def"]),
        "amplifying": None,
    }
    target = {"level": 90, "resistance": 0.1, "def_reduction": 0.0, "def_ignore": 0.0}
    bonuses = [
        {"set_id": 1, "pieces_required": 2, "stats": {tags.Q_ATK_PCT: 0.18}},
        {"set_id": 2, "pieces_required": 4, "stats": {tags.dmg_bonus_q(channel): 0.35}},
    ]

    log = build_log(NodeRegistry())
    for quantity, value in base.items():
        log.add(quantity, value, tags.SRC_CHARACTER, "case")

    result = optimize(
        tuple(log.contributions),
        [
            ArtifactCandidate(
                artifact_id=p["id"], slot=p["slot"], set_id=p["set_id"],
                rarity=5, level=20, main_stat=p["main_stat"],
                substats=tuple(
                    {"stat": _prop_for(q), "value": v} for q, v in p["substats"].items()
                ),
            )
            for p in inventory
        ],
        Hit(multiplier=hit["multiplier"], channel=channel, scope="burst",
            scaling_stat=hit["scaling_stat"]),
        Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1)),
        character_level=90,
        set_bonuses=[
            SetBonus(set_id=b["set_id"], pieces_required=b["pieces_required"],
                     add_props=tuple({"prop_type": _prop_for(q), "value": v}
                                     for q, v in b["stats"].items()))
            for b in bonuses
        ],
        constraints=OptimizerConstraints(top_n=3),
    )

    return {
        "id": f"search-{index:03d}",
        "inventory": inventory,
        "base": base,
        "hit": hit,
        "target": target,
        "set_bonuses": bonuses,
        "expected": {
            "winner_ids": list(result.builds[0].artifact_ids),
            "winner_damage": result.builds[0].damage,
            "top_damages": [b.damage for b in result.builds],
            "evaluated": result.evaluated,
            "pareto_removed": result.prefilter.pareto_removed,
        },
    }


#: DAG quantity → the `FIGHT_PROP_*` the stat calculator maps back from. The generator speaks
#: quantities because the kernel does; the Python optimizer takes props.
def _prop_for(quantity: str) -> str:
    from app.services.stat_calculator import _PROP_QUANTITIES  # noqa: PLC0415

    for prop, q in _PROP_QUANTITIES.items():
        if q == quantity:
            return prop
    msg = f"no FIGHT_PROP for {quantity}"
    raise SystemExit(msg)


def generate(count: int = 40, per_slot: int = 4) -> dict[str, Any]:
    """The search fixtures, deterministically."""
    rng = random.Random(SEED)  # noqa: S311 - reproducible fixtures
    return {
        "note": (
            "Winners produced by app/services/artifact_optimizer.optimize. The browser "
            "kernel must pick the same build, within the f32 tolerance — see "
            "scripts/kernel/generate_search_cases.py on near-ties."
        ),
        "seed": SEED,
        "cases": [_case(rng, i, per_slot) for i in range(count)],
    }


def main() -> None:
    """Write the search fixtures."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = generate()
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {OUT.name}: {len(payload['cases'])} cases")


if __name__ == "__main__":
    main()
