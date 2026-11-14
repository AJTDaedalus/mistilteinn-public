"""Math-fallback P3, task 12 — weapon passives as data (`app/formula/genshin/weapon_passives.py`).

The files are checked for what a reader would otherwise have to trust: each is named after its
slug, cited to the pinned GO and gcsim commits, verified by GO fixtures that exist and that name
it, numbers only by reference (a constant carries its citation), and pinned per refinement. The
resolver is checked for the receiver rules and the per-candidate conversions a subject's own
buff becomes, and for withholding rather than misreading a changed list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.genshin import set_effects, sheets, weapon_passives
from app.services.unreleased import is_unreleased_class
from tests.unit.test_go_formula_fixtures import _stated_registry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "formula" / "go_fixtures.json"
KEYS = (Path(__file__).resolve().parents[2] / "app" / "data" / "gcsim" / "keys.json")
GO_ROOT = "libs/gi/sheets/src/Weapons/"


def _wielder(nanoka_id: str, refinement: int, stats: dict[str, float] | None = None,
             params: list[float] | None = None) -> weapon_passives.Wielder:
    passive = weapon_passives.passive_for(nanoka_id)
    assert passive is not None
    return weapon_passives.Wielder(
        "Wielder", refinement,
        list(passive.pins[refinement]) if params is None else params,
        _stated_registry(stats or {}),
    )


def _resolve(nanoka_id: str, refinement: int = 1, *, subject: bool,
             stats: dict[str, float] | None = None, element: str | None = "pyro",
             params: list[float] | None = None) -> sheets.ResolvedKit:
    passive = weapon_passives.passive_for(nanoka_id)
    assert passive is not None
    return weapon_passives.resolve(passive, _wielder(nanoka_id, refinement, stats, params),
                                   wielder_is_subject=subject, receiver_element=element,
                                   team_elements=[element, "hydro"])


def test_every_file_loads_named_after_its_slug_and_cited_to_the_pins():
    passives = weapon_passives.all_passives()
    assert len(passives) >= 15
    pin = json.loads(KEYS.read_text(encoding="utf-8"))["pinned_commit_sha"]
    for passive in passives.values():
        assert passive.go_commit == set_effects.curated().go_commit, passive.slug
        assert passive.gcsim_commit in (None, pin), passive.slug
        assert passive.go.startswith(GO_ROOT), passive.slug
        assert passive.go.endswith("/index.tsx"), passive.slug


def test_every_file_is_verified_by_fixtures_that_exist_and_name_it():
    """`verified` is a claim: true only when the GO fixtures it names are committed, and every
    committed fixture that carries a weapon's source is listed by that weapon."""
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))["fixtures"]
    names = {f["name"] for f in fixtures}
    for passive in weapon_passives.all_passives().values():
        assert passive.verified_by, f"{passive.slug} ships unverified"
        assert set(passive.verified_by) <= names, passive.slug
        sid = weapon_passives.source_id(passive)
        carrying = {f["name"] for f in fixtures
                    if any(s["id"].split(":")[:2] == sid.split(":") for s in f["sources"])}
        assert carrying == set(passive.verified_by), passive.slug


def test_no_number_is_written_into_a_file():
    for passive in weapon_passives.all_passives().values():
        for effect in passive.effects:
            assert effect.value.constant is None or effect.value.cite, (passive.slug, effect.key)
        for refinement, pin in passive.pins.items():
            assert len(pin) == len(passive.pins[1]), (passive.slug, refinement)


def test_no_file_names_a_weapon_of_a_class_the_game_has_not_shipped():
    """The export gate rejects names nanoka lists as new in the current beta, and every file
    was curated from a seeded row whose `is_beta` was false. What the committed index can show
    without a database is the class: no file is a weapon of an unreleased class."""
    index = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"
                        / "weapon.json").read_text(encoding="utf-8"))
    for nanoka_id in weapon_passives.all_passives():
        row = index.get(nanoka_id)
        assert row is None or not is_unreleased_class(row["type"]), nanoka_id


