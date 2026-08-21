"""Tests for ZZZ-specific tag conventions.

Covers the ``sheet``/``name`` category extensions and ``formula_tag``
helper added in Phase 6.2c for per-agent formula sheets.
"""

from __future__ import annotations

from app.formula.zzz.tags import (
    NAME,
    Q_ANOM_BUILDUP,
    Q_ANOMALY_DMG,
    Q_DAZE_BUILDUP,
    Q_DISORDER_DMG,
    Q_STANDARD_DMG,
    SHEET,
    Q,
    formula_tag,
)


class TestFormulaTag:
    def test_builds_canonical_three_category_tag(self) -> None:
        t = formula_tag("burnice", "basic_0", Q_STANDARD_DMG)
        assert t.get(SHEET) == "burnice"
        assert t.get(NAME) == "basic_0"
        assert t.get(Q) == Q_STANDARD_DMG

    def test_different_names_not_equal(self) -> None:
        a = formula_tag("burnice", "basic_0", Q_STANDARD_DMG)
        b = formula_tag("burnice", "basic_1", Q_STANDARD_DMG)
        assert a != b

    def test_different_sheets_not_equal(self) -> None:
        a = formula_tag("burnice", "basic_0", Q_STANDARD_DMG)
        b = formula_tag("ellen", "basic_0", Q_STANDARD_DMG)
        assert a != b

    def test_different_quantities_share_sheet_and_name(self) -> None:
        """A single attack hit registers 3 sibling formulas that all share
        ``{sheet, name}`` but differ in ``q`` — enables reads that gather
        all quantities for a named hit, or filter by quantity alone."""
        dmg = formula_tag("burnice", "basic_0", Q_STANDARD_DMG)
        daze = formula_tag("burnice", "basic_0", Q_DAZE_BUILDUP)
        anom = formula_tag("burnice", "basic_0", Q_ANOM_BUILDUP)

        # Same sheet + name
        assert dmg.get(SHEET) == daze.get(SHEET) == anom.get(SHEET)
        assert dmg.get(NAME) == daze.get(NAME) == anom.get(NAME)

        # Different q — all distinct tags
        assert dmg != daze
        assert daze != anom
        assert dmg != anom

    def test_formula_tag_matches_full_eval_context(self) -> None:
        """A formula registered at ``{sheet:burnice, name:basic_0, q:standard_dmg}``
        is gathered when the read's effective context carries the same
        three entries (registered-is-subset-of-query semantics)."""
        registered = formula_tag("burnice", "basic_0", Q_STANDARD_DMG)
        query = formula_tag("burnice", "basic_0", Q_STANDARD_DMG)
        assert registered.is_subset_of(query)

    def test_formula_tag_not_matched_by_wrong_name(self) -> None:
        registered = formula_tag("burnice", "basic_0", Q_STANDARD_DMG)
        query = formula_tag("burnice", "basic_1", Q_STANDARD_DMG)
        assert not registered.is_subset_of(query)


class TestNewQuantityNames:
    """Sanity-check the Phase 6.2c quantity strings are distinct and stable."""

    def test_all_distinct(self) -> None:
        names = {
            Q_STANDARD_DMG,
            Q_ANOMALY_DMG,
            Q_DISORDER_DMG,
            Q_ANOM_BUILDUP,
            Q_DAZE_BUILDUP,
        }
        assert len(names) == 5

    def test_match_zo_quantity_style(self) -> None:
        """Snake-case Fairy convention; ZO uses camelCase but maps 1:1."""
        assert Q_STANDARD_DMG == "standard_dmg"
        assert Q_ANOMALY_DMG == "anomaly_dmg"
        assert Q_DISORDER_DMG == "disorder_dmg"
        assert Q_ANOM_BUILDUP == "anom_buildup"
        assert Q_DAZE_BUILDUP == "daze_buildup"
