"""Math-fallback P2, task 11 (fifth batch) — the next DPS characters' sheets, and the three small
format extensions they needed (`docs/DESIGN_team_math_fallback.md` §2.6, fifth-batch table).

Each sheet's GO agreement on its main effect is `test_go_formula_fixtures.py`'s job (fixtures in
`go_fixtures_batch5.py`). This file checks what one fixture per sheet does not: a passive held
from the start (`a0`), a cited offset on a talent row (a whole multiplier written as a base
multiplier), a unit on a per-candidate self conversion, the team-count gates written as separate
effects, and the parts of each kit the sheet names instead of applying.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins`; talent rows are the seeded rows at level 10, verbatim.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.formula.builder import const
from app.formula.genshin import sheets, tags
from app.pando.calculator import NodeRegistry
from app.services import kit_buffs

ARLE_NORMAL_LABELS = ["Masque of the Red Death Increase|{param12:F2P}", "1-Hit DMG|{param1:F1P}"]
ARLE_NORMAL_10 = [0.938961, 1.029996, 1.29251, 0.734264, 1.383358, 1.687709, 1.7952, 25.0,
                  1.26378, 2.527025, 3.15639, 2.38, 0.075, 0.3, 40.0]
WRIO_SKILL_LABELS = ["Enhanced Repelling Fist DMG|{param1:F1P} Normal Attack DMG"]
WRIO_SKILL_10 = [1.70312, 0.045, 10.0, 16.0, 0.0, 0.0, 0.0, 0.70312]
YOIMIYA_SKILL_LABELS = ["Blazing Arrow DMG|{param4:F1P} Normal Attack DMG"]
YOIMIYA_SKILL_10 = [0.61744, 10.0, 18.0, 1.61744]
#: Navia's seeded skill row at level 10: param2 is the 15% per extra charge no label names.
NAVIA_SKILL_10 = [7.1064, 0.15, 300.0, 9.0, 0.648, 7.0]
EULA_BURST_LABELS = ["Lightfall Sword Base DMG|{param2:F1P}", "DMG Per Stack|{param3:F1P}"]
EULA_BURST_10 = [4.4208, 7.2556, 1.4824, 30.0, 20.0, 80.0]
EULA_SKILL_LABELS = ["Physical RES Decrease|{param4:P}", "Cryo RES Decrease|{param5:P}"]
EULA_SKILL_10 = [2.6352, 4.4208, 1.728, 0.25, 0.25, 7.0]
LYNEY_SKILL_LABELS = ["Skill DMG|{param1:F1P}", "Skill DMG Bonus|{param2:F1P} ATK/Stack"]
LYNEY_SKILL_10 = [3.0096, 0.9576, 0.2]


def _sheet(slug: str) -> sheets.Sheet:
    [sheet] = [s for s in sheets.all_sheets().values() if s.slug == slug]
    return sheet


def _giver(sheet: sheets.Sheet, *, constellation: int = 0, ascension: int = 6,
           rows: dict[tuple[str, int], tuple[list[str], list[float]]] | None = None,
           levels: dict[str, int] | None = None, **stats: float) -> sheets.Giver:
    """`levels` are the build's stored levels; absent, each row's level (no boost reaches it)."""
    registry = NodeRegistry()
    for quantity, value in stats.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return sheets.Giver(
        name=sheet.character, nanoka_id=sheet.nanoka_id, constellation=constellation,
        ascension_phase=ascension,
        talent_levels=levels or dict((rows or {}).keys()),
        talent_rows={k: sheets.TalentRow(*v) for k, v in (rows or {}).items()},
        constellation_params={n: list(v) for n, v in sheet.pins.constellations.items()},
        passive_params={n: list(v) for n, v in sheet.pins.passives.items()},
        registry=registry,
    )


def _by_key(kit: sheets.ResolvedKit, sheet: sheets.Sheet) -> dict[str, list[float]]:
    """Applied values, grouped by the stat and scope each sheet effect writes."""
    out: dict[str, list[float]] = {}
    for e in kit.bonus.effects:
        out.setdefault(e.stat, []).append(e.value)
    return out


def _unmodelled(kit: sheets.ResolvedKit) -> str:
    return " | ".join(f"{u.what}: {u.reason}" for u in kit.bonus.unmodelled)


# ── a passive held from the start (`a0`): Arlecchino's Balemoon ──────────────────────────


def test_a_passive_unlocked_at_phase_zero_is_read_and_ungated():
    arle = _sheet("arlecchino")
    kit = sheets.resolve(arle, _giver(arle, ascension=0), giver_is_subject=True)
    assert _by_key(kit, arle)["dmg_bonus"] == [arle.pins.passives[0][0]]
    assert sheets.SOURCE_LABEL["a0"] == tags.SRC_ASCENSION_PASSIVE


def test_passive_phases_are_zero_one_and_four():
    sheets.ValueRef(passive=0, param=0)
    with pytest.raises(ValidationError, match="phase 0, 1 or 4"):
        sheets.ValueRef(passive=2, param=0)


def test_the_giver_keeps_a_phase_zero_passive_and_drops_an_unphased_one():
    passives = [SimpleNamespace(unlock_ascension=0, param_list=[0.4, 2.0]),
                SimpleNamespace(unlock_ascension=4, param_list=[1.0]),
                SimpleNamespace(unlock_ascension=None, param_list=[9.0])]
    build = SimpleNamespace(
        id="b", constellation_level=0, ascension_phase=6, talent_levels={},
        character=SimpleNamespace(name="X", nanoka_id=1, talents=[], constellations=[],
                                  ascension_passives=passives))
    giver = kit_buffs.giver_of(build, NodeRegistry())  # type: ignore[arg-type]
    assert dict(giver.passive_params) == {0: [0.4, 2.0], 4: [1.0]}


# ── a unit on a self conversion: the Masque per point of Bond of Life ────────────────────


def test_the_masque_on_arlecchino_is_a_per_candidate_conversion_divided_by_its_unit():
    arle = _sheet("arlecchino")
    # C3 raises Normal Attack by 3: a stored 10 reads the row at 13 (the same numbers here).
    giver = _giver(arle, constellation=6, levels={"normal_attack": 10},
                   rows={("normal_attack", 13): (ARLE_NORMAL_LABELS, ARLE_NORMAL_10)})
    kit = sheets.resolve(arle, giver, giver_is_subject=True)
    flat = [(e.moves, e.value, e.per) for e in kit.bonus.effects
            if e.stat == "flat_damage_from_atk"]
    assert flat == [
        (("normal",), pytest.approx(ARLE_NORMAL_10[11] / 100), "bond"),
        (("normal",), pytest.approx(arle.pins.constellations[1][0] / 100), "bond"),
        (("burst",), pytest.approx(arle.pins.constellations[6][4] / 100), "bond"),
    ]
    bond = next(c for c in kit.bonus.conditions if c.key == "bond")
    assert (bond.default, bond.default_reason, bond.max) == (200, "self", 200)


def test_arlecchinos_kit_reaches_no_teammate():
    arle = _sheet("arlecchino")
    kit = sheets.resolve(arle, _giver(arle, constellation=6), giver_is_subject=False)
    assert kit.bonus.effects == ()


# ── a cited offset: a talent row that is a hit's whole multiplier ────────────────────────


@pytest.mark.parametrize(("slug", "rows", "whole"), [
    ("wriothesley", {("elemental_skill", 10): (WRIO_SKILL_LABELS, WRIO_SKILL_10)},
     WRIO_SKILL_10[0]),
    ("yoimiya", {("elemental_skill", 10): (YOIMIYA_SKILL_LABELS, YOIMIYA_SKILL_10)},
     YOIMIYA_SKILL_10[3]),
])
def test_a_whole_multiplier_row_becomes_a_base_multiplier_less_one(slug, rows, whole):
    sheet = _sheet(slug)
    kit = sheets.resolve(sheet, _giver(sheet, rows=rows), giver_is_subject=True)
    [fist] = [e for e in kit.bonus.effects if e.stat == "base_dmg_bonus"]
    assert fist.value == pytest.approx(whole - 1)
    assert fist.moves == ("normal",)


def test_an_offset_belongs_to_a_plain_parameter():
    offset = sheets.Cited(constant=-1, cite="test")
    with pytest.raises(ValidationError, match="offset"):
        sheets.ValueRef(passive=4, param=0, times_stat="atk", offset=offset)


# ── Hu Tao: the capped conversion is named, C2 moves with her HP ─────────────────────────


def test_hu_tao_names_her_capped_skill_conversion_and_converts_c2_per_candidate():
    hu = _sheet("hu_tao")
    kit = sheets.resolve(hu, _giver(hu, constellation=6), giver_is_subject=True)
    assert "capped conversion of her own Max HP" in _unmodelled(kit)
    assert "DECISIONS §39" in _unmodelled(kit)
    assert [(e.stat, e.moves, e.value) for e in kit.bonus.effects
            if e.stat.startswith("flat")] == [
        ("flat_damage_from_hp", ("skill",), hu.pins.constellations[2][0])]
    # A1 and C4 are for her teammates; C6 is her own.
    assert _by_key(kit, hu)["crit_rate"] == [hu.pins.constellations[6][3]]


def test_hu_taos_a1_and_c4_reach_her_teammates_off_by_default():
    hu = _sheet("hu_tao")
    kit = sheets.resolve(hu, _giver(hu, constellation=4), giver_is_subject=False)
    assert sorted(_by_key(kit, hu)["crit_rate"]) == sorted(
        [hu.pins.passives[1][0], hu.pins.constellations[4][0]])
    assert {c.key: c.default for c in kit.bonus.conditions} == {"flutter": 0, "rest": 0}


# ── Clorinde: the capped A1 named; C4 per Bond of Life ───────────────────────────────────


def test_clorinde_names_her_capped_a1_and_reads_c4_per_point():
    clorinde = _sheet("clorinde")
    kit = sheets.resolve(clorinde, _giver(clorinde, constellation=6), giver_is_subject=True)
    assert "capped conversion of her own ATK" in _unmodelled(kit)
    [c4] = [e for e in kit.bonus.effects if e.per == "bond"]
    assert (c4.stat, c4.moves, c4.value) == ("dmg_bonus", ("burst",),
                                             clorinde.pins.constellations[4][0])
    bond = next(c for c in kit.bonus.conditions if c.key == "bond")
    # 100 points × 2% = C4's own 200% cap.
    assert bond.max * c4.value == pytest.approx(clorinde.pins.constellations[4][1])  # type: ignore[operator]


# ── Navia and Lyney: counts written as gated effects ─────────────────────────────────────


@pytest.mark.parametrize(("team", "atk"), [
    (["geo", "geo", "anemo", "dendro"], 0.0), (["geo", "pyro", "anemo", "geo"], 0.2),
    (["geo", "pyro", "hydro", "anemo"], 0.4), (["geo", "pyro", "hydro", "cryo"], 0.4)])
def test_navias_a4_counts_at_most_two_members(team: list[str], atk: float):
    navia = _sheet("navia")
    kit = sheets.resolve(navia, _giver(navia), giver_is_subject=True,
                         receiver_element="geo", team_elements=team)
    assert sum(_by_key(kit, navia).get("atk_pct", [])) == pytest.approx(
        atk / 0.2 * navia.pins.passives[4][0])


def test_navias_extra_charge_constant_is_the_seeded_skill_parameter():
    navia = _sheet("navia")
    [extra] = [e for e in navia.effects if e.key == "skill_extra"]
    assert extra.value.constant == NAVIA_SKILL_10[1]


@pytest.mark.parametrize(("pyros", "bonus"), [(1, 0), (2, 1), (3, 2), (4, 2)])
def test_lyneys_a4_grows_with_up_to_two_other_pyro_members(pyros: int, bonus: int):
    lyney = _sheet("lyney")
    team = ["pyro"] * pyros + ["anemo"] * (4 - pyros)
    kit = sheets.resolve(lyney, _giver(lyney), giver_is_subject=True, receiver_element="pyro",
                         team_elements=team)
    a4 = lyney.pins.passives[4]
    assert sum(_by_key(kit, lyney)["dmg_bonus"]) == pytest.approx(a4[0] + bonus * a4[1])


def test_lyneys_a1_names_its_row_and_his_props_read_the_skill_row():
    lyney = _sheet("lyney")
    giver = _giver(lyney, rows={("elemental_skill", 10): (LYNEY_SKILL_LABELS, LYNEY_SKILL_10)})
    kit = sheets.resolve(lyney, giver, giver_is_subject=True, receiver_element="pyro",
                         team_elements=["pyro"])
    flat = {e.per or "hat": (e.moves, e.rows, e.value) for e in kit.bonus.effects
            if e.stat == "flat_damage_from_atk"}
    assert flat["props"] == (("skill",), None, pytest.approx(LYNEY_SKILL_10[1]))
    moves, rows, value = flat["hat"]
    assert (moves, value) == (None, lyney.pins.passives[1][1])
    assert [(r.talent, r.label) for r in rows] == [("normal_attack", "Pyrotechnic Strike DMG")]


# ── Yoimiya's A4 is for her teammates; Ganyu's field defaults by who stands in it ────────


def test_yoimiyas_a4_reaches_teammates_only_and_reads_her_stacks():
    yoimiya = _sheet("yoimiya")
    own = sheets.resolve(yoimiya, _giver(yoimiya), giver_is_subject=True)
    mate = sheets.resolve(yoimiya, _giver(yoimiya), giver_is_subject=False)
    assert "atk_pct" not in _by_key(own, yoimiya)
    a4 = yoimiya.pins.passives[4]
    assert [(e.value, e.per) for e in mate.bonus.effects] == [(a4[0], None), (a4[1], "tricks")]
    assert {c.key: c.default for c in mate.bonus.conditions} == {"aurous": 0, "tricks": 10}


def test_ganyus_field_and_c4_default_on_for_her_and_off_for_a_teammate():
    ganyu = _sheet("ganyu")
    own = sheets.resolve(ganyu, _giver(ganyu, constellation=4), giver_is_subject=True)
    mate = sheets.resolve(ganyu, _giver(ganyu, constellation=4), giver_is_subject=False)
    assert {c.key: c.default for c in own.bonus.conditions} == {
        "a1_fired": 1, "in_field": 1, "c1_hit": 1, "c4_stacks": 5}
    assert {c.key: c.default for c in mate.bonus.conditions} == {
        "in_field": 0, "c1_hit": 0, "c4_stacks": 0}
    [c4] = [e for e in mate.bonus.effects if e.per == "c4_stacks"]
    assert c4.value == 0.05
    [c1] = [e for e in mate.bonus.effects if e.stat == "enemy_res"]
    assert c1.value == ganyu.pins.constellations[1][0] < 0


# ── Eula: the Lightfall stacks on her sword only; RES decreases negated ──────────────────


def test_eulas_stacks_reach_her_lightfall_sword_and_her_skill_shreds():
    eula = _sheet("eula")
    # C3 raises her burst by 3: a stored 10 reads the row at 13 (the same numbers here).
    giver = _giver(eula, constellation=4, levels={"elemental_burst": 10, "elemental_skill": 10},
                   rows={("elemental_burst", 13): (EULA_BURST_LABELS, EULA_BURST_10),
        ("elemental_skill", 10): (EULA_SKILL_LABELS, EULA_SKILL_10)})
    kit = sheets.resolve(eula, giver, giver_is_subject=True)
    [stacks] = [e for e in kit.bonus.effects if e.per == "lightfall"]
    assert (stacks.stat, stacks.value) == ("flat_damage_from_atk", EULA_BURST_10[2])
    assert [(r.talent, r.label) for r in stacks.rows or ()] == [
        ("elemental_burst", "Lightfall Sword Base DMG")]
    res = {e.elements: e.value for e in kit.bonus.effects if e.stat == "enemy_res"}
    assert res == {("cryo",): -EULA_SKILL_10[4], ("physical",): -EULA_SKILL_10[3]}
    [c4] = [e for e in kit.bonus.effects if e.stat == "dmg_bonus" and e.rows]
    assert c4.value == eula.pins.constellations[4][0]


def test_every_fifth_batch_fixture_agrees_with_go_exactly():
    """No amplifying reaction in any of them, so not even the 2.78 vs 25/9 gap applies."""
    from tests.unit.go_fixtures_batch5 import batch5_fixtures

    for f in batch5_fixtures():
        assert f["expected"] == pytest.approx(f["go_value"], rel=1e-12), f["name"]
        assert not any(u["reason"].startswith("withheld")
                       for u in f["sources"][0]["bonus"]["unmodelled"]), f["name"]


def test_every_new_sheet_names_what_it_leaves_out():
    for slug in ("hu_tao", "arlecchino", "clorinde", "navia", "wriothesley", "lyney", "yoimiya",
                 "ganyu", "eula"):
        sheet = _sheet(slug)
        assert sheet.unmodelled, slug
        assert sheet.verified_by, slug
