"""Math-fallback P2, task 11 (fourth batch) — Nahida, the next buffers, and the format extensions
they needed (`docs/DESIGN_team_math_fallback.md` §2.6).

Each sheet's GO agreement on its main effects is `test_go_formula_fixtures.py`'s job (its
fixtures live in `go_fixtures_batch4.py`). This file checks what those do not: each extension
resolves, and refuses, as the DESIGN says — a value from the party's highest stat, a talent row
chosen by a team count, a row-scoped self buff, a stack table, enemy DEF reduction and DEF
ignore, flat DEF, a team-count gate, a clamped team table and a capped giver stat.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins` rather than retyped, so a re-pin moves these tests with the sheets.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.formula.builder import const
from app.formula.genshin import sheets, tags
from app.pando.calculator import NodeRegistry
from tests.unit.go_fixtures_batch4 import batch4_fixtures

NAHIDA_BURST_LABELS = ["Pyro: DMG Bonus|1 Character {param1:F1P}",
                       "Pyro: DMG Bonus|2 Characters {param2:F1P}"]
NAHIDA_BURST_10 = [0.26784, 0.40176]


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


def _nahida(constellation: int = 0) -> sheets.Giver:
    return _giver(_sheet("nahida"), constellation=constellation,
                  talent_levels={"elemental_burst": 10},
                  talent_rows={("elemental_burst", 10): sheets.TalentRow(
                      NAHIDA_BURST_LABELS, NAHIDA_BURST_10)})


def _effects(kit: sheets.ResolvedKit, stat: str) -> list[Any]:
    return [e for e in kit.bonus.effects if e.stat == stat]


# ── a value from the party's highest stat (Nahida's A1) ───────────────────────────────────


@pytest.mark.parametrize(("highest", "expected"), [(600.0, 150.0), (1200.0, 250.0)])
def test_a1_is_a_quarter_of_the_teams_highest_em_capped(highest: float, expected: float):
    nahida = _sheet("nahida")
    assert nahida.pins.passives[1][:2] == (0.25, 250.0)
    kit = sheets.resolve(nahida, _nahida(), giver_is_subject=False,
                         receiver_element="pyro", team_elements=["pyro", "dendro"],
                         team_max={"elemental_mastery": highest})
    [a1] = _effects(kit, "elemental_mastery")
    assert a1.value == pytest.approx(expected)
    read = sheets.stats_read(nahida, _nahida(), {"elemental_mastery": highest})
    assert read["team_max_elemental_mastery"] == highest
    # Her own EM is read too, since DECISIONS §40: her A4 converts it.
    assert set(read) == {"team_max_elemental_mastery", "elemental_mastery"}


def test_a1_without_the_teams_highest_is_withheld_and_on_nahida_herself_too():
    nahida = _sheet("nahida")
    blind = sheets.resolve(nahida, _nahida(), giver_is_subject=False,
                           receiver_element="pyro", team_elements=["pyro", "dendro"])
    assert _effects(blind, "elemental_mastery") == []
    assert any("team's highest elemental_mastery, which was not given" in u.reason
               for u in blind.bonus.unmodelled)
    own = sheets.resolve(nahida, _nahida(), giver_is_subject=True,
                         receiver_element="dendro", team_elements=["pyro", "dendro"],
                         team_max={"elemental_mastery": 900.0})
    assert _effects(own, "elemental_mastery") == []
    assert any(u.reason.startswith("withheld: it reads the team's highest")
               for u in own.bonus.unmodelled)


def test_times_team_max_names_a_stat_and_not_the_givers_too():
    with pytest.raises(ValidationError, match="times_team_max must be one of"):
        sheets.ValueRef(passive=1, param=0, times_team_max="crit_rate")
    with pytest.raises(ValidationError, match="not both"):
        sheets.ValueRef(passive=1, param=0, times_team_max="atk", times_stat="atk")


# ── a talent row chosen by a team count, with a constellation counting one more ───────────


@pytest.mark.parametrize(("team", "constellation", "expected"), [
    (["dendro", "hydro"], 0, None),
    (["dendro", "pyro"], 0, NAHIDA_BURST_10[0]),
    (["dendro", "pyro", "pyro"], 0, NAHIDA_BURST_10[1]),
    # Three Pyro members read the last row, as GO's `cmpEq(level, 1, a, b)` gives `b`.
    (["dendro", "pyro", "pyro", "pyro"], 0, NAHIDA_BURST_10[1]),
    # C1 counts one more: no Pyro reads the first row, one Pyro the second.
    (["dendro", "hydro"], 1, NAHIDA_BURST_10[0]),
    (["dendro", "pyro"], 1, NAHIDA_BURST_10[1]),
])
def test_the_burst_bonus_reads_its_row_by_the_pyro_count(
    team: list[str], constellation: int, expected: float | None,
):
    kit = sheets.resolve(_sheet("nahida"), _nahida(constellation), giver_is_subject=True,
                         receiver_element="dendro", team_elements=team)
    bonus = _effects(kit, "dmg_bonus")
    assert [e.value for e in bonus] == ([] if expected is None else [pytest.approx(expected)])
    for effect in bonus:
        assert [(r.talent, r.label) for r in effect.rows or ()] == [
            ("elemental_skill", "Tri-Karma Purification DMG")]


def test_a_team_chosen_row_missing_from_the_seeded_row_is_withheld():
    giver = _giver(_sheet("nahida"), talent_levels={"elemental_burst": 10},
                   talent_rows={("elemental_burst", 10): sheets.TalentRow(
                       ["Pyro: DMG Bonus|1 Character {param1:F2P}", NAHIDA_BURST_LABELS[1]],
                       NAHIDA_BURST_10)})
    kit = sheets.resolve(_sheet("nahida"), giver, giver_is_subject=True,
                         receiver_element="dendro", team_elements=["dendro", "pyro"])
    assert _effects(kit, "dmg_bonus") == []
    assert any("is not in the seeded row any more" in u.reason for u in kit.bonus.unmodelled)


def test_the_bonus_reaches_only_nahida_and_a_row_scope_only_a_self_effect():
    kit = sheets.resolve(_sheet("nahida"), _nahida(), giver_is_subject=False,
                         receiver_element="pyro", team_elements=["dendro", "pyro"],
                         team_max={"elemental_mastery": 900.0})
    assert _effects(kit, "dmg_bonus") == []
    nahida = _sheet("nahida")
    [burst] = [e for e in nahida.effects if e.key == "burst_tri_karma"]
    with pytest.raises(ValidationError, match="only a self effect names"):
        sheets.SheetEffect.model_validate({**burst.model_dump(), "receivers": "active"})


# ── a stack table (Nahida's C4) ───────────────────────────────────────────────────────────


def test_c4_reads_its_em_by_the_opponent_count_from_the_list():
    nahida = _sheet("nahida")
    kit = sheets.resolve(nahida, _nahida(4), giver_is_subject=True,
                         receiver_element="dendro", team_elements=["dendro"])
    [c4] = _effects(kit, "elemental_mastery")
    assert c4.per == "c4_count"
    assert c4.by_stack == nahida.pins.constellations[4][:4]
    count = next(c for c in kit.bonus.conditions if c.key == "c4_count")
    # The estimate scores one target (§40 (ii)): one opponent, said.
    assert (count.max, count.default, count.default_reason) == (4, 1, "usual")
    assert "one target" in (count.default_note or "")


def test_a_stack_table_needs_a_fixed_maximum_and_a_list():
    nahida = _sheet("nahida")
    [c4] = [e for e in nahida.effects if e.key == "c4_em"]
    with pytest.raises(ValidationError, match="needs the condition it reads"):
        sheets.SheetEffect.model_validate({**c4.model_dump(), "per": None})
    with pytest.raises(ValidationError, match="reads a constellation or passive list"):
        sheets.SheetEffect.model_validate(
            {**c4.model_dump(), "value": {"constant": 1.0, "cite": "x"}})


# ── enemy DEF reduction and DEF ignore ────────────────────────────────────────────────────


def test_c2_reduces_the_enemys_def_and_reaches_every_receiver():
    nahida = _sheet("nahida")
    for subject in (True, False):
        kit = sheets.resolve(nahida, _nahida(2), giver_is_subject=subject,
                             receiver_element="pyro", team_elements=["dendro", "pyro"],
                             team_max={"elemental_mastery": 900.0})
        [c2] = _effects(kit, "def_reduction")
        assert c2.value == pytest.approx(nahida.pins.constellations[2][1])
        assert [w.condition for w in c2.when] == ["c2_quicken"]


@pytest.mark.parametrize(("stat", "receivers", "message"), [
    ("def_reduction", "team", "is an enemy debuff"),
    ("crit_rate", "enemy", "an enemy debuff writes one of"),
    ("def_ignore", "team", "belongs to the giver's own hits"),
])
def test_the_def_terms_reach_only_where_they_belong(stat: str, receivers: str, message: str):
    nahida = _sheet("nahida")
    [c2] = [e for e in nahida.effects if e.key == "c2_def"]
    with pytest.raises(ValidationError, match=message):
        sheets.SheetEffect.model_validate(
            {**c2.model_dump(), "stat": stat, "receivers": receivers})


# ── a team-count gate, a clamped team table, flat DEF (Gorou) ─────────────────────────────

GOROU_SKILL_13 = sheets.TalentRow(
    ["Skill DMG|{param1:F1P}", "DEF Increase|{param2:I}", "Geo DMG Bonus|{param3:P}"],
    [2.278, 438.09, 0.15])


def _gorou_kit(team: list[str]) -> sheets.ResolvedKit:
    gorou = _sheet("gorou")
    giver = _giver(gorou, constellation=6, talent_levels={"elemental_skill": 10},
                   talent_rows={("elemental_skill", 13): GOROU_SKILL_13})
    return sheets.resolve(gorou, giver, giver_is_subject=False, receiver_element="pyro",
                          team_elements=team)


@pytest.mark.parametrize(("team", "geo_dmg", "crit_dmg_entry"), [
    (["geo", "pyro"], [], 0),
    (["geo", "geo", "pyro"], [], 1),
    (["geo", "geo", "geo", "pyro"], [0.15], 2),
    # A fourth Geo member reads the table's last entry again, as GO writes it.
    (["geo", "geo", "geo", "geo"], [0.15], 2),
])
def test_gorous_banner_and_c6_follow_the_geo_count(
    team: list[str], geo_dmg: list[float], crit_dmg_entry: int,
):
    kit = _gorou_kit(team)
    assert [e.value for e in _effects(kit, "flat_def")] == [pytest.approx(438.09)]
    assert [e.value for e in _effects(kit, "dmg_bonus")] == [pytest.approx(v) for v in geo_dmg]
    [c6] = _effects(kit, "crit_dmg")
    assert c6.value == pytest.approx(_sheet("gorou").pins.constellations[6][crit_dmg_entry])


def test_a_team_table_past_its_size_is_withheld_unless_it_clamps():
    ref = sheets.TeamIndex(count="elements", elements=("geo",), size=3)
    assert ref.clamp is False
    with pytest.raises(ValidationError, match="names a bound"):
        sheets.TeamCount(elements=("geo",))


# ── the Geo sample's OR, and a gate on at most N members (Xilonen) ────────────────────────


@pytest.mark.parametrize(("state", "constellation", "expected"), [
    ({"source_active": 1, "ns_blessing": 0}, 0, ["geo_res_source"]),
    ({"source_active": 0, "ns_blessing": 1}, 0, ["geo_res_blessing"]),
    ({"source_active": 1, "ns_blessing": 1}, 0, ["geo_res_source"]),
    ({"source_active": 0, "ns_blessing": 0}, 0, []),
    ({"source_active": 0, "ns_blessing": 0}, 2, ["geo_res_c2"]),
    ({"source_active": 1, "ns_blessing": 1}, 2, ["geo_res_source"]),
])
def test_the_geo_sample_is_one_shred_whichever_way_it_is_on(
    state: dict[str, int], constellation: int, expected: list[str],
):
    """GO `cmpGE(sum(sourceActive, nsBlessing, C2), 1, …)`: an OR, never a sum. The sheet writes
    it as three effects whose `when`s are disjoint; under any state at most one holds."""
    xilonen = _sheet("xilonen")
    geo = [e for e in xilonen.effects if e.key.startswith("geo_res_")]
    on = [e.key for e in geo
          if constellation >= int(e.source[1:] if e.source.startswith("c") else 0)
          and all(state[w.condition] in w.values for w in e.when)]
    assert on == expected


def test_the_geo_sample_needs_fewer_than_three_converted_samplers():
    xilonen = _sheet("xilonen")
    def giver() -> sheets.Giver:  # one resolution per registry (LOG, task 11)
        return _giver(xilonen, talent_levels={"elemental_skill": 10},
                      talent_rows={("elemental_skill", 10): sheets.TalentRow(
                          ["Rush DMG|{param1:F1P} DEF", "Elemental RES Decrease|{param2:F1P}"],
                          [3.2256, 0.36])})
    open_team = sheets.resolve(xilonen, giver(), giver_is_subject=True, receiver_element="geo",
                               team_elements=["geo", "pyro", "hydro", "anemo"])
    full = sheets.resolve(xilonen, giver(), giver_is_subject=True, receiver_element="geo",
                          team_elements=["geo", "pyro", "hydro", "cryo"])
    geo = lambda kit: [e for e in _effects(kit, "enemy_res") if e.elements == ("geo",)]  # noqa: E731
    # Below C2: the Source-Sample and the Blessing variants, disjoint by their `when`s.
    assert len(geo(open_team)) == 2
    assert geo(full) == []
    # The samplers present each get theirs, the absent one none.
    assert sorted(e.elements[0] for e in _effects(full, "enemy_res")) == [
        "cryo", "hydro", "pyro"]


# ── a capped giver stat, and a row scope that cannot double count (Xianyun) ──────────────


@pytest.mark.parametrize(("atk", "counted"), [(3000.0, 3000.0), (6000.0, 4500.0)])
def test_xianyuns_a4_caps_her_atk_before_multiplying(atk: float, counted: float):
    xianyun = _sheet("xianyun")
    kit = sheets.resolve(xianyun, _giver(xianyun, base_atk=atk), giver_is_subject=False,
                         receiver_element="pyro", team_elements=["pyro", "anemo"])
    [a4] = _effects(kit, "flat_damage")
    assert xianyun.pins.passives[4][1] == 4500.0
    assert a4.value == pytest.approx(xianyun.pins.passives[4][0] * counted)


def test_xianyuns_a4_on_herself_is_a_capped_conversion_and_her_wave_buffs_name_the_row():
    """Her A4 on her own plunges reads her own ATK, capped at 4,500 before it multiplies: since
    the owner's 2026-11-14 ruling (DECISIONS §40) it is priced per candidate, the stat cap
    carried as a cap on the term (ratio × 4,500), not withheld."""
    xianyun = _sheet("xianyun")
    kit = sheets.resolve(xianyun, _giver(xianyun, constellation=6, base_atk=900.0),
                         giver_is_subject=True, receiver_element="anemo",
                         team_elements=["anemo", "pyro"])
    assert _effects(kit, "flat_damage") == []
    converted = _effects(kit, "flat_damage_from_atk")
    assert converted
    for a4 in converted:
        assert a4.moves == ("plunge",)
        assert a4.cap == pytest.approx(a4.value * xianyun.pins.passives[4][1])
        assert a4.threshold is None
    assert not any("through a cap" in u.reason for u in kit.bonus.unmodelled)
    [team_a1, own_a1] = _effects(kit, "crit_rate")
    # Team plunges by move; her own wave by row, only while its move is Skill: never both.
    assert (team_a1.moves, team_a1.rows) == (("plunge",), None)
    assert own_a1.moves == ("skill",)
    assert [(r.talent, r.label) for r in own_a1.rows or ()] == [
        ("elemental_skill", "Driftcloud Wave DMG")]
    assert own_a1.by_stack == xianyun.pins.passives[1][:4]


def test_a_stat_cap_belongs_to_a_value_that_reads_a_stat():
    with pytest.raises(ValidationError, match="stat cap belongs"):
        sheets.ValueRef(passive=4, param=0, stat_cap={"passive": 4, "param": 1})


# ── Mona: a CRIT Rate published negated, and an ER conversion the recipe cannot carry ────


def test_monas_c4_is_her_lists_magnitude_and_her_a4_on_herself_is_withheld():
    mona = _sheet("mona")
    assert mona.pins.constellations[4][0] < 0
    giver = _giver(mona, constellation=4, energy_recharge=1.8)
    kit = sheets.resolve(mona, giver, giver_is_subject=True, receiver_element="hydro",
                         team_elements=["hydro", "pyro"])
    assert [e.value for e in _effects(kit, "crit_rate")] == [
        pytest.approx(-mona.pins.constellations[4][0])]
    assert not [e for e in _effects(kit, "dmg_bonus") if e.elements == ("hydro",)]
    assert any("cannot carry dmg_bonus from energy_recharge" in u.reason
               for u in kit.bonus.unmodelled)


# ── Raiden: a row's second parameter, and one talent row times another ───────────────────

RAIDEN_ROWS = {
    ("elemental_skill", 10): sheets.TalentRow(
        ["Elemental Burst DMG Bonus|{param4:F2P} Per Energy"], [2.1096, 0.756, 25.0, 0.003]),
    ("elemental_burst", 10): sheets.TalentRow(
        ["Resolve Bonus|{param2:F2P} Initial/{param3:F2P} ATK DMG Per Stack",
         "Energy Cost|{param20:I}"],
        [7.2144, 0.069984, 0.013071, *([0.0] * 16), 90.0]),
}


def _raiden(constellation: int = 0) -> sheets.Giver:
    return _giver(_sheet("raiden_shogun"), constellation=constellation,
                  talent_levels={"elemental_skill": 10, "elemental_burst": 10},
                  talent_rows=RAIDEN_ROWS)


def test_raidens_eye_on_herself_is_the_ratio_times_her_own_bursts_cost():
    kit = sheets.resolve(_sheet("raiden_shogun"), _raiden(), giver_is_subject=True,
                         receiver_element="electro", team_elements=["electro"])
    [eye] = [e for e in _effects(kit, "dmg_bonus") if e.per is None]
    assert eye.value == pytest.approx(0.003 * 90.0)
    assert eye.moves == ("burst",)


def test_resolve_reads_each_part_of_its_row_per_stack_on_her_own_rows():
    kit = sheets.resolve(_sheet("raiden_shogun"), _raiden(), giver_is_subject=True,
                         receiver_element="electro", team_elements=["electro"])
    initial, infused = _effects(kit, "flat_damage_from_atk")
    assert (initial.value, infused.value) == (pytest.approx(0.069984), pytest.approx(0.013071))
    assert initial.per == infused.per == "resolve"
    assert [r.label for r in initial.rows or ()] == ["Musou no Hitotachi Base DMG"]
    assert "Musou no Hitotachi Base DMG" not in [r.label for r in infused.rows or ()]
    assert any(u.what.startswith("A4: Enlightened One: Electro DMG")
               for u in kit.bonus.unmodelled)


def test_the_eye_for_a_teammate_is_per_energy_they_state_and_c2_is_hers_alone():
    kit = sheets.resolve(_sheet("raiden_shogun"), _raiden(2), giver_is_subject=False,
                         receiver_element="pyro", team_elements=["electro", "pyro"])
    [eye] = _effects(kit, "dmg_bonus")
    assert (eye.value, eye.per) == (pytest.approx(0.003), "eye_energy")
    assert _effects(kit, "def_ignore") == []
    own = sheets.resolve(_sheet("raiden_shogun"), _raiden(2), giver_is_subject=True,
                         receiver_element="electro", team_elements=["electro"])
    assert [e.value for e in _effects(own, "def_ignore")] == [pytest.approx(0.6)]


def test_a_part_past_the_rows_parameters_is_withheld():
    rows = dict(RAIDEN_ROWS)
    rows[("elemental_burst", 10)] = sheets.TalentRow(
        ["Resolve Bonus|{param2:F2P} Initial/{param3:F2P} ATK DMG Per Stack",
         "Energy Cost|{param20:I}"], [7.2144, 0.069984])
    giver = _giver(_sheet("raiden_shogun"), talent_levels={"elemental_skill": 10,
                                                          "elemental_burst": 10},
                   talent_rows=rows)
    kit = sheets.resolve(_sheet("raiden_shogun"), giver, giver_is_subject=True,
                         receiver_element="electro", team_elements=["electro"])
    assert len(_effects(kit, "flat_damage_from_atk")) == 1
    with pytest.raises(ValidationError, match="talent and a row, not a param"):
        sheets.ParamRef(talent="elemental_burst", row="Energy Cost", param=0)


# ── raised stack maxima, revisited (Nefer's C2, Valeriy's C4) ────────────────────────────


@pytest.mark.parametrize(("constellation", "stacks", "em"), [
    (0, 3, "a1"), (1, 3, "a1"), (2, 3, None), (2, 4, None), (2, 5, "c2"),
])
def test_nefers_c2_raises_the_veils_to_five_and_replaces_the_a1_em(
    constellation: int, stacks: int, em: str | None,
):
    """GO `cmpGE(constellation, 2, cmpGE(stacks, 5, c2), cmpGE(stacks, 3, a1))`: from C2 the EM
    is C2's at five Veils and nothing below — A1's at three does not survive alongside it."""
    nefer = _sheet("nefer")
    kit = sheets.resolve(nefer, _giver(nefer, constellation=constellation),
                         giver_is_subject=True, receiver_element="dendro",
                         team_elements=["dendro", "hydro"])
    veils = next(c for c in kit.bonus.conditions if c.key == "veil_stacks")
    assert veils.max == (5 if constellation >= 2 else 3)
    assert veils.default == veils.max
    applied = [e for e in _effects(kit, "elemental_mastery")
               if all(stacks in w.values for w in e.when if w.condition == "veil_stacks")]
    expected = {"a1": [nefer.pins.passives[1][2]], "c2": [nefer.pins.constellations[2][2]],
                None: []}[em]
    assert [e.value for e in applied] == expected


def test_valeriys_c4_raises_the_momentum_limit_by_a_cited_thirty():
    valeriy = _sheet("valeriy")
    for constellation, top in ((3, 100), (4, 130)):
        kit = sheets.resolve(valeriy, _giver(valeriy, constellation=constellation, atk=2000.0),
                             giver_is_subject=True, receiver_element="electro",
                             team_elements=["electro"])
        momentum = next(c for c in kit.bonus.conditions if c.key == "momentum")
        assert (momentum.max, momentum.default) == (top, top)
    with pytest.raises(ValidationError, match="by a parameter or a constant"):
        sheets.SheetCondition(
            key="x", label="x", kind="stacks", default_by="self", max=3, go="x",
            max_raise={"constellation": 2, "param": 0},
            max_raise_cited={"constellation": 2, "add": {"constant": 2.0, "cite": "x"}})


# ── the fixtures: only the EM coefficient may divide them from GO ─────────────────────────


def test_the_batch_fixtures_differ_from_go_only_by_the_em_coefficient():
    for f in batch4_fixtures():
        gap = abs(f["expected"] - f["go_value"]) / f["go_value"]
        if f["divergence"].startswith("none"):
            assert gap == 0, f["name"]
        else:
            assert any(r["amplifying"] for r in f["rows"]), f["name"]
            assert 0 < gap < 5e-4, f["name"]