# ── The resolver ───────────────────────────────────────────────────────────────────────────


def test_homa_on_its_wielder_becomes_per_candidate_conversions():
    kit = _resolve("13501", 1, subject=True)
    stats = [(e.stat, e.value) for e in kit.bonus.effects]
    assert stats == [("hp_pct", 0.2), ("flat_atk_from_hp", 0.008), ("flat_atk_from_hp", 0.01)]
    [low] = kit.bonus.conditions
    assert (low.key, low.default, low.default_reason) == ("low_hp", 0, "situational")
    assert kit.source_id == "weapon:staff_of_homa"
    assert kit.label == "Staff of Homa R1 (Wielder)"


def test_homa_reaches_nobody_else():
    """Every Homa effect is its wielder's own: a teammate's Homa gives the subject nothing."""
    kit = _resolve("13501", 5, subject=False, stats={"base_hp": 15000.0})
    assert kit.bonus.effects == ()
    assert kit.status in {"no_damage_effect", "unmodelled"}


def test_a_team_buff_is_a_number_from_the_wielders_own_stats_with_its_own_hp():
    """Key of Khaj-Nisut's party EM: 0.2% of the wielder's Max HP, which carries the weapon's
    own +20% HP (GO `input.total.hp`)."""
    kit = _resolve("11511", 1, subject=False, stats={"base_hp": 10000.0, "hp_pct": 0.5})
    [team] = kit.bonus.effects
    assert team.stat == "elemental_mastery"
    assert team.value == pytest.approx(0.002 * 10000.0 * (1 + 0.5 + 0.2))


def test_a_subject_buff_the_recipe_cannot_carry_is_withheld_by_name():
    kit = _resolve("11511", 1, subject=True, stats={"base_hp": 10000.0})
    assert [e.stat for e in kit.bonus.effects] == ["hp_pct"]
    withheld = [u.what for u in kit.bonus.unmodelled]
    assert any("Grand Hymn" in w for w in withheld)
    assert kit.status == "partial"


def test_others_never_reach_the_wielder():
    kit = _resolve("14302", 5, subject=True)
    assert kit.bonus.effects == ()
    kit = _resolve("14302", 5, subject=False)
    assert [(e.stat, e.value) for e in kit.bonus.effects] == [("atk_pct", 0.48)]


def test_a_changed_refinement_list_is_withheld_not_misread():
    pin = list(weapon_passives.passive_for("13501").pins[1])  # type: ignore[union-attr]
    kit = _resolve("13501", 1, subject=True, params=[0.3, *pin[1:]])
    assert kit.bonus.effects == ()
    [why] = kit.bonus.unmodelled
    assert "param_list changed since curation" in why.reason


def test_own_element_follows_the_receiver():
    kit = _resolve("11509", 1, subject=True, element="cryo")
    emblem = [e for e in kit.bonus.effects if e.when]
    assert {e.elements for e in emblem} == {("cryo",)}
    every = next(e for e in kit.bonus.effects if not e.when)
    assert set(every.elements or ()) == set(sheets.VISIONS)


def test_a_situational_condition_must_say_why_it_is_off():
    """The sheets' default rule (`DECISIONS.md` §41) holds for weapons by construction: the
    condition type is the sheet's, which refuses a situational one with no usual value."""
    data = json.loads((weapon_passives._DATA / "staff_of_homa.json").read_text())
    data["conditions"][0].pop("usual")
    with pytest.raises(ValueError, match="situational"):
        weapon_passives.WeaponPassive.model_validate(data)


def test_a_reference_past_the_pinned_list_is_refused():
    data = json.loads((weapon_passives._DATA / "the_stringless.json").read_text())
    data["effects"][0]["value"]["param"] = 99
    with pytest.raises(ValueError, match="not pinned"):
        weapon_passives.WeaponPassive.model_validate(data)
