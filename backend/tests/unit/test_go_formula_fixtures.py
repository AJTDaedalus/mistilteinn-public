"""Math-fallback P1 — the formula estimate's buffs against Genshin Optimizer's formula.

**GO is the comparator for the formula estimate** (`docs/DECISIONS.md` §38). Each fixture
below is worked by hand from GO's formula and sheets at commit
`2c13fc40c4694fd8beae513493c4c8a7537173c6`, using **our** numbers throughout: the talent rows
are this repo's (the seeded catalogue, or the committed nanoka fixture), the set and
resonance values come out of `set_effects`/`resonance` resolving our pinned `param_list`s,
and the stat block is a stated build, as in `test_go_single_hit_fixtures.py`. Nothing of GO's
data tables is copied — only the shape of its formula, cited to file and line.

The figures are committed to `tests/fixtures/formula/go_fixtures.json` together with every
input, and the browser's synthetic recipe is held to them by
`frontend/scripts/verify-formula-recipe.mjs` (`npm run formula:verify`). So the same
hand-worked number binds the Python resolution here and the TypeScript application there.
This test fails if the committed file drifts from what the formula and the resolver give;
regenerate it with `python -m tests.unit.test_go_formula_fixtures` from `backend/`.

## GO's formula, as these figures use it

`libs/gi/wr/src/formula.ts` (`hit.dmg`, `:434-453`):

    dmg = (hit.base + hit.dmgInc) * (1 + hit.dmgBonus) * avgHit * enemy.def * resMulti * amp
    avgHit     = 1 + cappedCritRate * critDMG_                             # :442, cap :357
    enemy.def  = (lvl + 100) / ((enemyLvl + 100)(1 - defRed)(1 - defIgn)) # :490-503
    amp        = {1.5 | 2} * (baseAmpBonus + total.<reaction>_dmg_)        # :454-484
    baseAmpBonus = 1 + 25/9 * EM / (1400 + EM)                             # :257

`enemy.def` there is `min(1, …)` of a fraction whose denominator omits the attacker's own
term; GO's displayed figure and this repo's `(lvl+100)/((lvl+100)+(enemyLvl+100)…)` agree,
because `input.lvl` there is added back in `enemy.def`'s callers — `test_go_single_hit_fixtures`
uses the same 190/390, and so does this.

## The one divergence, recorded per fixture

**The amplifying EM coefficient.** GO writes `25/9` (2.7778); gcsim and this repo's chain
write **2.78** (`damage.py:AMPLIFYING_EM_NUMERATOR`, gcsim `damage.go:113`). The owner's
ruling is to follow gcsim for every constant, so `expected` uses 2.78 and `go_value` uses
25/9; each amplified fixture states the relative gap, which is ~1e-4 and nowhere near a ranking
difference. A fixture with no reaction has `expected == go_value` exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.formula.builder import const
from app.formula.genshin import resonance, set_effects, sheets, tags
from app.pando.calculator import NodeRegistry
from app.schemas.formula import FormulaBonusRead
from app.services.talent_scaling import parse_talent_row

GO_COMMIT = "2c13fc40c4694fd8beae513493c4c8a7537173c6"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "formula" / "go_fixtures.json"

#: Level 90 against level 100, `enemy.def`; 10% RES, `res()` below 75%.
GO_DEF = 190 / 390
GO_RES = 0.9
OUR_EM_COEFFICIENT = 2.78
GO_EM_COEFFICIENT = 25 / 9

#: Static 2-piece pools a fixture's 4-piece state also carries (the kernel applies them from
#: `/artifacts/set-bonuses`; Crimson Witch's 2-piece is FIGHT_PROP_FIRE_ADD_HURT 0.15).
CRIMSON_WITCH_TWO_PIECE = {"pyro_dmg_bonus": 0.15}

# Talent rows, verbatim. Xiangling's are the seeded catalogue's (nanoka 7.2.50, talent
# level 10); Ayaka's is the committed `nanoka_gi/detail/character_10000002.json` (7.0.51).
PYRONADO = ("Pyronado DMG|{param4:P}", [1.296, 1.584, 1.9728, 2.016])
GUOBA = ("Flame DMG|{param1:P}", [2.00304])
HYOUKA = ("Skill DMG|{param1:P}", [4.5448])


def _multiplier(row: tuple[str, list[float]]) -> float:
    [hit] = parse_talent_row([row[0]], row[1])
    return hit.multiplier


def _set_source(set_id: int, pieces: int, params: list[float],
                extra_rows: list[set_effects.AffixRow]) -> dict[str, Any]:
    rows = [set_effects.AffixRow(pieces=pieces, param_list=params, add_props=()), *extra_rows]
    (tier,) = set_effects.resolve_set(set_id, rows)
    assert tier.status not in ("stale", "uncurated"), tier.problem
    return {
        "id": f"set:{set_id}:{pieces}", "label": f"set {set_id} {pieces}pc",
        "citation": tier.citation, "bonus": FormulaBonusRead.of(tier.bonus).model_dump(),
    }


def _resonance_source(elements: list[str]) -> list[dict[str, Any]]:
    return [
        {"id": f"resonance:{r.key}", "label": r.name, "citation": r.citation,
         "bonus": FormulaBonusRead.of(r.bonus).model_dump()}
        for r in resonance.active(elements)
    ]


WITCH_PARAMS = [0.4, 0.15, 0.15, 0.5, 10, 0, 0, 0]
WITCH_TWO_PIECE_ROW = set_effects.AffixRow(
    pieces=2, param_list=[0.15], add_props=[{"prop_type": "FIGHT_PROP_FIRE_ADD_HURT",
                                             "value": 0.15}],
)

#: A stated Xiangling build at 90: base ATK is character + weapon, the rest artifacts.
XIANGLING_BASE = {
    "base_atk": 735.0, "atk_pct": 0.0, "flat_atk": 0.0, "base_hp": 10875.0, "hp_pct": 0.0,
    "flat_hp": 0.0, "base_def": 669.0, "def_pct": 0.0, "flat_def": 0.0,
    "elemental_mastery": 96.0, "crit_rate": 0.05, "crit_dmg": 0.5, "energy_recharge": 1.0,
}
XIANGLING_ARTIFACTS = {
    "atk_pct": 0.5, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466, "crit_rate": 0.3,
    "crit_dmg": 0.7, "elemental_mastery": 80.0,
}
AYAKA_BASE = {
    "base_atk": 950.0, "atk_pct": 0.0, "flat_atk": 0.0, "base_hp": 12858.0, "hp_pct": 0.0,
    "flat_hp": 0.0, "base_def": 784.0, "def_pct": 0.0, "flat_def": 0.0,
    "elemental_mastery": 0.0, "crit_rate": 0.05, "crit_dmg": 0.884, "energy_recharge": 1.0,
}
AYAKA_ARTIFACTS = {
    "atk_pct": 0.466, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466, "crit_rate": 0.2,
    "crit_dmg": 0.6,
}


def _go_hit(*, multiplier: float, atk: float, dmg_bonus: float, crit_rate: float,
            crit_dmg: float, em: float, amp_base: float | None, reaction_bonus: float,
            em_coefficient: float) -> float:
    """GO's `hit.dmg` (`formula.ts:434-453`) for an ATK hit, written out."""
    avg_hit = 1 + max(min(crit_rate, 1.0), 0.0) * crit_dmg
    amp = 1.0
    if amp_base is not None:
        amp = amp_base * (1 + em_coefficient * em / (1400 + em) + reaction_bonus)
    return multiplier * atk * (1 + dmg_bonus) * avg_hit * GO_DEF * GO_RES * amp


