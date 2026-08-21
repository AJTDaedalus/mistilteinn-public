"""Unit tests for the pure parsing/detection logic in
HakushinCoreDescriptionPatchImporter (Task 23)."""

from __future__ import annotations

from app.data.importers.hakushin_core_description_patch_importer import (
    is_blank_core_description,
    parse_passive_descriptions,
)


class TestIsBlankCoreDescription:
    def test_none_is_blank(self) -> None:
        assert is_blank_core_description(None) is True

    def test_empty_string_is_blank(self) -> None:
        assert is_blank_core_description("") is True

    def test_join_of_two_empty_halves_is_blank(self) -> None:
        # " | ".join(["", ""]) — the exact artifact NanokaImporter produced for Velina
        assert is_blank_core_description(" | ") is True

    def test_bare_pipe_is_blank(self) -> None:
        assert is_blank_core_description("|") is True

    def test_real_text_is_not_blank(self) -> None:
        assert is_blank_core_description("Velina gains 45 Windbloom.") is False

    def test_real_text_with_pipe_join_is_not_blank(self) -> None:
        assert is_blank_core_description("First half. | Second half.") is False

    def test_whitespace_only_is_blank(self) -> None:
        assert is_blank_core_description("   ") is True


class TestParsePassiveDescriptions:
    def test_extracts_joined_desc_by_level(self) -> None:
        data = {
            "Passive": {
                "Level": {
                    "1561501": {
                        "Level": 1,
                        "Name": ["Core Passive: Breeze in Bloom", "Additional Ability: X"],
                        "Desc": ["First half.", "Second half."],
                    },
                    "1561502": {
                        "Level": 2,
                        "Name": ["Core Passive: Breeze in Bloom", "Additional Ability: X"],
                        "Desc": ["First half v2.", "Second half v2."],
                    },
                }
            }
        }
        result = parse_passive_descriptions(data)
        assert result == {
            1: "First half. | Second half.",
            2: "First half v2. | Second half v2.",
        }

    def test_strips_color_tags(self) -> None:
        data = {
            "Passive": {
                "Level": {
                    "x": {
                        "Level": 1,
                        "Desc": ["Deals <color=#A6C5FD>Wind DMG</color>.", ""],
                    }
                }
            }
        }
        result = parse_passive_descriptions(data)
        assert result[1] == "Deals Wind DMG. | "

    def test_missing_passive_returns_empty(self) -> None:
        assert parse_passive_descriptions({}) == {}

    def test_missing_desc_list_yields_empty_string(self) -> None:
        data = {"Passive": {"Level": {"x": {"Level": 3, "Desc": []}}}}
        assert parse_passive_descriptions(data) == {3: ""}
