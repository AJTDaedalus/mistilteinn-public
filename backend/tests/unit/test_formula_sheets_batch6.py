"""Math-fallback P2, task 11 (sixth batch): the fifth batch's leftovers (Chasca, Kinich, Wanderer,
Keqing) and the supports and buffers next by use, and the two small format extensions they
needed (`docs/DESIGN_team_math_fallback.md` §2.6, sixth-batch table).

Each sheet's GO agreement on its main effect is `test_go_formula_fixtures.py`'s job (fixtures in
`go_fixtures_batch6.py`). This file checks what one fixture per sheet does not: a distinct-element
count limited to some elements with a constellation counting one more (Chasca's A1), a value times
a cited constant (Kokomi's A4), the gates and defaults each sheet chose, the per-row moves, and the
parts of each kit the sheets name instead of applying.

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins`; talent rows are the seeded rows at the level named, verbatim.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.formula.builder import const
from app.formula.genshin import sheets, tags
from app.pando.calculator import NodeRegistry


def _sheet(slug: str) -> sheets.Sheet:
    [sheet] = [s for s in sheets.all_sheets().values() if s.slug == slug]
    return sheet


def _giver(sheet: sheets.Sheet, *, constellation: int = 0, ascension: int = 6,
           levels: dict[str, int] | None = None,
           rows: dict[tuple[str, int], tuple[list[str], list[float]]] | None = None,
           **stats: float) -> sheets.Giver:
    registry = NodeRegistry()
    for quantity, value in stats.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return sheets.Giver(
        name=sheet.character, nanoka_id=sheet.nanoka_id, constellation=constellation,
        ascension_phase=ascension, talent_levels=levels or {},
        talent_rows={k: sheets.TalentRow(*v) for k, v in (rows or {}).items()},
        constellation_params={n: list(v) for n, v in sheet.pins.constellations.items()},
        passive_params={n: list(v) for n, v in sheet.pins.passives.items()},
        registry=registry,
    )


def _values(kit: sheets.ResolvedKit, stat: str) -> list[float]:
    return [e.value for e in kit.bonus.effects if e.stat == stat]


def _unmodelled(kit: sheets.ResolvedKit) -> str:
    return " | ".join(f"{u.what}: {u.reason}" for u in kit.bonus.unmodelled)


# ── a distinct count limited to some elements, with a constellation counting one more ────────

ABSORBABLE = ["pyro", "hydro", "electro", "cryo"]


@pytest.mark.parametrize(("constellation", "team", "entry"), [
    (0, ["anemo", "pyro", "pyro", "geo"], 3),            # one absorbable element: the first entry
    (0, ["anemo", "pyro", "hydro", "geo"], 4),           # two, Geo not counted
    (0, ["anemo", "pyro", "hydro", "electro"], 5),       # three
    (2, ["anemo", "pyro", "pyro", "geo"], 4),            # C2 counts one more
    (2, ["anemo", "pyro", "hydro", "electro"], 5),       # three plus one, capped at three
    (2, ["anemo", "anemo", "geo", "geo"], 3),            # none present, C2's one alone
])
def test_chascas_a1_reads_the_absorbable_elements_present_with_c2_counting_one_more(
        constellation, team, entry):
    """GO `min(sum(cmpGE(count[ele], 1, 1) for absorbable, cmpGE(constellation, 2, 1)), 3)`,
    then `subscript(n, [-1, passive1[3], passive1[4], passive1[5]])` (`pando Chasca.ts:104-121`):
    distinct, not members — two Pyro characters are one element."""
    chasca = _sheet("chasca")
    kit = sheets.resolve(chasca, _giver(chasca, constellation=constellation),
                         giver_is_subject=True, receiver_element="anemo", team_elements=team)
    a1 = [e for e in kit.bonus.effects if e.stat == "dmg_bonus"]
    assert [e.value for e in a1] == [chasca.pins.passives[1][entry]]
    assert a1[0].rows == (sheets.TalentRowScope(talent="elemental_skill",
                                                label="Shining Shadowhunt Shell DMG"),)


def test_chascas_a1_is_absent_with_nothing_to_absorb_below_c2():
    chasca = _sheet("chasca")
    kit = sheets.resolve(chasca, _giver(chasca), giver_is_subject=True,
                         team_elements=["anemo", "anemo", "geo", "dendro"])
    assert _values(kit, "dmg_bonus") == []


def test_a_distinct_count_may_name_its_elements_and_an_elements_count_must():
    sheets.TeamIndex(count="distinct", elements=("pyro",), size=3)
    sheets.TeamIndex(count="distinct", size=4)
    with pytest.raises(ValidationError, match="names its elements"):
        sheets.TeamIndex(count="elements", size=4)


# ── a value times a cited constant: Kokomi's A4 on her innate Healing Bonus ─────────────────

KOKOMI_BURST_LABELS = ["Skill DMG|{param1:F1P} Max HP",
                       "Normal Attack DMG Bonus|{param4:F1P} Max HP",
                       "Charged Attack DMG Bonus|{param5:F1P} Max HP",
                       "Bake-Kurage DMG Bonus|{param9:F1P} Max HP"]
KOKOMI_BURST_10 = [0.187488, 0.014544, 169.49507, 0.08712, 0.121968, 10.0, 18.0, 70.0, 0.127734]


def test_kokomis_a4_is_its_ratio_times_her_innate_healing_bonus_of_her_max_hp():
    kokomi = _sheet("sangonomiya_kokomi")
    giver = _giver(kokomi, levels={"elemental_burst": 10},
                   rows={("elemental_burst", 10): (KOKOMI_BURST_LABELS, KOKOMI_BURST_10)})
    kit = sheets.resolve(kokomi, giver, giver_is_subject=True)
    a4 = [(e.moves, e.value) for e in kit.bonus.effects
          if e.stat == "flat_damage_from_hp" and e.value < 0.05]
    ratio = kokomi.pins.passives[4][0]
    assert a4 == [(("normal",), pytest.approx(ratio * 0.25)),
                  (("charged",), pytest.approx(ratio * 0.25))]
    assert _values(kit, "crit_rate") == [-1.0]
    assert "Healing Bonus" in _unmodelled(kit)


def test_kokomis_kit_reaches_no_teammate():
    kokomi = _sheet("sangonomiya_kokomi")
    kit = sheets.resolve(kokomi, _giver(kokomi, constellation=6, hp=40000.0),
                         giver_is_subject=False)
    assert kit.bonus.effects == ()


def test_a_cited_constant_on_a_value_carries_its_citation():
    with pytest.raises(ValidationError):
        sheets.ValueRef(passive=4, param=0, times_constant={"constant": 0.25})


# ── raised maxima, gates and defaults ────────────────────────────────────────────────────────


def test_ayatos_namisen_reaches_five_stacks_only_from_c2():
    """GO `cmpGE(skillStacks, 5, cmpGE(constellation, 2, skillStacks), skillStacks)` with
    `maxStacks: 4` and C2's `extraStacks` (`pando KamisatoAyato.ts:51,76,100-105`)."""
    ayato = _sheet("kamisato_ayato")
    skill = (["Namisen DMG Bonus|{param5:F2P}Max HP/Stack"],
             [1.0455, 1.1645, 1.2835, 6.0, 0.011091])
    rows = {("elemental_skill", 10): skill}
    for constellation, top in ((0, 4), (2, 5)):
        kit = sheets.resolve(ayato, _giver(ayato, constellation=constellation,
                                           levels={"elemental_skill": 10}, rows=rows),
                             giver_is_subject=True)
        namisen = next(c for c in kit.bonus.conditions if c.key == "namisen")
        assert (namisen.max, namisen.default) == (top, top)
    c2 = sheets.resolve(ayato, _giver(ayato, constellation=2), giver_is_subject=True)
    hp = next(e for e in c2.bonus.effects if e.stat == "hp_pct")
    assert hp.when[0].values == (3, 4, 5)


