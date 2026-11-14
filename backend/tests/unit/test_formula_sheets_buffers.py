"""Math-fallback P2, task 11 (second batch) — the buffers' sheets, and the format extensions
they needed (`docs/DESIGN_team_math_fallback.md` §2.6).

Each sheet's GO agreement on its main effect is `test_go_formula_fixtures.py`'s job. This file
checks what one fixture per sheet does not: each extension resolves, and refuses, as the
DESIGN says — a raised condition maximum, a value read from a table by a team count, a
team-composition gate, a cap with a per-N-points unit, an extra ascension gate, and self flat
damage from HP or EM per candidate.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins` rather than retyped, so a re-pin moves these tests with the sheets.
"""

from __future__ import annotations

import pytest

from app.formula.builder import const
from app.formula.genshin import sheets, tags
from app.pando.calculator import NodeRegistry

FURINA_BURST_LABELS = [
    "Skill DMG|{param1:F1P} Max HP", "Maximum Fanfare|{param4:I}",
    "Fanfare to DMG Increase Conversion Ratio|{param5:F2P}"]
FURINA_BURST_10 = [0.205315, 18.0, 0.01, 300.0, 0.0025]


def _sheet(slug: str) -> sheets.Sheet:
    [sheet] = [s for s in sheets.all_sheets().values() if s.slug == slug]
    return sheet


def _giver(sheet: sheets.Sheet, *, constellation: int = 0, ascension: int = 6,
           talent_levels: dict[str, int] | None = None,
           talent_rows: dict[tuple[str, int], sheets.TalentRow] | None = None,
           cons: dict[int, list[float]] | None = None, **stats: float) -> sheets.Giver:
    registry = NodeRegistry()
    for quantity, value in stats.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return sheets.Giver(
        name=sheet.character, nanoka_id=sheet.nanoka_id, constellation=constellation,
        ascension_phase=ascension, talent_levels=talent_levels or {},
        talent_rows=talent_rows or {},
        constellation_params=cons or {n: list(v) for n, v in sheet.pins.constellations.items()},
        passive_params={n: list(v) for n, v in sheet.pins.passives.items()},
        registry=registry,
    )


def _furina(**kw: object) -> sheets.Giver:
    furina = _sheet("furina")
    return _giver(furina, talent_levels={"elemental_burst": 10},
                  talent_rows={("elemental_burst", 10): sheets.TalentRow(
                      FURINA_BURST_LABELS, FURINA_BURST_10)}, **kw)  # type: ignore[arg-type]


def _condition(kit: sheets.ResolvedKit, key: str) -> object:
    return next(c for c in kit.bonus.conditions if c.key == key)


def _values(kit: sheets.ResolvedKit, stat: str) -> list[float]:
    return [e.value for e in kit.bonus.effects if e.stat == stat]


# ── a raised condition maximum (Furina's C1) ─────────────────────────────────────────────


def test_c1_raises_the_fanfare_limit_and_the_subjects_default_follows():
    furina = _sheet("furina")
    raise_by = furina.pins.constellations[1][1]
    c0 = sheets.resolve(furina, _furina(), giver_is_subject=True)
    c1 = sheets.resolve(furina, _furina(constellation=1), giver_is_subject=True)
    fanfare0, fanfare1 = _condition(c0, "fanfare"), _condition(c1, "fanfare")
    assert (fanfare0.max, fanfare0.default) == (300, 300)  # type: ignore[attr-defined]
    assert fanfare1.max == 300 + raise_by  # type: ignore[attr-defined]
    assert fanfare1.default == 300 + raise_by  # type: ignore[attr-defined]


def test_fanfare_is_at_the_cap_for_a_teammate_and_its_value_is_the_burst_rows_ratio():
    """A teammate's buff at its usual value (DECISIONS §40 (ii)): no typical stack is documented,
    so the cap (raised by C1), said; the value is per point, multiplied in the browser."""
    furina = _sheet("furina")
    kit = sheets.resolve(furina, _furina(constellation=1), giver_is_subject=False)
    fanfare = _condition(kit, "fanfare")
    assert (fanfare.default, fanfare.default_reason) == (400, "usual")  # type: ignore[attr-defined]
    assert "at the cap" in fanfare.default_note  # type: ignore[attr-defined]
    [burst] = [e for e in kit.bonus.effects if e.per == "fanfare"]
    assert (burst.stat, burst.value, burst.elements) == ("dmg_bonus", pytest.approx(0.0025), None)


