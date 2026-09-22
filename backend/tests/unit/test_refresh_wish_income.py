"""The wish-income refresher's guards, exercised against synthetic workbooks.

**No test here touches the network.** The point is not that the live sheet parses today — the
script proves that when it runs — but that each guard *fires*, because a validation that has
never been seen to fail is indistinguishable from one that cannot.

The three invariants exist because a public spreadsheet can be re-laid-out by its maintainers
at any moment, and a column shift returns a perfectly valid HTTP 200 full of wrong numbers.
`docs/RESEARCH_wish_planner.md` §10 records the version of that failure already living in the
sister project: hoyincome reads the Acquaint column where it means Intertwined, gets away with
it because it only takes a difference, and silently drops 4 wishes a patch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.refresh_wish_income import (
    MIN_SUMMARY_OVERLAP,
    RefreshError,
    VersionIncome,
    _check_subscriptions,
    _check_summary,
    _currency_columns,
    _read_patch,
    _wishes,
    load_snapshot,
    parse_version,
)

SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "app" / "data" / "wishes" / "income_snapshot.json"
)

HEADER = ["", "", "Resin", "Mora", "", "", "", "", "", "Primogems", "Acquaint", "Intertwined"]


def _patch_rows(f2p_primo: float, f2p_fate: float, welkin: float, bp_primo: float,
                bp_fate: float) -> list[list[str]]:
    """A minimal per-patch tab with the four rows the script reads."""

    def row(label: str, primogems: float, acquaint: float, intertwined: float) -> list[str]:
        cells = [""] * 12
        cells[1] = label
        cells[9], cells[10], cells[11] = str(primogems), str(acquaint), str(intertwined)
        return cells

    p2p_primo = f2p_primo + welkin + bp_primo
    return [
        HEADER,
        row("Total F2P", f2p_primo, 15.9, f2p_fate),
        row("Welkin 42 Days", welkin, 0, 0),
        row("Battle Pass - Paid Bonus", bp_primo, 0, bp_fate),
        row("Total P2P", p2p_primo, 15.9, f2p_fate + bp_fate),
    ]


# --- version parsing ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("1.0", ("1.0", 1, 0, False)),
        ("7.0", ("7.0", 7, 0, False)),
        ("7.1 est.", ("7.1", 7, 1, True)),
        ("  6.3  ", ("6.3", 6, 3, False)),
        ("summary", None),
        ("dust", None),
        ("5th anniversary", None),
    ],
)
def test_version_parsing(name: str, expected: tuple | None) -> None:
    """`est.` is a flag, not part of the version — and a prose tab is not a version."""
    assert parse_version(name) == expected


# --- columns are found by header, never by position -----------------------------------


def test_currency_columns_come_from_the_header() -> None:
    assert _currency_columns([HEADER]) == (9, 11)


def test_a_shifted_layout_is_refused_rather_than_misread() -> None:
    """The guard that hoyincome does not have.

    Inserting a column moves Intertwined from 11 to 12. Reading by position would silently
    return Acquaint; reading by header finds it, and a *missing* header refuses outright.
    """
    shifted = [["inserted", *HEADER]]
    assert _currency_columns(shifted) == (10, 12)

    with pytest.raises(RefreshError, match="layout has changed"):
        _currency_columns([["Resin", "Mora", "Primogems", "Acquaint"]])


def test_acquaint_is_never_counted() -> None:
    """Acquaint Fate buys the standard banner. Owner ruling, 2026-09-22."""
    row = [""] * 12
    row[9], row[10], row[11] = "1600", "999", "3"
    assert _wishes(row, 9, 11) == pytest.approx(13.0)


# --- invariant 1: the tiers must rebuild the sheet's own paid total --------------------


def test_a_patch_tab_that_does_not_add_up_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _patch_rows(f2p_primo=16000, f2p_fate=8, welkin=4200, bp_primo=680, bp_fate=4)
    rows[4][9] = "99999"  # Total P2P no longer equals the parts
    monkeypatch.setattr("scripts.refresh_wish_income._rows", lambda _gid: rows)

    with pytest.raises(RefreshError, match="Total P2P"):
        _read_patch("5.2", "gid")


def test_a_patch_tab_missing_a_row_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _patch_rows(16000, 8, 4200, 680, 4)
    del rows[2]  # no Welkin row
    monkeypatch.setattr("scripts.refresh_wish_income._rows", lambda _gid: rows)

    with pytest.raises(RefreshError, match="Welkin"):
        _read_patch("5.2", "gid")


def test_a_well_formed_patch_tab_reads_all_three_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.refresh_wish_income._rows",
        lambda _gid: _patch_rows(16000, 8, 4200, 680, 4),
    )
    income = _read_patch("7.1 est.", "gid")
    assert income.version == "7.1"
    assert income.is_estimate is True
    assert income.f2p == pytest.approx(16000 / 160 + 8)
    assert income.welkin == pytest.approx(income.f2p + 4200 / 160)
    assert income.welkin_bp == pytest.approx(income.welkin + 680 / 160 + 4)


# --- invariant 2: the summary tab must independently agree ----------------------------


def _income(count: int) -> list[VersionIncome]:
    return [
        VersionIncome(f"1.{i}", 1, i, False, f2p=100.0 + i, welkin=126.0 + i, welkin_bp=134.0 + i)
        for i in range(count)
    ]


def _summary_tab(income: list[VersionIncome], *, offset: float = 0.0) -> list[list[str]]:
    """A summary tab whose column 3 carries the F2P total, with other columns as noise."""
    return [
        [entry.version, "1", "2", str(entry.f2p + offset), "4"] for entry in income
    ]


def test_the_summary_column_is_found_by_agreement(monkeypatch: pytest.MonkeyPatch) -> None:
    income = _income(MIN_SUMMARY_OVERLAP + 5)
    monkeypatch.setattr("scripts.refresh_wish_income._rows", lambda _gid: _summary_tab(income))
    _check_summary([("summary", "gid")], income)


def test_a_summary_that_agrees_with_nothing_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """This is the column-shift alarm: no column reproduces the patch tabs."""
    income = _income(MIN_SUMMARY_OVERLAP + 5)
    monkeypatch.setattr(
        "scripts.refresh_wish_income._rows",
        lambda _gid: _summary_tab(income, offset=25.0),
    )
    with pytest.raises(RefreshError, match="below the"):
        _check_summary([("summary", "gid")], income)


def test_too_little_overlap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gutted summary tab means the patch tabs would go unverified, so refuse."""
    income = _income(MIN_SUMMARY_OVERLAP + 5)
    monkeypatch.setattr(
        "scripts.refresh_wish_income._rows", lambda _gid: _summary_tab(income[:3])
    )
    with pytest.raises(RefreshError, match="too few to cross-check"):
        _check_summary([("summary", "gid")], income)