def _xiangling_totals(*, fervent: bool, witch_stacks: int) -> dict[str, float]:
    """Xiangling's totals: base + artifacts + (Fervent Flames) + CW 2pc + CW stacks."""
    atk_pct = XIANGLING_BASE["atk_pct"] + XIANGLING_ARTIFACTS["atk_pct"] + (0.25 if fervent else 0)
    return {
        "atk": XIANGLING_BASE["base_atk"] * (1 + atk_pct) + XIANGLING_ARTIFACTS["flat_atk"],
        # 2pc 15% + 7.5% per stack (GO `CrimsonWitchOfFlames/index.tsx:43`, (0.15 * i) / 2).
        "pyro": XIANGLING_ARTIFACTS["pyro_dmg_bonus"] + 0.15 + 0.075 * witch_stacks,
        "cr": XIANGLING_BASE["crit_rate"] + XIANGLING_ARTIFACTS["crit_rate"],
        "cd": XIANGLING_BASE["crit_dmg"] + XIANGLING_ARTIFACTS["crit_dmg"],
        "em": XIANGLING_BASE["elemental_mastery"] + XIANGLING_ARTIFACTS["elemental_mastery"],
    }


def _xiangling_hit(row: tuple[str, list[float]], totals: dict[str, float], *,
                   vaporize: bool, em_coefficient: float) -> float:
    return _go_hit(
        multiplier=_multiplier(row), atk=totals["atk"], dmg_bonus=totals["pyro"],
        crit_rate=totals["cr"], crit_dmg=totals["cd"], em=totals["em"],
        # Pyro onto Hydro is GO's `vaporize` × `pyro` → 1.5 (`formula.ts:464-467`); this
        # repo spells it `reverse_vaporize`. CW's 15% is `total.vaporize_dmg_` (`:466`).
        amp_base=1.5 if vaporize else None, reaction_bonus=0.15 if vaporize else 0.0,
        em_coefficient=em_coefficient,
    )


