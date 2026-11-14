"""Math-fallback P2, task 11 (seventh batch): the commonly played characters next on the list, and
the one small format extension they needed (`docs/DESIGN_team_math_fallback.md` §2.6,
seventh-batch table): a giver's own CRIT Rate as a value's stat (Rosaria's A4).

Each sheet's GO agreement on its main effect is `test_go_formula_fixtures.py`'s job (fixtures in
`go_fixtures_batch7.py`). This file checks what one fixture per sheet does not: the cap on
Rosaria's share, a choice that follows the receiver (Venti's C6), a team gate (Nilou), a stack
cap written as two gated effects (Freminet's C4), a raised stack maximum (Mika), the receivers and
the subject's conversions (Sigewinne, Sethos, Albedo), the defaults each sheet chose, the per-row
moves, and the parts of each kit the sheets name instead of applying.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins`; talent rows are the seeded rows at the level named, verbatim.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import sheets, tags
from tests.unit.test_formula_sheets_batch6 import _giver, _sheet, _unmodelled, _values

BATCH7 = ("xiao", "venti", "nilou", "albedo", "chiori", "sigewinne", "sethos",
          "shikanoin_heizou", "freminet", "rosaria", "candace", "mika", "diluc", "klee", "lisa",
          "ningguang", "chongyun")


# ── a giver's own CRIT Rate: Rosaria's A4 ───────────────────────────────────────────────────


def test_crit_rate_is_a_giver_stat_a_value_may_read():
    assert tags.Q_CRIT_RATE in sheets.GIVER_STATS
    assert tags.Q_CRIT_RATE not in sheets.STATIC_STATS


@pytest.mark.parametrize(("crit_rate", "share"), [
    (0.5, 0.15 * 0.5),        # below the cap: 15% of her CRIT Rate
    (1.0, 0.15),              # exactly at it
    (1.4, 0.15),              # past it: capped at A4's own 15%
])
def test_rosarias_a4_shares_a_part_of_her_crit_rate_up_to_its_cap(crit_rate, share):
    """GO `min(prod(percent(crBonus), own.premod.critRate_), percent(maxBonus))` (`pando
    Rosaria.ts:99-110`), into `notOwnBuff`."""
    rosaria = _sheet("rosaria")
    assert rosaria.pins.passives[4][0] == 0.15
    assert rosaria.pins.passives[4][2] == 0.15
    kit = sheets.resolve(rosaria, _giver(rosaria, crit_rate=crit_rate), giver_is_subject=False)
    assert _values(kit, "crit_rate") == [pytest.approx(share)]


def test_rosarias_a4_does_not_reach_herself():
    rosaria = _sheet("rosaria")
    kit = sheets.resolve(rosaria, _giver(rosaria, crit_rate=0.8), giver_is_subject=True)
    assert _values(kit, "crit_rate") == [rosaria.pins.passives[1][0]]   # her A1 alone


# ── choices, gates and stack caps ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("receiver", "default"), [
    ("pyro", "pyro"), ("cryo", "cryo"), ("anemo", ""), ("geo", ""),
])
def test_ventis_c6_absorbs_the_receivers_element(receiver, default):
    venti = _sheet("venti")
    absorbed = next(c for c in venti.conditions if c.key == "c6_absorbed")
    assert absorbed.resolve(giver_is_subject=False, receiver_element=receiver).default == default


def test_ventis_c2_doubles_on_a_launched_opponent_and_names_its_constants():
    venti = _sheet("venti")
    kit = sheets.resolve(venti, _giver(venti, constellation=2), giver_is_subject=False)
    by_state = {(e.when[0].values[0], e.elements): e.value for e in kit.bonus.effects}
    assert by_state == {("hit", ("anemo",)): -0.12, ("hit", ("physical",)): -0.12,
                        ("launched", ("anemo",)): -0.24, ("launched", ("physical",)): -0.24}
    c2 = next(c for c in venti.conditions if c.key == "c2_state")
    assert c2.resolve(giver_is_subject=False).default == "hit"


@pytest.mark.parametrize(("team", "applies"), [
    (["hydro", "dendro"], True),
    (["hydro", "dendro", "dendro", "hydro"], True),
    (["hydro", "hydro"], False),                      # no Dendro member
    (["hydro", "dendro", "pyro"], False),             # a third element
])
def test_nilous_bounty_holds_only_in_a_hydro_and_dendro_party(team, applies):
    nilou = _sheet("nilou")
    kit = sheets.resolve(nilou, _giver(nilou, constellation=2), giver_is_subject=False,
                         receiver_element="dendro", team_elements=team)
    stats = {e.stat for e in kit.bonus.effects}
    assert ("elemental_mastery" in stats) is applies
    assert ("enemy_res" in stats) is applies


def test_nilous_talent_boosts_follow_the_game_data_not_the_pando_port():
    """GO's pando port gives C3 to her skill; its WR sheet, gcsim and the generated table give
    C3 to her burst and C5 to her skill."""
    nilou = _sheet("nilou")
    assert {(b.constellation, b.talent) for b in nilou.talent_boosts} == {
        (3, "elemental_burst"), (5, "elemental_skill")}


@pytest.mark.parametrize(("stacks", "atk"), [(1, 0.09), (2, 0.18), (3, 0.18)])
def test_freminets_c4_stops_at_two_stacks_of_three(stacks, atk):
    """GO `prod(atk_, min(stacks, maxStacks))` (`pando Freminet.ts:108-115`): two effects, per
    stack below the maximum and the maximum times C4's own 2 at three."""
    freminet = _sheet("freminet")
    kit = sheets.resolve(freminet, _giver(freminet, constellation=6), giver_is_subject=True)
    total = 0.0
    for e in kit.bonus.effects:
        if e.stat != "atk_pct" or not any(stacks in w.values for w in e.when):
            continue
        total += e.value * (stacks if e.per else 1)
    assert total == pytest.approx(atk)


