"""Math-fallback P2, task 9 — kit sheets: the schema, the pins and the giver-context resolution.

The numbers in these givers are this repo's seeded rows, verbatim (nanoka 7.2.51, the throwaway
re-seed of P1 task 4): Bennett's burst "ATK Bonus Ratio" row at levels 10 and 13, his C1/C2/C6
lists, and Kazuha's A4 list. The sheets pin those same lists; a test below changes one and
watches the effect withheld.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.builder import const
from app.formula.genshin import set_effects, sheets, tags
from app.pando.calculator import NodeRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "formula" / "go_fixtures.json"
KEYS = Path(__file__).resolve().parents[2] / "app" / "data" / "gcsim" / "keys.json"

BURST_LABELS = ["Skill DMG|{param1:P}", ("Continuous Regeneration Per Sec|{param2:F2P} "
                "Max HP+{param3:I}"), "ATK Bonus Ratio|{param4:P}", "Duration|{param5:F1}s"]
BURST_10 = [4.1904, 0.108, 1270.2417, 1.008, 12.0]
BURST_13 = [4.947, 0.1275, 1587.8221, 1.19, 12.0]
BENNETT_CONS = {1: [0.2] + [0.0] * 9, 2: [0.7, 0.3] + [0.0] * 8, 3: [0.0] * 10,
                4: [1.35] + [0.0] * 9, 5: [0.0] * 10, 6: [0.15] + [0.0] * 9}
KAZUHA_A4 = [0.0004, 8.0] + [0.0] * 28


def _registry(**stat_values: float) -> NodeRegistry:
    """A giver's pass-1 registry from stated stats, one contribution per quantity."""
    registry = NodeRegistry()
    for quantity, value in stat_values.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return registry


def bennett(*, constellation: int = 0, burst: int = 10, ascension: int = 6,
            cons: dict[int, list[float]] | None = None,
            labels: list[str] | None = None, base_atk: float = 191.16 + 608.0) -> sheets.Giver:
    rows = {("elemental_burst", 10): sheets.TalentRow(labels or BURST_LABELS, BURST_10),
            ("elemental_burst", 13): sheets.TalentRow(labels or BURST_LABELS, BURST_13)}
    return sheets.Giver(
        name="Bennett", nanoka_id="10000032", constellation=constellation,
        ascension_phase=ascension, talent_levels={"elemental_burst": burst}, talent_rows=rows,
        constellation_params=cons or BENNETT_CONS, passive_params={},
        registry=_registry(base_atk=base_atk, flat_atk=311.0, atk_pct=0.5),
    )


def kazuha(*, ascension: int = 6, em: float = 960.0) -> sheets.Giver:
    return sheets.Giver(
        name="Kaedehara Kazuha", nanoka_id="10000047", constellation=0,
        ascension_phase=ascension, talent_levels={}, talent_rows={},
        constellation_params={}, passive_params={4: KAZUHA_A4},
        registry=_registry(elemental_mastery=em, base_atk=900.0),
    )


BENNETT = sheets.sheet_for("10000032")
KAZUHA = sheets.sheet_for("10000047")


def _effects(kit: sheets.ResolvedKit) -> dict[tuple[str, tuple[str, ...] | None], float]:
    return {(e.stat, e.elements): e.value for e in kit.bonus.effects}


# ── the committed sheets ─────────────────────────────────────────────────────────────────


#: Task 11: every released character gcsim cannot run at the pin, with a kit to model. Derived
#: from `gcsim_status` over the seeded catalogue (7.2.51): Kachina, Nefer, Lohen, Linnea,
#: Mitya, Valeriy, Vodyanitsa and Vesna. Excluded: the practice mannequins, the beta
#: characters, and the two element-less Traveler bodies (10000134/10000135), which have no
#: talents, passives or constellations to write a sheet from.
UNGATED = {"kachina", "nefer", "lohen", "linnea", "mitya", "valeriy", "vodyanitsa", "vesna"}


#: Task 11, second batch: the buffers and supports in the owner's saved teams, then the most
#: used ones (`TASKS_team_math_fallback.md`).
BUFFERS = {"furina", "xingqiu", "xiangling", "citlali", "yelan", "escoffier", "chevreuse",
           "jean", "zhongli", "faruzan", "sucrose"}

