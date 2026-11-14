"""Capped self-conversions in the formula estimate (owner ruling 2026-11-14, DECISIONS §40), and
the Alhaitham and Tighnari sheets that waited for them.

`docs/DESIGN_team_math_fallback.md` §2.6, the capped-conversions table. A kit value read from the
optimized character's own artifact-moved stat **through a cap or a threshold** used to be withheld
by name; it now resolves to a per-candidate conversion carrying its cap (in the term's units) and
threshold, and the recipe prices `min(k × max(stat − t, 0), cap)` for each build. GO agreement on
each is `test_go_formula_fixtures.py`'s job (`go_fixtures_capped.py`, a build below and one past
every cap); this file checks the sheets' resolution, the format additions and what is still
withheld.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51) read back through
`Sheet.pins`; talent rows are the seeded rows, verbatim.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.formula.builder import const
from app.formula.genshin import sheets, tags
from app.formula.genshin.formula_effects import Effect
from app.pando.calculator import NodeRegistry

#: Hu Tao's seeded skill row at 10 and 13 (C3 boosts it): `params[6]` is the 4.0 no label names.
HU_TAO_SKILL_LABELS = ["Activation Cost|{param1:P} Current HP", "ATK Increase|{param2:F2P} Max HP",
                       "Blood Blossom DMG|{param3:P}"]
HU_TAO_SKILL_10 = [0.3, 0.06256, 1.152, 8.0, 9.0, 16.0, 4.0]
HU_TAO_SKILL_13 = [0.3, 0.07153, 1.36, 8.0, 9.0, 16.0, 4.0]


def _sheet(slug: str) -> sheets.Sheet:
    [sheet] = [s for s in sheets.all_sheets().values() if s.slug == slug]
    return sheet


def _giver(sheet: sheets.Sheet, *, constellation: int = 0, ascension: int = 6,
           rows: dict[tuple[str, int], tuple[list[str], list[float]]] | None = None,
           levels: dict[str, int] | None = None, **stats: float) -> sheets.Giver:
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


def _effects(kit: sheets.ResolvedKit, stat: str) -> list[Effect]:
    return [e for e in kit.bonus.effects if e.stat == stat]


def _unmodelled(kit: sheets.ResolvedKit) -> str:
    return " | ".join(f"{u.what}: {u.reason}" for u in kit.bonus.unmodelled)


def _hu_tao(constellation: int = 0, *, labels: list[str] | None = None, **stats: float):
    hu = _sheet("hu_tao")
    level = 13 if constellation >= 3 else 10
    row = HU_TAO_SKILL_13 if level == 13 else HU_TAO_SKILL_10
    giver = _giver(hu, constellation=constellation, levels={"elemental_skill": 10},
                   rows={("elemental_skill", level): (labels or HU_TAO_SKILL_LABELS, row)},
                   **({"base_atk": 715.0} | stats))
    return hu, giver


# ── Hu Tao: ATK from her Max HP, capped at a multiple of her base ATK ───────────────────────


def test_hu_taos_paramita_atk_is_a_conversion_capped_at_four_times_her_base_atk():
    hu, giver = _hu_tao()
    kit = sheets.resolve(hu, giver, giver_is_subject=True)
    [atk] = _effects(kit, "flat_atk_from_hp")
    assert atk.value == HU_TAO_SKILL_10[1]
    # GO `prod(percent(maxAtkInc), own.base.atk)`: the unnamed param6 × her (static) base ATK.
    assert atk.cap == pytest.approx(HU_TAO_SKILL_10[6] * 715.0)
    assert atk.threshold is None
    assert [w.condition for w in atk.when] == ["paramita"]
    # Her own skill: on by default (§39), and a visible toggle.
    [paramita] = [c for c in kit.bonus.conditions if c.key == "paramita"]
    assert (paramita.default, paramita.default_reason) == (1, "self")


def test_hu_taos_conversion_reads_her_boosted_skill_row_at_c3():
    hu, giver = _hu_tao(3)
    [atk] = _effects(sheets.resolve(hu, giver, giver_is_subject=True), "flat_atk_from_hp")
    assert atk.value == HU_TAO_SKILL_13[1]


def test_hu_taos_conversion_does_not_reach_her_teammates():
    hu, giver = _hu_tao()
    kit = sheets.resolve(hu, giver, giver_is_subject=False)
    assert not _effects(kit, "flat_atk_from_hp")
    assert not _effects(kit, "flat_atk")


def test_an_unnamed_parameter_a_label_comes_to_name_is_withheld():
    """A re-seed whose labels start naming `param7` would mean the index means something new."""
    hu, giver = _hu_tao(labels=[*HU_TAO_SKILL_LABELS, "Max ATK Bonus|{param7:P} Base ATK"])
    kit = sheets.resolve(hu, giver, giver_is_subject=True)
    assert not _effects(kit, "flat_atk_from_hp")
    assert "named by a seeded label now" in _unmodelled(kit)


def test_a_cap_that_reads_a_stat_artifacts_move_is_withheld_on_the_subject():
    hu, giver = _hu_tao()
    moved = hu.model_copy(update={"effects": tuple(
        e.model_copy(update={"value": e.value.model_copy(update={"cap_times_stat": "atk"})})
        if e.key == "skill_atk" else e for e in hu.effects)})
    kit = sheets.resolve(moved, giver, giver_is_subject=True)
    assert not _effects(kit, "flat_atk_from_hp")
    assert "the cap itself would move" in _unmodelled(kit)


# ── Clorinde: A1 per stack, the stacked total capped; C2 replaces it ────────────────────────


@pytest.mark.parametrize(("constellation", "ratio", "cap"), [
    (0, ("passive", 1, 2), ("passive", 1, 1)), (1, ("passive", 1, 2), ("passive", 1, 1)),
    (2, ("constellation", 2, 1), ("constellation", 2, 0)),
    (6, ("constellation", 2, 1), ("constellation", 2, 0))])
def test_clorindes_a1_is_capped_and_c2_replaces_it(constellation: int, ratio: Any, cap: Any):
    clorinde = _sheet("clorinde")
    kit = sheets.resolve(clorinde, _giver(clorinde, constellation=constellation),
                         giver_is_subject=True)
    pin = {"passive": clorinde.pins.passives, "constellation": clorinde.pins.constellations}
    want = (pin[ratio[0]][ratio[1]][ratio[2]], pin[cap[0]][cap[1]][cap[2]])
    converted = _effects(kit, "flat_damage_from_atk")
    assert [(e.value, e.cap, e.per) for e in converted] == [(*want, "a1_stacks")] * 2
    # One on her burst by move, one on her Night Vigil rows by row: never both on one hit.
    assert {(e.moves, tuple((r.talent, r.label) for r in e.rows or ())) for e in converted} == {
        (("burst",), ()),
        (None, (("elemental_skill", "Swift Hunt DMG"), ("elemental_skill",
                                                         "Impale the Night DMG")))}
    # The party's reactions are the trigger: situational, off until the user says.
    [stacks] = [c for c in kit.bonus.conditions if c.key == "a1_stacks"]
    assert (stacks.default, stacks.max) == (0, 3)


def test_clorindes_c2_needs_her_first_ascension_too():
    clorinde = _sheet("clorinde")
    kit = sheets.resolve(clorinde, _giver(clorinde, constellation=2, ascension=0),
                         giver_is_subject=True)
    assert not _effects(kit, "flat_damage_from_atk")


# ── Nahida: A4 above 200 EM, at most 800 counted ────────────────────────────────────────────


def test_nahidas_a4_is_a_thresholded_capped_conversion_on_tri_karma():
    nahida = _sheet("nahida")
    p = nahida.pins.passives[4]
    kit = sheets.resolve(nahida, _giver(nahida), giver_is_subject=True,
                         receiver_element="dendro", team_elements=["dendro", "hydro"])
    [dmg] = _effects(kit, "dmg_bonus_from_em")
    [cr] = _effects(kit, "crit_rate_from_em")
    assert (dmg.value, dmg.threshold, dmg.cap) == (p[2], p[0], pytest.approx(p[2] * p[1]))
    assert (cr.value, cr.threshold, cr.cap) == (p[3], p[0], pytest.approx(p[3] * p[1]))
    # 0.1% × 800 = 80%, 0.03% × 800 = 24%: the caps GO and gcsim write.
    assert (dmg.cap, cr.cap) == (pytest.approx(0.8), pytest.approx(0.24))
    for e in (dmg, cr):
        assert [(r.talent, r.label) for r in e.rows or ()] == [
            ("elemental_skill", "Tri-Karma Purification DMG")]
    assert "Awakening Elucidated" not in _unmodelled(kit)


@pytest.mark.parametrize(("em", "counted"), [(150.0, 0.0), (500.0, 300.0), (1000.0, 800.0),
                                             (1400.0, 800.0)])
def test_the_threshold_and_stat_cap_resolve_as_a_constant_off_the_subject(em: float,
                                                                          counted: float):
    """The same value read for a receiver who is not the giver is a number: GO's
    `min(max(eleMas - 200, 0), 800) × 0.1%`, evaluated in the giver's graph."""
    nahida = _sheet("nahida")
    shared = nahida.model_copy(update={"effects": tuple(
        e.model_copy(update={"receivers": "team", "rows": None})
        for e in nahida.effects if e.key == "a4_dmg")})
    kit = sheets.resolve(shared, _giver(nahida, elemental_mastery=em), giver_is_subject=False)
    [a4] = _effects(kit, "dmg_bonus")
    assert a4.value == pytest.approx(0.001 * counted)
    assert a4.cap is None