@pytest.mark.parametrize(("constellation", "top"), [(0, 4), (5, 4), (6, 5)])
def test_mikas_detector_maximum_is_raised_by_c6(constellation, top):
    mika = _sheet("mika")
    kit = sheets.resolve(mika, _giver(mika, constellation=constellation),
                         giver_is_subject=False)
    detector = next(c for c in kit.bonus.conditions if c.key == "detector")
    assert (detector.max, detector.default) == (top, top)


@pytest.mark.parametrize(("stacks", "flat_rows"), [(3, 1), (4, 2)])
def test_heizous_conviction_joins_only_at_four_stacks(stacks, flat_rows):
    heizou = _sheet("shikanoin_heizou")
    labels = ["Skill DMG|{param1:F1P}", "Declension DMG Bonus|{param2:F1P}/stack",
              "Conviction DMG Bonus|{param3:F1P}"]
    giver = _giver(heizou, levels={"elemental_skill": 10},
                   rows={("elemental_skill", 10): (labels, [4.09536, 1.02384, 2.04768])})
    kit = sheets.resolve(heizou, giver, giver_is_subject=True)
    flats = [e for e in kit.bonus.effects if e.stat == "flat_damage_from_atk"]
    reaching = [e for e in flats if not e.when or any(stacks in w.values for w in e.when)]
    assert len(reaching) == flat_rows
    assert {r.label for e in flats for r in e.rows or ()} == {"Skill DMG"}


# ── receivers, and the subject's own conversions ────────────────────────────────────────────


def test_sigewinnes_a1_and_c1_sum_to_one_cap_for_a_teammate():
    """GO `min(cmpGE(c1, 3500, 2800), prod(max(0, hp - 30000), cmpGE(c1, 100, 80) / 1000))`
    (`pando Sigewinne.ts:150-169`): A1 and C1's raise reach their caps at the same HP, so the
    two effects sum to GO's one."""
    sigewinne = _sheet("sigewinne")
    for hp_pct, expected in ((1.0, (13348 * 2 + 4780 - 30000) * 0.1), (5.0, 3500.0)):
        kit = sheets.resolve(sigewinne, _giver(sigewinne, constellation=1, base_hp=13348.0,
                                               hp_pct=hp_pct, flat_hp=4780.0),
                             giver_is_subject=False)
        assert sum(_values(kit, "flat_damage")) == pytest.approx(expected)


def test_sigewinnes_own_skill_gets_her_a1_as_one_capped_conversion():
    sigewinne = _sheet("sigewinne")
    kit = sheets.resolve(sigewinne, _giver(sigewinne, constellation=1, base_hp=13348.0),
                         giver_is_subject=True)
    [own] = [e for e in kit.bonus.effects if e.stat == "flat_damage_from_hp"]
    assert (own.value, own.threshold, own.cap) == pytest.approx((0.08, 30000.0, 2800.0))
    assert "two capped conversions" in _unmodelled(kit)