def test_a_stale_raise_keeps_the_maximum_and_says_so():
    furina = _sheet("furina")
    cons = {n: list(v) for n, v in furina.pins.constellations.items()}
    cons[1] = [150.0, 999.0] + [0.0] * 8
    kit = sheets.resolve(furina, _furina(constellation=1, cons=cons), giver_is_subject=True)
    assert _condition(kit, "fanfare").max == 300  # type: ignore[attr-defined]
    assert any("raised maximum" in u.what and u.reason.startswith("withheld")
               for u in kit.bonus.unmodelled)


# ── a value read from a table by a team count ────────────────────────────────────────────


@pytest.mark.parametrize(("team", "entry"), [
    (["cryo"], 0), (["cryo", "hydro", "pyro"], 1), (["cryo", "hydro", "cryo", "geo"], 2),
    (["cryo", "hydro", "hydro", "cryo"], 3),
])
def test_escoffiers_a4_reads_its_table_by_the_hydro_and_cryo_count(team: list[str], entry: int):
    escoffier = _sheet("escoffier")
    kit = sheets.resolve(escoffier, _giver(escoffier), giver_is_subject=False,
                         receiver_element="pyro", team_elements=team)
    assert _values(kit, "enemy_res") == [pytest.approx(-escoffier.pins.passives[4][entry])]


def test_a_count_of_zero_is_no_buff_and_no_team_is_withheld():
    escoffier = _sheet("escoffier")
    none = sheets.resolve(escoffier, _giver(escoffier), giver_is_subject=False,
                          receiver_element="pyro", team_elements=["pyro", "geo"])
    assert _values(none, "enemy_res") == []
    blind = sheets.resolve(escoffier, _giver(escoffier), giver_is_subject=False)
    assert _values(blind, "enemy_res") == []
    assert any("team's elements" in u.reason for u in blind.bonus.unmodelled)


def test_a_count_past_the_tables_end_is_withheld_not_read():
    """A table of four entries is followed by the A4 list's duration; a fifth member (no
    such team) would read it as a resistance."""
    escoffier = _sheet("escoffier")
    kit = sheets.resolve(escoffier, _giver(escoffier), giver_is_subject=False,
                         receiver_element="pyro", team_elements=["cryo"] * 5)
    assert _values(kit, "enemy_res") == []
    assert any("4 entries" in u.reason for u in kit.bonus.unmodelled)


@pytest.mark.parametrize(("team", "entry"), [
    (["hydro"], 0), (["hydro", "hydro", "pyro"], 1), (["hydro", "pyro", "cryo", "cryo"], 2),
    (["hydro", "pyro", "cryo", "electro"], 3),
])
def test_yelans_a1_reads_its_table_by_distinct_elements(team: list[str], entry: int):
    yelan = _sheet("yelan")
    kit = sheets.resolve(yelan, _giver(yelan), giver_is_subject=True,
                         receiver_element="hydro", team_elements=team)
    assert _values(kit, "hp_pct")[0] == pytest.approx(yelan.pins.passives[1][entry])


# ── a team-composition gate ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("team", "holds"), [
    (["pyro", "electro"], True), (["pyro", "pyro", "electro", "electro"], True),
    (["pyro", "pyro"], False), (["pyro", "electro", "hydro"], False),
])
def test_chevreuses_a1_needs_a_pyro_and_electro_only_party(team: list[str], holds: bool):
    chevreuse = _sheet("chevreuse")
    kit = sheets.resolve(chevreuse, _giver(chevreuse), giver_is_subject=False,
                         receiver_element="pyro", team_elements=team)
    assert bool(_values(kit, "enemy_res")) is holds


@pytest.mark.parametrize(("team", "holds"), [
    (["cryo", "hydro", "hydro", "cryo"], True), (["cryo", "hydro", "hydro"], False),
    (["cryo", "hydro", "hydro", "pyro"], False),
])
def test_escoffiers_c1_needs_four_hydro_or_cryo_members(team: list[str], holds: bool):
    escoffier = _sheet("escoffier")
    kit = sheets.resolve(escoffier, _giver(escoffier, constellation=1), giver_is_subject=False,
                         receiver_element="cryo", team_elements=team)
    assert bool(_values(kit, "crit_dmg")) is holds