#: Task 11, fourth batch: Nahida (who waited on three mechanics) and the next buffers.
BATCH4 = {"nahida", "kujou_sara", "shenhe", "yun_jin", "gorou", "xilonen", "xianyun", "mona",
          "raiden_shogun"}


#: Task 11, third batch: the DPS characters in the owner's saved teams that had no sheet.
DPS = {"skirk", "neuvillette", "kamisato_ayaka", "noelle", "mavuika", "kuki_shinobu"}


def test_every_sheet_loads_and_is_named_after_its_slug():
    assert {s.slug for s in sheets.all_sheets().values()} == {
        "bennett", "kaedehara_kazuha", *UNGATED, *BUFFERS, *BATCH4, *DPS}


def test_every_sheet_is_cited_to_the_pinned_go_and_gcsim_commits():
    """One GO commit for every curated structure (sets and sheets), and gcsim's pin."""
    pin = json.loads(KEYS.read_text(encoding="utf-8"))["pinned_commit_sha"]
    for sheet in sheets.all_sheets().values():
        assert sheet.go_commit == set_effects.curated().go_commit, sheet.slug
        assert sheet.gcsim_commit in (None, pin), sheet.slug
        for effect in sheet.effects:
            assert effect.go.startswith(("pando:", "wr:")), (sheet.slug, effect.key)
        for boost in sheet.talent_boosts:
            assert boost.go, (sheet.slug, boost.constellation)


def test_a_verified_sheet_names_fixtures_that_exist():
    """`verified` is a claim; it is only true when the GO fixtures it names are committed."""
    names = {f["name"] for f in json.loads(FIXTURES.read_text(encoding="utf-8"))["fixtures"]}
    for sheet in sheets.all_sheets().values():
        assert sheet.verified_by, f"{sheet.slug} ships unverified"
        assert set(sheet.verified_by) <= names, sheet.slug


def test_no_number_is_written_into_a_sheet():
    """Values are references into the seeded rows; a constant must carry its own citation."""
    for sheet in sheets.all_sheets().values():
        for effect in sheet.effects:
            ref = effect.value
            assert ref.constant is None or ref.cite, (sheet.slug, effect.key)


# ── Bennett, as a teammate and as himself ─────────────────────────────────────────────────


def test_bennett_burst_is_his_ratio_times_his_own_base_atk():
    """GO `prod(inAreaActive, sum(burstAtkRatio, c1AtkRatio), own.base.atk)` (Bennett.ts:97-101):
    the giver's **base** ATK — not his total, which his flat ATK and ATK% would inflate."""
    kit = sheets.resolve(BENNETT, bennett(), giver_is_subject=False)
    assert _effects(kit) == {("flat_atk", None): pytest.approx(1.008 * 799.16)}
    [condition] = kit.bonus.conditions
    assert (condition.key, condition.default, condition.default_reason) == (
        "in_field", 0, "situational")
    assert kit.verified
    assert "burst_atk pando:Bennett.ts" in kit.citation


def test_c1_adds_its_own_effect_and_c5_raises_the_burst_level():
    """C1 is a second flat-ATK effect (0.2 x base ATK); C5 is burst +3 (Bennett.ts:128), so a
    stored level 10 reads the level-13 row, 1.19."""
    kit = sheets.resolve(BENNETT, bennett(constellation=6), giver_is_subject=False)
    flat = [e.value for e in kit.bonus.effects if e.stat == "flat_atk"]
    assert flat == [pytest.approx(1.19 * 799.16), pytest.approx(0.2 * 799.16)]
    assert _effects(kit)[("dmg_bonus", ("pyro",))] == pytest.approx(0.15)
    # C2 is `ownBuff` (Bennett.ts:130): it never reaches a teammate.
    assert all(e.stat != "energy_recharge" for e in kit.bonus.effects)


def test_bennett_on_himself_defaults_the_field_on_and_keeps_c2():
    kit = sheets.resolve(BENNETT, bennett(constellation=2), giver_is_subject=True)
    by_key = {c.key: c for c in kit.bonus.conditions}
    assert (by_key["in_field"].default, by_key["in_field"].default_reason) == (1, "self")
    assert (by_key["below_70_hp"].default, by_key["below_70_hp"].default_reason) == (
        0, "situational")
    assert _effects(kit)[("energy_recharge", None)] == pytest.approx(0.3)


