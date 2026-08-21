"""Loader behaviour on duplicate source_ids — Task H3 of the 14158 hotfix.

`_find_file_by_source_id` used to return the first `directory.glob("*.json")`
hit: non-deterministic order, silent winner. It now sorts the glob and raises
on a multi-match instead of picking one (docs/TASKS_wengine_id_collision.md).
"""

from __future__ import annotations

import json

import pytest

from app.services.modifier_loader import _cached_find_file, _find_file_by_source_id


def _write_kit(directory, filename: str, source_id: str) -> None:
    (directory / filename).write_text(
        json.dumps({"source_id": source_id, "source_name": filename, "modifiers": []})
    )


class TestFindFileBySourceId:
    def test_single_match_returns_the_path(self, tmp_path):
        _write_kit(tmp_path, "only.json", "9999")
        result = _find_file_by_source_id(tmp_path, "9999")
        assert result is not None
        assert result.name == "only.json"

    def test_no_match_returns_none(self, tmp_path):
        _write_kit(tmp_path, "only.json", "9999")
        assert _find_file_by_source_id(tmp_path, "1234") is None

    def test_missing_directory_returns_none(self, tmp_path):
        assert _find_file_by_source_id(tmp_path / "nope", "9999") is None

    def test_two_claimants_raise_naming_both_paths(self, tmp_path):
        _write_kit(tmp_path, "a.json", "9999")
        _write_kit(tmp_path, "b.json", "9999")
        with pytest.raises(ValueError, match=r"a\.json.*b\.json") as exc_info:
            _find_file_by_source_id(tmp_path, "9999")
        assert "9999" in str(exc_info.value)

    def test_other_ids_unaffected_by_a_collision(self, tmp_path):
        """A collision on one id must not break lookups of a different id."""
        _write_kit(tmp_path, "a.json", "9999")
        _write_kit(tmp_path, "b.json", "9999")
        _write_kit(tmp_path, "c.json", "1234")
        result = _find_file_by_source_id(tmp_path, "1234")
        assert result is not None
        assert result.name == "c.json"


class TestCachedFindFile:
    def test_raise_is_not_memoised_as_a_value(self, tmp_path):
        """`_cached_find_file` is lru_cache'd: the raise propagates out of the
        cached call and must repeat on a second call — not be "fixed" into a
        cached None."""
        _write_kit(tmp_path, "a.json", "9999")
        _write_kit(tmp_path, "b.json", "9999")
        with pytest.raises(ValueError, match="9999"):
            _cached_find_file(str(tmp_path), "9999")
        with pytest.raises(ValueError, match="9999"):
            _cached_find_file(str(tmp_path), "9999")
