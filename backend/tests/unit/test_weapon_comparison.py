"""D.5 — comparing weapons, and being honest about what the comparison cannot see.

The dangerous thing here is not an arithmetic mistake. It is a **precise-looking ordering**
that is wrong because the modelled part of a weapon is not the interesting part of it. Most
of these tests are about that.
"""

from __future__ import annotations

import pytest

from app.formula.genshin.explain import Contribution
from app.formula.genshin.tags import SRC_WEAPON
from app.services.weapon_comparison import WeaponCandidate, compare_weapons


def _weapon(
    weapon_id: str, name: str, base_atk: float, *, passive: tuple[str, str] | None = None,
) -> WeaponCandidate:
    return WeaponCandidate(
        weapon_id=weapon_id,
        name=name,
        base_contributions=(
            Contribution(quantity="base_atk", value=800.0, source="character", note="Ayaka"),
            Contribution(quantity="base_atk", value=base_atk, source=SRC_WEAPON, note=name),
            Contribution(quantity="crit_rate", value=1.0, source="character", note="pinned"),
        ),
        unmodelled_passive=passive,
    )


_ARTIFACTS = ()


def _hit():
    from app.formula.genshin.damage import Hit

    return Hit(multiplier=2.0, channel="cryo", scope="burst", scaling_stat="atk")


def _enemy():
    """All eight channels, because `Enemy` refuses a partial profile — treating a missing
    channel as 0% RES would overstate every hit against it by about 10%."""
    from app.formula.genshin import tags
    from app.services.damage_calculator import Enemy

    return Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))


def _compare(candidates, equipped="w1"):
    return compare_weapons(
        candidates, equipped, _ARTIFACTS, _hit(), _enemy(), character_level=90,
    )


# ── The ranking ───────────────────────────────────────────────────────────────


def test_a_stronger_weapon_ranks_higher_and_reports_its_gain():
    result = _compare([_weapon("w1", "Dull Blade", 100.0), _weapon("w2", "Mistsplitter", 674.0)])

    assert [w.weapon_id for w in result.weapons] == ["w2", "w1"]
    assert result.weapons[0].delta > 0
    assert result.weapons[1].delta == 0.0, "the equipped weapon is its own baseline"


def test_the_equipped_weapon_has_no_differences_against_itself():
    result = _compare([_weapon("w1", "Dull Blade", 100.0), _weapon("w2", "Other", 200.0)])
    equipped = next(w for w in result.weapons if w.weapon_id == "w1")
    assert equipped.differences == ()


def test_a_candidate_explains_what_it_changed_not_just_that_it_won():
    """DESIGN §3.5: "this weapon wins because …", not merely "this build scores higher"."""
    result = _compare([_weapon("w1", "Dull Blade", 100.0), _weapon("w2", "Mistsplitter", 674.0)])
    winner = result.weapons[0]

    atk = next(d for d in winner.differences if d.quantity == "base_atk")
    assert atk.delta == pytest.approx(574.0)
    assert any(p.note == "Mistsplitter" for p in atk.gained)
    assert any(p.note == "Dull Blade" for p in atk.lost)


def test_the_comparison_needs_the_equipped_weapon_among_the_candidates():
    """Otherwise the baseline is an arbitrary candidate and every delta means nothing."""
    with pytest.raises(ValueError, match="not among the candidates"):
        _compare([_weapon("w2", "Mistsplitter", 674.0)], equipped="w1")


def test_every_candidate_is_scored_against_the_same_fixed_build():
    """A difference in the answer must be a difference the weapon made, not the setup."""
    result = _compare([
        _weapon("w1", "A", 300.0), _weapon("w2", "B", 300.0), _weapon("w3", "C", 300.0),
    ])
    assert len({round(w.damage, 9) for w in result.weapons}) == 1


# ── What it does not know, and says so ────────────────────────────────────────


def test_a_weapon_with_a_stored_but_unapplied_passive_is_named():
    """`weapon_refinements` holds the text; nothing reads it yet (Chunk H)."""
    result = _compare([
        _weapon("w1", "Dull Blade", 100.0),
        _weapon(
            "w2", "Mistsplitter", 674.0,
            passive=("Mistsplitter's Edge", "Elemental DMG +12%"),
        ),
    ])

    assert not result.is_complete
    assert len(result.unmodelled_passives) == 1
    assert result.unmodelled_passives[0].passive_name == "Mistsplitter's Edge"
    assert result.unmodelled_passives[0].text == "Elemental DMG +12%"


def test_completeness_is_all_or_nothing():
    """One unapplied passive is enough to reorder the list, so "mostly complete" would be a
    comfort with nothing behind it."""
    result = _compare([
        _weapon("w1", "A", 300.0),
        _weapon("w2", "B", 300.0),
        _weapon("w3", "C", 300.0, passive=("Something", "does something")),
    ])
    assert not result.is_complete


def test_a_complete_comparison_says_so_and_still_states_the_fixed_artifacts_caveat():
    """Even with every effect modelled, "best in this build" is not "best"."""
    result = _compare([_weapon("w1", "A", 300.0), _weapon("w2", "B", 400.0)])
    assert result.is_complete
    assert "held fixed" in result.caveat()
    assert "with its own best artifacts" in result.caveat()


def test_the_caveat_names_the_weapons_whose_passives_are_missing():
    """A number beside an unnamed doubt is a number people act on anyway."""
    result = _compare([
        _weapon("w1", "Dull Blade", 100.0),
        _weapon("w2", "Mistsplitter", 674.0, passive=("Mistsplitter's Edge", "…")),
    ])
    caveat = result.caveat()
    assert "Mistsplitter" in caveat
    assert "Mistsplitter's Edge" in caveat
    assert "can be wrong" in caveat, "the ordering itself, not merely its precision"


def test_a_weapon_with_no_passive_contributes_no_caveat():
    """Empty is a real answer: that weapon genuinely is fully modelled."""
    result = _compare([_weapon("w1", "A", 300.0), _weapon("w2", "B", 400.0)])
    assert result.unmodelled_passives == ()