# ── Furina: A4, Salon members only ──────────────────────────────────────────────────────────


def test_furinas_a4_reads_her_hp_per_thousand_capped_on_the_salon_rows():
    furina = _sheet("furina")
    p = furina.pins.passives[4]
    kit = sheets.resolve(furina, _giver(furina), giver_is_subject=True)
    [a4] = _effects(kit, "dmg_bonus_from_hp")
    assert a4.value == pytest.approx(p[0] / 1000)
    assert a4.cap == p[1]
    assert {r.label for r in a4.rows or ()} == {
        "Gentilhomme Usher DMG", "Surintendante Chevalmarin DMG", "Mademoiselle Crabaletta DMG"}
    # Her Ousia bubble is the same move and GO leaves it out: scoped by row, not by move.
    assert a4.moves is None


# ── Alhaitham ───────────────────────────────────────────────────────────────────────────────


def test_alhaithams_a4_is_capped_on_his_projections_and_his_burst():
    alhaitham = _sheet("alhaitham")
    p = alhaitham.pins.passives[4]
    kit = sheets.resolve(alhaitham, _giver(alhaitham), giver_is_subject=True,
                         receiver_element="dendro", team_elements=["dendro"])
    projection, burst = _effects(kit, "dmg_bonus_from_em")
    assert (projection.value, projection.cap) == (p[0], p[1])
    assert {r.label for r in projection.rows or ()} == {
        "1-Mirror Projection Attack DMG", "2-Mirror Projection Attack DMG",
        "3-Mirror Projection Attack DMG"}
    assert (burst.value, burst.cap, burst.moves) == (p[0], p[1], ("burst",))


