"""C.1 — the differential-test case file, and whether it is usable.

DESIGN §6: the browser kernel is a **second damage chain**, and the gate that makes that
acceptable is a sweep of generated cases, not the two committed crossval fixtures.

**This file tests the harness, not the chain.** The cases were produced *by* the Python
chain, so replaying them through it would be circular if it were done the same way. It is
not: these replay **from the JSON**, reconstructing every input from the serialised case.
That catches the harness's real failure mode — a case file missing a field the kernel would
need, which would otherwise show up as "the kernel is wrong" when the file was incomplete.

## What anchors these to gcsim

Not directly. A case is a synthetic stat bundle with an arbitrary multiplier, and there is
no gcsim config that expresses one — gcsim simulates *characters*, not hypothetical stat
vectors. So the anchoring is **transitive**: `tests/crossval` pins the Python chain to gcsim
at 1.3e-8, and the chain generates these.

That is one link longer than DESIGN §6 implied when it said "gcsim confirms a sample", and
the difference is worth naming: **if the chain drifts from gcsim, these cases drift with it
silently.** What prevents that is the crossval suite running on every CI build with
`CROSSVAL_REQUIRE_DB=1`, so the anchor cannot skip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Amplifying, Hit, ScalingStat
from app.pando.calculator import NodeRegistry
from app.services.damage_calculator import BuildEvaluator, Enemy
from app.services.stat_calculator import build_log

CASES = Path(__file__).resolve().parents[1] / "fixtures" / "kernel" / "cases.json"


def _payload() -> dict:
    return json.loads(CASES.read_text())


def _replay(case: dict) -> dict[str, float]:
    """Recompute a case **from its serialised form**, touching nothing in-memory."""
    log = build_log(NodeRegistry())
    for quantity, value in case["stats"].items():
        log.add(quantity, value, tags.SRC_CHARACTER, "case")
    bonus = case["dmg_bonus"]
    log.add(tags.dmg_bonus_q(bonus["channel"]), bonus["value"], tags.SRC_ARTIFACT, "case")

    spec = case["hit"]
    hit = Hit(
        multiplier=spec["multiplier"],
        channel=spec["channel"],
        scope=spec["scope"],
        scaling_stat=ScalingStat(spec["scaling_stat"]),
        flat_damage=spec["flat_damage"],
        base_damage_bonus=spec["base_damage_bonus"],
        amplifying=Amplifying(spec["amplifying"]) if spec["amplifying"] else None,
        reaction_bonus=spec["reaction_bonus"],
    )
    enemy_spec = case["enemy"]
    enemy = Enemy(
        level=enemy_spec["level"],
        resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, enemy_spec["resistance"]),
        def_reduction=enemy_spec["def_reduction"],
        def_ignore=enemy_spec["def_ignore"],
    )
    result = BuildEvaluator(
        registry=log.registry, enemy=enemy, character_level=case["character_level"],
    ).evaluate(hit)
    return {"non_crit": result.non_crit, "crit": result.crit, "expected": result.expected}


def test_every_case_replays_from_json_alone():
    """The case file must contain everything needed to reproduce its own answer.

    If it does not, a kernel failing these would look wrong when the *fixture* was
    incomplete — and the first thing anyone would do is change the kernel.
    """
    cases = _payload()["cases"]
    assert len(cases) >= 1000, "a sweep this small cannot cover the surface it claims to"

    mismatches = [
        case["id"]
        for case in cases
        if _replay(case) != pytest.approx(case["expected"], rel=1e-12)
    ]

    assert not mismatches, (
        f"{len(mismatches)} cases do not reproduce from their serialised form "
        f"(first: {mismatches[:3]}). The case file is missing an input the chain reads."
    )


# ---- The sweep has to actually reach the edges it names ---------------------

def test_the_sweep_covers_every_scaling_stat_channel_and_scope():
    cases = _payload()["cases"]

    assert {c["hit"]["scaling_stat"] for c in cases} == {s.value for s in ScalingStat}
    assert {c["hit"]["channel"] for c in cases} == set(tags.DAMAGE_CHANNELS)
    assert {c["hit"]["scope"] for c in cases} == set(tags.SCOPES)


def test_the_sweep_covers_every_amplifying_reaction_and_none():
    amplifying = {c["hit"]["amplifying"] for c in _payload()["cases"]}

    assert None in amplifying, "no un-reacted hits — the common case would go untested"
    assert {a.value for a in Amplifying} <= amplifying


def test_the_sweep_reaches_past_the_crit_rate_cap():
    """`crit_multiplier` clamps at 100%. A kernel that does not is wrong *only* above the
    cap, which no ordinary case reaches — so the sweep has to."""
    over = [c for c in _payload()["cases"] if c["stats"][tags.Q_CRIT_RATE] > 1.0]

    assert len(over) > 100, f"only {len(over)} cases exceed the crit cap"


def test_the_sweep_covers_all_three_resistance_branches():
    """The RES curve has three, and this repo deliberately treats 0.75 as continuous where
    gcsim's `>` reads as `>=` (CROSSVAL_gcsim.md). A sweep that missed the boundary would
    miss the one place the two are known to differ."""
    resistances = [c["enemy"]["resistance"] for c in _payload()["cases"]]

    assert any(r < 0 for r in resistances), "no negative resistance — the weakness branch"
    assert any(0 <= r < 0.75 for r in resistances), "no ordinary resistance"
    assert any(r == 0.75 for r in resistances), "nothing exactly on the boundary"
    assert any(r > 0.75 for r in resistances), "no high-resistance branch"


def test_the_sweep_combines_both_enemy_def_mechanics():
    """DEF reduction and DEF ignore combine, and combined wrongly here for a while. A sweep
    that only ever varied one would not have caught it."""
    both = [
        c for c in _payload()["cases"]
        if c["enemy"]["def_reduction"] > 0 and c["enemy"]["def_ignore"] > 0
    ]

    assert len(both) > 50, f"only {len(both)} cases exercise both DEF mechanics together"


def test_the_cases_are_deterministic():
    """A regenerated file must diff only when the chain's answers change — which is then a
    claim worth reviewing, rather than noise that trains people to ignore the diff."""
    from scripts.kernel.generate_cases import generate

    regenerated = generate(count=25)["cases"]
    committed = _payload()["cases"][:25]

    assert [c["id"] for c in regenerated] == [c["id"] for c in committed]
    assert [c["expected"] for c in regenerated] == [c["expected"] for c in committed]
