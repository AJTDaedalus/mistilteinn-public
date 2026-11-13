"""Math-fallback P1, task 7 — every conditional set tier has a condition, a default, a reason.

`docs/RESEARCH_math_fallback_inventory.md` §3.3 counted **60 conditional four-pieces and 9
conditional two-pieces** in the seeded catalogue, all scoring zero in the single-hit chain.
These tests hold the curation (`app/data/formula/set_effects.json`) to three things:

- **coverage** — every set the committed nanoka index has gets its 4-piece curated, plus the
  nine 2-pieces and the five 1-piece Prayers;
- **numbers from our params** — each value is an index into the pinned `param_list`, and a
  list that changed is refused as stale rather than read by an index that may now mean
  something else;
- **honesty** — what is not applied is named with a reason, never silently zero.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.formula.genshin import set_effects
from app.formula.genshin.formula_effects import NO_DAMAGE

INDEX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "artifact.json"

#: Static 2-piece props a `times_tier_prop` value reads. Crimson Witch's is its Pyro 15%
#: (`CrimsonWitchOfFlames/index.tsx:22-27` in GO; the seeded add_props carry the same).
STATIC_TWO_PIECE = {
    15006: [{"prop_type": "FIGHT_PROP_FIRE_ADD_HURT", "value": 0.15}],
}

#: The nine conditional 2-pieces §3.3 counted.
TWO_PIECES = {10004, 10006, 10008, 15007, 15031, 15032, 15037, 15038, 15039}


def _resolve_pin(tier: set_effects.CuratedTier) -> set_effects.ResolvedTier:
    rows = [set_effects.AffixRow(pieces=tier.pieces, param_list=tier.params, add_props=())]
    if tier.set_id in STATIC_TWO_PIECE:
        rows.append(set_effects.AffixRow(
            pieces=2, param_list=[], add_props=STATIC_TWO_PIECE[tier.set_id],
        ))
    resolved = set_effects.resolve_set(tier.set_id, rows)
    assert len(resolved) == 1, tier.set_id
    return resolved[0]


@pytest.fixture(scope="module")
def resolved() -> dict[tuple[int, int], set_effects.ResolvedTier]:
    return {(t.set_id, t.pieces): _resolve_pin(t) for t in set_effects.curated().tiers}


def test_the_curation_covers_every_four_piece_in_the_committed_index():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    with_four = {int(sid) for sid, entry in index.items() if len(entry["set"]) >= 2}
    curated = Counter(t.pieces for t in set_effects.curated().tiers)
    four = {t.set_id for t in set_effects.curated().tiers if t.pieces == 4}
    assert with_four <= four
    assert curated == {4: 60, 2: 9, 1: 5}
    assert {t.set_id for t in set_effects.curated().tiers if t.pieces == 2} == TWO_PIECES


def test_every_pinned_tier_resolves_without_a_problem(resolved):
    problems = {k: t.problem for k, t in resolved.items() if t.problem}
    assert problems == {}


def test_the_status_counts_are_what_the_report_says(resolved):
    counts = Counter((k[1], t.status) for k, t in resolved.items())
    assert counts == {
        (4, "modelled"): 30, (4, "partial"): 16, (4, "unmodelled"): 5,
        (4, "no_damage_effect"): 9,
        (2, "modelled"): 7, (2, "no_damage_effect"): 2,
        (1, "no_damage_effect"): 5,
    }


def test_unmodelled_parts_always_carry_a_reason(resolved):
    for key, tier in resolved.items():
        for part in tier.bonus.unmodelled:
            assert part.what, key
            assert part.reason, key
        if tier.status == "unmodelled":
            # Not silently zero: an unmodelled tier names what is missing and why.
            assert tier.bonus.unmodelled, key
            assert not any(u.reason.startswith(NO_DAMAGE) for u in tier.bonus.unmodelled), key


def test_every_tier_cites_a_go_sheet_or_says_why_there_is_none():
    for tier in set_effects.curated().tiers:
        assert "index.tsx" in tier.go or tier.go.startswith("(none"), tier.set_id
        if tier.effects:
            assert "index.tsx:" in tier.go, f"{tier.set_id}: a modelled tier cites lines"


def _effects(resolved, set_id, pieces):
    return resolved[(set_id, pieces)].bonus.effects


def test_crimson_witch_stack_is_half_its_two_piece(resolved):
    # GO `CrimsonWitchOfFlames/index.tsx:43`: percent((0.15 * i) / 2) per stack — here
    # param[3] (0.5) times the 2-piece's own 15%, three stacks at most.
    witch = resolved[(15006, 4)].bonus
    stack = next(e for e in witch.effects if e.stat == "dmg_bonus")
    assert stack.value == pytest.approx(0.075)
    assert stack.per == "stacks"
    assert witch.conditions[0].max == 3
    assert witch.conditions[0].default == 3
    reactions = [(e.reactions, e.value) for e in witch.effects if e.stat == "reaction_bonus"]
    assert reactions == [
        (("vaporize", "reverse_vaporize"), 0.15), (("melt", "reverse_melt"), 0.15),
    ]


def test_value_forms(resolved):
    # Vourukasha's per-stack 10% x 80% = 8%, GO's `stack * 0.08` (`:36`).
    assert _effects(resolved, 15030, 4)[1].value == pytest.approx(0.08)
    # Nighttime Whispers' crystallize increase 20% x 150% = 30%, GO `0.2 * 1.5` (`:28`).
    assert _effects(resolved, 15034, 4)[1].value == pytest.approx(0.3)
    # A shred is stated positive in the list and applied negative.
    assert _effects(resolved, 15002, 4)[0].value == pytest.approx(-0.4)
    assert _effects(resolved, 15025, 4)[0].value == pytest.approx(-0.3)
    # Nymph's Dream steps are not linear: 7/16/25% ATK, GO `atk_arr` (`:27`).
    nymph = _effects(resolved, 15029, 4)[0]
    assert nymph.by_stack == pytest.approx((0.07, 0.16, 0.25))
    # Emblem: 25% of ER, capped at 75%.
    emblem = _effects(resolved, 15020, 4)[0]
    assert (emblem.value, emblem.cap) == (0.25, 0.75)


def test_a_changed_param_list_is_stale_not_reread():
    witch = next(t for t in set_effects.curated().tiers if (t.set_id, t.pieces) == (15006, 4))
    changed = list(witch.params)
    changed[3] = 0.6
    rows = [
        set_effects.AffixRow(pieces=4, param_list=changed, add_props=()),
        set_effects.AffixRow(pieces=2, param_list=[], add_props=STATIC_TWO_PIECE[15006]),
    ]
    (tier,) = set_effects.resolve_set(15006, rows)
    assert tier.status == "stale"
    assert tier.bonus.effects == ()
    assert "param_list changed" in (tier.problem or "")


def test_a_conditional_tier_with_no_curation_is_named():
    rows = [set_effects.AffixRow(pieces=4, param_list=[0.1], add_props=())]
    (tier,) = set_effects.resolve_set(99999, rows)
    assert tier.status == "uncurated"
    assert tier.problem


def test_a_static_tier_is_not_repeated():
    # The kernel applies static props from `bonus_stats`; resolving them here would count
    # them twice.
    rows = [set_effects.AffixRow(pieces=2, param_list=[0.15],
                                 add_props=STATIC_TWO_PIECE[15006])]
    assert set_effects.resolve_set(15006, rows) == []


def test_weapon_gated_sets_name_the_classes(resolved):
    gladiator = _effects(resolved, 15001, 4)[0]
    assert set(gladiator.weapon_types or ()) == {
        "WEAPON_SWORD_ONE_HAND", "WEAPON_CLAYMORE", "WEAPON_POLE",
    }
    troupe = _effects(resolved, 15003, 4)[0]
    assert set(troupe.weapon_types or ()) == {"WEAPON_CATALYST", "WEAPON_BOW"}


def test_defaults_follow_the_stated_rule(resolved):
    # `self` → on at its maximum; `situational` → off. The model refuses anything else, so
    # this counts what the rule produced.
    reasons = Counter(
        c.default_reason for t in resolved.values() for c in t.bonus.conditions
    )
    assert reasons["self"] >= 15
    assert reasons["situational"] >= 30