def _dendro_by_mirrors(constellation: int) -> dict[int, float]:
    """His C4 Dendro DMG on himself at each count of mirrors consumed, summed over the effects
    whose `when` holds — the browser's `applySources`, by hand."""
    alhaitham = _sheet("alhaitham")
    kit = sheets.resolve(alhaitham, _giver(alhaitham, constellation=constellation),
                         giver_is_subject=True, receiver_element="dendro",
                         team_elements=["dendro"])
    dendro = [e for e in kit.bonus.effects if e.stat == "dmg_bonus" and e.elements == ("dendro",)]
    return {n: sum(e.value for e in dendro
                   if all(n in w.values for w in e.when if w.condition == "mirrors_consumed"))
            for n in (1, 2, 3)}


def test_alhaithams_c4_dendro_is_ten_percent_per_mirror_generated():
    """GO `cmpGE(consumed, 1, prod(generated, 10%))`, generated `3 - consumed`, or 3 at C6."""
    p = _sheet("alhaitham").pins.constellations[4][2]
    assert _dendro_by_mirrors(4) == pytest.approx({1: 2 * p, 2: p, 3: 0.0})
    assert _dendro_by_mirrors(6) == pytest.approx({1: 3 * p, 2: 3 * p, 3: 3 * p})


def test_alhaithams_c4_em_reaches_the_others_and_c2_is_his_own():
    alhaitham = _sheet("alhaitham")
    pins = alhaitham.pins.constellations
    mate = sheets.resolve(alhaitham, _giver(alhaitham, constellation=6), giver_is_subject=False,
                          receiver_element="pyro", team_elements=["pyro", "dendro"])
    assert [(e.value, e.per) for e in _effects(mate, "elemental_mastery")] == [
        (pins[4][0], "mirrors_consumed")]
    himself = sheets.resolve(alhaitham, _giver(alhaitham, constellation=6), giver_is_subject=True,
                             receiver_element="dendro", team_elements=["dendro"])
    assert [(e.value, e.per) for e in _effects(himself, "elemental_mastery")] == [
        (pins[2][0], "debate")]
    [debate] = [c for c in himself.bonus.conditions if c.key == "debate"]
    assert (debate.default, debate.max) == (pins[2][2], pins[2][2])


