"""Refused damage rows are published beside the offered hits, not dropped (owner, 2026-11-13).

`talent_scaling` refuses some rows by name — Venti's Windsunder Arrow is a multiple of his
Normal Attack DMG, which the closed-form chain has no term for. They used to vanish from the
pickers, which read as a broken picker. `refused_hits` publishes them with the reason, from
the same rows at the same levels `available_hits` reads.
"""

from __future__ import annotations

from app.models.enums import TalentType
from app.services.talent_hits import available_hits, refused_hits
from tests.unit.test_talent_hit_resolution import _Character, _Scaling, _Talent

#: Venti's normal-attack row at level 9, verbatim from the seeded catalogue (nanoka 7.2.51),
#: trimmed to the rows that matter here.
VENTI_NA = [
    "1-Hit DMG|{param1:F1P}+{param1:F1P}",
    "Aimed Shot|{param2:F1P}",
    "Windsunder Arrow DMG|{param3:F1P} Normal Attack DMG",
]


def _venti(level: int = 9) -> _Character:
    return _Character(
        [_Talent(TalentType.NORMAL_ATTACK, [_Scaling(level, VENTI_NA, [0.38, 0.79, 0.65])])],
        name="Venti",
    )


def test_windsunder_arrow_is_refused_with_the_parsers_reason():
    refused = refused_hits(_venti(), {"normal_attack": 9})

    assert [(r.talent, r.label, r.spec) for r in refused] == [
        (
            TalentType.NORMAL_ATTACK, "Windsunder Arrow DMG",
            "{param3:F1P} Normal Attack DMG",
        ),
    ]
    assert "Normal Attack DMG" in refused[0].reason
    # The row is already a field; the reason is the sentence, not the row repeated.
    assert not refused[0].reason.startswith("'Windsunder")


def test_a_refused_row_is_never_also_offered():
    offered = {h.label for h in available_hits(_venti(), {"normal_attack": 9})}

    assert "Windsunder Arrow DMG" not in offered
    assert {"1-Hit DMG", "Aimed Shot"} <= offered


def test_a_talent_with_no_level_contributes_no_refusals():
    """Its absence is `available_hits`' to explain — it is not a refusal of a hit."""
    assert refused_hits(_venti(), {}) == []


def test_a_kit_with_nothing_refused_publishes_nothing():
    clean = _Character([
        _Talent(TalentType.ELEMENTAL_BURST, [_Scaling(1, ["Cutting DMG|{param1:P}"], [1.1])]),
    ])
    assert refused_hits(clean, {"elemental_burst": 1}) == []