@pytest.mark.parametrize(("slug", "constellation", "stat"), [
    ("sethos", 0, "flat_damage_from_em"),          # Dusk Bolts, A4
    ("albedo", 2, "flat_damage_from_def"),         # C2 on his burst
    ("chiori", 6, "flat_damage_from_def"),         # C6 on her Normal Attacks
    ("shikanoin_heizou", 0, "flat_damage_from_atk"),
    ("candace", 0, "dmg_bonus_from_hp"),           # A4 on her own Normal Attacks
])
def test_a_subjects_buff_from_her_own_moving_stat_is_a_per_candidate_conversion(
        slug, constellation, stat):
    sheet = _sheet(slug)
    rows = {}
    if slug == "sethos":
        dusk = "Dusk Bolt DMG Increase|{param1:F1P} Elemental Mastery"
        rows = {("elemental_burst", 10): ([dusk], [3.53088])}
    if slug == "shikanoin_heizou":
        rows = {("elemental_skill", 10): (["Declension DMG Bonus|{param2:F1P}/stack",
                                           "Conviction DMG Bonus|{param3:F1P}"],
                                          [4.09536, 1.02384, 2.04768])}
    if slug == "candace":
        rows = {("elemental_burst", 10): (["DMG Bonus|{param3:F1P}"], [0.118987, 9.0, 0.2])}
    giver = _giver(sheet, constellation=constellation,
                   levels=dict.fromkeys(sheets.TALENTS, 10), rows=rows)
    kit = sheets.resolve(sheet, giver, giver_is_subject=True)
    assert stat in {e.stat for e in kit.bonus.effects}


@pytest.mark.parametrize(("slug", "constellation", "stat", "reaches_teammate"), [
    ("xiao", 6, "dmg_bonus", False),
    ("venti", 6, "enemy_res", True),
    ("venti", 6, "dmg_bonus", False),        # C4 is his own
    ("albedo", 6, "elemental_mastery", True),
    ("albedo", 6, "flat_damage", False),
    ("sethos", 4, "elemental_mastery", True),
    ("shikanoin_heizou", 6, "elemental_mastery", True),
    ("mika", 6, "crit_dmg", True),
    ("diluc", 6, "dmg_bonus", False),
    ("klee", 6, "def_reduction", True),
    ("klee", 6, "dmg_bonus", True),          # C6 party Pyro (A1's Charged bonus is hers)
    ("lisa", 0, "def_reduction", True),
    ("ningguang", 0, "dmg_bonus", True),
    ("chongyun", 6, "enemy_res", True),
    ("chongyun", 6, "dmg_bonus", False),
    ("chiori", 6, "dmg_bonus", False),
])
def test_who_each_kit_reaches(slug, constellation, stat, reaches_teammate):
    sheet = _sheet(slug)
    kit = sheets.resolve(sheet, _giver(sheet, constellation=constellation, hp=30000.0),
                         giver_is_subject=False, team_elements=["pyro", "hydro"],
                         receiver_element="pyro")
    assert (stat in {e.stat for e in kit.bonus.effects}) is reaches_teammate


def test_klees_teammate_gets_only_her_c6_pyro_and_c2_def():
    klee = _sheet("klee")
    kit = sheets.resolve(klee, _giver(klee, constellation=6), giver_is_subject=False)
    assert sorted((e.stat, e.value) for e in kit.bonus.effects) == [
        ("def_reduction", 0.23), ("dmg_bonus", 0.1)]


# ── defaults (DECISIONS §41) ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "key", "subject", "value", "reason"), [
    ("xiao", "a1_stacks", True, 5, "self"),
    ("venti", "c6_hit", False, 1, "teammate"),
    ("nilou", "bounty", False, 1, "teammate"),
    ("albedo", "low_hp", True, 0, "situational"),
    ("albedo", "c6_shield", False, 0, "situational"),
    ("chiori", "construct", True, 0, "situational"),
    ("sethos", "c4_two", False, 0, "situational"),          # one target
    ("freminet", "shatter", True, 0, "situational"),
    ("freminet", "c4c6_stacks", True, 0, "situational"),
    ("rosaria", "a4_share", False, 1, "teammate"),
    ("diluc", "c1_above", True, 0, "situational"),
    ("diluc", "c2_stacks", True, 0, "situational"),
    ("chongyun", "c6_lower", True, 0, "situational"),
    ("klee", "spark", True, 1, "self"),
])
def test_each_new_condition_defaults_by_the_rule(slug, key, subject, value, reason):
    condition = next(c for c in _sheet(slug).conditions if c.key == key)
    c = condition.resolve(giver_is_subject=subject, receiver_element="pyro")
    assert (c.default, c.default_reason) == (value, reason)
    assert reason == "self" or c.default_note


# ── per-row moves, and what each sheet leaves out ───────────────────────────────────────────


def test_sethos_shadowpiercing_shot_is_a_charged_attack():
    assert sheets.row_move("10000097", "normal_attack", "Shadowpiercing Shot DMG") == "charged"
    assert sheets.row_move("10000097", "normal_attack", "1-Hit DMG") is None


def test_every_batch7_sheet_is_verified_and_names_what_it_leaves_out():
    for slug in BATCH7:
        sheet = _sheet(slug)
        assert sheet.unmodelled, slug
        assert sheet.verified_by, slug
