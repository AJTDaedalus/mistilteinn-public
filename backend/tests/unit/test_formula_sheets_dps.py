"""Math-fallback P2, task 11 (third batch) — the DPS characters' sheets, and the format extensions
they needed (`docs/DESIGN_team_math_fallback.md` §2.6).

Each sheet's GO agreement on its main effect is `test_go_formula_fixtures.py`'s job. This file
checks what one fixture per sheet does not: each extension resolves, and refuses, as the DESIGN
says — the n-th parameter of a talent row, a unit on a `per` condition, ATK from the subject's
own DEF, base ATK, a base-damage multiplier — and the parts of each kit a fixture does not reach.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins` rather than retyped, so a re-pin moves these tests with the sheets.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.formula.builder import const
from app.formula.genshin import sheets, tags
from app.pando.calculator import NodeRegistry

SKIRK_BURST_LABELS = [
    "Slash DMG|{param1:F1P} \u00d75", "Final Slash DMG|{param2:F1P}",
    "Serpent's Subtlety Bonus|{param3:F2P} ATK Per Point",
    "0/1/2/3 Void Rift Absorption DMG Bonus|{param4:F1P}/{param5:F1P}/{param6:F1P}/{param7:F1P}",
    "CD|{param8:F1}s"]
SKIRK_BURST_10 = [2.20968, 3.6828, 0.34782, 0.08, 0.12, 0.16, 0.2, 15.0]
NOELLE_BURST_LABELS = ["Burst DMG|{param1:P}", "Skill DMG|{param2:P}", "ATK Bonus|{param3:P} DEF"]
#: Seeded burst rows at 9 and at 12 (C5's boost), verbatim.
NOELLE_BURST = {9: [1.1424, 1.5776, 0.68], 12: [1.344, 1.856, 0.8]}
MAVUIKA_BURST_LABELS = ["Skill DMG|{param1:F1P}",
                        "Crucible of Death and Life Duration|{param2:F1}s",
                        "Sunfell Slice DMG Bonus|{param3:F1P} ATK per Fighting Spirit"]
MAVUIKA_BURST_10 = [8.0064, 7.0, 0.0288]


def _sheet(slug: str) -> sheets.Sheet:
    [sheet] = [s for s in sheets.all_sheets().values() if s.slug == slug]
    return sheet


def _giver(sheet: sheets.Sheet, *, constellation: int = 0, ascension: int = 6,
           talent_levels: dict[str, int] | None = None,
           talent_rows: dict[tuple[str, int], sheets.TalentRow] | None = None,
           **stats: float) -> sheets.Giver:
    registry = NodeRegistry()
    for quantity, value in stats.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return sheets.Giver(
        name=sheet.character, nanoka_id=sheet.nanoka_id, constellation=constellation,
        ascension_phase=ascension, talent_levels=talent_levels or {},
        talent_rows=talent_rows or {},
        constellation_params={n: list(v) for n, v in sheet.pins.constellations.items()},
        passive_params={n: list(v) for n, v in sheet.pins.passives.items()},
        registry=registry,
    )


def _skirk(constellation: int = 0, labels: list[str] | None = None) -> sheets.Giver:
    return _giver(_sheet("skirk"), constellation=constellation,
                  talent_levels={"elemental_burst": 10},
                  talent_rows={("elemental_burst", 10): sheets.TalentRow(
                      labels or SKIRK_BURST_LABELS, SKIRK_BURST_10)}, atk=2000.0)


def _effects(kit: sheets.ResolvedKit, stat: str) -> list[float]:
    return [e.value for e in kit.bonus.effects if e.stat == stat]


def _condition(kit: sheets.ResolvedKit, key: str) -> object:
    return next(c for c in kit.bonus.conditions if c.key == key)


# ── the n-th parameter of a talent row (Skirk's Void Rifts) ──────────────────────────────


def test_each_void_rift_count_reads_its_own_parameter_of_the_one_row():
    kit = sheets.resolve(_sheet("skirk"), _skirk(), giver_is_subject=True)
    by_rifts = {e.when[0].values[0]: e.value for e in kit.bonus.effects
                if e.when and e.when[0].condition == "void_rifts"}
    assert by_rifts == {"0": pytest.approx(0.08), "1": pytest.approx(0.12),
                        "2": pytest.approx(0.16), "3": pytest.approx(0.2)}
    rifts = _condition(kit, "void_rifts")
    assert (rifts.default, rifts.default_reason) == ("", "situational")  # type: ignore[attr-defined]


def test_a_row_that_names_fewer_parameters_withholds_the_missing_ones():
    labels = [*SKIRK_BURST_LABELS[:3],
              "0/1/2/3 Void Rift Absorption DMG Bonus|{param4:F1P}/{param5:F1P}",
              "CD|{param8:F1}s"]
    kit = sheets.resolve(_sheet("skirk"), _skirk(labels=labels), giver_is_subject=True)
    # The pinned label changed, so all four are withheld by name rather than read by position.
    assert not [e for e in kit.bonus.effects if e.when and e.when[0].condition == "void_rifts"]
    assert sum("Void Rifts" in u.what and u.reason.startswith("withheld")
               for u in kit.bonus.unmodelled) == 4


def test_nth_belongs_to_a_talent_row():
    with pytest.raises(ValidationError, match="nth"):
        sheets.ValueRef(constellation=2, param=0, nth=1)


# ── Skirk: the serpent's flat damage, its C2 raise, A4 and C4 by stack ──────────────────


def test_serpents_subtlety_is_self_flat_damage_per_point_raised_by_c2():
    skirk = _sheet("skirk")
    c0 = sheets.resolve(skirk, _skirk(), giver_is_subject=True)
    c2 = sheets.resolve(skirk, _skirk(constellation=2), giver_is_subject=True)
    assert _effects(c0, "flat_damage_from_atk") == [pytest.approx(0.34782)]
    assert _condition(c0, "serpent_over").default == 12  # type: ignore[attr-defined]
    raise_by = skirk.pins.constellations[2][0]
    assert _condition(c2, "serpent_over").default == 12 + raise_by  # type: ignore[attr-defined]


def test_skirks_a4_and_c4_are_read_by_the_stack_count_and_default_off():
    skirk = _sheet("skirk")
    kit = sheets.resolve(skirk, _skirk(constellation=4), giver_is_subject=True)
    a4 = skirk.pins.passives[4]
    by_move = {(e.moves, e.when[0].values[0]): e.value for e in kit.bonus.effects
               if e.stat == "base_dmg_bonus"}
    assert by_move == {(("normal",), 1): pytest.approx(a4[1]), (("normal",), 2): a4[2],
                       (("normal",), 3): a4[3], (("burst",), 1): a4[4], (("burst",), 2): a4[5],
                       (("burst",), 3): a4[6]}
    c4 = {e.when[0].values[0]: e.value for e in kit.bonus.effects
          if e.stat == "atk_pct" and e.when[0].condition == "a4_stacks"}
    assert c4 == dict(zip((1, 2, 3), skirk.pins.constellations[4][:3], strict=True))
    stacks = _condition(kit, "a4_stacks")
    assert (stacks.default, stacks.max) == (0, 3)  # type: ignore[attr-defined]


# ── a unit on a `per` condition (Neuvillette's A4) ───────────────────────────────────────


def test_neuvillettes_a4_is_per_percentage_point_of_hp_counted_per_100():
    neuvillette = _sheet("neuvillette")
    kit = sheets.resolve(neuvillette, _giver(neuvillette), giver_is_subject=True)
    [a4] = [e for e in kit.bonus.effects if e.per == "a4_hp"]
    assert (a4.stat, a4.elements) == ("dmg_bonus", ("hydro",))
    assert a4.value == pytest.approx(neuvillette.pins.passives[4][2] / 100)
    hp = _condition(kit, "a4_hp")
    assert (hp.default, hp.default_reason, hp.max) == (0, "situational", 50)  # type: ignore[attr-defined]


def test_a_unit_counts_a_stat_or_a_condition_and_nothing_else():
    unit = sheets.Cited(constant=100, cite="test")
    with pytest.raises(ValidationError, match="unit"):
        sheets.SheetEffect(key="k", label="l", source="a4", receivers="self", stat="dmg_bonus",
                           value=sheets.ValueRef(passive=4, param=2, stat_unit=unit), go="pando:x")


def test_neuvillettes_a1_is_a_base_multiplier_on_charged_attacks_by_stack():
    neuvillette = _sheet("neuvillette")
    kit = sheets.resolve(neuvillette, _giver(neuvillette, constellation=2), giver_is_subject=True)
    a1 = {e.when[0].values[0]: e.value for e in kit.bonus.effects if e.stat == "base_dmg_bonus"}
    assert a1 == dict(zip((1, 2, 3), neuvillette.pins.passives[1][:3], strict=True))
    [c2] = [e for e in kit.bonus.effects if e.stat == "crit_dmg"]
    assert (c2.per, c2.moves, c2.value) == ("a1_stacks", ("charged",),
                                            neuvillette.pins.constellations[2][0])


# ── ATK from the subject's own DEF (Noelle's Sweeping Time) ──────────────────────────────


def _noelle(constellation: int = 0) -> sheets.Giver:
    rows = {("elemental_burst", lv): sheets.TalentRow(NOELLE_BURST_LABELS, params)
            for lv, params in NOELLE_BURST.items()}
    return _giver(_sheet("noelle"), constellation=constellation,
                  talent_levels={"elemental_burst": 9}, talent_rows=rows, **{"def": 2500.0})


def test_noelle_on_herself_carries_atk_from_def_per_candidate_not_a_frozen_number():
    kit = sheets.resolve(_sheet("noelle"), _noelle(), giver_is_subject=True)
    assert [(e.stat, e.value) for e in kit.bonus.effects] == [
        ("flat_atk_from_def", pytest.approx(0.68))]


def test_c5_raises_the_ratio_and_c6_adds_its_own_share():
    noelle = _sheet("noelle")
    kit = sheets.resolve(noelle, _noelle(constellation=6), giver_is_subject=True)
    assert sorted(_effects(kit, "flat_atk_from_def")) == pytest.approx(
        sorted([0.8, noelle.pins.constellations[6][0]]))
    assert _effects(kit, "dmg_bonus") == [pytest.approx(noelle.pins.constellations[2][1])]


def test_sweeping_time_reaches_noelle_only():
    kit = sheets.resolve(_sheet("noelle"), _noelle(), giver_is_subject=False)
    assert kit.bonus.effects == ()


# ── Mavuika: base ATK, the A4 constant to the active character ───────────────────────────


def _mavuika(constellation: int = 0) -> sheets.Giver:
    return _giver(_sheet("mavuika"), constellation=constellation,
                  talent_levels={"elemental_burst": 10},
                  talent_rows={("elemental_burst", 10): sheets.TalentRow(
                      MAVUIKA_BURST_LABELS, MAVUIKA_BURST_10)}, atk=2500.0)


def test_mavuika_on_herself_at_c2():
    mavuika = _sheet("mavuika")
    kit = sheets.resolve(mavuika, _mavuika(constellation=2), giver_is_subject=True)
    assert _effects(kit, "base_atk") == [mavuika.pins.constellations[2][0]]
    assert sorted(_effects(kit, "flat_damage_from_atk")) == pytest.approx(
        sorted([0.0288, mavuika.pins.constellations[2][4]]))
    assert sorted(_effects(kit, "atk_pct")) == pytest.approx(
        sorted([mavuika.pins.passives[1][0], mavuika.pins.constellations[1][2]]))
    assert _condition(kit, "fighting_spirit").default == 200  # type: ignore[attr-defined]


def test_mavuikas_a4_reaches_a_teammate_off_by_default_and_c4_needs_a4():
    mavuika = _sheet("mavuika")
    kit = sheets.resolve(mavuika, _mavuika(constellation=4), giver_is_subject=False)
    assert sorted(_effects(kit, "dmg_bonus")) == pytest.approx(
        sorted([0.002, mavuika.pins.constellations[4][0]]))
    assert _condition(kit, "a4_after_burst").default == 0  # type: ignore[attr-defined]
    assert _condition(kit, "fighting_spirit").default == 0  # type: ignore[attr-defined]
    low = sheets.resolve(mavuika, _giver(mavuika, constellation=4, ascension=3),
                         giver_is_subject=False)
    assert _effects(low, "dmg_bonus") == []


# ── Kuki Shinobu and Kamisato Ayaka ──────────────────────────────────────────────────────


def test_kukis_a4_on_herself_is_skill_flat_damage_from_her_own_em():
    kuki = _sheet("kuki_shinobu")
    kit = sheets.resolve(kuki, _giver(kuki, elemental_mastery=800.0), giver_is_subject=True)
    [a4] = kit.bonus.effects
    assert (a4.stat, a4.value, a4.moves) == ("flat_damage_from_em", kuki.pins.passives[4][1],
                                             ("skill",))


def test_kukis_c6_em_is_situational():
    kuki = _sheet("kuki_shinobu")
    kit = sheets.resolve(kuki, _giver(kuki, constellation=6), giver_is_subject=True)
    assert _effects(kit, "elemental_mastery") == [kuki.pins.constellations[6][2]]
    assert _condition(kit, "c6_low_hp").default == 0  # type: ignore[attr-defined]


def test_ayakas_c6_appears_at_c6_only():
    ayaka = _sheet("kamisato_ayaka")
    c0 = sheets.resolve(ayaka, _giver(ayaka), giver_is_subject=True)
    c6 = sheets.resolve(ayaka, _giver(ayaka, constellation=6), giver_is_subject=True)
    assert len(c6.bonus.effects) == len(c0.bonus.effects) + 1
    assert {c.key for c in c0.bonus.conditions} == {"after_skill", "after_sprint_hit"}
    assert any(e.moves == ("charged",) and e.value == ayaka.pins.constellations[6][1]
               for e in c6.bonus.effects)
