"""A kit's talent-level raise and CRIT from Max HP (owner approval 2026-11-14,
`docs/DECISIONS.md` §42; `docs/DESIGN_team_math_fallback.md` §2.6).

GO agreement on each sheet's main effect is `test_go_formula_fixtures.py`'s job (fixtures in
`go_fixtures_talent_crit.py`). This file checks the mechanics around them: the schema's rules for
a `talent_level` effect, who each raise reaches (`sheets.talent_raises`), how a raise reaches a
giver's own values (`Giver.talent_raises`, Shenhe's Icy Quill in Skirk's party), the subject's
raised rows and their ordering and cap (`team_talent_levels.raised_talents`), and Nilou's and
Sigewinne's C6 as per-candidate capped conversions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.formula.genshin import sheets
from app.formula.genshin.formula_effects import Effect
from app.models.enums import TalentType
from app.services import kit_buffs
from app.services.team_talent_levels import raised_talents
from tests.unit.test_formula_sheets_batch6 import _giver, _sheet, _unmodelled, _values

# ── the schema ───────────────────────────────────────────────────────────────────────────────


def _raise_effect(**over: object) -> dict[str, object]:
    effect: dict[str, object] = {
        "key": "x", "label": "x", "source": "a0", "receivers": "team", "stat": "talent_level",
        "talent": "normal_attack", "value": {"constant": 1, "cite": "GO"}, "go": "x",
    }
    effect.update(over)
    return effect


@pytest.mark.parametrize("over", [
    {"talent": None},                                         # names no talent
    {"talent": "constellation"},                              # not a talent
    {"value": {"constant": 0.5, "cite": "GO"}},               # not a whole number
    {"value": {"constellation": 1, "param": 0}},              # not a cited literal
    {"receivers": "enemy"},
    {"moves": ["normal"]},                                    # reaches every row of its talent
])
def test_a_talent_level_raise_is_a_cited_whole_number_on_a_talent(over):
    with pytest.raises(ValidationError):
        sheets.SheetEffect.model_validate(_raise_effect(**over))


def test_only_a_talent_level_raise_names_a_talent():
    with pytest.raises(ValidationError):
        sheets.SheetEffect.model_validate(_raise_effect(stat="crit_rate"))
    with pytest.raises(ValidationError):
        Effect(stat="crit_rate", value=0.1, talent="normal_attack")
    with pytest.raises(ValidationError):
        Effect(stat="talent_level", value=1)


def test_a_sheet_reading_a_talent_its_own_conditional_raise_lifts_is_refused():
    """Lohen's High Spirits raises his skill under a condition; the browser applies it per row,
    and his values are resolved here without it. A sheet whose values read that talent would
    disagree with itself, so it is refused (his reads no skill row)."""
    shenhe = _sheet("shenhe").model_dump(by_alias=True)
    shenhe["conditions"] = [*shenhe["conditions"], {
        "key": "spirits", "label": "x", "kind": "toggle", "default_by": "self", "go": "x"}]
    shenhe["effects"] = [*shenhe["effects"], _raise_effect(
        key="lift", talent="elemental_skill", when=[{"condition": "spirits", "values": [1]}])]
    with pytest.raises(ValidationError, match="conditional talent-level raise"):
        sheets.Sheet.model_validate(shenhe)
    lohen = _sheet("lohen")
    assert any(e.stat == "talent_level" and e.when for e in lohen.effects)


# ── who each raise reaches ──────────────────────────────────────────────────────────────────


def _raises(slug: str, *, team: list[str], receiver: str, giver_is_receiver: bool,
            subject: bool = True, constellation: int = 0, ascension: int = 6) -> dict[str, int]:
    return sheets.talent_raises(
        _sheet(slug), constellation=constellation, ascension_phase=ascension,
        giver_is_receiver=giver_is_receiver, receiver_is_subject=subject,
        receiver_element=receiver, team_elements=team,
    )


def test_tartaglia_raises_everyones_normal_attack_himself_included():
    for itself in (True, False):
        assert _raises("tartaglia", team=["hydro", "pyro"], receiver="pyro",
                       giver_is_receiver=itself) == {"normal_attack": 1}
    # His A0 is held from ascension 0 (GO passive3, ungated).
    assert _raises("tartaglia", team=["hydro"], receiver="hydro", giver_is_receiver=True,
                   ascension=0) == {"normal_attack": 1}


@pytest.mark.parametrize(("team", "raised"), [
    (["cryo", "hydro"], True),
    (["cryo", "hydro", "hydro", "cryo"], True),
    (["cryo", "cryo"], False),                   # needs a Hydro member
    (["cryo", "hydro", "pyro"], False),          # every member Hydro or Cryo
    (["cryo", "hydro", None], False),            # an element-less member is neither
])
def test_skirks_raise_holds_only_in_a_hydro_and_cryo_party(team, raised):
    """GO `cmpGE(cryo, 1, cmpGE(hydro, 1, cmpEq(cryo + hydro, all, 1)))` (`pando
    Skirk.ts:206-219`), gcsim `skirk.go:69-96`."""
    got = _raises("skirk", team=team, receiver="hydro", giver_is_receiver=False)
    assert got == ({"elemental_skill": 1} if raised else {})


def test_lohens_conditional_raise_is_never_a_giver_raise():
    """High Spirits is per row in the browser; `talent_raises` carries unconditional ones only."""
    assert _raises("lohen", team=["cryo"], receiver="cryo", giver_is_receiver=True) == {}


def test_a_raise_reaches_a_givers_own_value():
    """Shenhe's Icy Quill is a share of her ATK read off her skill's "DMG Bonus" row. In Skirk's
    party her skill is one level up, and GO reads the quill there (`own.char.skill`)."""
    shenhe = _sheet("shenhe")
    label = shenhe.pins.talent_rows["elemental_skill"][0]
    rows = {("elemental_skill", 10): ([label], [0.0, 0.0, 0.8]),
            ("elemental_skill", 11): ([label], [0.0, 0.0, 0.9])}
    def giver() -> sheets.Giver:  # a fresh registry each time: a sheet registers into it
        return _giver(shenhe, levels={"elemental_skill": 10}, rows=rows, base_atk=1000.0)

    def quill(g: sheets.Giver) -> float:
        kit = sheets.resolve(shenhe, g, giver_is_subject=False, receiver_element="cryo",
                             team_elements=["cryo", "hydro"])
        [value] = _values(kit, "flat_damage")
        return value

    assert quill(giver()) == pytest.approx(800.0)
    assert quill(replace(giver(), talent_raises={"elemental_skill": 1})) == pytest.approx(900.0)


def _member(build_id: str, nanoka_id: str, element: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=build_id, constellation_level=0, ascension_phase=6,
        character=SimpleNamespace(nanoka_id=nanoka_id, element=element),
    )


def test_member_raises_sums_every_members_unconditional_raise():
    skirk = _member("s", "10000114", "Cryo")
    shenhe = _member("h", "10000063", "Cryo")
    furina = _member("f", "10000089", "Hydro")
    party = [skirk, shenhe, furina]
    elements = ["cryo", "cryo", "hydro"]
    for member in party:
        assert kit_buffs.member_raises(party, member, "s", elements) == {"elemental_skill": 1}
    tartaglia = _member("t", "10000033", "Hydro")
    party = [*party, tartaglia]
    assert kit_buffs.member_raises(party, shenhe, "s", [*elements, "hydro"]) == {
        "elemental_skill": 1, "normal_attack": 1}


# ── the subject's raised rows: ordering and cap ─────────────────────────────────────────────


@dataclass(frozen=True)
class _Scaling:
    level: int
    labels: list[str]
    params: list[float]


@dataclass(frozen=True)
class _Talent:
    talent_type: TalentType
    scalings: list[_Scaling]


@dataclass(frozen=True)
class _Character:
    name: str
    nanoka_id: str
    element: str
    talents: list[_Talent]


def _lohen(top: int = 15) -> _Character:
    """Lohen's skill, a row per level whose one multiplier is the level, so a level reads back."""
    return _Character("Lohen", "10000129", "Cryo", [_Talent(TalentType.ELEMENTAL_SKILL, [
        _Scaling(level, ["1-Hit DMG|{param1:F1P}"], [float(level)])
        for level in range(1, top + 1)])])