def test_wanderers_a1_needs_the_element_in_the_party():
    """GO leaves the absorbed element to the user; the estimate applies each only when a member
    has it, and says so."""
    wanderer = _sheet("wanderer")
    with_both = sheets.resolve(wanderer, _giver(wanderer), giver_is_subject=True,
                               team_elements=["anemo", "pyro", "cryo"])
    neither = sheets.resolve(wanderer, _giver(wanderer), giver_is_subject=True,
                             team_elements=["anemo", "hydro", "electro"])
    assert (_values(with_both, "atk_pct"), _values(with_both, "crit_rate")) == ([0.3], [0.2])
    assert (_values(neither, "atk_pct"), _values(neither, "crit_rate")) == ([], [])
    assert "without a Pyro or Cryo member" in _unmodelled(neither)


IANSAN_BURST_LABELS = ["High Nightsoul Points ATK Conversion Rate|{param2:P} ATK",
                       "Max ATK Bonus|{param4:F1}"]
IANSAN_BURST_10 = [7.7472, 0.27, 0.005, 690.0]
IANSAN_BURST_13 = [9.146, 0.27, 0.005, 810.0]


def test_iansans_burst_is_a_share_of_her_atk_capped_by_the_row_at_her_boosted_level():
    iansan = _sheet("iansan")
    rows = {("elemental_burst", 10): (IANSAN_BURST_LABELS, IANSAN_BURST_10),
            ("elemental_burst", 13): (IANSAN_BURST_LABELS, IANSAN_BURST_13)}
    stats = {"base_atk": 917.0, "atk_pct": 2.0, "flat_atk": 311.0}   # ATK 3,062
    c0 = sheets.resolve(iansan, _giver(iansan, levels={"elemental_burst": 10}, rows=rows,
                                       **stats), giver_is_subject=False)
    c5 = sheets.resolve(iansan, _giver(iansan, constellation=5, levels={"elemental_burst": 10},
                                       rows=rows, **stats), giver_is_subject=False)
    assert _values(c0, "flat_atk") == [pytest.approx(690.0)]    # 826.74 capped at level 10
    assert _values(c5, "flat_atk") == [pytest.approx(810.0)]    # capped at level 13
    low = sheets.resolve(iansan, _giver(iansan, levels={"elemental_burst": 10}, rows=rows,
                                        base_atk=917.0, atk_pct=0.5, flat_atk=311.0),
                         giver_is_subject=False)
    assert _values(low, "flat_atk") == [pytest.approx(0.27 * (917 * 1.5 + 311))]


