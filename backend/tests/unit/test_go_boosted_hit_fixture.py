"""Math-fallback 9b — a constellation-boosted single hit, against GO's formula (D-F4).

A C6 Xiangling with Pyronado **stored** at 9, as a GOOD export carries it. GO reads her burst
row at the **effective** level:

- `burstBoost: nodeC3`, with `nodeC3 = greaterEq(input.constellation, 3, 3)` —
  `libs/gi/sheets/src/Characters/Xiangling/index.tsx:155,160`;
- the boost is summed into `premod.burst` — `libs/gi/wr/src/formula.ts:271`;
- `burstIndex = total.burst - 1` — `formula.ts:348-350`;
- `dmgNado: dmgNode('atk', dm.burst.dmgNado, 'burst', …)` — `Xiangling/index.tsx:138` —
  subscripts the table by `total.burstIndex` (`Characters/dataUtil.tsx:179-182`).

So level 12, the twelfth entry. gcsim agrees (`internal/characters/xiangling/xiangling.go:21`:
`c.BurstCon = 3`, applied by `TalentLvlBurst`, `pkg/core/player/character/character.go:251-264`).

The row is our own, verbatim from the seeded catalogue (nanoka 7.2.50): `Pyronado
DMG|{param4:P}`, param4 = 1.904 at level 9 and 2.24 at level 12. GO's formula is
`test_go_single_hit_fixtures.py`'s; the build and target are the same as there: character 90
against enemy 100 (`enemy.def` = 190 / 390), 10% RES, 46.6% Pyro DMG bonus, 60% / 120% crit
(`avgHit` 1.72), 2,000 ATK, no reaction. Her C6 Pyro bonus is conditional and, in GO,
cancelled on Pyronado itself (`antiC6`, `index.tsx:117,138-140`), so it is not in the figure.

GO base = 2.24 x 2,000 = 4,480 -> 4,480 x 1.466 x 1.72 x 190/390 x 0.9 = 4,953.04.
At the stored level it would be 1.904 x 2,000 = 3,808 -> 4,210.08, 15% low.
"""

from __future__ import annotations

import types

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Hit
from app.formula.genshin.explain import ContributionLog
from app.models.enums import TalentType
from app.pando.calculator import NodeRegistry
from app.services.damage_calculator import Enemy, evaluate_hit
from app.services.talent_boosts import effective_talent_levels
from app.services.talent_hits import resolve_talent_hit

LABELS = [
    "1-Hit Swing DMG|{param1:P}", "2-Hit Swing DMG|{param2:P}", "3-Hit Swing DMG|{param3:P}",
    "Pyronado DMG|{param4:P}", "Duration|{param5:F1}s", "CD|{param6:F1}s",
    "Energy Cost|{param7:I}",
]
ROWS = {
    9: [1.224, 1.496, 1.8632, 1.904, 10, 20, 80],
    12: [1.44, 1.76, 2.192, 2.24, 10, 20, 80],
}

GO_DEF = 190 / 390
GO_RES = 0.9
GO_AVG_HIT = 1.72
DMG_BONUS = 0.466
ATK = 2000.0
TARGET = Enemy(level=100, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))


def _xiangling() -> types.SimpleNamespace:
    burst = types.SimpleNamespace(
        talent_type=TalentType.ELEMENTAL_BURST,
        scalings=[
            types.SimpleNamespace(level=level, labels=LABELS, params=params)
            for level, params in ROWS.items()
        ],
    )
    return types.SimpleNamespace(
        nanoka_id="10000023", name="Xiangling", element="Pyro", talents=[burst],
    )


def _pyronado(constellation: int) -> float:
    character = _xiangling()
    levels = effective_talent_levels(character, constellation, {"elemental_burst": 9})
    talent = resolve_talent_hit(character, levels, TalentType.ELEMENTAL_BURST, "Pyronado DMG")
    log = ContributionLog(registry=NodeRegistry())
    for quantity, value in {
        "base_atk": ATK, "crit_rate": 0.6, "crit_dmg": 1.2,
        tags.dmg_bonus_q("pyro"): DMG_BONUS,
    }.items():
        log.add(quantity, value, tags.SRC_CHARACTER, "fixture")
    hit = Hit(
        multiplier=talent.multiplier, channel="pyro", scope="burst",
        scaling_stat=talent.scaling_stat, extra_terms=talent.extra_terms,
    )
    return evaluate_hit(log.registry, hit, TARGET, character_level=90).expected


def test_a_c6_xiangling_pyronado_matches_go_at_the_effective_level() -> None:
    expected = 2.24 * ATK * (1 + DMG_BONUS) * GO_AVG_HIT * GO_DEF * GO_RES

    assert _pyronado(6) == pytest.approx(expected, rel=1e-9)
    assert _pyronado(6) == pytest.approx(4953.04, abs=0.01)


def test_a_c2_xiangling_pyronado_is_read_at_the_stored_level() -> None:
    assert _pyronado(2) == pytest.approx(4210.08, abs=0.01)
