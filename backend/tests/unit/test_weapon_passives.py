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
        # A passive with no damage effect (Favonius's energy) has nothing a fixture could check.
        assert passive.verified_by or not passive.effects, f"{passive.slug} ships unverified"
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
    # Said once, as no damage effect on this receiver, never as "applied" (found driving it).
    assert kit.status == "no_damage_effect"
    [said] = kit.bonus.unmodelled
    assert "Wielder's own" in said.reason


def test_a_team_buff_is_a_number_from_the_wielders_own_stats_with_its_own_hp():
    """Key of Khaj-Nisut's party EM: 0.2% of the wielder's Max HP, which carries the weapon's
    own +20% HP (GO `input.total.hp`)."""
    kit = _resolve("11511", 1, subject=False, stats={"base_hp": 10000.0, "hp_pct": 0.5})
    [team] = kit.bonus.effects
    assert team.stat == "elemental_mastery"
    assert team.value == pytest.approx(0.002 * 10000.0 * (1 + 0.5 + 0.2))


def test_the_wielders_em_from_hp_is_a_per_candidate_conversion():
    """Owner approval 2026-11-14 (§45): Key of Khaj-Nisut on its wielder converts their own Max
    HP into EM per candidate, both the stacked self part and the party share at three stacks."""
    kit = _resolve("11511", 1, subject=True, stats={"base_hp": 10000.0})
    assert [(e.stat, e.value, e.per) for e in kit.bonus.effects] == [
        ("hp_pct", 0.2, None), ("em_from_hp", 0.0012, "stacks"), ("em_from_hp", 0.002, None)]
    assert kit.bonus.effects[2].non_stack == "key"
    assert kit.status == "modelled"


@pytest.mark.parametrize(("nanoka_id", "stat", "value", "cap", "threshold"), [
    # Engulfing Lightning R1: 28% of ER above 100%, at most 80% (GO EngulfingLightning:18-31).
    ("13509", "atk_pct_from_er", 0.28, 0.8, 1.0),
    # Makhaira Aquamarine / Wandering Evenstar R1: 24% of the wielder's EM as ATK.
    ("12415", "flat_atk_from_em", 0.24, None, None),
    ("14416", "flat_atk_from_em", 0.24, None, None),
])
def test_the_withheld_wielder_conversions_are_carried(nanoka_id, stat, value, cap, threshold):
    kit = _resolve(nanoka_id, 1, subject=True)
    [conversion] = [e for e in kit.bonus.effects if e.stat == stat]
    assert conversion.value == pytest.approx(value)
    assert conversion.cap == (None if cap is None else pytest.approx(cap))
    assert conversion.threshold == threshold
    assert not [u for u in kit.bonus.unmodelled if "withheld" in u.reason]


def test_peak_patrol_songs_stat_cap_becomes_the_conversions_cap():
    """`k × min(DEF, 3200) / 1000` is `min(k × DEF / 1000, k × 3.2)`."""
    kit = _resolve("11516", 1, subject=True)
    [party] = [e for e in kit.bonus.effects if e.stat == "dmg_bonus_from_def"]
    assert party.value == pytest.approx(0.08 / 1000)
    assert party.cap == pytest.approx(0.08 * 3.2)
    assert party.non_stack == "patrol"


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


def test_a_condition_no_effect_reads_is_refused():
    """Found curating Thrilling Tales: its effect had lost its `when`, so its toggle switched
    nothing and the buff was always on. The schema now refuses the shape."""
    path = weapon_passives._DATA / "thrilling_tales_of_dragon_slayers.json"
    data = json.loads(path.read_text())
    data["effects"][0].pop("when")
    with pytest.raises(ValueError, match="no effect reads this condition"):
        weapon_passives.WeaponPassive.model_validate(data)


# ── Non-stacking families (owner approval 2026-11-14, `DECISIONS.md` §45) ──────────────────


