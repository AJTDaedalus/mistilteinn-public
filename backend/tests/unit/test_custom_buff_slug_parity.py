"""The custom-buff slug rule, pinned across the language boundary (#64, Task B8).

`disabled_buffs` entries for stage buffs are composed **client-side** — the toggle lives
in the stage-buff editor, which has to name a buff without a round trip — and consumed
here by `synthesize_custom_buffs`. So the rule has two implementations:
`app/services/modifiers.py::slugify` and `frontend/src/app/shared/custom-buff-id.ts`.

Duplication across a language boundary cannot be removed, only pinned. This table is
asserted verbatim in `custom-buff-id.spec.ts`; if the two ever disagree, switching a
stage buff off silently stops working, which is the one thing a toggle may not do — and
it fails silently in both directions, since each side is individually self-consistent.

**Keep the two tables identical.** Adding a case here without adding it there (or vice
versa) leaves the boundary untested for exactly the input someone thought was worth
testing.
"""

from __future__ import annotations

import pytest

from app.services.modifiers import custom_buff_label, slugify

# (label, expected slug) — mirrored in custom-buff-id.spec.ts's PARITY_CASES.
PARITY_CASES = [
    ("DA Stage 3: Ice DMG", "da_stage_3_ice_dmg"),
    ("DA stage 3 — ice dmg", "da_stage_3_ice_dmg"),
    ("Stage 3 ATK", "stage_3_atk"),
    ("stage-3-atk", "stage_3_atk"),
    ("  leading and trailing  ", "leading_and_trailing"),
    ("🔥 3", "3"),
    ("Shiyu 2.1 Node 2", "shiyu_2_1_node_2"),
]

UNADDRESSABLE = ["!!!", "🔥", "   ", "---"]


@pytest.mark.parametrize(("label", "expected"), PARITY_CASES)
def test_slug_matches_the_frontend_table(label: str, expected: str) -> None:
    assert slugify(label) == expected


@pytest.mark.parametrize(("label", "expected"), PARITY_CASES)
def test_custom_buff_label_is_the_prefixed_slug(label: str, expected: str) -> None:
    assert custom_buff_label(label) == f"custom:{expected}"


@pytest.mark.parametrize("label", UNADDRESSABLE)
def test_the_frontends_unaddressable_set_slugifies_to_nothing_here_too(label: str) -> None:
    """The editor greys these out locally; the server must agree they are unusable, or
    the UI would block something the API accepts (or worse, the reverse)."""
    assert slugify(label) == ""


def test_runs_of_punctuation_collapse_rather_than_emitting_empty_segments() -> None:
    assert slugify("a  ---  b") == "a_b"
