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
    [hit] = parse_talent_row([row[0]], row[1])
    out: dict[str, Any] = {
        "id": row_id, "label": label, "move": move, "count": count,
        "talent_row": {"label": row[0], "params": row[1]},
        "multiplier": hit.multiplier, "scaling_stat": str(hit.scaling_stat),
        "amplifying": amplifying, "conditionals": conditionals or {},
    }
    if hit.extra_terms:
        # A mixed-stat row (Nefer's and Mitya's burst, `ATK + EM`): one hit, several terms.
        out["extra_terms"] = [{"stat": str(t.stat), "multiplier": t.multiplier}
                              for t in hit.extra_terms]
    return out


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


def _kit_source(nanoka_id: str, giver: sheets.Giver, *, subject: bool,
                receiver_element: str | None = None,
                team_elements: list[str] | None = None) -> dict[str, Any]:
    sheet = sheets.sheet_for(nanoka_id)
    assert sheet is not None
    kit = sheets.resolve(sheet, giver, giver_is_subject=subject,
                         receiver_element=receiver_element, team_elements=team_elements)
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


# ── Math-fallback P2, task 11: the characters gcsim cannot run ─────────────────────────────
#
# One fixture per sheet, on its main damage-relevant effect, by the same method: GO's formula
# worked by hand from its sheet, with our numbers. Talent rows are verbatim from the seeded
# catalogue (nanoka 7.2.51); constellation and passive lists are the sheets' pins (the seeded
# lists they were curated against). Builds are stated, as above.


def _res_multiplier(res: float) -> float:
    """GO `resMulti` (`formula.ts:505-514`), the three-branch curve this repo shares."""
    if res < 0:
        return 1 - res / 2
    return 1 - res if res < 0.75 else 1 / (4 * res + 1)


def _go_general(*, base: float, flat: float, dmg_bonus: float, crit_rate: float,
                crit_dmg: float, res_shred: float = 0.0) -> float:
    """GO `hit.dmg` for any scaling, no amplifying reaction: `(hit.base + dmgInc) × (1 +
    dmgBonus) × avgHit × enemy.def × resMulti` (`formula.ts:434-453`)."""
    avg_hit = 1 + max(min(crit_rate, 1.0), 0.0) * crit_dmg
    return ((base + flat) * (1 + dmg_bonus) * avg_hit * GO_DEF
            * _res_multiplier(0.1 + res_shred))


def _ungated_giver(name: str, nanoka_id: str, *, constellation: int = 0,
                   talent_levels: dict[str, int] | None = None,
                   talent_rows: dict[tuple[str, int], sheets.TalentRow] | None = None,
                   cons: dict[int, list[float]] | None = None,
                   passives: dict[int, list[float]] | None = None,
                   stats: dict[str, float] | None = None) -> sheets.Giver:
    return sheets.Giver(
        name=name, nanoka_id=nanoka_id, constellation=constellation, ascension_phase=6,
        talent_levels=talent_levels or {}, talent_rows=talent_rows or {},
        constellation_params=cons or {}, passive_params=passives or {},
        registry=_stated_registry(stats or {}),
    )


def _pinned(nanoka_id: str) -> tuple[dict[int, list[float]], dict[int, list[float]]]:
    """A sheet's pinned constellation and passive lists: the seeded rows it was curated on."""
    sheet = sheets.sheet_for(nanoka_id)
    assert sheet is not None
    return ({n: list(v) for n, v in sheet.pins.constellations.items()},
            {n: list(v) for n, v in sheet.pins.passives.items()})


def _stats(base: dict[str, float], artifacts: dict[str, float]) -> dict[str, float]:
    return {k: base.get(k, 0.0) + artifacts.get(k, 0.0) for k in {*base, *artifacts}}


def _total(stats: dict[str, float], stat: str, extra_pct: float = 0.0) -> float:
    return (stats[f"base_{stat}"] * (1 + stats.get(f"{stat}_pct", 0.0) + extra_pct)
            + stats.get(f"flat_{stat}", 0.0))


def _base_stats(**kw: float) -> dict[str, float]:
    out = {"base_atk": 0.0, "atk_pct": 0.0, "flat_atk": 0.0, "base_hp": 0.0, "hp_pct": 0.0,
           "flat_hp": 0.0, "base_def": 0.0, "def_pct": 0.0, "flat_def": 0.0,
           "elemental_mastery": 0.0, "crit_rate": 0.05, "crit_dmg": 0.5, "energy_recharge": 1.0}
    out.update(kw)
    return out


