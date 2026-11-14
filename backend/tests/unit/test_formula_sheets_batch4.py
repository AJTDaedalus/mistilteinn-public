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
    assert sheets.stats_read(nahida, _nahida(), {"elemental_mastery": highest}) == {
        "team_max_elemental_mastery": highest}


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
    assert (count.max, count.default, count.default_reason) == (4, 0, "situational")


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