def test_iansans_burst_on_herself_is_withheld_by_name():
    iansan = _sheet("iansan")
    rows = {("elemental_burst", 10): (IANSAN_BURST_LABELS, IANSAN_BURST_10)}
    kit = sheets.resolve(iansan, _giver(iansan, levels={"elemental_burst": 10}, rows=rows),
                         giver_is_subject=True)
    assert _values(kit, "flat_atk") == []
    assert "withheld" in _unmodelled(kit)
    assert "flat_atk from atk" in _unmodelled(kit)


@pytest.mark.parametrize(("slug", "key", "subject", "value", "reason"), [
    ("kinich", "c2_first", True, 0, "situational"),         # only the first cannon
    ("kinich", "c2_hit", False, 1, "teammate"),             # his shred, as a teammate plays it
    ("wanderer", "c2_points", True, 50, "usual"),           # at its maximum, said
    ("keqing", "reacted", True, 1, "usual"),
    ("baizhu", "active_hp", True, "above", "usual"),
    ("kamisato_ayato", "low_hp", False, 0, "situational"),
    ("ororon", "c2_hits", True, 1, "usual"),                # one target
    ("iansan", "high_points", False, 1, "teammate"),
])
def test_each_new_condition_defaults_by_the_rule(slug, key, subject, value, reason):
    condition = next(c for c in _sheet(slug).conditions if c.key == key)
    c = condition.resolve(giver_is_subject=subject, receiver_element="pyro")
    assert (c.default, c.default_reason) == (value, reason)
    assert reason == "self" or c.default_note