def _crimson_witch(coefficient: float) -> float:
    """**Fixture 1 — a conditional 4-piece.** Xiangling's Pyronado, reverse-vaporized, in
    Crimson Witch at **one** stack.

    GO: Pyronado `dmgNado: dmgNode('atk', dm.burst.dmgNado, 'burst', {premod: {pyro_dmg_:
    antiC6}})` (`Characters/Xiangling/index.tsx:138-140`; `antiC6` is 0 below C6). Crimson
    Witch `set4Pyro_dmg_ = lookup(condStack, {i: percent((0.15 * i) / 2)})` and `set4Vape =
    percent(0.15)` into `vaporize_dmg_` (`Artifacts/CrimsonWitchOfFlames/index.tsx:35-55`),
    the 2-piece `pyro_dmg_` 0.15 (`:22-27`).
    """
    totals = _xiangling_totals(fervent=False, witch_stacks=1)
    return _xiangling_hit(PYRONADO, totals, vaporize=True, em_coefficient=coefficient)


def _shattering_ice(coefficient: float) -> float:  # no reaction: the same either way
    """**Fixture 2 — a resonance.** Ayaka's Hyouka press in a Cryo/Cryo/Hydro/Pyro team,
    Shattering Ice **on**.

    GO: `press: dmgNode('atk', dm.skill.press, 'skill')` (`Characters/KamisatoAyaka/
    index.tsx:142`); Shattering Ice `greaterEq(teamSize, 4, greaterEq(tally.cryo, 2,
    equal(condSI, 'on', percent(0.15))))` into `critRate_` (`Resonance.tsx:147-158`).
    """
    atk = AYAKA_BASE["base_atk"] * (1 + AYAKA_ARTIFACTS["atk_pct"]) + AYAKA_ARTIFACTS["flat_atk"]
    return _go_hit(
        multiplier=_multiplier(HYOUKA), atk=atk, dmg_bonus=AYAKA_ARTIFACTS["cryo_dmg_bonus"],
        crit_rate=AYAKA_BASE["crit_rate"] + AYAKA_ARTIFACTS["crit_rate"] + 0.15,
        crit_dmg=AYAKA_BASE["crit_dmg"] + AYAKA_ARTIFACTS["crit_dmg"], em=0.0, amp_base=None,
        reaction_bonus=0.0, em_coefficient=coefficient,
    )


def _multi_target(coefficient: float) -> float:
    """**Fixture 3 — a multi-target total.** Six vaporized Pyronado spins, six dry ones, and
    four Guoba flames — the last with Crimson Witch at **zero** stacks, a per-row override
    (GO's newer "frames") where the others take the default three. Fervent Flames from a
    Pyro/Pyro/Hydro/Anemo team.

    GO: a multi-target is `sum(...targetNodes)` of `prod(constant(weight), hit_i)`
    (`libs/gi/wr/src/api.ts:195-230`). Guoba `press: dmgNode('atk', dm.skill.press,
    'skill')` (`Characters/Xiangling/index.tsx:128`); Fervent Flames `greaterEq(teamSize, 4,
    greaterEq(tally.pyro, 2, percent(0.25)))` into `atk_` (`Resonance.tsx:81-86`).
    """
    three = _xiangling_totals(fervent=True, witch_stacks=3)
    zero = _xiangling_totals(fervent=True, witch_stacks=0)
    return (
        6 * _xiangling_hit(PYRONADO, three, vaporize=True, em_coefficient=coefficient)
        + 6 * _xiangling_hit(PYRONADO, three, vaporize=False, em_coefficient=coefficient)
        + 4 * _xiangling_hit(GUOBA, zero, vaporize=False, em_coefficient=coefficient)
    )


def _row(row_id: str, label: str, move: str, count: float, row: tuple[str, list[float]],
         amplifying: str | None, conditionals: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": row_id, "label": label, "move": move, "count": count,
        "talent_row": {"label": row[0], "params": row[1]},
        "multiplier": _multiplier(row), "scaling_stat": "atk", "amplifying": amplifying,
        "conditionals": conditionals or {},
    }


# ── Math-fallback P2: kit sheets (task 10) ──────────────────────────────────────────────────
#
# Four more fixtures, the same method: GO's formula worked by hand from its sheets, our numbers.
# The kit sources are what `sheets.resolve` gives for a stated **giver** — the giver's pass-1
# stats written out, as the subject's build is — so the committed source is checked against
# the resolver here and applied by the browser in `formula:verify`. GO's figure is written from
# GO's sheet independently of the resolver: if the resolver read Bennett's total ATK instead of
# his base, or missed the C5 level boost, the committed source would change and the browser's
# total would leave `expected` (`test_a_planted_wrong_buff_fails`).
#
# Talent rows verbatim from the seeded catalogue (nanoka 7.2.51, P1 task 4's re-seed).
BENNETT_BURST_DMG = ("Skill DMG|{param1:P}", [4.1904])
KAZUHA_BURST_ADD = ("Additional Elemental DMG|{param3:P}", [4.7232, 2.16, 0.648])
BENNETT_BURST_ROWS = {
    10: sheets.TalentRow(["Skill DMG|{param1:P}", "ATK Bonus Ratio|{param4:P}"],
                         [4.1904, 0.108, 1270.2417, 1.008]),
    13: sheets.TalentRow(["Skill DMG|{param1:P}", "ATK Bonus Ratio|{param4:P}"],
                         [4.947, 0.1275, 1587.8221, 1.19]),
}
BENNETT_CONSTELLATIONS = {1: [0.2] + [0.0] * 9, 2: [0.7, 0.3] + [0.0] * 8,
                          6: [0.15] + [0.0] * 9}