def test_locked_parts_are_absent_and_unlocked_gaps_are_named():
    kit = sheets.resolve(BENNETT, bennett(ascension=3), giver_is_subject=False)
    named = " ".join(u.what for u in kit.bonus.unmodelled)
    assert "A1: Rekindle" in named
    assert "Fearnaught" not in named  # A4 needs ascension 4
    assert "Unexpected Odyssey" not in named  # C4 is locked at C0
    assert kit.status == "partial"


def test_a_changed_constellation_list_is_withheld_not_misread():
    cons = {**BENNETT_CONS, 1: [0.25] + [0.0] * 9}
    kit = sheets.resolve(BENNETT, bennett(constellation=1, cons=cons), giver_is_subject=False)
    assert [e.value for e in kit.bonus.effects] == [pytest.approx(1.008 * 799.16)]
    [withheld] = [u for u in kit.bonus.unmodelled if u.reason.startswith("withheld")]
    assert "C1 param_list changed since curation" in withheld.reason


def test_a_relabelled_talent_row_is_withheld():
    labels = [*BURST_LABELS[:2], "ATK Bonus Ratio|{param5:P}", BURST_LABELS[3]]
    kit = sheets.resolve(BENNETT, bennett(labels=labels), giver_is_subject=False)
    assert kit.bonus.effects == ()
    assert any("changed since curation" in u.reason for u in kit.bonus.unmodelled)


def test_a_missing_talent_row_is_withheld():
    kit = sheets.resolve(BENNETT, bennett(burst=9), giver_is_subject=False)
    assert kit.bonus.effects == ()
    assert any("no published row at level 9" in u.reason for u in kit.bonus.unmodelled)
    # A toggle that gates nothing applied is not offered.
    assert kit.bonus.conditions == ()


# ── Kazuha: a giver stat that moves with artifacts ───────────────────────────────────────


def test_kazuha_a4_is_four_toggles_from_his_own_em():
    kit = sheets.resolve(KAZUHA, kazuha(), giver_is_subject=False)
    assert _effects(kit) == {
        ("dmg_bonus", (e,)): pytest.approx(0.0004 * 960)
        for e in ("pyro", "hydro", "electro", "cryo")
    }
    assert {(c.key, c.default) for c in kit.bonus.conditions} == {
        ("swirl_pyro", 0), ("swirl_hydro", 0), ("swirl_electro", 0), ("swirl_cryo", 0)}


def test_kazuha_on_himself_becomes_a_per_candidate_conversion():
    """His own EM moves with every candidate, so the number would be frozen at his equipped
    build. It travels as the coefficient, `dmg_bonus_from_em`, for the recipe to multiply."""
    kit = sheets.resolve(KAZUHA, kazuha(em=500.0), giver_is_subject=True)
    assert [(e.stat, e.value) for e in kit.bonus.effects] == [
        ("dmg_bonus_from_em", pytest.approx(0.0004))] * 4


def test_kazuha_below_a4_contributes_nothing():
    kit = sheets.resolve(KAZUHA, kazuha(ascension=3), giver_is_subject=False)
    assert kit.bonus.effects == ()


def test_stats_read_reports_what_each_number_came_from():
    assert sheets.stats_read(BENNETT, bennett()) == {"base_atk": pytest.approx(799.16)}
    assert sheets.stats_read(KAZUHA, kazuha()) == {"elemental_mastery": pytest.approx(960)}


def test_a_self_buff_from_a_moving_stat_the_recipe_cannot_carry_is_withheld():
    """Bennett's burst on himself reads base ATK, which does not move — so it stays a number.
    The same buff off his **total** ATK would move, and nothing carries flat ATK from ATK."""
    effect = BENNETT.effects[0].model_copy(update={
        "value": BENNETT.effects[0].value.model_copy(update={"times_stat": "atk"})})
    sheet = BENNETT.model_copy(update={"effects": (effect,)})
    kit = sheets.resolve(sheet, bennett(), giver_is_subject=True)
    assert kit.bonus.effects == ()
    assert "moves with every candidate" in kit.bonus.unmodelled[-1].reason
