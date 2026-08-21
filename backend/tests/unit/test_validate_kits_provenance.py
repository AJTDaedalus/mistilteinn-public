"""Task 22 — provenance tags + the gated guide(vX.Y.Z)/db: escape for agents
absent from zo_constants.json (DESIGN_remielle.md §9.2, D-KV21-style).
"""

from __future__ import annotations

from pathlib import Path

from scripts.validate_kits import (
    check_l0,
    check_l1,
    check_l2,
    find_estimated_values,
    iter_kits,
)

REMIELLE_PATH = Path("agents/remielle.json")


def _real_remielle_kit():
    for path, kit in iter_kits():
        if path.name == "remielle.json" and kit.get("source_type") == "agent":
            return path, kit
    raise AssertionError("agents/remielle.json not found by iter_kits()")


class TestGatedEscapeForAgentsAbsentFromZO:
    def test_l0_l1_l2_all_green_with_remielle_present(self):
        kits = iter_kits()
        assert check_l0(kits) == []
        assert check_l1(kits) == []
        l2_findings = check_l2(kits)
        remielle_findings = [f for f in l2_findings if f.source_name == "Remielle"]
        assert remielle_findings == []

    def test_db_citation_satisfies_the_escape_for_a_zo_absent_agent(self):
        kit = [
            (
                Path("agents/synthetic_no_zo.json"),
                {
                    "source_type": "agent",
                    "source_id": "999999",
                    "source_name": "Synthetic No-ZO Agent",
                    "modifiers": [
                        {
                            "stat": "flat_atk",
                            "value": 100,
                            "source": "core_skill",
                            "source_label": "Core",
                            "notes": 'db:"ATK increases by 100."',
                        }
                    ],
                },
            )
        ]
        assert check_l2(kit) == []

    def test_guide_citation_satisfies_the_escape_for_a_zo_absent_agent(self):
        kit = [
            (
                Path("agents/synthetic_no_zo.json"),
                {
                    "source_type": "agent",
                    "source_id": "999999",
                    "source_name": "Synthetic No-ZO Agent",
                    "modifiers": [
                        {
                            "stat": "flat_atk",
                            "value": 100,
                            "source": "core_skill",
                            "source_label": "Core",
                            "notes": "guide(v3.1.12): ATK increases by 100.",
                        }
                    ],
                },
            )
        ]
        assert check_l2(kit) == []

    def test_no_citation_at_all_still_fails_for_a_zo_absent_agent(self):
        kit = [
            (
                Path("agents/synthetic_no_zo.json"),
                {
                    "source_type": "agent",
                    "source_id": "999999",
                    "source_name": "Synthetic No-ZO Agent",
                    "modifiers": [
                        {
                            "stat": "flat_atk",
                            "value": 100,
                            "source": "core_skill",
                            "source_label": "Core",
                            "notes": "Trust me.",
                        }
                    ],
                },
            )
        ]
        findings = check_l2(kit)
        assert [f.code for f in findings] == ["no_zo_reference"]

    def test_fabricated_guide_citation_still_fails_for_an_agent_with_a_real_zo_sheet(self):
        """The escape is gated to `zo_key is None` only -- an agent ZO DOES
        cover (e.g. Astra Yao) cannot bypass a real symbol check by citing
        `guide(...)` instead of a genuine ZO symbol."""
        kit = [
            (
                Path("agents/astra_yao.json"),
                {
                    "source_type": "agent",
                    "source_id": "1311",
                    "source_name": "Astra Yao",
                    "modifiers": [
                        {
                            "stat": "flat_atk",
                            "value": 100,
                            "source": "core_skill",
                            "source_label": "Fabricated",
                            "notes": "guide(v3.1.12): a completely made-up 100 ATK bonus.",
                        }
                    ],
                },
            )
        ]
        findings = check_l2(kit)
        assert [f.code for f in findings] == ["no_zo_citation"]


class TestFindEstimatedValues:
    def test_finds_the_one_known_estimated_modifier_in_the_real_corpus(self):
        reports = find_estimated_values(iter_kits())
        assert any("piper.json" in r for r in reports)

    def test_remielle_currently_cites_no_estimated_values(self):
        """Every authored Remielle value traces to a real DB quote (Task
        18/19/20) -- zero 'estimated' tags is the correct, verified state
        here, not a gap in the scanner."""
        path, kit = _real_remielle_kit()
        reports = find_estimated_values([(path, kit)])
        assert reports == []

    def test_scanner_finds_a_synthetic_estimated_tag(self):
        kit = [
            (
                Path("agents/synthetic.json"),
                {
                    "source_type": "agent",
                    "source_id": "999998",
                    "source_name": "Synthetic Agent",
                    "modifiers": [
                        {
                            "stat": "flat_atk",
                            "value": 100,
                            "source": "core_skill",
                            "source_label": "Placeholder",
                            "notes": "estimated -- no source found yet, revisit later.",
                        }
                    ],
                },
            )
        ]
        reports = find_estimated_values(kit)
        assert len(reports) == 1
        assert "Placeholder" in reports[0]
