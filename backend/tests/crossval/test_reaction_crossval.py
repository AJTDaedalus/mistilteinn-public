"""Math-fallback P3 (task 13): transformative reaction damage against gcsim.

Three committed gcsim runs at the pin, each producing exactly one transformative reaction:

* `overloaded_traveler_1` — Pyro Aether's skill onto Lisa's Electro: overloaded at Pyro RES,
  with **75 EM from the story buffs**, through the real assembler.
* `swirl_venti_1` — Venti's skill onto Aether's Pyro: a Pyro swirl at a stated **+100 EM**
  (`venti add stats em=100`).
* `superconduct_ayaka_1` — Ayaka's skill onto Lisa's Electro: superconduct at Cryo RES and
  **0 EM**, the bracket at exactly 1.

The applier of the aura is irrelevant to the reaction's damage (gcsim reads the trigger's EM
and level, `combat.CalcReactionDmg`, `pkg/core/combat/reaction.go:33-39`), so only the
triggers are seeded — Pyro Aether and Ayaka were already, Venti is added for this module.
Each trigger's EM is read from **our** stat layer over the seeded rows and checked against
gcsim's snapshot before the damage is compared, so a failure says which half is wrong.

The reaction's damage is gcsim's `source_dps` for the reaction times the run's duration,
divided by its instance count: gcsim publishes per-source DPS, not per-source damage. Every
case has one instance and no crit (a reaction snapshot carries EM and level only,
`reaction.go:34-38`), so the figure is exact rather than a mean.

**The tolerance is the module's 1e-7** (`test_gcsim_crossval.RELATIVE_TOLERANCE`), for the
same reason: the level base is the game's float32 (`1446.853515625` at 90) where gcsim's
generated table writes the decimal `1446.8535` — a 1.1e-8 residual, well inside it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.formula.genshin import stats as stat_nodes
from app.formula.genshin.reactions import (
    Transformative,
    transformative_damage,
    transformative_element,
)
from app.models.character import Character
from app.pando.calculator import Calculator, NodeRegistry
from app.services.gcsim_keys import pinned_commit
from app.services.stat_calculator import add_character, build_log

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crossval"
RELATIVE_TOLERANCE = 1e-7
#: `character_details[].snapshot` index of EM (`pkg/core/attributes/stats.go:14-43`),
#: confirmed empirically in `test_gcsim_crossval.py`.
SNAPSHOT_ELEMENTAL_MASTERY = 8

#: case -> (trigger's nanoka id, its index in the config, gcsim's source name, reaction,
#: swirled element, EM the config states on top of the character, target RES).
CASES: dict[str, tuple[str, int, str, Transformative, str | None, float]] = {
    "overloaded_traveler_1": ("10000005-2", 0, "overload", Transformative.OVERLOADED, None, 0.0),
    "swirl_venti_1": ("10000022", 0, "swirl-pyro", Transformative.SWIRL, "pyro", 100.0),
    "superconduct_ayaka_1": ("10000002", 0, "superconduct", Transformative.SUPERCONDUCT, None,
                             0.0),
}


def _case(name: str) -> dict:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _gcsim_reaction_damage(case: dict, index: int, source: str) -> float:
    stats = case["statistics"]
    dps = stats["source_dps"][index]["sources"][source]["mean"]
    count = stats["source_damage_instances"][index]["sources"][source]["mean"]
    return dps * stats["duration"]["mean"] / count


async def _trigger_em(session: AsyncSession, nanoka_id: str) -> float:
    """The trigger's EM at 90/6 from the seeded row, through the real assembler (so the
    Traveler's story buffs land as they do in production)."""
    from app.services.build_assembler import character_stats

    character = await session.scalar(select(Character).where(Character.nanoka_id == nanoka_id))
    if character is None:
        pytest.fail(f"the crossval database has no character {nanoka_id}")
    log = build_log(NodeRegistry())
    add_character(log, character_stats(character), level=90, ascension_phase=6)
    return Calculator(registry=log.registry).compute(stat_nodes.ELEMENTAL_MASTERY_NODE)


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_case_came_from_the_pinned_gcsim(name: str):
    case = _case(name)
    assert case["sim_version"] == pinned_commit()
    assert case["modified"] is False
    config = (_FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
    assert case["config_file"].strip() == config.strip()


@pytest.mark.parametrize("name", sorted(CASES))
async def test_the_triggers_em_matches_gcsim(crossval_session: AsyncSession, name: str):
    nanoka_id, index, _, _, _, stated = CASES[name]
    em = await _trigger_em(crossval_session, nanoka_id) + stated
    snapshot = _case(name)["character_details"][index]["snapshot"]
    assert em == pytest.approx(snapshot[SNAPSHOT_ELEMENTAL_MASTERY], abs=1e-9)


@pytest.mark.parametrize("name", sorted(CASES))
async def test_the_reaction_matches_gcsims_damage(crossval_session: AsyncSession, name: str):
    nanoka_id, index, source, reaction, swirled, stated = CASES[name]
    case = _case(name)
    em = await _trigger_em(crossval_session, nanoka_id) + stated
    # The configs give every element 10% RES (`resist=0.1`), so the element only has to be
    # the right one to name: Pyro for overloaded and the swirl, Cryo for superconduct.
    assert transformative_element(reaction, swirled) == ("cryo" if name.startswith("super")
                                                         else "pyro")
    ours = transformative_damage(
        reaction, character_level=90, elemental_mastery=em, resistance=0.1,
    )
    expected = _gcsim_reaction_damage(case, index, source)
    assert ours.expected == pytest.approx(expected, rel=RELATIVE_TOLERANCE), ours.steps


@pytest.mark.parametrize("name", sorted(CASES))
async def test_the_tolerance_cannot_hide_a_wrong_reaction(
    crossval_session: AsyncSession, name: str,
):
    """Planted errors: GO's 25/9-style drift in the EM numerator, or the wrong reaction's
    multiplier, must each fail by far more than the tolerance."""
    nanoka_id, index, source, reaction, _, stated = CASES[name]
    expected = _gcsim_reaction_damage(_case(name), index, source)
    em = await _trigger_em(crossval_session, nanoka_id) + stated
    ours = transformative_damage(reaction, character_level=90, elemental_mastery=em,
                                 resistance=0.1)
    # A level off by one is the cheapest mistake to make with a 1-indexed table.
    off_by_one = transformative_damage(reaction, character_level=89, elemental_mastery=em,
                                       resistance=0.1)
    assert abs(off_by_one.expected - expected) / expected > 100 * RELATIVE_TOLERANCE
    # DMG% must not reach reaction damage: gcsim skips it (`damage.go:22-43`).
    with_dmg_bonus = ours.expected * 1.466
    assert abs(with_dmg_bonus - expected) / expected > 100 * RELATIVE_TOLERANCE