def _levels(raised: list, raise_by: int) -> list[float]:
    return [r.hit.multiplier for t in raised for r in t.rows if r.raise_by == raise_by]


def test_stored_then_constellation_then_kits_10_3_1_is_14():
    [talent] = raised_talents(_lohen(), 3, {"elemental_skill": 10}, {"elemental_skill": 1})
    assert (talent.talent, talent.level, talent.max_raise) == ("elemental_skill", 13, 1)
    assert _levels([talent], 1) == [14.0]


def test_two_raises_reach_15_the_tables_last_row():
    """Lohen at C3, High Spirits on, in Skirk's party: 10 + 3 + 1 + 1. GO adds without a cap."""
    [talent] = raised_talents(_lohen(), 3, {"elemental_skill": 10}, {"elemental_skill": 2})
    assert _levels([talent], 1) == [14.0]
    assert _levels([talent], 2) == [15.0]
    assert talent.unavailable == ()


def test_past_the_tables_last_row_nothing_is_read():
    [talent] = raised_talents(_lohen(top=14), 3, {"elemental_skill": 10},
                              {"elemental_skill": 2})
    assert _levels([talent], 2) == []
    [(raise_by, why)] = talent.unavailable
    assert raise_by == 2
    assert "no published row at level 15" in why


def test_below_c3_no_constellation_boost_is_added():
    [talent] = raised_talents(_lohen(), 0, {"elemental_skill": 10}, {"elemental_skill": 1})
    assert talent.level == 10
    assert _levels([talent], 1) == [11.0]