KAZUHA_A4_PARAMS = [0.0004, 8.0] + [0.0] * 28

#: A stated Bennett at 90: base ATK is character + weapon (191.16 + 608), the rest artifacts.
#: Only the base is read by his burst (GO `own.base.atk`, Bennett.ts:100); the flat ATK and
#: ATK% are here so that reading his **total** instead would show.
BENNETT_GIVER_STATS = {"base_atk": 799.16, "atk_pct": 0.466, "flat_atk": 311.0}
BENNETT_BASE = {
    "base_atk": 799.16, "atk_pct": 0.0, "flat_atk": 0.0, "base_hp": 12397.0, "hp_pct": 0.0,
    "flat_hp": 0.0, "base_def": 771.0, "def_pct": 0.0, "flat_def": 0.0,
    "elemental_mastery": 0.0, "crit_rate": 0.05, "crit_dmg": 0.5, "energy_recharge": 1.267,
}
BENNETT_ARTIFACTS = {
    "atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466, "crit_rate": 0.3,
    "crit_dmg": 0.6,
}
#: A stated Kazuha at 90: base ATK character + weapon; EM 115.2 from his ascension plus a
#: 165-EM weapon substat, before artifacts.
KAZUHA_BASE = {
    "base_atk": 905.0, "atk_pct": 0.0, "flat_atk": 0.0, "base_hp": 13348.0, "hp_pct": 0.0,
    "flat_hp": 0.0, "base_def": 807.0, "def_pct": 0.0, "flat_def": 0.0,
    "elemental_mastery": 280.2, "crit_rate": 0.05, "crit_dmg": 0.5, "energy_recharge": 1.0,
}
KAZUHA_ARTIFACTS = {"elemental_mastery": 680.0, "flat_atk": 311.0, "crit_rate": 0.2,
                    "crit_dmg": 0.4}
#: Kazuha as a teammate: his pass-1 EM, stated (base 280.2 + artifacts 680).
KAZUHA_GIVER_STATS = {"elemental_mastery": 960.2, "base_atk": 905.0}


def _stated_registry(stats: dict[str, float]) -> NodeRegistry:
    registry = NodeRegistry()
    for quantity, value in stats.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return registry


def _bennett_giver(constellation: int, stats: dict[str, float]) -> sheets.Giver:
    return sheets.Giver(
        name="Bennett", nanoka_id="10000032", constellation=constellation, ascension_phase=6,
        talent_levels={"elemental_burst": 10},
        talent_rows={("elemental_burst", lv): row for lv, row in BENNETT_BURST_ROWS.items()},
        constellation_params=BENNETT_CONSTELLATIONS, passive_params={},
        registry=_stated_registry(stats),
    )


def _kazuha_giver(stats: dict[str, float]) -> sheets.Giver:
    return sheets.Giver(
        name="Kaedehara Kazuha", nanoka_id="10000047", constellation=0, ascension_phase=6,
        talent_levels={"elemental_burst": 10}, talent_rows={}, constellation_params={},
        passive_params={4: KAZUHA_A4_PARAMS}, registry=_stated_registry(stats),
    )


def _kit_source(nanoka_id: str, giver: sheets.Giver, *, subject: bool) -> dict[str, Any]:
    sheet = sheets.sheet_for(nanoka_id)
    assert sheet is not None
    kit = sheets.resolve(sheet, giver, giver_is_subject=subject)
    return {"id": kit.source_id, "label": kit.label, "citation": kit.citation,
            "bonus": FormulaBonusRead.of(kit.bonus).model_dump()}


def _bennett_on_xiangling(coefficient: float) -> float:
    """**Fixture 4 — a teammate's kit buff from the giver's own stats.** Xiangling's Pyronado
    with a **C6** Bennett's field: stored burst 10, so 13 after C5.

    GO: `activeInAreaAtk = prod(inAreaActive, sum(burstAtkRatio, c1AtkRatio), own.base.atk)`
    into `teamBuff.final.atk` (`pando Bennett.ts:95-101,132`; WR `teamBuff.total.atk`,
    `index.tsx:98-114,189-192`), `burstAtkRatio` at `own.char.burst`, which C5 raises by 3
    (`:128`); C6 `teamBuff.premod.dmg_.pyro` 15% (`:107-110,133`).
    """
    atk = (XIANGLING_BASE["base_atk"] * (1 + XIANGLING_ARTIFACTS["atk_pct"])
           + XIANGLING_ARTIFACTS["flat_atk"] + (1.19 + 0.2) * BENNETT_GIVER_STATS["base_atk"])
    return _go_hit(
        multiplier=_multiplier(PYRONADO), atk=atk,
        dmg_bonus=XIANGLING_ARTIFACTS["pyro_dmg_bonus"] + 0.15,
        crit_rate=XIANGLING_BASE["crit_rate"] + XIANGLING_ARTIFACTS["crit_rate"],
        crit_dmg=XIANGLING_BASE["crit_dmg"] + XIANGLING_ARTIFACTS["crit_dmg"], em=0.0,
        amp_base=None, reaction_bonus=0.0, em_coefficient=coefficient,
    )


