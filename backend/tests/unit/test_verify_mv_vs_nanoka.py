"""Tests for scripts/verify_mv_vs_nanoka.py (F-33 bulk MV/daze diff harness)."""

from __future__ import annotations

from app.models.agent import Attack
from scripts.verify_mv_vs_nanoka import diff_agent, extract_expected_rows


def _fixture_data() -> dict:
    """Small nanoka-shaped fixture: one basic move, two hits."""
    return {
        "skill": {
            "basic": {
                "description": [
                    {
                        "name": "Basic Attack: Test Strike",
                        "param": [
                            {
                                "name": "1 Test Strike DMG",
                                "param": {
                                    "1001": {
                                        "damage_percentage": 16380,
                                        "damage_percentage_growth": 1490,
                                    }
                                },
                            },
                            {
                                "name": "1 Test Strike Daze",
                                "param": {"1001": {"stun_ratio": 5000}},
                            },
                            {
                                "name": "2 Test Strike DMG",
                                "param": {
                                    "1002": {
                                        "damage_percentage": 9000,
                                        "damage_percentage_growth": 800,
                                    }
                                },
                            },
                        ],
                    }
                ]
            },
            "unknown_skill_type": {
                "description": [
                    {
                        "name": "Ignored",
                        "param": [
                            {
                                "name": "DMG",
                                "param": {
                                    "9999": {"damage_percentage": 1, "damage_percentage_growth": 1}
                                },
                            }
                        ],
                    }
                ]
            },
        }
    }


def test_extract_expected_rows_pulls_dmg_only() -> None:
    expected = extract_expected_rows(_fixture_data())

    assert expected == {1001: (16380, 1490), 1002: (9000, 800)}
    assert 9999 not in expected  # unknown skill_key filtered out


def test_extract_expected_rows_dedupes_bookkeeping_ids() -> None:
    """Nanoka lists sibling skill_ids sharing identical values (e.g. Nicole's
    Dodge Counter: 1031205 + 1031206 both = (9120, 830)); only the first-seen
    id should survive, matching the importer's per-param dedup."""
    data = {
        "skill": {
            "dodge": {
                "description": [
                    {
                        "name": "Dodge Counter: Diverted Bombard",
                        "param": [
                            {
                                "name": "DMG Multiplier",
                                "param": {
                                    "1031205": {
                                        "damage_percentage": 9120,
                                        "damage_percentage_growth": 830,
                                    },
                                    "1031206": {
                                        "damage_percentage": 9120,
                                        "damage_percentage_growth": 830,
                                    },
                                },
                            }
                        ],
                    }
                ]
            }
        }
    }

    expected = extract_expected_rows(data)

    assert expected == {1031205: (9120, 830)}
    assert 1031206 not in expected


def test_extract_expected_rows_keeps_both_halves_of_a_potential_pair() -> None:
    """Both halves of a base/Potential param pair are expected (#90).

    Under #85 the base (`potential: [0]`) param was dropped to match an importer
    that stored only the unlocked kit. Since #90 the importer stores both states
    tagged, and this harness runs at `PotentialVariant.BOTH` because it diffs the
    whole `attacks` table — so expecting only the Potential sibling would flag
    every base row in the DB as an unexplained extra."""
    data = {
        "skill": {
            "basic": {
                "description": [
                    {
                        "name": "Basic Attack: Penetrating Shock",
                        "param": [
                            {
                                "name": "3rd-Hit DMG Multiplier",
                                "potential": [0],
                                "param": {
                                    "1381003": {
                                        "damage_percentage": 8010,
                                        "damage_percentage_growth": 6527,
                                    }
                                },
                            },
                            {
                                "name": "3rd-Hit DMG Multiplier",
                                "potential": [
                                    1381100,
                                    1381101,
                                    1381102,
                                    1381103,
                                    1381104,
                                    1381105,
                                ],
                                "param": {
                                    "1381022": {
                                        "damage_percentage": 10010,
                                        "damage_percentage_growth": 6999,
                                    }
                                },
                            },
                        ],
                    }
                ]
            }
        }
    }

    expected = extract_expected_rows(data)

    assert expected == {1381003: (8010, 6527), 1381022: (10010, 6999)}


def test_diff_agent_matches_clean() -> None:
    expected = {1001: (16380, 1490), 1002: (9000, 800)}
    attacks = [
        Attack(hakushin_skill_id=1001, damage_base=16380, damage_growth=1490),
        Attack(hakushin_skill_id=1002, damage_base=9000, damage_growth=800),
    ]

    errors = diff_agent("Yanagi", expected, attacks)

    assert errors == []


def test_diff_agent_reports_mismatch() -> None:
    expected = {1001: (16380, 1490)}
    attacks = [Attack(hakushin_skill_id=1001, damage_base=15000, damage_growth=1490)]

    errors = diff_agent("Yanagi", expected, attacks)

    assert len(errors) == 1
    assert "MISMATCH" in errors[0]
    assert "15000" in errors[0]
    assert "16380" in errors[0]


def test_diff_agent_reports_missing_from_db() -> None:
    expected = {1001: (16380, 1490)}
    attacks: list[Attack] = []

    errors = diff_agent("Yanagi", expected, attacks)

    assert len(errors) == 1
    assert "missing from DB" in errors[0]


def test_diff_agent_accepts_curated_variant_row_sharing_skill_id() -> None:
    """Ye Shunguang's Soaring Light: one hakushin_skill_id, two DB rows — a
    nanoka-sourced "6 swords" row and a synthetic "1 sword" curation row
    (skill_overrides). The nanoka value only needs to match ONE of them."""
    expected = {1431018: (105800, 9620)}
    attacks = [
        Attack(hakushin_skill_id=1431018, damage_base=105800, damage_growth=9620),
        Attack(hakushin_skill_id=1431018, damage_base=17633, damage_growth=1603),
    ]

    errors = diff_agent("Ye Shunguang", expected, attacks)

    assert errors == []


def test_diff_agent_reports_extra_in_db() -> None:
    expected: dict[int, tuple[int, int]] = {}
    attacks = [Attack(hakushin_skill_id=1001, damage_base=16380, damage_growth=1490)]

    errors = diff_agent("Yanagi", expected, attacks)

    assert len(errors) == 1
    assert "not found in fresh nanoka pull" in errors[0]


def test_script_module_imports() -> None:
    """Smoke test: the script imports cleanly (no top-level side effects)."""
    import scripts.verify_mv_vs_nanoka as mod

    assert callable(mod.main)