# Kachina: the subject, C0, skill 10. A1's Geo DMG (her own doing, on by default) and A4's 20%
# of her own DEF into the skill's base, per candidate.
KACHINA_INDEPENDENT = ("Turbo Twirly Independent DMG|{param2:F1P} DEF", [1.57968, 1.14768])
KACHINA_BASE = _base_stats(base_atk=674.0, base_hp=11799.0, base_def=792.0)
KACHINA_ARTIFACTS = {"def_pct": 0.874, "flat_def": 58.0, "geo_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.6}


def _kachina(_: float) -> float:
    """GO: `dmg('skill_independent', info, 'def', dm.skill.independentDmg, 'skill')` (`pando
    Kachina.ts:124`); `ownBuff.formula.base.skill.add(prod(percent(dm.passive2.dmgInc),
    own.premod.def))` (`:91-96,111`); `ownBuff.premod.dmg_.geo` from A1 (`:88-90,110`)."""
    stats = _stats(KACHINA_BASE, KACHINA_ARTIFACTS)
    defense = _total(stats, "def")
    return _go_general(base=_multiplier(KACHINA_INDEPENDENT) * defense, flat=0.2 * defense,
                       dmg_bonus=stats["geo_dmg_bonus"] + 0.2, crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"])


# Nefer: the subject, C0, burst 10, Ascendant Gleam on. A1: burst DMG 3 × the burst row's
# "DMG Bonus" (0.4 at 10), and 100 EM at three Veil stacks — both her own, at their maximum.
NEFER_BURST_HIT1 = ("1-Hit DMG|{param1:F1P} ATK+{param2:F1P} Elemental Mastery",
                    [4.04352, 8.08704])
NEFER_BURST_LABELS = ["1-Hit DMG|{param1:F1P} ATK+{param2:F1P} Elemental Mastery",
                      "2-Hit DMG|{param3:F1P} ATK+{param4:F1P} Elemental Mastery",
                      "DMG Bonus|{param5:F1P} Per Veil of Falsehood Stack", "CD|{param6:F1}s",
                      "Energy Cost|{param7:I}"]
NEFER_BURST_10 = [4.04352, 8.08704, 6.06528, 12.13056, 0.4, 15.0, 60.0]
NEFER_BASE = _base_stats(base_atk=820.0, base_hp=12560.0, base_def=790.0,
                         elemental_mastery=265.0, crit_dmg=0.884)
NEFER_ARTIFACTS = {"elemental_mastery": 400.0, "flat_atk": 311.0, "dendro_dmg_bonus": 0.466,
                   "crit_rate": 0.35, "crit_dmg": 0.5}


def _nefer(_: float) -> float:
    """GO: `splitScaleDmg('burst_hit1', info, ['atk', 'eleMas'], [hit1Atk, hit1EleMas],
    'burst')` (`pando Nefer.ts:270-276`); `ownBuff.premod.dmg_.burst` = veils ×
    `talentSubscript(burst, dmgPerStack)`, gated on A1 and moonsign >= 2 (`:126-137,212`);
    `ownBuff.premod.eleMas` = `passive1.maxVeilEleMas` at 3 Veils (`:153-166,213`)."""
    stats = _stats(NEFER_BASE, NEFER_ARTIFACTS)
    [hit] = parse_talent_row([NEFER_BURST_HIT1[0]], NEFER_BURST_HIT1[1])
    base = (hit.multiplier * _total(stats, "atk")
            + hit.extra_terms[0].multiplier * (stats["elemental_mastery"] + 100.0))
    return _go_general(base=base, flat=0.0, dmg_bonus=stats["dendro_dmg_bonus"] + 3 * 0.4,
                       crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


def _lohen_on_xiangling(coefficient: float) -> float:
    """**Lohen's A4 on a teammate.** Xiangling's Pyronado after a Cryo reaction in
    Masterstroke: GO `notOwnBuff.premod.atk_.add(a4MasterCryo ? passive2.teammateAtk_)`
    (`pando Lohen.ts:159-161,206-207`)."""
    atk = (XIANGLING_BASE["base_atk"] * (1 + XIANGLING_ARTIFACTS["atk_pct"] + 0.15)
           + XIANGLING_ARTIFACTS["flat_atk"])
    return _go_hit(
        multiplier=_multiplier(PYRONADO), atk=atk, dmg_bonus=XIANGLING_ARTIFACTS["pyro_dmg_bonus"],
        crit_rate=XIANGLING_BASE["crit_rate"] + XIANGLING_ARTIFACTS["crit_rate"],
        crit_dmg=XIANGLING_BASE["crit_dmg"] + XIANGLING_ARTIFACTS["crit_dmg"], em=0.0,
        amp_base=None, reaction_bonus=0.0, em_coefficient=coefficient,
    )


# Linnea: the subject, C4, skill stored 10 (13 after C3, the row GO reads). A1's Geo RES -15%
# (Lumi present: her own doing), C2's CRIT DMG to a Geo receiver, C4's DEF to herself and, in
# Moondrift, to the active character — who is she.
LINNEA_PUMMELER_13 = ("Lumi Pound-Pound Pummeler DMG|{param1:F1P} DEF \u00d72", [2.04])
LINNEA_BASE = _base_stats(base_atk=640.0, base_hp=10540.0, base_def=896.0, crit_rate=0.242)
LINNEA_ARTIFACTS = {"def_pct": 1.166, "flat_def": 39.0, "geo_dmg_bonus": 0.466,
                    "crit_rate": 0.25, "crit_dmg": 0.9}


def _linnea(_: float) -> float:
    """GO: `dmg('skill_pummelerDmg', info, 'def', dm.skill.pummelerDmg, 'skill')` (`pando
    Linnea.ts:270`); A1 `enemyDebuff.common.preRes.geo` = `-passive1.geo_enemyRes_` without
    moonsign (`:121-132,255`); C2 `teamBuff.premod.critDMG_` for a Hydro or Geo receiver
    (`:199-208,252`); C4 `ownBuff.premod.def_` and `teamBuff.premod.def_` to the active one
    (`:213-223,243,253`). One hit (the row's `×2` is its count)."""
    stats = _stats(LINNEA_BASE, LINNEA_ARTIFACTS)
    defense = _total(stats, "def", extra_pct=0.25 + 0.25)
    return _go_general(base=_multiplier(LINNEA_PUMMELER_13) * defense, flat=0.0,
                       dmg_bonus=stats["geo_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"] + 0.4, res_shred=-0.15)


# Mitya: the subject, C0, burst 10. A1's +30 EM per Gradient Beacon (4, his own) and A4's +5%
# CRIT Rate per stack (4).
MITYA_BURST = ("Skill DMG|{param1:F1P} ATK+{param2:F1P} Elemental Mastery", [6.0048, 12.0096])
MITYA_BASE = _base_stats(base_atk=780.0, base_hp=11990.0, base_def=816.0,
                         elemental_mastery=221.0, crit_dmg=0.884)
MITYA_ARTIFACTS = {"elemental_mastery": 300.0, "atk_pct": 0.466, "flat_atk": 311.0,
                   "electro_dmg_bonus": 0.466, "crit_rate": 0.25, "crit_dmg": 0.5}


def _mitya(_: float) -> float:
    """GO WR: `splitScaleDmgNode(['atk', 'eleMas'], [skillDmgAtk, skillDmgEleMas], 'burst')`
    (`Mitya/index.tsx:259-265`); `teamBuff.premod.eleMas` = beacons × `passive1.eleMas`
    (`:130-144,295`); `premod.critRate_` = stacks × `passive2.critRate_` (`:146-157,290`)."""
    stats = _stats(MITYA_BASE, MITYA_ARTIFACTS)
    [hit] = parse_talent_row([MITYA_BURST[0]], MITYA_BURST[1])
    base = (hit.multiplier * _total(stats, "atk")
            + hit.extra_terms[0].multiplier * (stats["elemental_mastery"] + 4 * 30.0))
    return _go_general(base=base, flat=0.0, dmg_bonus=stats["electro_dmg_bonus"],
                       crit_rate=stats["crit_rate"] + 4 * 0.05, crit_dmg=stats["crit_dmg"])


# Valeriy: the subject, C0, burst 10, normal attack 10. Offensive Directive (the normal-attack
# row's "Electro DMG Bonus", 0.43776 × ATK) and A4 at 100 Momentum (0.003 × ATK × 100): both flat
# Electro damage from his own ATK, per candidate.
VALERIY_BURST = ("Skill DMG|{param1:F1P}", [2.43216])
VALERIY_NORMAL_LABELS = [
    "1-Hit DMG|{param1:F1P}", "2-Hit DMG|{param2:F1P}", "3-Hit DMG|{param3:F1P}",
    "Charged Attack DMG|{param4:F1P}",
    "Direct-Fire Mortar: Point-Blank Bombardment DMG|{param5:F1P}",
    "Charged Attack Stamina Cost|{param6:F1}", "Electro DMG Bonus|{param7:F2P} ATK",
    "Stellar-Conduct DMG Bonus|{param8:F2P} ATK", "Offensive Directive Stacks|{param9:I}",
    "Offensive Directive Duration|{param10:F1}s", "Plunge DMG|{param11:F1P}",
    "Low/High Plunge DMG|{param12:F1P}/{param13:F1P}"]
VALERIY_NORMAL_10 = [0.642124, 0.5797, 0.897787, 1.9822, 4.1256, 20.0, 0.43776, 1.31328, 15.0,
                     18.0, 1.26378, 2.527025, 3.15639]
VALERIY_BASE = _base_stats(base_atk=860.0, atk_pct=0.24, base_hp=12000.0, base_def=845.0)
VALERIY_ARTIFACTS = {"atk_pct": 0.932, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.7}


def _valeriy(_: float) -> float:
    """GO WR: `dmgNode('atk', dm.burst.skillDmg, 'burst')` (`Valeriy/index.tsx:270`);
    `electro_dmgInc` = `subscript(autoIndex, charged.electro_dmgInc) × premod.atk` to the
    active (`:135-161,293`) and A4 `passive2.nonRadiance_dmg_ × premod.atk × momentum`
    (`:195-224`)."""
    stats = _stats(VALERIY_BASE, VALERIY_ARTIFACTS)
    atk = _total(stats, "atk")
    return _go_general(base=_multiplier(VALERIY_BURST) * atk,
                       flat=(0.43776 + 0.003 * 100) * atk,
                       dmg_bonus=stats["electro_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"])


# Vodyanitsa: the subject, C0, skill 10. Her skill's Hydro/Cryo RES reduction (the skill row's
# "Hydro/Cryo RES Reduction", 0.3 at 10) on her own Hydro skill hit.
VODYANITSA_SKILL = ("Skill DMG|{param1:F2P} Max HP", [0.058896])
VODYANITSA_SKILL_LABELS = [
    "Skill DMG|{param1:F2P} Max HP", "Duration|{param2:F1}s",
    "Horn of Spring's Call Attack Interval|{param3:F1}s",
    "Horn of Spring's Call DMG|{param4:F2P} Max HP",
    "Song of Ages Past Healing|{param5:I} + {param6:F2P} Max HP",
    "Song of Ages Past Healing Interval|{param7:F1}s", "Hydro/Cryo RES Reduction|{param8:F1P}",
    "RES Reduction Duration|{param9:F1}s", "Skill CD|{param10:F1}s"]
VODYANITSA_SKILL_10 = [0.058896, 16.0, 3.0, 0.058896, 593.2278, 0.0504, 1.5, 0.3, 6.0, 16.0]
VODYANITSA_BASE = _base_stats(base_atk=520.0, base_hp=14000.0, hp_pct=0.24, base_def=455.0)
VODYANITSA_ARTIFACTS = {"hp_pct": 1.398, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                        "crit_rate": 0.3, "crit_dmg": 0.8}


def _vodyanitsa(_: float) -> float:
    """GO: `dmg('skill', info, 'hp', dm.skill.skillDmg, 'skill')` (`pando Vodyanitsa.ts:307`);
    `enemyDebuff.common.preRes.hydro` = `-talentSubscript(skill, hydrocryo_enemyRes_)` while
    `skillHit` (`:59,121-124,296`)."""
    stats = _stats(VODYANITSA_BASE, VODYANITSA_ARTIFACTS)
    return _go_general(base=_multiplier(VODYANITSA_SKILL) * _total(stats, "hp"), flat=0.0,
                       dmg_bonus=stats["hydro_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"], res_shred=-0.3)


# Vesna: the subject, C4, skill stored 10 (13 after C3), in Stellar Radiance, with a Cryo, a
# Pyro and a Hydro teammate. A4: ATK 6% per Anemo/Cryo member (2) and EM 25 per member of
# another element (2), each × (1 + C4's 2.0); C2: ATK +40% at 6 Disciplinary Action stacks (her
# own, on at the maximum by default).
VESNA_SKILL_13 = ("Skill DMG|{param1:F1P}", [0.85])
VESNA_TEAM = ["anemo", "cryo", "pyro", "hydro"]
VESNA_BASE = _base_stats(base_atk=890.0, base_hp=12700.0, base_def=700.0, crit_rate=0.242)
VESNA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "anemo_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 1.0}


def _vesna(_: float) -> float:
    """GO: `dmg('skill_skillDmg', info, 'atk', dm.skill.skillDmg, 'skill')` (`pando
    Vesna.ts:225`); A4 `ownBuff.premod.atk_` = `passive2.atk_ × (count.anemo + count.cryo) ×
    (1 + C4 additionalBuffMult)` (`:130-146,206`); C2 `ownBuff.premod.atk_` =
    `constellation2.atk_` at 6 stacks (`:173-177,210`)."""
    stats = _stats(VESNA_BASE, VESNA_ARTIFACTS)
    atk = _total(stats, "atk", extra_pct=0.06 * 2 * (1 + 2.0) + 0.4)
    return _go_general(base=_multiplier(VESNA_SKILL_13) * atk, flat=0.0,
                       dmg_bonus=stats["anemo_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"])


def ungated_fixtures() -> list[dict[str, Any]]:
    """Task 11: one fixture per sheet of a character gcsim cannot run."""
    none = "none: no reaction"
    formula = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
    out: list[dict[str, Any]] = []

    cons, pas = _pinned("10000100")
    out.append({
        "name": "kachina_a4_on_her_own_skill",
        "covers": "a self flat-damage buff from a stat artifacts move: per-candidate DEF",
        "go": [formula, "libs/gi/formula/src/data/char/Kachina.ts:55-61,88-96,110-111,124"],
        "givers": [{"name": "Kachina", "constellation": 0, "ascension_phase": 6,
                    "stats": "the optimized character: her DEF is the candidate's"}],
        "team": {"element": "geo", "weapon_type": "WEAPON_POLE", "member_elements": ["geo"]},
        "base": KACHINA_BASE, "artifacts": KACHINA_ARTIFACTS, "set_pools": [], "channel": "geo",
        "rows": [_row("independent", "Turbo Twirly Independent DMG", "skill", 1,
                      KACHINA_INDEPENDENT, None)],
        "sources": [_kit_source("10000100", _ungated_giver(
            "Kachina", "10000100", cons=cons, passives=pas, stats=KACHINA_BASE), subject=True)],
        "conditionals": {}, "expected": _kachina(OUR_EM_COEFFICIENT),
        "go_value": _kachina(GO_EM_COEFFICIENT), "divergence": none,
    })

    cons, pas = _pinned("10000122")
    out.append({
        "name": "nefer_veils_on_her_own_burst",
        "covers": "a self buff valued from a talent row times a stack count; self EM into an EM "
                  "term",
        "go": [formula, "libs/gi/formula/src/data/char/Nefer.ts:66-82,123-166,212-213,270-276"],
        "givers": [{"name": "Nefer", "constellation": 0, "ascension_phase": 6,
                    "talent_levels": {"elemental_burst": 10},
                    "stats": "the optimized character"}],
        "team": {"element": "dendro", "weapon_type": "WEAPON_CATALYST",
                 "member_elements": ["dendro", "hydro"]},
        "base": NEFER_BASE, "artifacts": NEFER_ARTIFACTS, "set_pools": [], "channel": "dendro",
        "rows": [_row("hit1", "1-Hit DMG", "burst", 1, NEFER_BURST_HIT1, None)],
        "sources": [_kit_source("10000122", _ungated_giver(
            "Nefer", "10000122", talent_levels={"elemental_burst": 10},
            talent_rows={("elemental_burst", 10): sheets.TalentRow(NEFER_BURST_LABELS,
                                                                   NEFER_BURST_10)},
            cons=cons, passives=pas, stats=NEFER_BASE), subject=True)],
        "conditionals": {"kit:nefer/moonsign_gleam": 1}, "expected": _nefer(OUR_EM_COEFFICIENT),
        "go_value": _nefer(GO_EM_COEFFICIENT), "divergence": none,
    })

    cons, pas = _pinned("10000129")
    out.append({
        "name": "lohen_a4_on_xiangling",
        "covers": "a teammate's ATK% buff that reaches the others only (GO `notOwnBuff`)",
        "go": [formula, "libs/gi/formula/src/data/char/Lohen.ts:83-87,159-161,206-207"],
        "givers": [{"name": "Lohen", "constellation": 0, "ascension_phase": 6, "stats": {}}],
        "team": {"element": "pyro", "weapon_type": "WEAPON_POLE",
                 "member_elements": ["pyro", "cryo"]},
        "base": XIANGLING_BASE, "artifacts": XIANGLING_ARTIFACTS, "set_pools": [],
        "channel": "pyro",
        "rows": [_row("nado", "Pyronado DMG", "burst", 1, PYRONADO, None)],
        "sources": [_kit_source("10000129", _ungated_giver(
            "Lohen", "10000129", cons=cons, passives=pas), subject=False)],
        "conditionals": {"kit:lohen/a4_master_cryo": 1},
        "expected": _lohen_on_xiangling(OUR_EM_COEFFICIENT),
        "go_value": _lohen_on_xiangling(GO_EM_COEFFICIENT), "divergence": none,
    })

    cons, pas = _pinned("10000130")
    out.append({
        "name": "linnea_c4_on_her_own_pummeler",
        "covers": "an enemy RES shred, a CRIT DMG buff gated on the receiver's element, two DEF% "
                  "buffs",
        "go": [formula, ("libs/gi/formula/src/data/char/Linnea.ts:62-65,84-93,121-132,199-223,"
                         "243,252-255,270")],
        "givers": [{"name": "Linnea", "constellation": 4, "ascension_phase": 6,
                    "stats": "the optimized character"}],
        "team": {"element": "geo", "weapon_type": "WEAPON_BOW", "member_elements": ["geo"]},
        "base": LINNEA_BASE, "artifacts": LINNEA_ARTIFACTS, "set_pools": [], "channel": "geo",
        "rows": [_row("pummeler", "Lumi Pound-Pound Pummeler DMG", "skill", 1,
                      LINNEA_PUMMELER_13, None)],
        "sources": [_kit_source("10000130", _ungated_giver(
            "Linnea", "10000130", constellation=4, cons=cons, passives=pas, stats=LINNEA_BASE),
            subject=True, receiver_element="geo", team_elements=["geo"])],
        "conditionals": {}, "expected": _linnea(OUR_EM_COEFFICIENT),
        "go_value": _linnea(GO_EM_COEFFICIENT), "divergence": none,
    })

    cons, pas = _pinned("10000136")
    out.append({
        "name": "mitya_beacons_on_his_own_burst",
        "covers": "a team EM buff per stack into an EM term; a self CRIT Rate buff per stack",
        "go": [formula, ("libs/gi/sheets/src/Characters/Mitya/index.tsx:74-81,130-157,259-265,"
                         "283-295")],
        "givers": [{"name": "Mitya", "constellation": 0, "ascension_phase": 6,
                    "stats": "the optimized character"}],
        "team": {"element": "electro", "weapon_type": "WEAPON_CATALYST",
                 "member_elements": ["electro", "cryo"]},
        "base": MITYA_BASE, "artifacts": MITYA_ARTIFACTS, "set_pools": [], "channel": "electro",
        "rows": [_row("burst", "Skill DMG", "burst", 1, MITYA_BURST, None)],
        "sources": [_kit_source("10000136", _ungated_giver(
            "Mitya", "10000136", cons=cons, passives=pas, stats=MITYA_BASE), subject=True)],
        "conditionals": {}, "expected": _mitya(OUR_EM_COEFFICIENT),
        "go_value": _mitya(GO_EM_COEFFICIENT), "divergence": none,
    })

    cons, pas = _pinned("10000137")
    out.append({
        "name": "valeriy_offensive_on_his_own_burst",
        "covers": "self flat damage from his own ATK per candidate: a talent-row ratio, and a "
                  "passive times a number condition",
        "go": [formula, ("libs/gi/sheets/src/Characters/Valeriy/index.tsx:48-56,80-84,114-224,"
                         "270,293")],
        "givers": [{"name": "Valeriy", "constellation": 0, "ascension_phase": 6,
                    "talent_levels": {"normal_attack": 10},
                    "stats": "the optimized character"}],
        "team": {"element": "electro", "weapon_type": "WEAPON_CATALYST",
                 "member_elements": ["electro", "pyro"]},
        "base": VALERIY_BASE, "artifacts": VALERIY_ARTIFACTS, "set_pools": [],
        "channel": "electro",
        "rows": [_row("burst", "Skill DMG", "burst", 1, VALERIY_BURST, None)],
        "sources": [_kit_source("10000137", _ungated_giver(
            "Valeriy", "10000137", talent_levels={"normal_attack": 10},
            talent_rows={("normal_attack", 10): sheets.TalentRow(VALERIY_NORMAL_LABELS,
                                                                 VALERIY_NORMAL_10)},
            cons=cons, passives=pas, stats=VALERIY_BASE), subject=True)],
        "conditionals": {}, "expected": _valeriy(OUR_EM_COEFFICIENT),
        "go_value": _valeriy(GO_EM_COEFFICIENT), "divergence": none,
    })

    cons, pas = _pinned("10000140")
    out.append({
        "name": "vodyanitsa_res_on_her_own_skill",
        "covers": "an enemy RES shred valued from a talent row, negated",
        "go": [formula, "libs/gi/formula/src/data/char/Vodyanitsa.ts:51-62,121-124,296,307"],
        "givers": [{"name": "Vodyanitsa", "constellation": 0, "ascension_phase": 6,
                    "talent_levels": {"elemental_skill": 10},
                    "stats": "the optimized character"}],
        "team": {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
                 "member_elements": ["hydro", "anemo"]},
        "base": VODYANITSA_BASE, "artifacts": VODYANITSA_ARTIFACTS, "set_pools": [],
        "channel": "hydro",
        "rows": [_row("skill", "Skill DMG", "skill", 1, VODYANITSA_SKILL, None)],
        "sources": [_kit_source("10000140", _ungated_giver(
            "Vodyanitsa", "10000140", talent_levels={"elemental_skill": 10},
            talent_rows={("elemental_skill", 10): sheets.TalentRow(VODYANITSA_SKILL_LABELS,
                                                                   VODYANITSA_SKILL_10)},
            cons=cons, passives=pas, stats=VODYANITSA_BASE), subject=True)],
        "conditionals": {}, "expected": _vodyanitsa(OUR_EM_COEFFICIENT),
        "go_value": _vodyanitsa(GO_EM_COEFFICIENT), "divergence": none,
    })

    cons, pas = _pinned("10000143")
    out.append({
        "name": "vesna_a4_c4_on_her_own_skill",
        "covers": "a self buff times a team element count, multiplied by a second parameter "
                  "(C4), and a buff gated on a stack count",
        "go": [formula, "libs/gi/formula/src/data/char/Vesna.ts:73-90,130-177,206-210,225"],
        "givers": [{"name": "Vesna", "constellation": 4, "ascension_phase": 6,
                    "stats": "the optimized character"}],
        "team": {"element": "anemo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
                 "member_elements": VESNA_TEAM},
        "base": VESNA_BASE, "artifacts": VESNA_ARTIFACTS, "set_pools": [], "channel": "anemo",
        "rows": [_row("skill", "Skill DMG", "skill", 1, VESNA_SKILL_13, None)],
        "sources": [_kit_source("10000143", _ungated_giver(
            "Vesna", "10000143", constellation=4, cons=cons, passives=pas, stats=VESNA_BASE),
            subject=True, receiver_element="anemo", team_elements=VESNA_TEAM)],
        "conditionals": {"kit:vesna/stellar_radiance": 1},
        "expected": _vesna(OUR_EM_COEFFICIENT), "go_value": _vesna(GO_EM_COEFFICIENT),
        "divergence": none,
    })
    return out


# ── Math-fallback P2, task 11: the buffers the owner's teams use ───────────────────────────
#
# One fixture per sheet, on its main damage-relevant effect, by the same method. Talent rows are
# verbatim from the seeded catalogue (nanoka 7.2.51); constellation and passive lists are the
# sheets' pins. Builds are stated. A teammate giver's stats are written out (their pass-1
# numbers); a giver who is the subject resolves against the subject's base stats.

FURINA_BURST_LABELS = [
    "Skill DMG|{param1:F1P} Max HP", "Duration|{param2:F1}s", "Maximum Fanfare|{param4:I}",
    "Fanfare to DMG Increase Conversion Ratio|{param5:F2P}",
    "Fanfare to Incoming Healing Bonus Conversion Ratio|{param6:F2P}", "CD|{param7:F1}s",
    "Energy Cost|{param8:I}"]
FURINA_BURST_10 = [0.205315, 18.0, 0.01, 300.0, 0.0025, 0.001, 15.0, 60.0]
FURINA_BURST = ("Skill DMG|{param1:F1P} Max HP", [0.205315])
FURINA_BASE = _base_stats(base_atk=674.0, base_hp=15307.0, base_def=696.0, crit_rate=0.242)
FURINA_ARTIFACTS = {"hp_pct": 0.932, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.9}


def _furina(_: float) -> float:
    """**Furina, C2, on her own burst**, both conditions at their default for the subject (her
    own doing): Fanfare at the C1-raised limit 400 and 400 points beyond it.

    GO: `dmg('burst_skillDmg', info, 'hp', dm.burst.skillDmg, 'burst')` (`pando Furina.ts:260`);
    `teamBuff.premod.dmg_` = `min(fanfare, 300 + C1 100)` × the burst row's ratio
    (`:114-119,129-137,202`); C2 `ownBuff.premod.hp_` = overstack × `constellation2.hp_`
    (`:120-125,160-164,200`)."""
    stats = _stats(FURINA_BASE, FURINA_ARTIFACTS)
    hp = _total(stats, "hp", extra_pct=400 * 0.0035)
    return _go_general(base=_multiplier(FURINA_BURST) * hp, flat=0.0,
                       dmg_bonus=stats["hydro_dmg_bonus"] + 400 * 0.0025,
                       crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


XINGQIU_RAIN = ("Sword Rain DMG|{param1:F1P}", [0.976896])
XINGQIU_BASE = _base_stats(base_atk=712.0, atk_pct=0.24, base_hp=10222.0, base_def=758.0)
XINGQIU_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "hydro_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.9}


def _xingqiu(_: float) -> float:
    """**Xingqiu, C2, on his own Rain Swords**: A4's Hydro DMG (always on) and C2's Hydro RES
    -15% (his own Rain Swords: on for the subject).

    GO: `dmg('burst', info, 'atk', dm.burst.dmg, 'burst', {ele: 'hydro'})` (`pando
    Xingqiu.ts:127`); A4 `ownBuff.premod.dmg_.hydro` 0.2 (`:61,103-106`); C2
    `enemyDebuff.common.preRes.hydro` -0.15 (`:64,107-110`)."""
    stats = _stats(XINGQIU_BASE, XINGQIU_ARTIFACTS)
    return _go_general(base=_multiplier(XINGQIU_RAIN) * _total(stats, "atk"), flat=0.0,
                       dmg_bonus=stats["hydro_dmg_bonus"] + 0.2, crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"], res_shred=-0.15)


def _xiangling_on_bennett(_: float) -> float:
    """**A C6 Xiangling's C1 and C6 on Bennett's burst**, Guoba's hit and Pyronado on.

    GO: C1 `enemyDebuff.common.preRes.pyro` = `-constellation1.pyroRes` (`pando
    Xiangling.ts:61-62,91-93,110`); C6 `teamBuff.premod.dmg_.pyro` (`:73-74,94-96,109`), which
    reaches Bennett whole (`antiC6` subtracts it only on Xiangling's own Pyronado rows)."""
    stats = _stats(BENNETT_BASE, BENNETT_ARTIFACTS)
    return _go_general(base=_multiplier(BENNETT_BURST_DMG) * _total(stats, "atk"), flat=0.0,
                       dmg_bonus=stats["pyro_dmg_bonus"] + 0.15, crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"], res_shred=-0.15)


#: Citlali as a teammate: her pass-1 EM, stated.
CITLALI_GIVER_STATS = {"elemental_mastery": 800.0}


def _citlali_on_xiangling(_: float) -> float:
    """**A C2 Citlali on Xiangling's Pyronado**, after a Frozen/Melt and with an Obsidian Blade
    consumed: A1's Pyro RES -20%, C2's second -20%, and C1's flat 200% of Citlali's EM.

    GO: `enemyDebuff.common.preRes.pyro` = A1 + C2's copy of it (`pando Citlali.ts:119-136,
    194-196`); C1 `notOwnBuff.formula.base.burst` = `prod(percent(constellation1.dmgInc),
    final.eleMas)` (`:149-151,191`)."""
    stats = _stats(XIANGLING_BASE, XIANGLING_ARTIFACTS)
    return _go_general(base=_multiplier(PYRONADO) * _total(stats, "atk"),
                       flat=2.0 * CITLALI_GIVER_STATS["elemental_mastery"],
                       dmg_bonus=stats["pyro_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"], res_shred=-0.4)


YELAN_SKILL = ("Skill DMG|{param1:F1P} Max HP", [0.407045])
YELAN_TEAM = ["hydro", "pyro", "cryo", "electro"]
YELAN_BASE = _base_stats(base_atk=785.0, base_hp=14450.0, base_def=548.0, crit_rate=0.242)
YELAN_ARTIFACTS = {"hp_pct": 0.932, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.9}


def _yelan(_: float) -> float:
    """**Yelan, C0, on her own skill** in a party of four different elements, Depth-Clarion Dice
    at 14 seconds (her own burst, on for the subject).

    GO: `dmg('skill', info, 'hp', dm.skill.dmg, 'skill')`; A1 `ownBuff.premod.hp_` =
    `subscript(eleCount, hp_Arr)` (`pando Yelan.ts:62-64,109-113,139`); A4
    `teamBuff.premod.dmg_` to the active = 1% + stacks × 3.5% (`:65-69,114-125,141`)."""
    stats = _stats(YELAN_BASE, YELAN_ARTIFACTS)
    return _go_general(base=_multiplier(YELAN_SKILL) * _total(stats, "hp", extra_pct=0.3),
                       flat=0.0, dmg_bonus=stats["hydro_dmg_bonus"] + 0.01 + 14 * 0.035,
                       crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


ESCOFFIER_SKILL = ("Skill DMG|{param1:F1P}", [0.9072])
ESCOFFIER_TEAM = ["cryo", "hydro", "hydro", "cryo"]
ESCOFFIER_BASE = _base_stats(base_atk=956.0, base_hp=13348.0, base_def=732.0, crit_rate=0.242)
ESCOFFIER_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466,
                       "crit_rate": 0.3, "crit_dmg": 0.7}


def _escoffier(_: float) -> float:
    """**Escoffier, C1, on her own skill** in a Hydro/Cryo party of four: A4's Cryo RES by the
    count (4 → 55%) and C1's Cryo CRIT DMG, both her own doing (on for the subject).

    GO: `enemyDebuff.common.preRes.cryo` = `subscript(count.hydro + count.cryo, [0, -5%, -10%,
    -15%, -55%])` (`pando Escoffier.ts:70-77,111-118,143`); C1 `teamBuff.premod.critDMG_.cryo`
    when the count is 4 (`:80-82,119-129,145`)."""
    stats = _stats(ESCOFFIER_BASE, ESCOFFIER_ARTIFACTS)
    return _go_general(base=_multiplier(ESCOFFIER_SKILL) * _total(stats, "atk"), flat=0.0,
                       dmg_bonus=stats["cryo_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"] + 0.6, res_shred=-0.55)


#: Chevreuse as a teammate: her pass-1 HP parts, stated (33,464.876 total).
CHEVREUSE_GIVER_STATS = {"base_hp": 11962.0, "hp_pct": 1.398, "flat_hp": 4780.0}
CHEVREUSE_TEAM = ["pyro", "pyro", "electro", "electro"]


def _chevreuse_on_xiangling(_: float) -> float:
    """**Chevreuse on Xiangling's Pyronado** in a Pyro/Electro party, after an Overloaded and
    an Overcharged Ball: A1's Pyro RES -40% and A4's ATK +1% per 1,000 of her Max HP.

    GO: A1 `enemyDebuff.common.preRes.pyro` with `onlyPyroElectroTeam` (`pando
    Chevreuse.ts:103-114,147`); A4 `teamBuff.premod.atk_` = `min(percent(0.01) × premod.hp /
    1000, 40%)` for a Pyro or Electro receiver (`:115-132,149`)."""
    giver_hp = (CHEVREUSE_GIVER_STATS["base_hp"] * (1 + CHEVREUSE_GIVER_STATS["hp_pct"])
                + CHEVREUSE_GIVER_STATS["flat_hp"])
    stats = _stats(XIANGLING_BASE, XIANGLING_ARTIFACTS)
    atk = _total(stats, "atk", extra_pct=min(0.01 * giver_hp / 1000, 0.4))
    return _go_general(base=_multiplier(PYRONADO) * atk, flat=0.0,
                       dmg_bonus=stats["pyro_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"], res_shred=-0.4)


JEAN_SKILL = ("Skill DMG|{param1:P}", [5.256])
JEAN_BASE = _base_stats(base_atk=847.0, base_hp=14695.0, base_def=769.0)
JEAN_ARTIFACTS = {"atk_pct": 0.932, "flat_atk": 311.0, "anemo_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.7}


def _jean(_: float) -> float:
    """**Jean, C4, on her own held Gale Blade**: C1's skill DMG (her own hold) and C4's Anemo
    RES -40% in her field (on for the subject).

    GO: `ownBuff.premod.dmg_.skill` = C1 (`pando Jean.ts:68-69,92-94,117`);
    `enemyDebuff.common.preRes.anemo` = `-|constellation4.anemoRes|` (`:76-77,101-103,122`)."""
    stats = _stats(JEAN_BASE, JEAN_ARTIFACTS)
    return _go_general(base=_multiplier(JEAN_SKILL) * _total(stats, "atk"), flat=0.0,
                       dmg_bonus=stats["anemo_dmg_bonus"] + 0.4, crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"], res_shred=-0.4)


ZHONGLI_BURST = ("Skill DMG|{param1:P}", [8.9972])
ZHONGLI_BASE = _base_stats(base_atk=859.0, base_hp=14695.0, base_def=738.0)
ZHONGLI_ARTIFACTS = {"hp_pct": 0.932, "flat_hp": 4780.0, "atk_pct": 0.466, "flat_atk": 311.0,
                     "geo_dmg_bonus": 0.754, "crit_rate": 0.3, "crit_dmg": 0.7}


def _zhongli(_: float) -> float:
    """**Zhongli, C0, on his own Planet Befall**, shielded (his own doing): Jade Shield's Geo
    RES -20% and A4's flat 33% of his Max HP, which moves with every candidate.

    GO: `enemyDebuff.common.preRes.geo` -0.2 (`pando Zhongli.ts:57,90,120-123`); A4
    `ownBuff.formula.base.burst` = `prod(percent(passive2.burst_), own.premod.hp)`
    (`:68-72,107-111,128`)."""
    stats = _stats(ZHONGLI_BASE, ZHONGLI_ARTIFACTS)
    return _go_general(base=_multiplier(ZHONGLI_BURST) * _total(stats, "atk"),
                       flat=0.33 * _total(stats, "hp"), dmg_bonus=stats["geo_dmg_bonus"],
                       crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"],
                       res_shred=-0.2)


FARUZAN_BURST_LABELS = [
    "Skill DMG|{param1:F1P}", "Anemo DMG Bonus|{param2:F1P}",
    "Prayerful Wind's Benefit Duration|{param3:F1}s", "Anemo RES Decrease|{param4:F1P}",
    "Perfidious Wind's Bale Duration|{param5:F1}s", "Duration|{param6:F1}s", "CD|{param7:F1}s",
    "Energy Cost|{param8:I}"]
FARUZAN_BURST_10 = [6.7968, 0.324, 4.0, 0.3, 4.0, 12.0, 20.0, 80.0]
FARUZAN_BURST = ("Skill DMG|{param1:F1P}", [6.7968])
FARUZAN_BASE = _base_stats(base_atk=804.0, base_hp=9569.0, base_def=628.0,
                           energy_recharge=1.24)
FARUZAN_ARTIFACTS = {"atk_pct": 0.932, "flat_atk": 311.0, "anemo_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.7}


def _faruzan(_: float) -> float:
    """**Faruzan, C0, on her own burst**, every condition her own doing: the burst's Anemo DMG
    (row 10), its Anemo RES -30%, and A4's flat 32% of her **base** ATK.

    GO: `teamBuff.premod.dmg_.anemo` = burst row (`pando Faruzan.ts:55,86-88,111`);
    `enemyDebuff.common.preRes.anemo` = `-burst[3][0]` (`:57,89-91,113`); A4
    `teamBuff.formula.base.anemo` = `prod(percent(gift_dmgInc), own.base.atk)`
    (`:67,93-97,114`)."""
    stats = _stats(FARUZAN_BASE, FARUZAN_ARTIFACTS)
    return _go_general(base=_multiplier(FARUZAN_BURST) * _total(stats, "atk"),
                       flat=0.32 * FARUZAN_BASE["base_atk"],
                       dmg_bonus=stats["anemo_dmg_bonus"] + 0.324,
                       crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"],
                       res_shred=-0.3)


#: Sucrose as a teammate: her pass-1 EM, stated.
SUCROSE_GIVER_STATS = {"elemental_mastery": 900.0}


def _sucrose_on_xiangling(coefficient: float) -> float:
    """**Sucrose on Xiangling's reverse-vaporized Pyronado**, after a Pyro Swirl and a skill
    hit: A1's 50 EM to a Pyro teammate and A4's 20% of Sucrose's EM, both into the EM the
    reaction reads.

    GO: A1 `notOwnBuff.premod.eleMas` for a receiver of the swirled element (`pando
    Sucrose.ts:143-150`); A4 `notOwnBuff.final.eleMas` = `prod(percent(passive2.eleMas_),
    own.premod.eleMas)` (`:125-131,152`); amp `formula.ts:257,454-484`."""
    totals = _xiangling_totals(fervent=False, witch_stacks=0)
    totals["pyro"] -= 0.15  # no Crimson Witch here: `_xiangling_totals` adds its 2-piece
    em = totals["em"] + 50.0 + 0.2 * SUCROSE_GIVER_STATS["elemental_mastery"]
    return _go_hit(multiplier=_multiplier(PYRONADO), atk=totals["atk"], dmg_bonus=totals["pyro"],
                   crit_rate=totals["cr"], crit_dmg=totals["cd"], em=em, amp_base=1.5,
                   reaction_bonus=0.0, em_coefficient=coefficient)


def _buffer(name: str, covers: str, go: list[str], giver: dict[str, Any], team: dict[str, Any],
            base: dict[str, float], artifacts: dict[str, float], channel: str,
            row: dict[str, Any], source: dict[str, Any], conditionals: dict[str, Any],
            figure: Any, divergence: str = "none: no reaction") -> dict[str, Any]:
    return {
        "name": name, "covers": covers, "go": go, "givers": [giver], "team": team,
        "base": base, "artifacts": artifacts, "set_pools": [], "channel": channel,
        "rows": [row], "sources": [source], "conditionals": conditionals,
        "expected": figure(OUR_EM_COEFFICIENT), "go_value": figure(GO_EM_COEFFICIENT),
        "divergence": divergence,
    }


def buffer_fixtures() -> list[dict[str, Any]]:
    """Task 11, second batch: one fixture per buffer sheet."""
    formula = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
    pando = "libs/gi/formula/src/data/char/"
    xiangling = {"element": "pyro", "weapon_type": "WEAPON_POLE"}
    nado = _row("nado", "Pyronado DMG", "burst", 1, PYRONADO, None)
    out: list[dict[str, Any]] = []

    cons, pas = _pinned("10000089")
    out.append(_buffer(
        "furina_fanfare_c2_on_her_own_burst",
        "a team DMG buff per stack from a talent row, its maximum raised by C1; a self HP% per "
        "stack (C2)",
        [formula, f"{pando}Furina.ts:114-137,160-164,196-202,260"],
        {"name": "Furina", "constellation": 2, "ascension_phase": 6,
         "talent_levels": {"elemental_burst": 10}, "stats": "the optimized character"},
        {"element": "hydro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["hydro", "pyro"]},
        FURINA_BASE, FURINA_ARTIFACTS, "hydro",
        _row("burst", "Skill DMG", "burst", 1, FURINA_BURST, None),
        _kit_source("10000089", _ungated_giver(
            "Furina", "10000089", constellation=2, talent_levels={"elemental_burst": 10},
            talent_rows={("elemental_burst", 10): sheets.TalentRow(FURINA_BURST_LABELS,
                                                                   FURINA_BURST_10)},
            cons=cons, passives=pas, stats=FURINA_BASE), subject=True),
        {}, _furina))

    cons, pas = _pinned("10000025")
    out.append(_buffer(
        "xingqiu_c2_on_his_own_burst",
        "two constants no seeded list carries (cited to GO and gcsim): a self DMG buff and an "
        "enemy RES shred",
        [formula, f"{pando}Xingqiu.ts:61-64,103-110,127"],
        {"name": "Xingqiu", "constellation": 2, "ascension_phase": 6,
         "stats": "the optimized character"},
        {"element": "hydro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["hydro", "pyro"]},
        XINGQIU_BASE, XINGQIU_ARTIFACTS, "hydro",
        _row("rain", "Sword Rain DMG", "burst", 1, XINGQIU_RAIN, None),
        _kit_source("10000025", _ungated_giver(
            "Xingqiu", "10000025", constellation=2, cons=cons, passives=pas,
            stats=XINGQIU_BASE), subject=True),
        {}, _xingqiu))

    cons, pas = _pinned("10000023")
    out.append(_buffer(
        "xiangling_c1_c6_on_bennett",
        "a teammate's RES shred and party DMG buff, the latter withheld from her own Pyronado",
        [formula, f"{pando}Xiangling.ts:61-62,73-74,91-98,109-110"],
        {"name": "Xiangling", "constellation": 6, "ascension_phase": 6, "stats": {}},
        {"element": "pyro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["pyro", "pyro"]},
        BENNETT_BASE, BENNETT_ARTIFACTS, "pyro",
        _row("burst", "Skill DMG", "burst", 1, BENNETT_BURST_DMG, None),
        _kit_source("10000023", _ungated_giver(
            "Xiangling", "10000023", constellation=6, cons=cons, passives=pas), subject=False),
        {"kit:xiangling/after_guoba_hit": 1, "kit:xiangling/pyronado": 1},
        _xiangling_on_bennett))

    cons, pas = _pinned("10000107")
    out.append(_buffer(
        "citlali_c2_on_xiangling",
        "a teammate's flat damage from the giver's EM (C1), and a RES shred doubled by C2",
        [formula, f"{pando}Citlali.ts:63-66,74-75,119-136,149-151,186-199"],
        {"name": "Citlali", "constellation": 2, "ascension_phase": 6,
         "stats": CITLALI_GIVER_STATS},
        {**xiangling, "member_elements": ["pyro", "cryo"]},
        XIANGLING_BASE, XIANGLING_ARTIFACTS, "pyro", nado,
        _kit_source("10000107", _ungated_giver(
            "Citlali", "10000107", constellation=2, cons=cons, passives=pas,
            stats=CITLALI_GIVER_STATS), subject=False),
        {"kit:citlali/a1_freeze_melt": 1, "kit:citlali/c1_blades": 1},
        _citlali_on_xiangling))

    cons, pas = _pinned("10000060")
    out.append(_buffer(
        "yelan_a1_a4_on_her_own_skill",
        "a value read from a table by the team's distinct elements (A1), and a ramping DMG buff "
        "(A4) as a base part and a per-second part",
        [formula, f"{pando}Yelan.ts:62-69,109-125,139-141"],
        {"name": "Yelan", "constellation": 0, "ascension_phase": 6,
         "stats": "the optimized character"},
        {"element": "hydro", "weapon_type": "WEAPON_BOW", "member_elements": YELAN_TEAM},
        YELAN_BASE, YELAN_ARTIFACTS, "hydro",
        _row("skill", "Skill DMG", "skill", 1, YELAN_SKILL, None),
        _kit_source("10000060", _ungated_giver(
            "Yelan", "10000060", cons=cons, passives=pas, stats=YELAN_BASE), subject=True,
            receiver_element="hydro", team_elements=YELAN_TEAM),
        {}, _yelan))

    cons, pas = _pinned("10000112")
    out.append(_buffer(
        "escoffier_a4_c1_on_her_own_skill",
        "a RES shred read from a table by the Hydro/Cryo count (A4), and a CRIT DMG buff gated on "
        "the whole party's composition (C1)",
        [formula, f"{pando}Escoffier.ts:70-82,111-129,143-145"],
        {"name": "Escoffier", "constellation": 1, "ascension_phase": 6,
         "stats": "the optimized character"},
        {"element": "cryo", "weapon_type": "WEAPON_POLE", "member_elements": ESCOFFIER_TEAM},
        ESCOFFIER_BASE, ESCOFFIER_ARTIFACTS, "cryo",
        _row("skill", "Skill DMG", "skill", 1, ESCOFFIER_SKILL, None),
        _kit_source("10000112", _ungated_giver(
            "Escoffier", "10000112", constellation=1, cons=cons, passives=pas,
            stats=ESCOFFIER_BASE), subject=True, receiver_element="cryo",
            team_elements=ESCOFFIER_TEAM),
        {}, _escoffier))

    cons, pas = _pinned("10000090")
    out.append(_buffer(
        "chevreuse_a1_a4_on_xiangling",
        "a teammate's ATK% from the giver's HP per 1,000, capped, for receivers of two elements; "
        "a RES shred gated on the party's composition",
        [formula, f"{pando}Chevreuse.ts:64-71,103-132,147-149"],
        {"name": "Chevreuse", "constellation": 0, "ascension_phase": 6,
         "stats": CHEVREUSE_GIVER_STATS},
        {**xiangling, "member_elements": CHEVREUSE_TEAM},
        XIANGLING_BASE, XIANGLING_ARTIFACTS, "pyro", nado,
        _kit_source("10000090", _ungated_giver(
            "Chevreuse", "10000090", cons=cons, passives=pas, stats=CHEVREUSE_GIVER_STATS),
            subject=False, receiver_element="pyro", team_elements=CHEVREUSE_TEAM),
        {"kit:chevreuse/a1_overloaded": 1, "kit:chevreuse/a4_after_ball": 1},
        _chevreuse_on_xiangling))

    cons, pas = _pinned("10000003")
    out.append(_buffer(
        "jean_c1_c4_on_her_own_skill",
        "a self move-scoped DMG buff (C1) and an enemy RES shred (C4)",
        [formula, f"{pando}Jean.ts:68-77,92-103,117-122"],
        {"name": "Jean", "constellation": 4, "ascension_phase": 6,
         "stats": "the optimized character"},
        {"element": "anemo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["anemo", "pyro"]},
        JEAN_BASE, JEAN_ARTIFACTS, "anemo",
        _row("skill", "Skill DMG", "skill", 1, JEAN_SKILL, None),
        _kit_source("10000003", _ungated_giver(
            "Jean", "10000003", constellation=4, cons=cons, passives=pas, stats=JEAN_BASE),
            subject=True),
        {}, _jean))

    cons, pas = _pinned("10000030")
    out.append(_buffer(
        "zhongli_shield_and_a4_on_his_own_burst",
        "an all-element RES shred (a cited constant), and self flat damage from his own HP per "
        "candidate",
        [formula, f"{pando}Zhongli.ts:57,68-72,90,107-111,120-128"],
        {"name": "Zhongli", "constellation": 0, "ascension_phase": 6,
         "stats": "the optimized character: his HP is the candidate's"},
        {"element": "geo", "weapon_type": "WEAPON_POLE", "member_elements": ["geo", "pyro"]},
        ZHONGLI_BASE, ZHONGLI_ARTIFACTS, "geo",
        _row("burst", "Skill DMG", "burst", 1, ZHONGLI_BURST, None),
        _kit_source("10000030", _ungated_giver(
            "Zhongli", "10000030", cons=cons, passives=pas, stats=ZHONGLI_BASE), subject=True),
        {}, _zhongli))

    cons, pas = _pinned("10000076")
    out.append(_buffer(
        "faruzan_burst_a4_on_her_own_burst",
        "a DMG buff and a RES shred from talent rows, and flat damage from the giver's base ATK",
        [formula, f"{pando}Faruzan.ts:55-57,67,86-97,111-114"],
        {"name": "Faruzan", "constellation": 0, "ascension_phase": 6,
         "talent_levels": {"elemental_burst": 10}, "stats": "the optimized character"},
        {"element": "anemo", "weapon_type": "WEAPON_BOW", "member_elements": ["anemo", "pyro"]},
        FARUZAN_BASE, FARUZAN_ARTIFACTS, "anemo",
        _row("burst", "Skill DMG", "burst", 1, FARUZAN_BURST, None),
        _kit_source("10000076", _ungated_giver(
            "Faruzan", "10000076", talent_levels={"elemental_burst": 10},
            talent_rows={("elemental_burst", 10): sheets.TalentRow(FARUZAN_BURST_LABELS,
                                                                   FARUZAN_BURST_10)},
            cons=cons, passives=pas, stats=FARUZAN_BASE), subject=True),
        {}, _faruzan))

    cons, pas = _pinned("10000043")
    out.append(_buffer(
        "sucrose_a4_on_xiangling",
        "teammate EM buffs (one gated on the receiver's element) into an amplifying reaction",
        ["libs/gi/wr/src/formula.ts:257,357,434-484",
         f"{pando}Sucrose.ts:58-63,125-131,143-152"],
        {"name": "Sucrose", "constellation": 0, "ascension_phase": 6,
         "stats": SUCROSE_GIVER_STATS},
        {**xiangling, "member_elements": ["pyro", "anemo", "hydro"]},
        XIANGLING_BASE, XIANGLING_ARTIFACTS, "pyro",
        _row("nado_vape", "Pyronado DMG (vaporize)", "burst", 1, PYRONADO, "reverse_vaporize"),
        _kit_source("10000043", _ungated_giver(
            "Sucrose", "10000043", cons=cons, passives=pas, stats=SUCROSE_GIVER_STATS),
            subject=False, receiver_element="pyro", team_elements=["pyro", "anemo", "hydro"]),
        {"kit:sucrose/swirl_pyro": 1, "kit:sucrose/skill_hit": 1},
        _sucrose_on_xiangling,
        "amplifying EM coefficient: 2.78 (gcsim, ours) against GO's 25/9"))
    return out


# ── Math-fallback P2, task 11 (third batch): the DPS characters in the owner's teams ─────────
#
# One fixture per sheet, on its main self buff, by the same method: GO's formula worked by hand
# from its sheet, with our numbers. Talent rows are verbatim from the seeded catalogue (nanoka
# 7.2.51); constellation and passive lists are the sheets' pins. Each subject resolves its own
# sheet against its base stats, as the buffers' fixtures do.

AYAKA_CHARGED = ("Charged Attack DMG|{param8:F1P}\u00d73", [0.84007, 0.894438, 1.150493, 0.416061,
                                                      0.0, 0.0, 1.436362, 1.01278])
AYAKA_SELF_BASE = _base_stats(base_atk=950.0, base_hp=12858.0, base_def=784.0, crit_dmg=0.884)
AYAKA_SELF_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466,
                        "crit_rate": 0.3, "crit_dmg": 0.6}


def _ayaka(_: float) -> float:
    """**Kamisato Ayaka, C0, on her own Charged Attack** (three hits), both passives her own
    doing: A1's 30% Normal and Charged Attack DMG after Hyouka and A4's 18% Cryo DMG.

    GO: `dmg('charged', info, 'atk', dm.charged.dmg1, 'charged')` (`pando KamisatoAyaka.ts:143`);
    A1 `ownBuff.premod.dmg_.charged` = `passive1.dmg_bonus` (`:59-62,99-103,128`); A4
    `ownBuff.premod.dmg_.cryo` = `passive2.cryo` (`:63-67,104-108,130`)."""
    stats = _stats(AYAKA_SELF_BASE, AYAKA_SELF_ARTIFACTS)
    one = _go_general(base=_multiplier(AYAKA_CHARGED) * _total(stats, "atk"), flat=0.0,
                      dmg_bonus=stats["cryo_dmg_bonus"] + 0.3 + 0.18,
                      crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])
    return 3 * one


KUKI_RING = ("Grass Ring of Sanctification DMG|{param4:F1P}", [1.287104, 0.051, 587.4528,
                                                             0.42908])
KUKI_BASE = _base_stats(base_atk=772.0, base_hp=12289.0, hp_pct=0.24, base_def=751.0)
KUKI_ARTIFACTS = {"elemental_mastery": 747.0, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                  "crit_rate": 0.2, "crit_dmg": 0.4}


def _kuki(_: float) -> float:
    """**Kuki Shinobu, C0, on her own Grass Ring**: A4 adds 25% of her Elemental Mastery to the
    ring's base, which moves with every candidate.

    GO: `dmg('ringDmg', info, 'atk', dm.skill.ringDmg, 'skill')` (`pando KukiShinobu.ts:143`);
    A4 `ownBuff.formula.base.skill` = `prod(percent(passive2.emSkillDmg_), final.eleMas)`
    (`:66-69,102-106,119`)."""
    stats = _stats(KUKI_BASE, KUKI_ARTIFACTS)
    return _go_general(base=_multiplier(KUKI_RING) * _total(stats, "atk"),
                       flat=0.25 * stats["elemental_mastery"],
                       dmg_bonus=stats["electro_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"])


NOELLE_NORMAL_4 = ("4-Hit DMG|{param4:P}", [1.4536, 1.34774, 1.58474, 2.08402])
NOELLE_BURST_LABELS = ["Burst DMG|{param1:P}", "Skill DMG|{param2:P}", "ATK Bonus|{param3:P} DEF",
                       "Duration|{param4:F1}s", "CD|{param5:F1}s", "Energy Cost|{param6:I}"]
NOELLE_BURST_9 = [1.1424, 1.5776, 0.68, 15.0, 15.0, 60.0]
NOELLE_BASE = _base_stats(base_atk=701.0, base_hp=12071.0, base_def=799.0, def_pct=0.3)
NOELLE_ARTIFACTS = {"def_pct": 1.166, "flat_def": 39.0, "flat_atk": 311.0,
                    "geo_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.8}


def _noelle(_: float) -> float:
    """**Noelle, C0, on her own 4-Hit DMG during Sweeping Time** (Geo, infused): her ATK gains
    68% of her own DEF (burst 9), which moves with every candidate's DEF.

    GO: `dmg('normal_3', info, 'atk', …, 'normal')` (`pando Noelle.ts:145-147`); `ownBuff.
    premod.atk.add(SweepingTime.ifOn(prod(own.premod.def, talentSubscript(burst,
    defToAtk))))` (`:64-71,99-110,137`)."""
    stats = _stats(NOELLE_BASE, NOELLE_ARTIFACTS)
    atk = _total(stats, "atk") + 0.68 * _total(stats, "def")
    return _go_general(base=_multiplier(NOELLE_NORMAL_4) * atk, flat=0.0,
                       dmg_bonus=stats["geo_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"])


NEUVILLETTE_JUDGMENT = ("Charged Attack: Equitable Judgment|{param5:F2P} Max HP",
                        [0.982382, 0.832421, 1.302077, 2.4624, 0.14467])
NEUVILLETTE_BASE = _base_stats(base_atk=601.0, base_hp=14695.0, base_def=576.0, crit_dmg=0.884)
NEUVILLETTE_ARTIFACTS = {"hp_pct": 0.932, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                         "crit_rate": 0.3, "crit_dmg": 0.6}


def _neuvillette(_: float) -> float:
    """**Neuvillette, C0, on his own Equitable Judgment**, set by the user (both are situational,
    DECISIONS §39): three A1 stacks (base DMG ×1.6) and HP 50 points above 30% (A4, +30% Hydro
    DMG).

    GO: `dmg('charged_judgment', info, 'hp', dm.charged.judgmentDmg, 'charged', {baseMulti:
    1 + subscript(a1Stacks, [0, …passive1])})` (`pando Neuvillette.ts:58-66,91-96,122-130`); A4
    `ownBuff.premod.dmg_.hydro` = `prod(a4Hp, passive2[2][0] / 100)` (`:67-72,97-101,115`)."""
    stats = _stats(NEUVILLETTE_BASE, NEUVILLETTE_ARTIFACTS)
    return _go_general(base=_multiplier(NEUVILLETTE_JUDGMENT) * _total(stats, "hp") * (1 + 0.6),
                       flat=0.0, dmg_bonus=stats["hydro_dmg_bonus"] + 50 * 0.6 / 100,
                       crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


MAVUIKA_BURST_LABELS = [
    "Skill DMG|{param1:F1P}", "Crucible of Death and Life Duration|{param2:F1}s",
    "Sunfell Slice DMG Bonus|{param3:F1P} ATK per Fighting Spirit",
    "Flamestrider Normal Attack DMG Bonus|{param4:F2P} ATK per Fighting Spirit",
    "Flamestrider Charged Attack DMG Bonus|{param5:F2P} ATK per Fighting Spirit",
    "CD|{param8:F1}s", "Fighting Spirit Limit|{param9:I}"]
MAVUIKA_BURST_10 = [8.0064, 7.0, 0.0288, 0.0051, 0.0102, 1.0, 1.5, 18.0, 200.0]
MAVUIKA_BURST = ("Skill DMG|{param1:F1P}", [8.0064])
MAVUIKA_BASE = _base_stats(base_atk=1013.0, base_hp=12552.0, base_def=792.0, crit_dmg=0.884)
MAVUIKA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.6}


def _mavuika(_: float) -> float:
    """**Mavuika, C2, on her own Sunfell Slice**, every condition her own doing at its maximum:
    200 Fighting Spirit (Sunfell's ATK per point, and A4's DMG to the active character), A1's
    and C1's ATK, C2's base ATK in either form and its share of ATK in Flamestrider form.

    GO: `dmg('burst', info, 'atk', dm.burst.skillDmg, 'burst')` (`pando Mavuika.ts:303-311`);
    `ownBuff.formula.base.burst` = Sunfell `prod(final.atk, burst row, spirit)` + C2 `prod(
    final.atk, constellation2.burst_dmgInc)` (`:132-136,199-205,234`); `ownBuff.base.atk` +C2
    (`:168-176,232`); `premod.atk_` A1 + C1 (`:148-150,165-167,231`); `teamBuff.premod.dmg_` A4
    at 0 s = `0.0001 × 20 × spirit` (`:78-83,151-164,236-242`)."""
    stats = _stats(MAVUIKA_BASE, MAVUIKA_ARTIFACTS)
    atk = (MAVUIKA_BASE["base_atk"] + 200.0) * (1 + stats["atk_pct"] + 0.3 + 0.4) \
        + stats["flat_atk"]
    return _go_general(base=_multiplier(MAVUIKA_BURST) * atk, flat=(200 * 0.0288 + 1.2) * atk,
                       dmg_bonus=stats["pyro_dmg_bonus"] + 200 * 0.002,
                       crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


SKIRK_BURST_LABELS = [
    "Slash DMG|{param1:F1P} \u00d75", "Final Slash DMG|{param2:F1P}",
    "Serpent's Subtlety Bonus|{param3:F2P} ATK Per Point",
    "0/1/2/3 Void Rift Absorption DMG Bonus|{param4:F1P}/{param5:F1P}/{param6:F1P}/{param7:F1P}",
    "CD|{param8:F1}s"]
SKIRK_BURST_10 = [2.20968, 3.6828, 0.34782, 0.08, 0.12, 0.16, 0.2, 15.0]
SKIRK_FINAL = ("Final Slash DMG|{param2:F1P}", [2.20968, 3.6828])
SKIRK_BASE = _base_stats(base_atk=1015.0, base_hp=12417.0, base_def=806.0, crit_dmg=0.884)
SKIRK_ARTIFACTS = {"atk_pct": 0.932, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.6}


def _skirk(_: float) -> float:
    """**Skirk, C0, on her own Havoc: Ruin final slash**, with 12 points of Serpent's Subtlety
    above 50 (the C0 maximum, her own doing): each adds the burst row's share of her ATK.

    GO: `burstHit('burst_finalDmg', dm.burst.finalDmg)` (`pando Skirk.ts:265-278,308`) with
    `ownBuff.formula.base.add(prod(serpentStacks, talentSubscript(burst, serpentBonus),
    a4mult, final.atk))` (`:159-171`), A4 at 0 stacks (situational) so `a4mult` is 1."""
    stats = _stats(SKIRK_BASE, SKIRK_ARTIFACTS)
    atk = _total(stats, "atk")
    return _go_general(base=_multiplier(SKIRK_FINAL) * atk, flat=12 * 0.34782 * atk,
                       dmg_bonus=stats["cryo_dmg_bonus"], crit_rate=stats["crit_rate"],
                       crit_dmg=stats["crit_dmg"])


def dps_fixtures() -> list[dict[str, Any]]:
    """Task 11, third batch: one fixture per DPS sheet, on its main self buff."""
    formula = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
    pando = "libs/gi/formula/src/data/char/"
    out: list[dict[str, Any]] = []

    def subject(name: str, constellation: int, talent_levels: dict[str, int] | None = None
                ) -> dict[str, Any]:
        giver: dict[str, Any] = {"name": name, "constellation": constellation,
                                 "ascension_phase": 6}
        if talent_levels:
            giver["talent_levels"] = talent_levels
        giver["stats"] = "the optimized character"
        return giver

    cons, pas = _pinned("10000002")
    out.append(_buffer(
        "ayaka_a1_a4_on_her_own_charged",
        "two self DMG buffs, one move-scoped (A1) and one element-scoped (A4), over a three-hit "
        "row",
        [formula, f"{pando}KamisatoAyaka.ts:59-67,99-108,127-130,143"],
        subject("Kamisato Ayaka", 0),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]},
        AYAKA_SELF_BASE, AYAKA_SELF_ARTIFACTS, "cryo",
        _row("charged", "Charged Attack DMG", "charged", 3, AYAKA_CHARGED, None),
        _kit_source("10000002", _ungated_giver(
            "Kamisato Ayaka", "10000002", cons=cons, passives=pas, stats=AYAKA_SELF_BASE),
            subject=True),
        {}, _ayaka))

    cons, pas = _pinned("10000065")
    out.append(_buffer(
        "kuki_a4_on_her_own_ring",
        "self flat damage from her own Elemental Mastery on one move, per candidate",
        [formula, f"{pando}KukiShinobu.ts:66-69,102-106,119,143"],
        subject("Kuki Shinobu", 0),
        {"element": "electro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["electro", "dendro"]},
        KUKI_BASE, KUKI_ARTIFACTS, "electro",
        _row("ring", "Grass Ring of Sanctification DMG", "skill", 1, KUKI_RING, None),
        _kit_source("10000065", _ungated_giver(
            "Kuki Shinobu", "10000065", cons=cons, passives=pas, stats=KUKI_BASE),
            subject=True),
        {}, _kuki))

    cons, pas = _pinned("10000034")
    out.append(_buffer(
        "noelle_burst_on_her_own_normal",
        "self flat ATK from her own DEF (a talent row), per candidate, into an ATK-scaling hit",
        [formula, f"{pando}Noelle.ts:64-71,99-110,137,145-147"],
        subject("Noelle", 0, {"elemental_burst": 9}),
        {"element": "geo", "weapon_type": "WEAPON_CLAYMORE", "member_elements": ["geo"]},
        NOELLE_BASE, NOELLE_ARTIFACTS, "geo",
        _row("normal_4", "4-Hit DMG", "normal", 1, NOELLE_NORMAL_4, None),
        _kit_source("10000034", _ungated_giver(
            "Noelle", "10000034", talent_levels={"elemental_burst": 9},
            talent_rows={("elemental_burst", 9): sheets.TalentRow(NOELLE_BURST_LABELS,
                                                                  NOELLE_BURST_9)},
            cons=cons, passives=pas, stats=NOELLE_BASE), subject=True),
        {}, _noelle))

    cons, pas = _pinned("10000087")
    out.append(_buffer(
        "neuvillette_a1_a4_on_his_own_judgment",
        "a base-damage multiplier read by a stack count (A1), and a DMG buff per percentage "
        "point of HP counted per 100 (A4), both situational and set by the user",
        [formula, f"{pando}Neuvillette.ts:58-72,91-101,115,122-130"],
        subject("Neuvillette", 0),
        {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["hydro", "hydro"]},
        NEUVILLETTE_BASE, NEUVILLETTE_ARTIFACTS, "hydro",
        _row("judgment", "Charged Attack: Equitable Judgment", "charged", 1,
             NEUVILLETTE_JUDGMENT, None),
        _kit_source("10000087", _ungated_giver(
            "Neuvillette", "10000087", cons=cons, passives=pas, stats=NEUVILLETTE_BASE),
            subject=True),
        {"kit:neuvillette/a1_stacks": 3, "kit:neuvillette/a4_hp": 50}, _neuvillette))

    cons, pas = _pinned("10000106")
    out.append(_buffer(
        "mavuika_c2_on_her_own_burst",
        "self flat damage from her own ATK per Fighting Spirit (a talent row) and from C2, base "
        "ATK (C2), ATK% (A1, C1), and a DMG buff to the active character from a cited constant "
        "(A4)",
        [formula, f"{pando}Mavuika.ts:66,78-96,125-176,199-205,231-242,303-311"],
        subject("Mavuika", 2, {"elemental_burst": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["pyro", "pyro", "cryo", "anemo"]},
        MAVUIKA_BASE, MAVUIKA_ARTIFACTS, "pyro",
        _row("burst", "Skill DMG", "burst", 1, MAVUIKA_BURST, None),
        _kit_source("10000106", _ungated_giver(
            "Mavuika", "10000106", constellation=2, talent_levels={"elemental_burst": 10},
            talent_rows={("elemental_burst", 10): sheets.TalentRow(MAVUIKA_BURST_LABELS,
                                                                   MAVUIKA_BURST_10)},
            cons=cons, passives=pas, stats=MAVUIKA_BASE), subject=True),
        {}, _mavuika))

    cons, pas = _pinned("10000114")
    out.append(_buffer(
        "skirk_serpent_on_her_own_burst",
        "self flat damage from her own ATK per point of a stack count (a talent row)",
        [formula, f"{pando}Skirk.ts:72-76,138-144,159-171,265-278,308"],
        subject("Skirk", 0, {"elemental_burst": 10}),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]},
        SKIRK_BASE, SKIRK_ARTIFACTS, "cryo",
        _row("final", "Final Slash DMG", "burst", 1, SKIRK_FINAL, None),
        _kit_source("10000114", _ungated_giver(
            "Skirk", "10000114", talent_levels={"elemental_burst": 10},
            talent_rows={("elemental_burst", 10): sheets.TalentRow(SKIRK_BURST_LABELS,
                                                                   SKIRK_BURST_10)},
            cons=cons, passives=pas, stats=SKIRK_BASE), subject=True),
        {}, _skirk))
    return out


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
    fixtures.extend(ungated_fixtures())
    fixtures.extend(buffer_fixtures())
    fixtures.extend(dps_fixtures())
    # Task 11, fourth batch (Nahida and the next buffers): their own module, the same method.
    # Imported here: that module imports this one for its helpers.
    from tests.unit.go_fixtures_batch4 import batch4_fixtures
    fixtures.extend(batch4_fixtures())
    # Task 11, fifth batch (the next DPS characters), the same way.
    from tests.unit.go_fixtures_batch5 import batch5_fixtures
    fixtures.extend(batch5_fixtures())
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
                 "kazuha_a4_pyro_on_xiangling", "kazuha_a4_on_his_own_burst",
                 *(f["name"] for f in ungated_fixtures()),
                 *(f["name"] for f in buffer_fixtures()
                   if f["name"] != "sucrose_a4_on_xiangling"),
                 *(f["name"] for f in dps_fixtures())):
        assert by_name[name]["relative_divergence_from_go"] == 0, name
    for name in ("crimson_witch_one_stack_reverse_vaporize", "xiangling_multi_target",
                 "sucrose_a4_on_xiangling"):
        gap = by_name[name]["relative_divergence_from_go"]
        # The gap grows with EM: ~1e-4 at Xiangling's 176, ~3e-4 at 406 with Sucrose's buffs.
        assert 0 < gap < 5e-4, name


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


def test_the_buffer_figures():
    """Two of task 11's second batch by hand, so a reader can check them against GO."""
    # Pyronado 2.016 x ATK 1,659.47 (735 x (1 + 0.5 + 0.0100 x 33,464.876 / 1,000) + 311)
    # x 1.466 x avgHit 1.42 x 190/390 x resMulti 1.15 (RES 0.1 - 0.4 = -0.3).
    assert _chevreuse_on_xiangling(OUR_EM_COEFFICIENT) == pytest.approx(3901.83, abs=0.01)
    # Burst 0.205315 x HP 55,782.92 (15,307 x (1 + 0.932 + 400 x 0.0035) + 4,780)
    # x (1 + 0.466 + 400 x 0.0025) x avgHit 1.7588 (1 + 0.542 x 1.4) x 190/390 x 0.9.
    assert _furina(OUR_EM_COEFFICIENT) == pytest.approx(21780.26, abs=0.01)


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