def _bennett_on_himself(coefficient: float) -> float:
    """**Fixture 5 — a giver who is the optimized character.** A C0 Bennett's burst DMG, in
    his own field (the default when he is the subject: his own doing).

    GO: `dmg('burst', info, 'atk', dm.burst.dmg, 'burst')` (`pando Bennett.ts:165`) reads
    `final.atk`, into which his own `teamBuff.final.atk` reaches (`destIsActive`: he is).
    """
    atk = (BENNETT_BASE["base_atk"] * (1 + BENNETT_ARTIFACTS["atk_pct"])
           + BENNETT_ARTIFACTS["flat_atk"] + 1.008 * BENNETT_BASE["base_atk"])
    return _go_hit(
        multiplier=_multiplier(BENNETT_BURST_DMG), atk=atk,
        dmg_bonus=BENNETT_ARTIFACTS["pyro_dmg_bonus"],
        crit_rate=BENNETT_BASE["crit_rate"] + BENNETT_ARTIFACTS["crit_rate"],
        crit_dmg=BENNETT_BASE["crit_dmg"] + BENNETT_ARTIFACTS["crit_dmg"], em=0.0,
        amp_base=None, reaction_bonus=0.0, em_coefficient=coefficient,
    )


def _kazuha_on_xiangling(coefficient: float) -> float:
    """**Fixture 6 — a teammate's buff from a stat artifacts move** (the giver's, so a number).
    Xiangling's Pyronado after Kazuha swirled Pyro.

    GO: `teamBuff.premod.dmg_[ele].add(prod(swirlByEleOn[ele], cmpGE(ascension, 4,
    prod(percent(dm.passive2.elemas_dmg_), own.premod.eleMas))))` (`pando
    KaedeharaKazuha.ts:154-166`; WR `index.tsx:107-124`).
    """
    atk = (XIANGLING_BASE["base_atk"] * (1 + XIANGLING_ARTIFACTS["atk_pct"])
           + XIANGLING_ARTIFACTS["flat_atk"])
    return _go_hit(
        multiplier=_multiplier(PYRONADO), atk=atk,
        dmg_bonus=XIANGLING_ARTIFACTS["pyro_dmg_bonus"]
        + 0.0004 * KAZUHA_GIVER_STATS["elemental_mastery"],
        crit_rate=XIANGLING_BASE["crit_rate"] + XIANGLING_ARTIFACTS["crit_rate"],
        crit_dmg=XIANGLING_BASE["crit_dmg"] + XIANGLING_ARTIFACTS["crit_dmg"], em=0.0,
        amp_base=None, reaction_bonus=0.0, em_coefficient=coefficient,
    )


def _kazuha_on_himself(coefficient: float) -> float:
    """**Fixture 7 — a self buff from a stat artifacts move, per candidate.** Kazuha's burst
    "Additional Elemental DMG", having absorbed Pyro, after he swirled Pyro: his A4 reads
    **his own** EM, base 280.2 plus the candidate's 680.

    GO: `dmg('burst_absorb_pyro', info, 'atk', dm.burst.add, 'burst', {ele: 'pyro', …})`
    (`pando KaedeharaKazuha.ts:214-219`); A4 as fixture 6, `own` being himself.
    """
    em = KAZUHA_BASE["elemental_mastery"] + KAZUHA_ARTIFACTS["elemental_mastery"]
    atk = KAZUHA_BASE["base_atk"] + KAZUHA_ARTIFACTS["flat_atk"]
    return _go_hit(
        multiplier=_multiplier(KAZUHA_BURST_ADD), atk=atk, dmg_bonus=0.0004 * em,
        crit_rate=KAZUHA_BASE["crit_rate"] + KAZUHA_ARTIFACTS["crit_rate"],
        crit_dmg=KAZUHA_BASE["crit_dmg"] + KAZUHA_ARTIFACTS["crit_dmg"], em=em,
        amp_base=None, reaction_bonus=0.0, em_coefficient=coefficient,
    )