def test_a_constellations_extra_ascension_gate_holds():
    """Escoffier's C1 reads her A4's count (GO `cmpGE(ascension, 4, …)` inside C1); Citlali's
    C2 copies her A1 shred, which needs ascension 1."""
    escoffier = _sheet("escoffier")
    team = ["cryo", "hydro", "hydro", "cryo"]
    low = sheets.resolve(escoffier, _giver(escoffier, constellation=1, ascension=3),
                         giver_is_subject=False, receiver_element="cryo", team_elements=team)
    assert _values(low, "crit_dmg") == []
    citlali = _sheet("citlali")
    kit = sheets.resolve(citlali, _giver(citlali, constellation=2, ascension=0),
                         giver_is_subject=False)
    assert _values(kit, "enemy_res") == []


# ── a cap, and a per-N-points unit ───────────────────────────────────────────────────────


def test_chevreuses_a4_is_one_percent_per_thousand_hp_up_to_its_cap():
    chevreuse = _sheet("chevreuse")
    per, cap = chevreuse.pins.passives[4][0], chevreuse.pins.passives[4][2]
    team = ["pyro", "electro"]
    low = sheets.resolve(chevreuse, _giver(chevreuse, base_hp=30000.0), giver_is_subject=False,
                         receiver_element="electro", team_elements=team)
    assert _values(low, "atk_pct") == [pytest.approx(per * 30000.0 / 1000)]
    high = sheets.resolve(chevreuse, _giver(chevreuse, base_hp=60000.0), giver_is_subject=False,
                          receiver_element="electro", team_elements=team)
    assert _values(high, "atk_pct") == [pytest.approx(cap)]
    other = sheets.resolve(chevreuse, _giver(chevreuse, base_hp=30000.0),
                           giver_is_subject=False, receiver_element="hydro",
                           team_elements=["pyro", "electro", "hydro"])
    assert _values(other, "atk_pct") == []


def test_a_capped_self_buff_from_a_moving_stat_is_withheld_by_name():
    """On Chevreuse herself the A4 reads her own HP, which moves with every candidate, through
    a cap: nothing carries that per candidate, so it is said rather than frozen."""
    chevreuse = _sheet("chevreuse")
    kit = sheets.resolve(chevreuse, _giver(chevreuse, base_hp=30000.0), giver_is_subject=True,
                         receiver_element="pyro", team_elements=["pyro", "electro"])
    assert _values(kit, "atk_pct") == []
    assert any("A4" in u.what and u.reason.startswith("withheld") for u in kit.bonus.unmodelled)


# ── self flat damage from HP or EM, per candidate ────────────────────────────────────────


def test_zhonglis_a4_on_himself_becomes_flat_damage_from_hp_per_move():
    zhongli = _sheet("zhongli")
    kit = sheets.resolve(zhongli, _giver(zhongli, base_hp=15000.0), giver_is_subject=True)
    by_move = {e.moves: (e.stat, e.value) for e in kit.bonus.effects if e.moves}
    a4 = zhongli.pins.passives[4]
    auto = by_move[("normal", "charged", "plunge")]
    assert auto == ("flat_damage_from_hp", pytest.approx(a4[0]))
    assert by_move[("skill",)] == ("flat_damage_from_hp", pytest.approx(a4[1]))
    assert by_move[("burst",)] == ("flat_damage_from_hp", pytest.approx(a4[2]))


def test_a_self_flat_damage_from_em_is_a_conversion_too():
    assert sheets.SELF_CONVERSIONS[("flat_damage", tags.Q_ELEMENTAL_MASTERY)] == (
        "flat_damage_from_em")


# ── scoping a teammate buff away from the giver's own hits ───────────────────────────────


def test_xianglings_c6_reaches_teammates_whole_and_her_own_pyronado_not_at_all():
    """GO's `antiC6` removes C6 from her own Pyronado and first two swings (cast before it)."""
    xiangling = _sheet("xiangling")
    team = sheets.resolve(xiangling, _giver(xiangling, constellation=6), giver_is_subject=False)
    own = sheets.resolve(xiangling, _giver(xiangling, constellation=6), giver_is_subject=True)
    [mate] = [e for e in team.bonus.effects if e.stat == "dmg_bonus"]
    [self_] = [e for e in own.bonus.effects if e.stat == "dmg_bonus"]
    assert mate.moves is None
    assert self_.moves is not None
    assert "burst" not in self_.moves


def test_every_buffer_sheet_is_verified_and_names_what_it_does_not_model():
    for slug in ("furina", "xingqiu", "xiangling", "citlali", "yelan", "escoffier",
                 "chevreuse", "jean", "zhongli", "faruzan", "sucrose"):
        sheet = _sheet(slug)
        assert sheet.verified_by, slug
        assert sheet.unmodelled, slug