def test_a_missing_summary_tab_is_refused() -> None:
    with pytest.raises(RefreshError, match="no `summary` tab"):
        _check_summary([("1.0", "gid")], _income(3))


def test_a_documented_minority_may_still_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    """1.0 really does differ, by its whole Permanent Content bucket. One outlier is fine."""
    income = _income(MIN_SUMMARY_OVERLAP + 5)
    rows = _summary_tab(income)
    rows[0][3] = "999"
    monkeypatch.setattr("scripts.refresh_wish_income._rows", lambda _gid: rows)
    _check_summary([("summary", "gid")], income)


# --- invariant 3: the subscriptions are fixed -----------------------------------------


def test_a_flat_subscription_passes() -> None:
    _check_subscriptions(_income(5))


def test_a_drifting_welkin_is_refused() -> None:
    """Welkin is 4,200 primogems a patch by definition; a value that moves is a misread."""
    income = _income(5)
    income[2] = VersionIncome("1.2", 1, 2, False, f2p=102.0, welkin=140.0, welkin_bp=148.0)
    with pytest.raises(RefreshError, match="welkin is a fixed subscription"):
        _check_subscriptions(income)


def test_a_drifting_battle_pass_is_refused() -> None:
    income = _income(5)
    income[3] = VersionIncome("1.3", 1, 3, False, f2p=103.0, welkin=129.0, welkin_bp=200.0)
    with pytest.raises(RefreshError, match="battle pass is a fixed subscription"):
        _check_subscriptions(income)


# --- the committed snapshot -----------------------------------------------------------


def test_the_snapshot_is_committed_and_loads_without_a_network() -> None:
    """A fresh clone and CI must be able to fill the store with no outbound request."""
    assert SNAPSHOT.exists(), "the committed seed is missing"
    income, fetched_at = load_snapshot()
    assert len(income) > 40
    assert fetched_at.tzinfo is not None, "fetched_at must be timezone-aware"


def test_the_snapshot_satisfies_the_same_invariants() -> None:
    """Whatever wrote it, the committed file has to pass the checks the refresher applies."""
    income, _ = load_snapshot()
    _check_subscriptions(income)
    assert all(entry.f2p < entry.welkin < entry.welkin_bp for entry in income)


def test_the_snapshot_records_where_it_came_from() -> None:
    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert raw["document_id"]
    assert "refresh_wish_income" in raw["note"]


def test_the_snapshot_marks_estimates() -> None:
    """The workbook publishes a forward estimate; a projection shown as history is a lie."""
    income, _ = load_snapshot()
    assert any(entry.is_estimate for entry in income), "no version is flagged an estimate"
    settled = [e for e in income if not e.is_estimate]
    estimates = [e for e in income if e.is_estimate]
    assert min(e.major * 100 + e.minor for e in estimates) > max(
        e.major * 100 + e.minor for e in settled
    ), "an estimate must be newer than every settled version"
