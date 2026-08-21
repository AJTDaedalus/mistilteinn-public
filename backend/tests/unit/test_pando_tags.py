"""Tests for the Pando tag system.

Semantics (from ``/tmp/genshin-optimizer/libs/pando/engine/src/tag/type.ts``):

* A tag is a map of ``category → value``. Missing categories mean
  "no constraint".
* A ``None`` value in a tag means "clear this category when merging".
* Two tags are equal only when canonicalized; order of insertion does not
  matter; ``None`` entries are stripped for comparison in the "effective"
  view (we preserve ``None`` in raw form because it carries merge intent).
"""

from __future__ import annotations

import pytest

from app.formula.tags import Tag


class TestTagConstruction:
    def test_empty_tag_has_no_entries(self) -> None:
        t = Tag.of()
        assert t.items == ()

    def test_of_sorts_entries_canonically(self) -> None:
        a = Tag.of(src="Anby", q="atk_")
        b = Tag.of(q="atk_", src="Anby")
        assert a == b
        assert hash(a) == hash(b)

    def test_get_returns_value(self) -> None:
        t = Tag.of(src="Anby", q="atk_")
        assert t.get("src") == "Anby"
        assert t.get("q") == "atk_"

    def test_get_missing_returns_empty_string(self) -> None:
        """Pando convention: reading a missing category yields ''."""
        t = Tag.of(src="Anby")
        assert t.get("q") == ""


class TestTagMerge:
    def test_merge_adds_new_categories(self) -> None:
        a = Tag.of(src="Anby")
        b = Tag.of(q="atk_")
        assert a.merge(b) == Tag.of(src="Anby", q="atk_")

    def test_merge_overwrites_existing_values(self) -> None:
        a = Tag.of(src="Anby", q="atk_")
        b = Tag.of(src="Lucy")
        assert a.merge(b) == Tag.of(src="Lucy", q="atk_")

    def test_merge_none_value_clears_category(self) -> None:
        a = Tag.of(src="Anby", q="atk_")
        b = Tag.of(src=None)
        merged = a.merge(b)
        assert merged.get("src") == ""
        assert merged.get("q") == "atk_"

    def test_merge_is_non_mutating(self) -> None:
        a = Tag.of(src="Anby")
        _ = a.merge(Tag.of(q="atk_"))
        assert a == Tag.of(src="Anby")

    def test_merge_empty_is_identity(self) -> None:
        a = Tag.of(src="Anby", q="atk_")
        assert a.merge(Tag.of()) == a


class TestTagEquality:
    def test_different_values_unequal(self) -> None:
        assert Tag.of(src="Anby") != Tag.of(src="Lucy")

    def test_different_categories_unequal(self) -> None:
        assert Tag.of(src="Anby") != Tag.of(q="Anby")

    def test_hashable_for_dict_keys(self) -> None:
        d: dict[Tag, int] = {Tag.of(src="Anby"): 1, Tag.of(src="Lucy"): 2}
        assert d[Tag.of(src="Anby")] == 1
        assert d[Tag.of(src="Lucy")] == 2


class TestTagSubset:
    """A tag ``a`` is a subset of ``b`` iff every concrete (non-None) entry
    in ``a`` is present with the same value in ``b``. Used by ``read``-op
    gathering to find all nodes whose registration tag matches the query.
    """

    def test_empty_is_subset_of_anything(self) -> None:
        assert Tag.of().is_subset_of(Tag.of(src="Anby"))

    def test_equal_tags_are_subsets(self) -> None:
        t = Tag.of(src="Anby", q="atk_")
        assert t.is_subset_of(t)

    def test_superset_is_subset_of_itself(self) -> None:
        assert Tag.of(src="Anby").is_subset_of(Tag.of(src="Anby", q="atk_"))

    def test_different_value_not_subset(self) -> None:
        assert not Tag.of(src="Anby").is_subset_of(Tag.of(src="Lucy"))

    def test_missing_category_in_query_not_subset(self) -> None:
        assert not Tag.of(src="Anby").is_subset_of(Tag.of(q="atk_"))


@pytest.mark.parametrize(
    ("kwargs", "expected_repr_contains"),
    [
        ({}, "Tag()"),
        ({"src": "Anby"}, "src=Anby"),
        ({"src": "Anby", "q": "atk_"}, "q=atk_"),
    ],
)
def test_repr_is_human_readable(kwargs: dict[str, str], expected_repr_contains: str) -> None:
    assert expected_repr_contains in repr(Tag.of(**kwargs))
