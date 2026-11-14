"""Math-fallback P2, task 11 (eighth batch): the small sheets of ordinary buffs — Amber, Xinyan,
Yanfei, Barbara, Razor, Kaeya, Qiqi, Sayu, Diona, Collei, Yaoyao and Gaming — then three of the
newer kits: Fischl (her non-Hexerei part), Mualani and Flins (his non-Lunar parts)
(`docs/DESIGN_team_math_fallback.md` §2.6, eighth-batch table). No format extension was needed.

Each sheet's GO agreement on its main effect is `test_go_formula_fixtures.py`'s job (fixtures in
`go_fixtures_batch8.py`). This file checks what one fixture per sheet does not: who each kit
reaches, the constants no seeded list carries, a stack maximum raised by a constellation
(Yanfei's Seals), the row scope (Sayu's kicks, Gaming's Cloudstrider, Xinyan's C2) and the row
move, the subject's conversion (Xinyan's C6), the defaults each sheet chose, and the parts each
kit leaves out.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins`.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import sheets
from tests.unit.test_formula_sheets_batch6 import _giver, _sheet, _unmodelled, _values

BATCH8 = ("amber", "xinyan", "yanfei", "barbara", "razor", "kaeya", "qiqi", "sayu", "diona",
          "collei", "yaoyao", "gaming", "fischl", "mualani", "flins")


# ── who each kit reaches ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "constellation", "stat", "reaches_teammate"), [
    ("amber", 6, "atk_pct", True),              # C6 to the party (A4 is hers)
    ("amber", 6, "crit_rate", False),           # A1 on her own burst
    ("xinyan", 6, "dmg_bonus", True),           # A4 Physical while shielded
    ("xinyan", 6, "enemy_res", True),
    ("xinyan", 6, "crit_rate", False),          # C2 on her own burst row
    ("xinyan", 6, "flat_atk", False),           # C6 on her own Charged Attacks
    ("yanfei", 6, "dmg_bonus", False),
    ("barbara", 6, "dmg_bonus", True),
    ("razor", 6, "def_reduction", True),
    ("razor", 6, "dmg_bonus", False),
    ("kaeya", 6, "crit_rate", False),
    ("qiqi", 6, "dmg_bonus", False),
    ("sayu", 6, "dmg_bonus", False),
    ("diona", 6, "elemental_mastery", True),
    ("diona", 6, "dmg_bonus", False),           # C2 on her own skill
    ("collei", 6, "elemental_mastery", True),
    ("yaoyao", 6, "dmg_bonus", True),
    ("gaming", 6, "crit_dmg", False),
])
def test_who_each_kit_reaches(slug, constellation, stat, reaches_teammate):
    sheet = _sheet(slug)
    kit = sheets.resolve(sheet, _giver(sheet, constellation=constellation),
                         giver_is_subject=False, team_elements=["pyro", "hydro"],
                         receiver_element="pyro")
    assert (stat in {e.stat for e in kit.bonus.effects}) is reaches_teammate


def test_colleis_c4_does_not_reach_herself():
    collei = _sheet("collei")
    kit = sheets.resolve(collei, _giver(collei, constellation=4), giver_is_subject=True)
    assert _values(kit, "elemental_mastery") == []


@pytest.mark.parametrize(("slug", "constellation", "stat", "value"), [
    ("barbara", 2, "dmg_bonus", 0.15),
    ("razor", 1, "dmg_bonus", 0.1),
    ("razor", 2, "crit_rate", 0.1),
    ("razor", 4, "def_reduction", 0.15),
    ("kaeya", 1, "crit_rate", 0.15),
    ("qiqi", 2, "dmg_bonus", 0.15),
])
def test_constants_no_seeded_list_carries_are_cited(slug, constellation, stat, value):
    """Their seeded constellation lists are empty, or carry the Hexerei rework (Qiqi's C2 0.5
    is the Hexerei ATK); GO and gcsim both write the number, and the sheet cites both."""
    sheet = _sheet(slug)
    [effect] = [e for e in sheet.effects
                if e.source == f"c{constellation}" and e.stat == stat]
    assert effect.value.constant == value
    assert "GO" in (effect.value.cite or "")
    assert "gcsim" in (effect.value.cite or "")
    kit = sheets.resolve(sheet, _giver(sheet, constellation=constellation),
                         giver_is_subject=True)
    assert value in _values(kit, stat)


def test_the_constants_stay_locked_below_their_constellation():
    razor = _sheet("razor")
    kit = sheets.resolve(razor, _giver(razor, constellation=0), giver_is_subject=True)
    assert kit.bonus.effects == ()


# ── a raised stack maximum, row scope and row moves ─────────────────────────────────────────


@pytest.mark.parametrize(("constellation", "top"), [(0, 3), (5, 3), (6, 4)])
def test_yanfeis_seal_maximum_is_raised_by_c6(constellation, top):
    yanfei = _sheet("yanfei")
    kit = sheets.resolve(yanfei, _giver(yanfei, constellation=constellation),
                         giver_is_subject=True)
    seals = next(c for c in kit.bonus.conditions if c.key == "seals")
    assert (seals.max, seals.default) == (top, top)


def test_sayus_c2_reaches_the_press_kick_flat_and_the_held_kicks_per_half_second():
    sayu = _sheet("sayu")
    kit = sheets.resolve(sayu, _giver(sayu, constellation=2), giver_is_subject=True)
    by_rows = {tuple(r.label for r in e.rows or ()): e.per for e in kit.bonus.effects}
    assert by_rows == {
        ("#Fuufuu Whirlwind Kick {LAYOUT_MOBILE#Tap}{LAYOUT_PC#Press}{LAYOUT_PS#Press} DMG",):
            None,
        ("Fuufuu Whirlwind Kick Hold DMG", "Fuufuu Whirlwind Kick Elemental DMG"): "hold",
    }
    assert {e.value for e in kit.bonus.effects} == {sayu.pins.constellations[2][0]}


def test_gamings_cloudstrider_is_a_plunge_and_carries_his_a4_and_c6():
    assert sheets.row_move("10000092", "elemental_skill",
                           "Plunging Attack: Charmed Cloudstrider DMG") == "plunge"
    gaming = _sheet("gaming")
    kit = sheets.resolve(gaming, _giver(gaming, constellation=6), giver_is_subject=True)
    scoped = {e.stat for e in kit.bonus.effects if e.rows}
    assert scoped == {"dmg_bonus", "crit_rate", "crit_dmg"}
    assert all(r.label == "Plunging Attack: Charmed Cloudstrider DMG"
               for e in kit.bonus.effects for r in e.rows or ())


def test_xinyans_c2_reaches_only_her_bursts_physical_row():
    xinyan = _sheet("xinyan")
    kit = sheets.resolve(xinyan, _giver(xinyan, constellation=2), giver_is_subject=True)
    [c2] = [e for e in kit.bonus.effects if e.stat == "crit_rate"]
    assert [(r.talent, r.label) for r in c2.rows or ()] == [("elemental_burst", "Skill DMG")]


def test_xinyans_c6_on_herself_is_a_per_candidate_conversion_on_charged_attacks():
    xinyan = _sheet("xinyan")
    kit = sheets.resolve(xinyan, _giver(xinyan, constellation=6, base_def=799.0),
                         giver_is_subject=True)
    [c6] = [e for e in kit.bonus.effects if e.stat == "flat_atk_from_def"]
    assert c6.value == pytest.approx(xinyan.pins.constellations[6][1])
    assert c6.moves == ("charged",)


# ── defaults (DECISIONS §41) ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "key", "subject", "value", "reason"), [
    ("amber", "a4_weak", True, 1, "self"),
    ("amber", "c6_rain", False, 1, "teammate"),
    ("xinyan", "shielded", False, 1, "teammate"),
    ("yanfei", "after_burst", True, 1, "self"),
    ("yanfei", "c2_low", True, 0, "situational"),
    ("barbara", "c2_skill", False, 1, "teammate"),
    ("razor", "c1_orb", True, 1, "self"),
    ("razor", "c2_low", True, 0, "situational"),
    ("kaeya", "cryo", True, 1, "self"),
    ("qiqi", "cryo", True, 1, "self"),
    ("sayu", "hold", True, 20, "self"),
    ("diona", "c6_above", False, 1, "teammate"),
    ("collei", "after_burst", False, 1, "teammate"),
    ("yaoyao", "c1_radish", False, 1, "teammate"),
    ("gaming", "a4_hp", True, 0, "situational"),
    ("gaming", "c2_overheal", True, 0, "situational"),
])
def test_each_new_condition_defaults_by_the_rule(slug, key, subject, value, reason):
    condition = next(c for c in _sheet(slug).conditions if c.key == key)
    c = condition.resolve(giver_is_subject=subject, receiver_element="pyro")
    assert (c.default, c.default_reason) == (value, reason)
    assert reason == "self" or c.default_note


# ── what each sheet leaves out ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "named"), [
    ("razor", "Hexerei"),
    ("qiqi", "Hexerei"),
    ("diona", "Hexerei"),
    ("sayu", "a product of two of her stats"),
    ("yaoyao", "capped conversion of her HP into EM"),
    ("amber", "separate skill row"),
    ("fischl", "Hexerei"),
    ("flins", "Lunar"),
])
def test_the_parts_each_kit_leaves_out_are_named(slug, named):
    sheet = _sheet(slug)
    kit = sheets.resolve(sheet, _giver(sheet, constellation=6), giver_is_subject=True)
    assert named in _unmodelled(kit)


# ── the newer kits: Fischl, Mualani, Flins ──────────────────────────────────────────────────

MUALANI_SKILL = (["Sharky's Bite Base DMG|{param1:F2P} Max HP",
                  "Wave Momentum DMG Bonus|{param2:F2P} Max HP/Stack",
                  "Sharky's Surging Bite Additional DMG Bonus|{param3:F2P} Max HP"],
                 [0.15624, 0.07812, 0.3906])


@pytest.mark.parametrize(("stacks", "first", "slope"), [
    (0, 0, 0.0),
    (2, 0, 2 * 0.07812),
    (3, 0, 3 * 0.07812 + 0.3906),        # a Surging Bite
    (3, 1, 3 * 0.07812 + 0.3906 + 0.66),
])
def test_mualanis_bite_adds_her_hp_per_stack_and_on_a_surging_bite(stacks, first, slope):
    """GO's four bite rows (`pando Mualani.ts:88-96,152-163`), on the catalogue's one: the
    subject's conversions that reach it under each state sum to GO's added share of Max HP."""
    mualani = _sheet("mualani")
    kit = sheets.resolve(mualani, _giver(mualani, constellation=1,
                                         levels={"elemental_skill": 10},
                                         rows={("elemental_skill", 10): MUALANI_SKILL}),
                         giver_is_subject=True)
    state = {"momentum": stacks, "c1_first": first}
    total = 0.0
    for e in kit.bonus.effects:
        if e.stat != "flat_damage_from_hp" or e.moves:
            continue
        if all(state[w.condition] in w.values for w in e.when):
            total += e.value * (stacks if e.per else 1)
    assert total == pytest.approx(slope)
    assert sheets.row_move("10000102", "elemental_skill", "Sharky's Bite Base DMG") == "normal"


@pytest.mark.parametrize(("stacks", "share"), [(1, 0.15), (2, 0.3), (3, 0.45)])
def test_mualanis_a4_reads_its_table_by_stack(stacks, share):
    mualani = _sheet("mualani")
    kit = sheets.resolve(mualani, _giver(mualani), giver_is_subject=True)
    [effect] = [e for e in kit.bonus.effects if e.moves == ("burst",) and e.when
                and e.when[0].condition == "puffer" and stacks in e.when[0].values]
    assert effect.value == pytest.approx(share)


def test_fischls_c2_is_a_per_candidate_conversion_on_summoning_dmg():
    fischl = _sheet("fischl")
    kit = sheets.resolve(fischl, _giver(fischl, constellation=2), giver_is_subject=True)
    [c2] = kit.bonus.effects
    assert (c2.stat, c2.value) == ("flat_damage_from_atk", fischl.pins.constellations[2][0])
    assert [r.label for r in c2.rows or ()] == ["Summoning DMG"]


def test_flins_c2_shred_needs_both_its_conditions_and_his_skill_rows_are_attacks():
    flins = _sheet("flins")
    kit = sheets.resolve(flins, _giver(flins, constellation=2), giver_is_subject=False)
    [c2] = [e for e in kit.bonus.effects if e.stat == "enemy_res"]
    assert c2.value == pytest.approx(-flins.pins.constellations[2][2])
    assert {w.condition for w in c2.when} == {"c2_hit", "moonsign"}
    assert sheets.row_move("10000120", "elemental_skill", "3-Hit DMG") == "normal"
    assert sheets.row_move("10000120", "elemental_skill", "Charged Attack DMG") == "charged"
    assert sheets.row_move("10000120", "normal_attack", "3-Hit DMG") is None


@pytest.mark.parametrize(("slug", "key", "value", "reason"), [
    ("mualani", "momentum", 3, "self"),
    ("mualani", "c1_first", 0, "situational"),
    ("mualani", "puffer", 0, "situational"),
    ("flins", "moonsign", 0, "situational"),
])
def test_the_newer_kits_conditions_default_by_the_rule(slug, key, value, reason):
    condition = next(c for c in _sheet(slug).conditions if c.key == key)
    c = condition.resolve(giver_is_subject=True, receiver_element="hydro")
    assert (c.default, c.default_reason) == (value, reason)


def test_every_batch8_sheet_is_verified_and_names_what_it_leaves_out():
    for slug in BATCH8:
        sheet = _sheet(slug)
        assert sheet.unmodelled, slug
        assert sheet.verified_by, slug