# ── scope: rows, moves, receivers ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("nanoka_id", "label", "move"), [
    ("10000104", "Multitarget Fire Tap DMG", "normal"),
    ("10000104", "Shadowhunt Shell DMG", "charged"),
    ("10000104", "Shining Shadowhunt Shell DMG", "charged"),
    ("10000066", "Shunsuiken 1-Hit DMG", "normal"),
    ("10000066", "Shunsuiken 3-Hit DMG", "normal"),
])
def test_skill_rows_dealt_as_other_moves_say_so(nanoka_id, label, move):
    assert sheets.row_move(nanoka_id, "elemental_skill", label) == move
    assert sheets.row_move(nanoka_id, "elemental_skill", "Resonance DMG") is None


def test_yaes_c6_ignores_def_on_her_level_two_to_four_sakura_only():
    yae = _sheet("yae_miko")
    kit = sheets.resolve(yae, _giver(yae, constellation=6), giver_is_subject=True)
    [ignore] = [e for e in kit.bonus.effects if e.stat == "def_ignore"]
    assert {r.label for r in ignore.rows or ()} == {
        f"Sesshou Sakura DMG: Level {n}" for n in (2, 3, 4)}
    teammate = sheets.resolve(yae, _giver(yae, constellation=6), giver_is_subject=False)
    assert {e.stat for e in teammate.bonus.effects} == {"dmg_bonus"}   # C4 alone reaches others


def test_yaes_a4_on_herself_is_a_per_candidate_conversion_of_her_em():
    yae = _sheet("yae_miko")
    kit = sheets.resolve(yae, _giver(yae, elemental_mastery=300.0), giver_is_subject=True)
    assert [(e.moves, e.value) for e in kit.bonus.effects if e.stat == "dmg_bonus_from_em"] == [
        (("skill",), yae.pins.passives[4][0])]


@pytest.mark.parametrize(("slug", "constellation", "stat", "receivers_reach_teammate"), [
    ("kinich", 2, "enemy_res", True),
    ("beidou", 6, "enemy_res", True),
    ("layla", 4, "flat_damage", True),
    ("thoma", 6, "dmg_bonus", True),
    ("kirara", 6, "dmg_bonus", True),
    ("lan_yan", 4, "elemental_mastery", True),
    ("ororon", 6, "atk_pct", True),
    ("dehya", 6, "crit_rate", False),
    ("chasca", 6, "crit_dmg", False),
])
def test_who_each_kit_reaches(slug, constellation, stat, receivers_reach_teammate):
    sheet = _sheet(slug)
    kit = sheets.resolve(sheet, _giver(sheet, constellation=constellation, hp=30000.0),
                         giver_is_subject=False, team_elements=["pyro", "hydro"],
                         receiver_element="pyro")
    assert (stat in {e.stat for e in kit.bonus.effects}) is receivers_reach_teammate


def test_kinichs_c2_shreds_dendro_res_as_a_reduction():
    kinich = _sheet("kinich")
    kit = sheets.resolve(kinich, _giver(kinich, constellation=2), giver_is_subject=False)
    [res] = [e for e in kit.bonus.effects if e.stat == "enemy_res"]
    assert (res.elements, res.value) == (("dendro",), -kinich.pins.constellations[2][0])


def test_every_batch6_sheet_names_what_it_leaves_out():
    for slug in ("chasca", "kinich", "wanderer", "keqing", "sangonomiya_kokomi", "yae_miko",
                 "kamisato_ayato", "baizhu", "dehya", "layla", "kirara", "lynette", "thoma",
                 "beidou", "ororon", "iansan", "lan_yan"):
        sheet = _sheet(slug)
        assert sheet.unmodelled, slug
        assert sheet.verified_by, slug
