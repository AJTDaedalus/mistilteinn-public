"""Generate differential-test cases for the browser kernel, with expected values.

    cd backend && python -m scripts.kernel.generate_cases

DESIGN §6: the client kernel is a **second damage chain**, which is the failure mode
§1 A6 exists to prevent. It is only acceptable with a gate, and the gate cannot be the
crossval fixtures — **there are two of them**, and two cases cannot catch a kernel that is
right on Ayaka-with-no-artifacts and wrong on DEF scaling, a capped crit rate, or an
amplifying reaction.

So the Python chain — which `tests/crossval` pins to gcsim at 1.3e-8 — generates expected
values for a **sweep of the whole input surface**, and the kernel must match all of them.

## Why this exists before any kernel code

A harness written after the kernel gets shaped to fit whatever the kernel already does.
Written first, it is shaped by the chain that is already verified, and the kernel has to come
to it. `TASKS_client_optimizer.md` C.1 says so, and this is that file.

## What is swept, and why each axis is here

Every axis below is one this repo has already had a bug in, or one where the chain does
something non-obvious:

* **scaling stat** — ATK/HP/DEF/EM. A DEF-scaling hit reads a different node; G.3's
  `_FLOOR_INPUTS` bug lived exactly here.
* **crit rate past 100%** — `crit_multiplier` clamps. A kernel that does not is wrong only
  above the cap, which no ordinary case reaches.
* **amplifying reactions** — the `2.78·EM/(1400+EM)` term, and the four reaction types with
  their 2.0/1.5 multipliers.
* **resistance below zero and above 75%** — the RES curve has three branches and this repo
  deliberately diverges from gcsim at exactly 0.75.
* **enemy DEF reduction and ignore** — two mechanics that combine, and combined wrongly for
  a while.
* **flat damage and base damage bonus** — added at different points in the chain, which is
  the sort of ordering a reimplementation gets subtly wrong.

Cases are deterministic: a fixed seed, so a regenerated file diffs only when the chain
changes — and a diff in this file is then a claim that the chain's answers changed, which is
exactly the kind of change that should be reviewed rather than absorbed.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from app.formula.genshin import tags
from app.formula.genshin.damage import Amplifying, Hit, ScalingStat
from app.pando.calculator import NodeRegistry
from app.services.damage_calculator import BuildEvaluator, Enemy
from app.services.stat_calculator import build_log

OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "kernel" / "cases.json"

SEED = 20260822

#: How often an optional field is present. Named rather than inline, so the sweep's shape is
#: readable: most cases exercise the common path, a healthy minority each rarer one.
_P_FLAT_DAMAGE = 0.3
_P_BASE_DMG_BONUS = 0.2
_P_AMPLIFYING = 0.4
_P_REACTION_BONUS = 0.2
_P_DEF_REDUCTION = 0.4
_P_DEF_IGNORE = 0.3

#: Stat pools a case can carry. Names are this repo's DAG quantities; the kernel will speak
#: the same vocabulary, because the alternative is a third translation layer to get wrong.
_STATS = (
    tags.Q_BASE_ATK, tags.Q_ATK_PCT, tags.Q_FLAT_ATK,
    tags.Q_BASE_HP, tags.Q_HP_PCT, tags.Q_FLAT_HP,
    tags.Q_BASE_DEF, tags.Q_DEF_PCT, tags.Q_FLAT_DEF,
    tags.Q_CRIT_RATE, tags.Q_CRIT_DMG, tags.Q_ELEMENTAL_MASTERY,
)


def _case(rng: random.Random, index: int) -> dict[str, Any]:
    """One randomised build-and-hit, plus what the Python chain says it does."""
    channel = rng.choice(tags.DAMAGE_CHANNELS)
    scaling = rng.choice(list(ScalingStat))

    stats = {
        tags.Q_BASE_ATK: round(rng.uniform(600, 1200), 4),
        tags.Q_BASE_HP: round(rng.uniform(10000, 40000), 4),
        tags.Q_BASE_DEF: round(rng.uniform(500, 1200), 4),
        tags.Q_ATK_PCT: round(rng.uniform(0, 2.0), 4),
        tags.Q_FLAT_ATK: round(rng.uniform(0, 600), 4),
        tags.Q_HP_PCT: round(rng.uniform(0, 2.0), 4),
        tags.Q_FLAT_HP: round(rng.uniform(0, 8000), 4),
        tags.Q_DEF_PCT: round(rng.uniform(0, 2.0), 4),
        tags.Q_FLAT_DEF: round(rng.uniform(0, 400), 4),
        # Deliberately reaches past 1.0 — `crit_multiplier` clamps, and a kernel that does
        # not is wrong only above the cap.
        tags.Q_CRIT_RATE: round(rng.uniform(0, 1.4), 4),
        tags.Q_CRIT_DMG: round(rng.uniform(0.5, 3.0), 4),
        tags.Q_ELEMENTAL_MASTERY: round(rng.uniform(0, 1200), 4),
    }
    dmg_bonus = round(rng.uniform(0, 1.5), 4)

    hit = Hit(
        multiplier=round(rng.uniform(0.5, 12.0), 4),
        channel=channel,
        scope=rng.choice(tags.SCOPES),
        scaling_stat=scaling,
        flat_damage=round(rng.uniform(0, 500), 4) if rng.random() < _P_FLAT_DAMAGE else 0.0,
        base_damage_bonus=(
            round(rng.uniform(0, 0.5), 4) if rng.random() < _P_BASE_DMG_BONUS else 0.0
        ),
        amplifying=rng.choice([None, *Amplifying]) if rng.random() < _P_AMPLIFYING else None,
        reaction_bonus=(
            round(rng.uniform(0, 0.4), 4) if rng.random() < _P_REACTION_BONUS else 0.0
        ),
    )

    # Resistance sweeps all three branches of the curve, including the 0.75 boundary this
    # repo deliberately treats as continuous (CROSSVAL_gcsim.md).
    resistance = rng.choice([
        round(rng.uniform(-0.5, 0.0), 4),
        round(rng.uniform(0.0, 0.74), 4),
        0.75,
        round(rng.uniform(0.75, 0.95), 4),
    ])
    enemy = Enemy(
        level=rng.randint(1, 110),
        resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, resistance),
        def_reduction=(
            round(rng.uniform(0, 0.6), 4) if rng.random() < _P_DEF_REDUCTION else 0.0
        ),
        def_ignore=(
            round(rng.uniform(0, 0.5), 4) if rng.random() < _P_DEF_IGNORE else 0.0
        ),
    )
    character_level = rng.randint(1, 90)

    log = build_log(NodeRegistry())
    for quantity, value in stats.items():
        log.add(quantity, value, tags.SRC_CHARACTER, "case")
    log.add(tags.dmg_bonus_q(channel), dmg_bonus, tags.SRC_ARTIFACT, "case")

    result = BuildEvaluator(
        registry=log.registry, enemy=enemy, character_level=character_level,
    ).evaluate(hit)

    return {
        "id": f"case-{index:04d}",
        "stats": stats,
        "dmg_bonus": {"channel": channel, "value": dmg_bonus},
        "hit": {
            "multiplier": hit.multiplier,
            "channel": hit.channel,
            "scope": hit.scope,
            "scaling_stat": hit.scaling_stat.value,
            "flat_damage": hit.flat_damage,
            "base_damage_bonus": hit.base_damage_bonus,
            "amplifying": hit.amplifying.value if hit.amplifying else None,
            "reaction_bonus": hit.reaction_bonus,
        },
        "enemy": {
            "level": enemy.level,
            "resistance": resistance,
            "def_reduction": enemy.def_reduction,
            "def_ignore": enemy.def_ignore,
        },
        "character_level": character_level,
        "expected": {
            "non_crit": result.non_crit,
            "crit": result.crit,
            "expected": result.expected,
        },
    }


def generate(count: int = 2000) -> dict[str, Any]:
    """The full case set, deterministically."""
    rng = random.Random(SEED)  # noqa: S311 - reproducible fixtures, not a security decision
    return {
        "note": (
            "Expected values produced by this repo's Python damage chain, which "
            "tests/crossval pins to gcsim at 1.3e-8. Regenerate with "
            "`python -m scripts.kernel.generate_cases`. A diff here is a claim that the "
            "chain's answers changed and should be reviewed as one."
        ),
        "seed": SEED,
        "cases": [_case(rng, i) for i in range(count)],
    }


def main() -> None:
    """Write the case file."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = generate()
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parents[3])}: {len(payload['cases'])} cases")


if __name__ == "__main__":
    main()