# ── Tighnari ────────────────────────────────────────────────────────────────────────────────


def test_tighnaris_a4_is_capped_on_charged_attacks_and_his_burst():
    tighnari = _sheet("tighnari")
    p = tighnari.pins.passives[4]
    kit = sheets.resolve(tighnari, _giver(tighnari, constellation=1), giver_is_subject=True,
                         receiver_element="dendro", team_elements=["dendro"])
    [a4] = _effects(kit, "dmg_bonus_from_em")
    assert (a4.value, a4.cap, a4.moves) == (p[0], p[1], ("charged", "burst"))
    [c1] = _effects(kit, "crit_rate")
    assert (c1.value, c1.moves) == (tighnari.pins.constellations[1][0], ("charged",))


@pytest.mark.parametrize(("choice", "times"), [("", 0), ("after", 1), ("react", 2)])
def test_tighnaris_c4_gives_the_party_its_em_once_or_twice(choice: str, times: int):
    tighnari = _sheet("tighnari")
    kit = sheets.resolve(tighnari, _giver(tighnari, constellation=4), giver_is_subject=False,
                         receiver_element="pyro", team_elements=["pyro", "dendro"])
    em = sum(e.value for e in _effects(kit, "elemental_mastery")
             if all(choice in w.values for w in e.when))
    assert em == times * tighnari.pins.constellations[4][0]


# ── The format ──────────────────────────────────────────────────────────────────────────────


def test_a_threshold_and_a_cap_stat_need_what_they_qualify():
    with pytest.raises(ValidationError, match="threshold belongs"):
        sheets.ValueRef(passive=4, param=0, threshold={"passive": 4, "param": 1})
    with pytest.raises(ValidationError, match="multiplies a cap"):
        sheets.ValueRef(passive=4, param=0, times_stat="hp", cap_times_stat="base_atk")
    with pytest.raises(ValidationError, match="indexes a talent row"):
        sheets.ParamRef(passive=4, param=0, unnamed=6)


def test_an_effect_carries_a_cap_or_threshold_only_as_a_conversion():
    Effect(stat="flat_atk_from_hp", value=0.06, cap=2860.0)
    Effect(stat="crit_rate_from_em", value=0.0003, cap=0.24, threshold=200.0)
    with pytest.raises(ValidationError, match="per-candidate conversion"):
        Effect(stat="dmg_bonus", value=0.2, cap=0.5)
    with pytest.raises(ValidationError, match="threshold belongs"):
        Effect(stat="dmg_bonus_from_energy_recharge", value=0.25, cap=0.75, threshold=1.0)
    with pytest.raises(ValidationError, match="carries its cap"):
        Effect(stat="dmg_bonus_from_energy_recharge", value=0.25)


# ── The fixtures ────────────────────────────────────────────────────────────────────────────


def test_every_capped_fixture_agrees_with_go_and_states_its_side_of_the_cap():
    from tests.unit.go_fixtures_capped import capped_fixtures

    fixtures = capped_fixtures()
    states = {f["name"]: f.get("cap_state") for f in fixtures}
    # A build below and one past the cap, for each of the six conversions.
    assert sorted(s for s in states.values() if s) == ["below"] * 6 + ["past"] * 6
    for f in fixtures:
        if f["name"].endswith("_on_xiangling"):
            gap = abs(f["expected"] - f["go_value"]) / f["go_value"]
            assert 0 < gap < 5e-4, f["name"]  # the 2.78 / 25/9 EM coefficient only
        else:
            assert f["expected"] == pytest.approx(f["go_value"], rel=1e-12), f["name"]
        withheld = [u["what"] for s in f["sources"] for u in s["bonus"]["unmodelled"]
                    if u["reason"].startswith("withheld")]
        # Only Nahida's A1 on herself, which reads the party's highest EM (still withheld).
        assert all("Compassion Illuminated" in w for w in withheld), (f["name"], withheld)


def test_the_new_sheets_are_verified_and_name_what_they_leave_out():
    names = {f["name"] for f in __import__(
        "tests.unit.go_fixtures_capped", fromlist=["capped_fixtures"]).capped_fixtures()}
    for slug in ("alhaitham", "tighnari", "hu_tao", "clorinde", "nahida", "furina"):
        sheet = _sheet(slug)
        assert sheet.unmodelled, slug
        assert sheet.verified_by, slug
    for slug in ("alhaitham", "tighnari"):
        assert set(_sheet(slug).verified_by) <= names, slug
