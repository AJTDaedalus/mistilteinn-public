"""Generate differential-test cases for the browser's reaction terms, with expected values.

    cd backend && python -m scripts.kernel.generate_reaction_cases

Math-fallback P3 (task 13). `frontend/src/app/sim/damage.ts` mirrors
`app/formula/genshin/reactions.py` — a second implementation, accepted on the same terms as
the talent chain's (`generate_cases.py`): a gate binds the two. This writes the gate's cases,
and `npm run kernel:verify` replays them through the TypeScript at the f32 tolerance.

Three families, each sweeping what can go wrong in it:

* **transformative** — every reaction, the swirled element, character levels 1-100 (the level
  base is read from the committed table and travels with the case, as the server sends it),
  EM to 1,500, a reaction bonus, all three RES branches, and a reaction CRIT only on the
  reactions GO lets crit;
* **additive** — a whole talent hit through `damage.compute_damage` with spread or aggravate
  on it, so the flat term's place in the chain (inside the base, under DMG%, DEF, RES and
  crit) is held, not just its value;
* **lunar** — both reactions with the character's own CRIT, reaching past 100%, and a base
  DMG bonus.

The anchor to gcsim is transitive, as for the talent cases: `tests/crossval` pins the Python
reaction chain to gcsim (`test_reaction_crossval.py`), and the chain generates these.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from app.data.snapshot import reaction_level_multiplier
from app.formula.genshin import tags
from app.formula.genshin.damage import Hit, ScalingStat, compute_damage
from app.formula.genshin.reactions import (
    SWIRL_ELEMENTS,
    TRANSFORMATIVE,
    Additive,
    Lunar,
    Transformative,
    lunar_damage,
    transformative_damage,
)

OUT = (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "kernel"
       / "reaction_cases.json")
SEED = 20261114
PER_FAMILY = 300


def _maybe(rng: random.Random, chance: float, low: float, high: float) -> float:
    """A value in [low, high] with probability `chance`, else 0: an optional field."""
    return round(rng.uniform(low, high), 4) if rng.random() < chance else 0.0


#: How often each optional field is present, named as `generate_cases.py` names its own.
_P_BONUS = 0.5
_P_CRIT = 0.4
_P_FLAT = 0.3
_P_BASE_BONUS = 0.2
_P_DEF_REDUCTION = 0.4
_P_DEF_IGNORE = 0.3


def _resistance(rng: random.Random) -> float:
    return rng.choice([
        round(rng.uniform(-0.5, 0.0), 4), round(rng.uniform(0.0, 0.74), 4), 0.75,
        round(rng.uniform(0.75, 0.95), 4),
    ])


def _transformative(rng: random.Random, index: int) -> dict[str, Any]:
    reaction = rng.choice(list(Transformative))
    swirled = rng.choice(SWIRL_ELEMENTS) if reaction is Transformative.SWIRL else None
    level = rng.randint(1, 100)
    em = round(rng.uniform(0, 1500), 4)
    bonus = _maybe(rng, _P_BONUS, 0, 1.0)
    res = _resistance(rng)
    crit_rate = crit_dmg = 0.0
    if TRANSFORMATIVE[reaction].crittable and rng.random() < _P_CRIT:
        crit_rate, crit_dmg = round(rng.uniform(0, 1.2), 4), round(rng.uniform(0, 1.5), 4)
    result = transformative_damage(
        reaction, character_level=level, elemental_mastery=em, resistance=res,
        reaction_bonus=bonus, crit_rate=crit_rate, crit_dmg=crit_dmg,
    )
    return {
        "id": f"transformative-{index:04d}", "kind": "transformative",
        "reaction": reaction.value, "swirled": swirled, "character_level": level,
        "level_base": reaction_level_multiplier(level), "elemental_mastery": em,
        "reaction_bonus": bonus, "resistance": res, "crit_rate": crit_rate,
        "crit_dmg": crit_dmg, "expected": result.expected,
    }


def _additive(rng: random.Random, index: int) -> dict[str, Any]:
    reaction = rng.choice(list(Additive))
    channel = "dendro" if reaction is Additive.SPREAD else "electro"
    level = rng.randint(1, 100)
    hit = Hit(
        multiplier=round(rng.uniform(0.3, 6.0), 4), channel=channel,
        scope=rng.choice(tags.SCOPES), scaling_stat=rng.choice(list(ScalingStat)),
        flat_damage=_maybe(rng, _P_FLAT, 0, 500),
        base_damage_bonus=_maybe(rng, _P_BASE_BONUS, 0, 0.5),
        reaction_bonus=_maybe(rng, _P_BONUS, 0, 0.6),
        additive=reaction,
    )
    inputs = {
        "scaling_value": round(rng.uniform(500, 40000), 4),
        "dmg_bonus": round(rng.uniform(0, 1.5), 4),
        "crit_rate": round(rng.uniform(0, 1.4), 4),
        "crit_dmg": round(rng.uniform(0.5, 3.0), 4),
        "elemental_mastery": round(rng.uniform(0, 1500), 4),
        "enemy_level": rng.randint(1, 110),
        "resistance": _resistance(rng),
        "def_reduction": _maybe(rng, _P_DEF_REDUCTION, 0, 0.6),
        "def_ignore": _maybe(rng, _P_DEF_IGNORE, 0, 0.5),
    }
    result = compute_damage(hit, character_level=level, **inputs)
    return {
        "id": f"additive-{index:04d}", "kind": "additive", "reaction": reaction.value,
        "character_level": level, "level_base": reaction_level_multiplier(level),
        "hit": {
            "multiplier": hit.multiplier, "scaling_stat": hit.scaling_stat.value,
            "flat_damage": hit.flat_damage, "base_damage_bonus": hit.base_damage_bonus,
            "reaction_bonus": hit.reaction_bonus,
        },
        **inputs, "expected": result.expected,
    }


def _lunar(rng: random.Random, index: int) -> dict[str, Any]:
    reaction = rng.choice(list(Lunar))
    level = rng.randint(1, 100)
    case = {
        "elemental_mastery": round(rng.uniform(0, 1500), 4),
        "resistance": _resistance(rng),
        "crit_rate": round(rng.uniform(0, 1.4), 4),
        "crit_dmg": round(rng.uniform(0.5, 3.0), 4),
        "reaction_bonus": _maybe(rng, _P_BONUS, 0, 0.8),
        "base_dmg_bonus": _maybe(rng, _P_BASE_BONUS, 0, 0.6),
    }
    result = lunar_damage(reaction, character_level=level, **case)
    return {
        "id": f"lunar-{index:04d}", "kind": "lunar", "reaction": reaction.value,
        "character_level": level, "level_base": reaction_level_multiplier(level), **case,
        "expected": result.expected,
    }


def generate(per_family: int = PER_FAMILY) -> dict[str, Any]:
    """Every family's cases, deterministically from one seed."""
    rng = random.Random(SEED)  # noqa: S311 - reproducible fixtures, not a security decision
    return {
        "note": (
            "Expected values produced by app/formula/genshin/reactions.py, which "
            "tests/crossval pins to gcsim. Regenerate with "
            "`python -m scripts.kernel.generate_reaction_cases`; a diff here is a claim that "
            "the reaction chain's answers changed."
        ),
        "seed": SEED,
        "cases": [_transformative(rng, i) for i in range(per_family)]
        + [_additive(rng, i) for i in range(per_family)]
        + [_lunar(rng, i) for i in range(per_family)],
    }


def main() -> None:
    """Write the case file."""
    payload = generate()
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parents[3])}: {len(payload['cases'])} cases")


if __name__ == "__main__":
    main()