def sheet_fixtures() -> list[dict[str, Any]]:
    """The P2 fixtures: kit buffs from Bennett and Kazuha, as teammates and as themselves."""
    xiangling = {"element": "pyro", "weapon_type": "WEAPON_POLE"}
    none = "none: no reaction"
    return [
        {
            "name": "bennett_c6_on_xiangling",
            "covers": "a teammate's kit buff from the giver's base ATK, with C1, C5 and C6",
            "go": [
                "libs/gi/wr/src/formula.ts:357,434-453",
                "libs/gi/formula/src/data/char/Bennett.ts:59,71,80-82,93-101,107-110,128,132-133",
                "libs/gi/sheets/src/Characters/Bennett/index.tsx:98-114,133-137,184-196",
            ],
            "givers": [{"name": "Bennett", "constellation": 6, "talent_levels":
                        {"elemental_burst": 10}, "stats": BENNETT_GIVER_STATS}],
            "team": {**xiangling, "member_elements": ["pyro", "pyro"]},
            "base": XIANGLING_BASE, "artifacts": XIANGLING_ARTIFACTS, "set_pools": [],
            "channel": "pyro",
            "rows": [_row("nado", "Pyronado DMG", "burst", 1, PYRONADO, None)],
            "sources": [_kit_source("10000032", _bennett_giver(6, BENNETT_GIVER_STATS),
                                    subject=False)],
            "conditionals": {"kit:bennett/in_field": 1},
            "expected": _bennett_on_xiangling(OUR_EM_COEFFICIENT),
            "go_value": _bennett_on_xiangling(GO_EM_COEFFICIENT),
            "divergence": none,
        },
        {
            "name": "bennett_burst_on_himself",
            "covers": "a giver who is the optimized character: his own field, by default",
            "go": [
                "libs/gi/wr/src/formula.ts:357,434-453",
                "libs/gi/formula/src/data/char/Bennett.ts:59,93-101,132,165",
            ],
            "givers": [{"name": "Bennett", "constellation": 0, "talent_levels":
                        {"elemental_burst": 10}, "stats": {"base_atk": BENNETT_BASE["base_atk"]}}],
            "team": {"element": "pyro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
                     "member_elements": ["pyro", "anemo"]},
            "base": BENNETT_BASE, "artifacts": BENNETT_ARTIFACTS, "set_pools": [],
            "channel": "pyro",
            "rows": [_row("burst", "Skill DMG", "burst", 1, BENNETT_BURST_DMG, None)],
            "sources": [_kit_source(
                "10000032", _bennett_giver(0, {**BENNETT_BASE, **BENNETT_ARTIFACTS}),
                subject=True)],
            "conditionals": {},
            "expected": _bennett_on_himself(OUR_EM_COEFFICIENT),
            "go_value": _bennett_on_himself(GO_EM_COEFFICIENT),
            "divergence": none,
        },
        {
            "name": "kazuha_a4_pyro_on_xiangling",
            "covers": "a teammate's kit buff from the giver's EM (two-pass: his EM first)",
            "go": [
                "libs/gi/wr/src/formula.ts:357,434-453",
                "libs/gi/formula/src/data/char/KaedeharaKazuha.ts:65-67,94-107,154-166",
                "libs/gi/sheets/src/Characters/KaedeharaKazuha/index.tsx:107-124,234-238",
            ],
            "givers": [{"name": "Kaedehara Kazuha", "constellation": 0, "ascension_phase": 6,
                        "stats": KAZUHA_GIVER_STATS}],
            "team": {**xiangling, "member_elements": ["pyro", "anemo"]},
            "base": XIANGLING_BASE, "artifacts": XIANGLING_ARTIFACTS, "set_pools": [],
            "channel": "pyro",
            "rows": [_row("nado", "Pyronado DMG", "burst", 1, PYRONADO, None)],
            "sources": [_kit_source("10000047", _kazuha_giver(KAZUHA_GIVER_STATS),
                                    subject=False)],
            "conditionals": {"kit:kaedehara_kazuha/swirl_pyro": 1},
            "expected": _kazuha_on_xiangling(OUR_EM_COEFFICIENT),
            "go_value": _kazuha_on_xiangling(GO_EM_COEFFICIENT),
            "divergence": none,
        },
        {
            "name": "kazuha_a4_on_his_own_burst",
            "covers": "a self buff from a stat artifacts move: per-candidate EM conversion",
            "go": [
                "libs/gi/wr/src/formula.ts:357,434-453",
                "libs/gi/formula/src/data/char/KaedeharaKazuha.ts:57,65-67,154-166,214-219",
            ],
            "givers": [{"name": "Kaedehara Kazuha", "constellation": 0, "ascension_phase": 6,
                        "stats": "the optimized character: his EM is the candidate's"}],
            "team": {"element": "anemo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
                     "member_elements": ["anemo", "pyro"]},
            "base": KAZUHA_BASE, "artifacts": KAZUHA_ARTIFACTS, "set_pools": [],
            "channel": "pyro",
            "rows": [_row("absorb", "Additional Elemental DMG", "burst", 1, KAZUHA_BURST_ADD,
                          None)],
            "sources": [_kit_source("10000047", _kazuha_giver({**KAZUHA_BASE}), subject=True)],
            "conditionals": {"kit:kaedehara_kazuha/swirl_pyro": 1},
            "expected": _kazuha_on_himself(OUR_EM_COEFFICIENT),
            "go_value": _kazuha_on_himself(GO_EM_COEFFICIENT),
            "divergence": none,
        },
    ]


