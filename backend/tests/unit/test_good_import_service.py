"""What the import refuses before it writes anything.

`test_good_importer.py` covers the *parser* — malformed records, unsupported envelopes. This
covers the checks the **service** makes on records that parsed cleanly, where the value is
well-formed and still cannot be true.
"""

from __future__ import annotations

from app.data.importers.good_importer import ParsedArtifact
from app.models.enums import ArtifactSlot, Rarity
from app.services.good_import_service import _impossible_reason, _impossible_substats

# ── values the game could not have produced ──────────────────────────────────


def _artifact(substats: list[dict], *, rarity: Rarity = Rarity.FIVE_STAR, level: int = 20):
    return ParsedArtifact(
        slot=ArtifactSlot.FLOWER, rarity=rarity, level=level,
        main_stat="FIGHT_PROP_HP", substats=tuple(substats), set_key="GladiatorsFinale",
    )


def test_a_value_no_combination_reaches_is_refused() -> None:
    """**Owner request, and a real piece.**

    One artifact in a 2,370-piece Irminsul export carries a CRIT DMG substat of **25.7%**,
    which no combination of the tiers reaches at any legal roll count — the nearest four-roll
    sums are 25.6 and 26.4. It is present verbatim in the GOOD file, `elixerCrafted` is false,
    and no game mechanic explains it, so it is a scanner error.

    Refused rather than imported, because every number computed from the piece would inherit
    the fault.
    """
    found = _impossible_substats(
        _artifact([{"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.257}]),
    )

    assert found == [("FIGHT_PROP_CRITICAL_HURT", 0.257)]


def test_an_ambiguous_line_is_not_an_impossible_one() -> None:
    """**The distinction the whole check rests on.**

    27.2% CRIT DMG is reachable as four rolls or five, so the *piece-level* solve decides it.
    That is legitimate and common — refusing it would throw away a large share of a real
    inventory. Only a value no count can produce is refused.
    """
    found = _impossible_substats(
        _artifact([{"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.272}]),
    )

    assert found == []


def test_a_value_on_a_rounding_boundary_is_not_impossible() -> None:
    """5.3% ATK% is a single legitimate roll whose exact tier is 5.2499998%.

    Before the display rounding was fixed it matched nothing — so a check like this one, added
    then, would have refused a tenth of every export. The order matters: get the rounding right
    first, then refuse what is left.
    """
    found = _impossible_substats(
        _artifact([{"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.053}], level=0),
    )

    assert found == []


def test_a_malformed_substat_is_left_to_the_parser() -> None:
    """A missing stat or a non-numeric value is a *parse* failure with its own message. Judging
    it here would report "no combination of rolls can produce it" about a value that is not a
    number, which is true and useless."""
    found = _impossible_substats(
        _artifact([{"stat": "", "value": None}, {"stat": "FIGHT_PROP_HP", "value": "x"}]),
    )

    assert found == []


def test_the_reason_names_the_values_so_they_can_be_found_in_game() -> None:
    reason = _impossible_reason([("FIGHT_PROP_CRITICAL_HURT", 0.257)])

    assert "FIGHT_PROP_CRITICAL_HURT=0.257" in reason
    assert "Re-scan" in reason
