"""C.2 — the f32 tolerance is derived and cannot hide a formula error.

`docs/CROSSVAL_gcsim.md` argues **1e-6** for the browser kernel. This is the executable half:
prose that nothing checks drifts from the code it describes, and a tolerance is exactly the
sort of number that gets quietly widened when something fails.

Both properties the argument rests on are asserted here against the real 2,000-case sweep:

1. **f32 arithmetic fits inside it** — otherwise the kernel fails for reasons that are not
   bugs, and the tolerance gets widened under pressure, which is how a tolerance stops
   meaning anything.
2. **No plausible formula error does** — the property `tests/crossval` already asserts for
   the float64 chain, re-established for this one.

`chain_in_f32` is not the kernel. It is a faithful f32 model of the chain, used to measure
what f32 costs *before* a kernel exists to blame.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.formula.genshin import tags
from app.formula.genshin.damage import (
    Amplifying,
    amplifying_multiplier,
    crit_multiplier,
    def_multiplier,
    res_multiplier,
)

#: The tolerance `docs/CROSSVAL_gcsim.md` argues. One definition, imported by anything that
#: needs it, so widening it is a visible edit rather than a scattered one.
F32_TOLERANCE = 1e-6

CASES = Path(__file__).resolve().parents[1] / "fixtures" / "kernel" / "cases.json"

_SCALING = {
    "atk": (tags.Q_BASE_ATK, tags.Q_ATK_PCT, tags.Q_FLAT_ATK),
    "hp": (tags.Q_BASE_HP, tags.Q_HP_PCT, tags.Q_FLAT_HP),
    "def": (tags.Q_BASE_DEF, tags.Q_DEF_PCT, tags.Q_FLAT_DEF),
}


def _cases() -> list[dict]:
    return json.loads(CASES.read_text())["cases"]


def chain_in_f32(case: dict) -> float:
    """The chain, every operation in `float32`. A model of what the kernel must do."""
    f32 = np.float32
    stats, hit, enemy = case["stats"], case["hit"], case["enemy"]

    if hit["scaling_stat"] == "elemental_mastery":
        scaling = f32(stats[tags.Q_ELEMENTAL_MASTERY])
    else:
        base_q, pct_q, flat_q = _SCALING[hit["scaling_stat"]]
        scaling = f32(stats[base_q]) * (f32(1) + f32(stats[pct_q])) + f32(stats[flat_q])

    value = (
        f32(hit["multiplier"]) * scaling * (f32(1) + f32(hit["base_damage_bonus"]))
        + f32(hit["flat_damage"])
    )
    value = value * (f32(1) + f32(case["dmg_bonus"]["value"]))
    value = value * f32(def_multiplier(
        case["character_level"], enemy["level"], enemy["def_reduction"], enemy["def_ignore"],
    ))
    value = value * f32(res_multiplier(enemy["resistance"]))
    if hit["amplifying"]:
        value = value * f32(amplifying_multiplier(
            Amplifying(hit["amplifying"]),
            stats[tags.Q_ELEMENTAL_MASTERY],
            hit["reaction_bonus"],
        ))
    return float(value * f32(crit_multiplier(
        stats[tags.Q_CRIT_RATE], stats[tags.Q_CRIT_DMG],
    )))


def _relative(got: float, want: float) -> float:
    return abs(got - want) / abs(want) if want else 0.0


# ---- 1. f32 fits inside the tolerance --------------------------------------

def test_f32_arithmetic_fits_inside_the_tolerance():
    """If it does not, the kernel fails for reasons that are not bugs — and the tolerance
    gets widened under pressure, which is how a tolerance stops meaning anything."""
    divergences = [
        _relative(chain_in_f32(case), case["expected"]["expected"])
        for case in _cases()
        if case["expected"]["expected"] != 0
    ]

    worst = max(divergences)
    assert worst < F32_TOLERANCE, (
        f"f32 diverges by {worst:.3e}, past the {F32_TOLERANCE:.0e} tolerance "
        f"docs/CROSSVAL_gcsim.md argues. Re-derive the tolerance from the measurement "
        f"rather than widening it to fit."
    )


def test_the_tolerance_is_not_wastefully_loose():
    """A tolerance far above what the arithmetic needs is one that has stopped being derived.

    This is the guard against the easy fix: if f32 gets *better*, the number should come down
    rather than sit as unexamined slack.
    """
    worst = max(
        _relative(chain_in_f32(case), case["expected"]["expected"])
        for case in _cases()
        if case["expected"]["expected"] != 0
    )

    assert worst * 100 > F32_TOLERANCE, (
        f"the tolerance is {F32_TOLERANCE / worst:.0f}x the measured worst case "
        f"({worst:.3e}). That is slack nobody derived; tighten it or re-argue it."
    )


# ---- 2. No plausible formula error fits inside it ---------------------------

def test_forgetting_the_crit_clamp_is_far_outside_the_tolerance():
    """`crit_multiplier` clamps at 100%. A kernel that does not is wrong only above the cap
    — invisible on ordinary builds, and exactly what the sweep goes past the cap for."""
    worst = min(
        _relative(1 + c["stats"][tags.Q_CRIT_RATE] * c["stats"][tags.Q_CRIT_DMG],
                  crit_multiplier(c["stats"][tags.Q_CRIT_RATE], c["stats"][tags.Q_CRIT_DMG]))
        for c in _cases()
        if c["stats"][tags.Q_CRIT_RATE] > 1.0
    )

    assert worst > F32_TOLERANCE * 100, f"only {worst / F32_TOLERANCE:.0f}x the tolerance"


def test_combining_the_def_mechanics_additively_is_far_outside_the_tolerance():
    """DEF reduction and DEF ignore combine multiplicatively; adding them is the natural
    mistake, and it combined wrongly in this repo for a while."""
    divergences = []
    for c in _cases():
        enemy = c["enemy"]
        if enemy["def_reduction"] <= 0 or enemy["def_ignore"] <= 0:
            continue
        right = def_multiplier(
            c["character_level"], enemy["level"], enemy["def_reduction"], enemy["def_ignore"],
        )
        wrong = def_multiplier(
            c["character_level"], enemy["level"],
            enemy["def_reduction"] + enemy["def_ignore"], 0.0,
        )
        divergences.append(_relative(wrong, right))

    assert divergences, "the sweep no longer combines both DEF mechanics"
    assert min(divergences) > F32_TOLERANCE * 100


def test_the_res_boundary_divergence_is_enormous():
    """At exactly 75% RES this repo takes the continuous branch and gcsim's `>` takes the
    other. It is the one place the two knowingly differ, and it is a 2.5x difference — a
    tolerance that could hide *this* would be hiding everything."""
    divergence = _relative(1 - 0.75 / 2, res_multiplier(0.75))

    assert divergence > F32_TOLERANCE * 100_000


def test_the_documented_tolerance_matches_the_constant():
    """Prose that nothing checks drifts from the code it describes."""
    doc = (Path(__file__).resolve().parents[3] / "docs" / "CROSSVAL_gcsim.md").read_text()

    assert "**`1e-6` relative**" in doc, (
        "docs/CROSSVAL_gcsim.md no longer states the f32 tolerance in the form this test "
        "reads. Keep the document and F32_TOLERANCE in step."
    )
    assert F32_TOLERANCE == 1e-6


def test_ci_runs_the_kernel_differential_gate():
    """The gate is only a gate if something runs it.

    `npm test` does not — the sweep reads a fixture from disk and Angular's test builder
    targets the browser, so it is a standalone Node script. That makes it exactly the shape
    that goes green by being forgotten, which is why `test_ci_runs_the_perf_gate.py` exists
    for the backend's equivalent.
    """
    import yaml

    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "test.yml").read_text(),
    )
    runs = [
        str(step.get("run", ""))
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    ]

    assert any("kernel:verify" in r for r in runs), (
        "no CI step runs the kernel differential gate. Without it a second damage chain "
        "exists with nothing binding it to the first, which is the whole hazard DESIGN §6 "
        "accepts the second chain under."
    )
