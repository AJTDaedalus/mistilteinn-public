"""Unit tests for the pure parsing/detection logic in
HakushinMindscapeDescriptionPatchImporter (Task 29)."""

from __future__ import annotations

from app.data.importers.hakushin_mindscape_description_patch_importer import (
    is_blank_mindscape_description,
    parse_mindscape_descriptions,
)


class TestIsBlankMindscapeDescription:
    def test_none_is_blank(self) -> None:
        assert is_blank_mindscape_description(None) is True

    def test_empty_string_is_blank(self) -> None:
        assert is_blank_mindscape_description("") is True

    def test_whitespace_only_is_blank(self) -> None:
        assert is_blank_mindscape_description("   ") is True

    def test_real_text_is_not_blank(self) -> None:
        assert is_blank_mindscape_description("Velina ignores 20% of the target's RES.") is False


class TestParseMindscapeDescriptions:
    def test_extracts_desc_by_level(self) -> None:
        data = {
            "Talent": {
                "1": {"Level": 1, "Name": "Orderly Elegance", "Desc": "M1 text."},
                "6": {"Level": 6, "Name": "Chief Angel", "Desc": "M6 text."},
            }
        }
        result = parse_mindscape_descriptions(data)
        assert result == {1: "M1 text.", 6: "M6 text."}

    def test_strips_color_tags(self) -> None:
        data = {
            "Talent": {
                "1": {"Level": 1, "Desc": "Deals <color=#A6C5FD>Wind DMG</color>."},
            }
        }
        result = parse_mindscape_descriptions(data)
        assert result[1] == "Deals Wind DMG."

    def test_missing_talent_returns_empty(self) -> None:
        assert parse_mindscape_descriptions({}) == {}

    def test_missing_desc_yields_empty_string(self) -> None:
        data = {"Talent": {"x": {"Level": 3, "Desc": ""}}}
        assert parse_mindscape_descriptions(data) == {3: ""}