def test_a_talent_the_build_has_no_level_for_is_unavailable_not_level_one():
    [talent] = raised_talents(_lohen(), 0, {}, {"elemental_skill": 1})
    assert talent.rows == ()
    assert talent.unavailable == ((1, "the build has no elemental_skill level"),)


def test_the_subjects_raises_sum_every_resolved_raise_conditional_ones_included():
    """`/formula/kit-buffs` publishes rows up to every raise's sum; the browser picks the one the
    row's conditions give."""
    lohen = _sheet("lohen")
    skirk = _sheet("skirk")
    kits = [
        sheets.resolve(lohen, _giver(lohen, constellation=3), giver_is_subject=True,
                       receiver_element="cryo", team_elements=["cryo", "hydro"]),
        sheets.resolve(skirk, _giver(skirk), giver_is_subject=False, receiver_element="cryo",
                       team_elements=["cryo", "hydro"]),
    ]
    subject = SimpleNamespace(character=_lohen(), constellation_level=3,
                              talent_levels={"elemental_skill": 10})
    [talent] = kit_buffs.subject_raised_talents(subject, kits)  # type: ignore[arg-type]
    assert talent.max_raise == 2
    assert _levels([talent], 2) == [15.0]


# ── CRIT from Max HP ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "moves", "conditioned"), [
    ("nilou", None, False),
    ("sigewinne", ("burst",), True),
])
def test_c6_crit_from_her_own_hp_is_a_capped_conversion_per_candidate(slug, moves, conditioned):
    sheet = _sheet(slug)
    c6 = sheet.pins.constellations[6]
    kit = sheets.resolve(sheet, _giver(sheet, constellation=6, hp=50000.0),
                         giver_is_subject=True, receiver_element="hydro",
                         team_elements=["hydro", "pyro"])
    rate = [e for e in kit.bonus.effects if e.stat == "crit_rate_from_hp"]
    dmg = [e for e in kit.bonus.effects if e.stat == "crit_dmg_from_hp"]
    assert [(e.value, e.cap, e.moves) for e in rate] == [
        (pytest.approx(c6[0] / 1000), c6[2 if slug == "nilou" else 3], moves)]
    assert [(e.value, e.cap, e.moves) for e in dmg] == [
        (pytest.approx(c6[1] / 1000), c6[3 if slug == "nilou" else 4], moves)]
    assert all(bool(e.when) is conditioned for e in (*rate, *dmg))
    assert "C6" not in _unmodelled(kit)


def test_c6_crit_reaches_no_teammate():
    for slug in ("nilou", "sigewinne"):
        sheet = _sheet(slug)
        kit = sheets.resolve(sheet, _giver(sheet, constellation=6, hp=50000.0),
                             giver_is_subject=False, receiver_element="pyro",
                             team_elements=["hydro", "pyro"])
        assert not {"crit_rate", "crit_dmg", "crit_rate_from_hp", "crit_dmg_from_hp"} & {
            e.stat for e in kit.bonus.effects}


def test_the_caps_bind_at_the_same_hp_for_each():
    """50,000 Max HP: Nilou 0.6%/1.2% per 1,000 to 30%/60%, Sigewinne 0.4%/2.2% to 20%/110%."""
    nilou = _sheet("nilou").pins.constellations[6]
    sige = _sheet("sigewinne").pins.constellations[6]
    assert nilou[2] / nilou[0] * 1000 == pytest.approx(50000)
    assert nilou[3] / nilou[1] * 1000 == pytest.approx(50000)
    assert sige[3] / sige[0] * 1000 == pytest.approx(50000)
    assert sige[4] / sige[1] * 1000 == pytest.approx(50000)