def test_non_stacking_families_come_from_gos_sheets():
    """Every weapon whose GO sheet calls `nonStackBuff` names it on its effects, and every name
    is one GO declares for that sheet: the Millennial Movement family is GO's `millenial*`."""
    declared = weapon_passives.go_non_stack()
    families: dict[str, set[str]] = {}
    for passive in weapon_passives.all_passives().values():
        go_key = weapon_passives.go_sheet_key(passive.go)
        named = {e.non_stack for e in passive.effects if e.non_stack}
        if go_key in declared:
            assert named, passive.slug
        else:
            assert not named, passive.slug
        for name in named:
            families.setdefault(name, set()).add(passive.weapon)
    millennial = set().union(*(w for n, w in families.items() if n.startswith("millenial")))
    assert millennial == {"Elegy for the End", "Freedom-Sworn", "Song of Broken Pines"}
    assert families["leafCon"] == {"Forest Regalia", "Sapwood Blade"}


def test_every_non_stacking_family_is_one_stat():
    """The precondition of "the stronger applies" (owner ruling 2026-11-15, `DECISIONS.md` §46):
    GO's families are per name, and each name grants one stat across every weapon holding it, so
    "stronger" is the larger amount of that stat for the receiving row (`applySources`) — never a
    comparison of ATK% against EM. A family that grew a second stat would need a score-based
    comparison instead, and this fails first."""
    stats: dict[str, set[str]] = {}
    for passive in weapon_passives.all_passives().values():
        for effect in passive.effects:
            if effect.non_stack:
                stats.setdefault(effect.non_stack, set()).add(effect.stat)
    assert stats, "no non-stacking family at all"
    assert {n: s for n, s in stats.items() if len(s) != 1} == {}
    # The Millennial Movement series as GO splits it: three names, three stats.
    assert stats["millenialatk"] == {"atk_pct"}
    assert stats["millenialelemas"] == {"elemental_mastery"}


def test_a_non_stack_name_go_does_not_declare_is_refused():
    passive = weapon_passives.passive_for("15503")
    assert passive is not None
    data = passive.model_dump(by_alias=True, mode="json")
    data["effects"][1]["non_stack"] = "millenialcritrate"
    with pytest.raises(ValueError, match="declares no non-stacking buff"):
        weapon_passives.WeaponPassive.model_validate(data)


def test_a_resolved_source_carries_its_wielders_go_key():
    passive = weapon_passives.passive_for("15503")
    assert passive is not None
    wielder = weapon_passives.Wielder("Venti", 1, list(passive.pins[1]), _stated_registry({}),
                                      stack_rank="Venti")
    kit = weapon_passives.resolve(passive, wielder, wielder_is_subject=False,
                                  receiver_element="pyro", team_elements=["pyro", "anemo"])
    assert kit.stack_rank == "Venti"
    assert {e.non_stack for e in kit.bonus.effects} == {"millenialelemas", "millenialatk"}


# ── Weapon procs (owner approval 2026-11-14, `DECISIONS.md` §45) ───────────────────────────


@pytest.mark.parametrize(("nanoka_id", "refinement", "multiplier", "layer"), [
    ("11501", 1, 2.0, "premod"),   # Aquila Favonia: GO atkDealt [2 … 3.2]
    ("11501", 5, 3.2, "premod"),
    ("15501", 1, 1.25, "total"),   # Skyward Harp: GO percent(1.25)
    ("13502", 5, 1.0, "total"),    # Skyward Spine: GO dmgPerc [0.4 … 1]
])
def test_a_wielders_proc_is_resolved_at_its_refinement(nanoka_id, refinement, multiplier, layer):
    kit = _resolve(nanoka_id, refinement, subject=True)
    [proc] = kit.procs
    assert proc.multiplier == pytest.approx(multiplier)
    assert (proc.element, proc.scaling, proc.stat_layer) == ("physical", "atk", layer)


def test_a_teammates_proc_is_named_not_a_row():
    kit = _resolve("11501", 1, subject=False)
    assert kit.procs == ()
    assert any("own hit" in u.reason for u in kit.bonus.unmodelled)


def test_a_passive_whose_damage_is_its_proc_is_modelled():
    kit = _resolve("13403", 1, subject=True)
    assert kit.bonus.effects == ()
    assert [p.key for p in kit.procs] == ["orb_hit"]
    assert kit.status == "modelled"
