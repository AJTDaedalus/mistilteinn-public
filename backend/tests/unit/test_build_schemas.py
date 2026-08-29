"""What `BuildRead` publishes beyond its columns.

A build is drawn on three surfaces — the saved list, the team slot picker and the optimize
header — and anything they all need is computed here rather than formatted three times.
"""

from __future__ import annotations

from app.schemas.build import BuildRead

# ── how a build names its weapon ─────────────────────────────────────────────


def _build(**over: object) -> BuildRead:
    base: dict[str, object] = {
        "id": "b1", "character_id": "c1", "weapon_id": "w1",
        "character_level": 90, "ascension_phase": 6, "weapon_level": 90,
        "refinement": 1, "constellation_level": 0,
        "weapon": {
            "id": "w1", "nanoka_id": 11101, "name": "Freedom-Sworn",
            "weapon_type": "WEAPON_SWORD_ONE_HAND", "rarity": "five_star",
        },
    }
    return BuildRead.model_validate(base | over)


def test_a_weapon_is_named_with_its_refinement_and_level() -> None:
    """Published once rather than formatted by each client.

    Three surfaces name a build's weapon — the saved list, the team slot picker and the
    optimize header — and all three printed the bare name, so a character showed `C6` while
    the weapon beside it said nothing about how far it had been taken.
    """
    assert _build().weapon_display == "Freedom-Sworn · R1 · Lv90"


def test_refinement_comes_before_level() -> None:
    """A Lv90 R1 and a Lv90 R5 are different weapons in practice, and the R is the scarcer
    fact — so it is the one a reader scanning a column meets first."""
    shown = _build(refinement=5, weapon_level=70).weapon_display

    assert shown is not None
    assert shown.index("R5") < shown.index("Lv70")


def test_a_build_with_no_weapon_names_none_rather_than_a_level() -> None:
    """`weapon_id` is nullable by design (OQ-T3). A caller should render "no weapon", not a
    refinement for a weapon that is not there."""
    assert _build(weapon=None, weapon_id=None).weapon_display is None