def build() -> dict[str, Any]:
    """Every fixture, inputs and figures, as the committed file holds them."""
    witch = _set_source(15006, 4, WITCH_PARAMS, [WITCH_TWO_PIECE_ROW])
    xiangling_team = {"element": "pyro", "weapon_type": "WEAPON_POLE"}
    fixtures = [
        {
            "name": "crimson_witch_one_stack_reverse_vaporize",
            "covers": "a conditional 4-piece set (stacks, reaction bonus)",
            "go": [
                "libs/gi/wr/src/formula.ts:257,357,434-484",
                "libs/gi/sheets/src/Characters/Xiangling/index.tsx:138-140",
                "libs/gi/sheets/src/Artifacts/CrimsonWitchOfFlames/index.tsx:22-55",
            ],
            "team": {**xiangling_team, "member_elements": ["pyro", "hydro", "cryo"]},
            "base": XIANGLING_BASE, "artifacts": XIANGLING_ARTIFACTS,
            "set_pools": [CRIMSON_WITCH_TWO_PIECE],
            "channel": "pyro",
            "rows": [_row("nado", "Pyronado DMG", "burst", 1, PYRONADO, "reverse_vaporize")],
            "sources": [witch],
            "conditionals": {"set:15006:4/stacks": 1},
            "expected": _crimson_witch(OUR_EM_COEFFICIENT),
            "go_value": _crimson_witch(GO_EM_COEFFICIENT),
            "divergence": "amplifying EM coefficient: 2.78 (gcsim, ours) against GO's 25/9",
        },
        {
            "name": "shattering_ice_on",
            "covers": "an elemental resonance (Cryo, conditional)",
            "go": [
                "libs/gi/wr/src/formula.ts:357,434-453",
                "libs/gi/sheets/src/Characters/KamisatoAyaka/index.tsx:142",
                "libs/gi/sheets/src/Resonance.tsx:147-158",
            ],
            "team": {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
                     "member_elements": ["cryo", "cryo", "hydro", "pyro"]},
            "base": AYAKA_BASE, "artifacts": AYAKA_ARTIFACTS, "set_pools": [],
            "channel": "cryo",
            "rows": [_row("press", "Skill DMG", "skill", 1, HYOUKA, None)],
            "sources": _resonance_source(["cryo", "cryo", "hydro", "pyro"]),
            "conditionals": {"resonance:shattering_ice/enemy_cryo": 1},
            "expected": _shattering_ice(OUR_EM_COEFFICIENT),
            "go_value": _shattering_ice(GO_EM_COEFFICIENT),
            "divergence": "none: no reaction",
        },
        {
            "name": "xiangling_multi_target",
            "covers": "a multi-target recipe total, with a per-row conditional",
            "go": [
                "libs/gi/wr/src/api.ts:195-230",
                "libs/gi/wr/src/formula.ts:257,357,434-484",
                "libs/gi/sheets/src/Characters/Xiangling/index.tsx:128,138-140",
                "libs/gi/sheets/src/Artifacts/CrimsonWitchOfFlames/index.tsx:22-55",
                "libs/gi/sheets/src/Resonance.tsx:81-86",
            ],
            "team": {**xiangling_team, "member_elements": ["pyro", "pyro", "hydro", "anemo"]},
            "base": XIANGLING_BASE, "artifacts": XIANGLING_ARTIFACTS,
            "set_pools": [CRIMSON_WITCH_TWO_PIECE],
            "channel": "pyro",
            "rows": [
                _row("nado_vape", "Pyronado DMG (vaporize)", "burst", 6, PYRONADO,
                     "reverse_vaporize"),
                _row("nado", "Pyronado DMG", "burst", 6, PYRONADO, None),
                _row("guoba", "Flame DMG", "skill", 4, GUOBA, None,
                     {"set:15006:4/stacks": 0}),
            ],
            "sources": [*_resonance_source(["pyro", "pyro", "hydro", "anemo"]), witch],
            "conditionals": {},
            "expected": _multi_target(OUR_EM_COEFFICIENT),
            "go_value": _multi_target(GO_EM_COEFFICIENT),
            "divergence": "amplifying EM coefficient: 2.78 (gcsim, ours) against GO's 25/9",
        },
    ]
    fixtures.extend(sheet_fixtures())
    for f in fixtures:
        f["relative_divergence_from_go"] = abs(f["expected"] - f["go_value"]) / f["go_value"]
    return {
        "_about": (
            "GO-cited fixtures for the formula estimate. Generated by "
            "backend/tests/unit/test_go_formula_fixtures.py (run it as a module to rewrite); "
            "read by frontend/scripts/verify-formula-recipe.mjs."
        ),
        "go_commit": GO_COMMIT,
        "target": {"level": 100, "resistance": 0.1, "def_reduction": 0.0, "def_ignore": 0.0},
        "character_level": 90,
        "fixtures": fixtures,
    }


