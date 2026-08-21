"""Task 23 — mechanism/policy purity: `app/services/lumiflux.py` must contain
no Remielle-specific (or any other agent-specific) constant. Every Lumiflux
coefficient is authored in that agent's kit JSON and loaded into a
`LumifluxSpec` at snapshot-build time; a second Lumiflux agent is a JSON
file, not an engine change (DESIGN §3).
"""

from __future__ import annotations

import re
from pathlib import Path

LUMIFLUX_PY = Path(__file__).resolve().parents[2] / "app" / "services" / "lumiflux.py"

# Remielle's own coefficients (DESIGN §6.1/§7.2/§7.3, docs/LOG_remielle.md
# Tasks 18/20): 0.02%/AP Refringe ratio, the 4000 ATK kink + 1600 flat cap
# from the AA squad-ATK rows, Phase Flow's 5.0s tick cadence, and the four
# Luminize trigger multipliers (16000/32000/33600/32000, in bp) from
# `moves/agents/remielle.json`. None of these may appear as a literal in the
# mechanism module -- they belong in her kit/move JSON only.
_MAGIC_NUMBER_LITERALS = ["4000", "1600", "16000", "32000", "33600"]


def _source() -> str:
    return LUMIFLUX_PY.read_text()


def test_lumiflux_module_exists():
    assert LUMIFLUX_PY.is_file()


def test_no_case_insensitive_remielle_mention():
    source = _source()
    assert not re.search(r"remielle", source, re.IGNORECASE), (
        "lumiflux.py names an agent by name -- mechanism/policy split violation"
    )


def test_no_other_agent_name_mentions_either():
    """Purity cuts both ways: no *other* Lumiflux-specialty agent's name is
    hardcoded either, in case a second agent lands on this element first."""
    source = _source()
    for name in ("astra", "yao", "burnice", "grace", "piper"):
        assert not re.search(rf"\b{name}\b", source, re.IGNORECASE), (
            f"lumiflux.py mentions agent name {name!r}"
        )


def test_no_remielle_magic_number_literals():
    source = _source()
    for literal in _MAGIC_NUMBER_LITERALS:
        assert literal not in source, (
            f"lumiflux.py hardcodes {literal!r}, one of Remielle's own kit "
            "coefficients -- should be authored in her kit JSON and carried "
            "on a LumifluxSpec instance instead"
        )


def test_no_ap_ratio_literal_as_bare_2():
    """`refringe_ap_ratio_bp` (0.02%/AP == 2 bp/AP) is the one Remielle
    coefficient too short to safely substring-match (a bare "2" collides
    with legitimate module content, e.g. tuple indices) -- assert instead
    that the field carries no default value at all, which is what actually
    prevents a de facto hardcode (see the dataclass's own docstring)."""
    source = _source()
    assert "refringe_ap_ratio_bp: int\n" in source, (
        "refringe_ap_ratio_bp must remain a bare, default-less dataclass "
        "field -- a default value here is a de facto hardcoded constant "
        "for whichever agent gets authored first (DESIGN §3)"
    )
    assert not re.search(r"refringe_ap_ratio_bp\s*[:=]\s*2\b", source)


def test_purity_regression_is_caught_if_a_coefficient_is_pasted_in():
    """Sanity-check the test itself: pasting one of Remielle's real magic
    numbers into the module text must fail the scan, proving these assertions
    are not vacuously true."""
    source = _source()
    poisoned = source.replace(
        "phase_flow_tick_s: float",
        "phase_flow_tick_s: float  # Remielle ticks every 5.0s at 4000 ATK, cap 1600",
    )
    assert re.search(r"remielle", poisoned, re.IGNORECASE)
    for literal in ("4000", "1600"):
        assert literal in poisoned