def test_the_committed_fixtures_are_what_the_formula_and_resolver_give():
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    built = json.loads(json.dumps(build()))
    assert committed["go_commit"] == built["go_commit"]
    assert [f["name"] for f in committed["fixtures"]] == [f["name"] for f in built["fixtures"]]
    for old, new in zip(committed["fixtures"], built["fixtures"], strict=True):
        assert old["sources"] == new["sources"], old["name"]
        assert old["rows"] == new["rows"], old["name"]
        assert old["expected"] == pytest.approx(new["expected"], rel=1e-12), old["name"]
        assert old["go_value"] == pytest.approx(new["go_value"], rel=1e-12), old["name"]


def test_the_known_figures():
    """The numbers themselves, so a reader can check them by hand against GO."""
    # Pyronado 2.016 x ATK 1,413.5 (735 x 1.5 + 311) x (1 + 0.691) x avgHit 1.42
    # (1 + 0.35 x 1.2) x 190/390 x 0.9 x amp 2.19069 (1.5 x (1 + 2.78 x 176/1,576 + 0.15)).
    assert _crimson_witch(OUR_EM_COEFFICIENT) == pytest.approx(6572.49, abs=0.01)
    # Hyouka 4.5448 x ATK 1,703.7 (950 x 1.466 + 311) x 1.466 x avgHit 1.5936
    # (1 + (0.05 + 0.2 + 0.15) x 1.484) x 190/390 x 0.9.
    assert _shattering_ice(OUR_EM_COEFFICIENT) == pytest.approx(7931.45, abs=0.01)


def test_the_divergence_is_only_the_em_coefficient():
    data = build()
    by_name = {f["name"]: f for f in data["fixtures"]}
    for name in ("shattering_ice_on", "bennett_c6_on_xiangling", "bennett_burst_on_himself",
                 "kazuha_a4_pyro_on_xiangling", "kazuha_a4_on_his_own_burst"):
        assert by_name[name]["relative_divergence_from_go"] == 0, name
    for name in ("crimson_witch_one_stack_reverse_vaporize", "xiangling_multi_target"):
        gap = by_name[name]["relative_divergence_from_go"]
        assert 0 < gap < 2e-4, name


def test_the_fixtures_would_catch_a_missing_buff():
    """Guards the guard: without the stacks (or the resonance) the figure is far off, so the
    fixtures are not passing by accident."""
    no_stack = _xiangling_hit(PYRONADO, _xiangling_totals(fervent=False, witch_stacks=0),
                              vaporize=True, em_coefficient=OUR_EM_COEFFICIENT)
    assert no_stack != pytest.approx(_crimson_witch(OUR_EM_COEFFICIENT), rel=0.01)


def test_the_kit_figures():
    """By hand, so a reader can check them against GO without running anything."""
    # Pyronado 2.016 x ATK 2,524.33 (735 x 1.5 + 311 + 1.39 x 799.16) x (1 + 0.616) x avgHit
    # 1.42 x 190/390 x 0.9.
    assert _bennett_on_xiangling(OUR_EM_COEFFICIENT) == pytest.approx(5120.33, abs=0.01)
    # Pyronado 2.016 x ATK 1,413.5 x (1 + 0.466 + 0.0004 x 960.2) x 1.42 x 190/390 x 0.9.
    assert _kazuha_on_xiangling(OUR_EM_COEFFICIENT) == pytest.approx(3282.44, abs=0.01)


def test_the_resolver_reads_the_givers_base_atk_not_his_total():
    """Guards the guard for sheets: a sheet that read Bennett's **total** ATK would resolve a
    different source, so the committed one — and `formula:verify`'s total — would move. The
    browser side of the same check plants a wrong value and watches the fixture fail."""
    committed = {f["name"]: f for f in json.loads(FIXTURE.read_text(encoding="utf-8"))["fixtures"]}
    sheet = sheets.sheet_for("10000032")
    assert sheet is not None
    wrong = sheet.model_copy(update={"effects": tuple(
        e.model_copy(update={"value": e.value.model_copy(update={"times_stat": "atk"})})
        if e.value.times_stat else e for e in sheet.effects)})
    kit = sheets.resolve(wrong, _bennett_giver(6, BENNETT_GIVER_STATS), giver_is_subject=False)
    wrong_values = [e.value for e in kit.bonus.effects]
    right_values = [e["value"] for e in
                    committed["bennett_c6_on_xiangling"]["sources"][0]["bonus"]["effects"]]
    assert wrong_values != pytest.approx(right_values, rel=1e-3)


def write() -> None:
    """Rewrite the committed fixture file from `build()`."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write()
