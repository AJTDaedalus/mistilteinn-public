"""Refresh wish income per game version from the community bookkeeping workbook.

    cd backend && python -m scripts.refresh_wish_income            # snapshot + database
    cd backend && python -m scripts.refresh_wish_income --dry-run  # fetch and check only
    cd backend && python -m scripts.refresh_wish_income --snapshot-only

**Nothing in `app/` calls this.** `app/` has exactly one request-time fetch
(`POST /rotations/import/link`) and E.6 argues the case for it; a third-party spreadsheet on
the request path would be a second, on a dependency nobody here controls. This runs on a
timer, writes the table, and the API only ever reads it.

## What it reads

The Genshin workbook that the sister project `/root/hoyincome` located
(`hoyo_pulls/config.py`): a `summary` tab and one tab per patch. The three tiers are line
items rather than a model — `Total F2P`, `Welkin 42 Days`, `Battle Pass - Paid Bonus` — and a
wish is `Primogems / 160 + Intertwined Fate`.

**Columns are found by reading the header row, never by index.** hoyincome hardcodes column 10
as the fate column; column 10 is *Acquaint* and column 11 is *Intertwined*. It gets away with
it because it only ever takes a difference between two rows whose Acquaint values are equal,
so the wrong column cancels — but it silently drops the paid Battle Pass's 4 Intertwined Fates
on every patch. `docs/RESEARCH_wish_planner.md` §10. A wrong column read as an absolute, which
is what this script needs, would not cancel.

## Three invariants gate every refresh

A public spreadsheet can be re-laid-out by its maintainers at any moment, and a column shift
returns a perfectly valid HTTP 200 full of wrong numbers. So a refresh that cannot prove its
own shape **refuses entirely** rather than writing part of itself:

1. `f2p + welkin + battle pass` equals the sheet's own `Total P2P` row.
2. Per-patch `Total F2P` equals the `summary` tab's own figure for that version.
3. Welkin and the paid Battle Pass are flat across patches — they are fixed subscriptions,
   and one that moves is a shape change rather than news.

And, following `seed_db`, it refuses to replace a healthy store with a much smaller one.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete

from app.database import async_session_factory
from app.models import WishIncome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: The Genshin bookkeeping workbook, via /root/hoyincome's `hoyo_pulls/config.py`.
DOCUMENT_ID = "1l9HPu2cAzTckdXtr7u-7D8NSKzZNUqOuvbmxERFZ_6w"

SNAPSHOT = Path(__file__).resolve().parents[1] / "app" / "data" / "wishes" / "income_snapshot.json"

PRIMOGEMS_PER_WISH = 160.0

#: Row labels in column B of a per-patch tab.
ROW_F2P = "Total F2P"
ROW_P2P = "Total P2P"
ROW_WELKIN = "Welkin 42 Days"
ROW_BATTLE_PASS = "Battle Pass - Paid Bonus"  # noqa: S105 — a sheet row label, not a secret

#: Header cells naming the two currencies that buy a limited-banner wish. `Acquaint` is
#: deliberately absent: it buys Wanderlust Invocation (owner ruling, 2026-09-22).
HEADER_PRIMOGEMS = "primogems"
HEADER_INTERTWINED = "intertwined"

TIERS = ("f2p", "welkin", "welkin_bp")

#: A refresh returning fewer than this share of the rows already stored is refused rather
#: than written. `seed_db`'s PRUNE REFUSED rule, for the same reason: a truncated but valid
#: HTTP 200 is indistinguishable from a real retraction, and only one of them is recoverable.
MIN_RETAINED_SHARE = 0.8

#: The two subscriptions are fixed, so their per-patch value must not vary. Tolerance covers
#: the workbook's own rounding only.
SUBSCRIPTION_TOLERANCE = 0.01
TOTAL_TOLERANCE = 0.01
SUMMARY_TOLERANCE = 0.05

#: Versions that must appear on both the summary tab and their own patch tab for invariant 2
#: to mean anything. Well below the ~54 that exist, so this fires on a gutted sheet rather
#: than on one patch being added ahead of its summary row.
MIN_SUMMARY_OVERLAP = 20

#: Share of shared versions on which the summary tab must agree with the patch tabs.
#:
#: Not 100%, because two versions genuinely differ and both were checked by hand (2026-09-22):
#: **1.0** reads 169.91 on the summary against 91.82 on its own tab, and the gap is exactly
#: the 78.09 in its Permanent Content column — the whole game's exploration income, which the
#: summary attributes to launch and the patch tab does not. **3.4** differs by 0.03, which is
#: the bookkeepers' own rounding. Everything else agrees to the digit.
#:
#: A column shift, which is what this invariant exists to catch, drops the best column's
#: agreement to near zero rather than to 96%.
MIN_SUMMARY_AGREEMENT = 0.9


class RefreshError(RuntimeError):
    """The workbook did not have the shape this script knows how to read."""


@dataclass(frozen=True, slots=True)
class VersionIncome:
    """One game version's income at all three tiers."""

    version: str
    major: int
    minor: int
    is_estimate: bool
    f2p: float
    welkin: float
    welkin_bp: float

    def wishes(self, tier: str) -> float:
        """Wishes earned at `tier`."""
        return {"f2p": self.f2p, "welkin": self.welkin, "welkin_bp": self.welkin_bp}[tier]


def _fetch(url: str, timeout: int = 60) -> str:
    """Read a URL on the workbook's fixed host."""
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 — fixed host
        return response.read().decode("utf-8", "replace")


def _tabs() -> list[tuple[str, str]]:
    """Map every tab name to its gid by reading the workbook's HTML view.

    Discovered rather than hardcoded, so the bookkeepers can add next patch's tab without a
    code change here — the same choice hoyincome made, and the right one.
    """
    html = _fetch(f"https://docs.google.com/spreadsheets/d/{DOCUMENT_ID}/htmlview")
    found = re.findall(r'items\.push\(\{name: "((?:[^"\\]|\\.)*)".*?gid: "(-?\d+)"', html)
    if not found:
        raise RefreshError("workbook HTML view listed no tabs; the page shape has changed")
    return found


def _rows(gid: str) -> list[list[str]]:
    url = f"https://docs.google.com/spreadsheets/d/{DOCUMENT_ID}/export?format=csv&gid={gid}"
    return list(csv.reader(io.StringIO(_fetch(url))))


def _number(cell: str | None) -> float:
    try:
        return float((cell or "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _currency_columns(rows: list[list[str]]) -> tuple[int, int]:
    """Locate the Primogems and Intertwined columns from the sheet's own header row.

    Raises:
        RefreshError: If either header is missing, which means the layout moved and every
            number this script would otherwise read is untrustworthy.
    """
    for row in rows[:10]:
        lowered = [cell.strip().lower() for cell in row]
        if HEADER_PRIMOGEMS in lowered and HEADER_INTERTWINED in lowered:
            return lowered.index(HEADER_PRIMOGEMS), lowered.index(HEADER_INTERTWINED)
    raise RefreshError(
        f"no header row naming both '{HEADER_PRIMOGEMS}' and '{HEADER_INTERTWINED}'; "
        "the workbook layout has changed and column positions cannot be trusted"
    )


def _labelled(rows: list[list[str]], label: str) -> list[str] | None:
    for row in rows:
        if len(row) > 1 and row[1].strip() == label:
            return row
    return None


def _wishes(row: list[str] | None, primogems: int, intertwined: int) -> float | None:
    """A limited-banner wish: primogems over 160, plus Intertwined Fate. Never Acquaint."""
    if row is None or len(row) <= max(primogems, intertwined):
        return None
    return _number(row[primogems]) / PRIMOGEMS_PER_WISH + _number(row[intertwined])


def parse_version(name: str) -> tuple[str, int, int, bool] | None:
    """`"7.1 est."` becomes `("7.1", 7, 1, True)`; a non-version tab becomes None."""
    match = re.match(r"^\s*(\d+)\.(\d+)\s*(est\.?)?\s*$", name, re.IGNORECASE)
    if match is None:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    return f"{major}.{minor}", major, minor, bool(match.group(3))


def _summary_rows(rows: list[list[str]]) -> dict[str, list[float]]:
    """Every numeric cell of each per-version row on the summary tab, by version.

    The per-version rows are **unlabelled** — the column headings live in a season roll-up
    block higher up the sheet and in a different order — so nothing here can name a column.
    `_check_summary` finds the right one by agreement instead of hardcoding its position,
    which is what hoyincome does and what breaks silently when a column is inserted.
    """
    found: dict[str, list[float]] = {}
    for row in rows:
        if not row:
            continue
        parsed = parse_version(row[0])
        if parsed is None:
            continue
        found[parsed[0]] = [_number(cell) for cell in row[1:]]
    return found


def _read_patch(name: str, gid: str) -> VersionIncome:
    parsed = parse_version(name)
    assert parsed is not None
    version, major, minor, is_estimate = parsed

    rows = _rows(gid)
    primogems, intertwined = _currency_columns(rows)

    f2p = _wishes(_labelled(rows, ROW_F2P), primogems, intertwined)
    p2p = _wishes(_labelled(rows, ROW_P2P), primogems, intertwined)
    welkin = _wishes(_labelled(rows, ROW_WELKIN), primogems, intertwined)
    battle_pass = _wishes(_labelled(rows, ROW_BATTLE_PASS), primogems, intertwined)

    missing = [
        label
        for label, value in (
            (ROW_F2P, f2p), (ROW_P2P, p2p), (ROW_WELKIN, welkin), (ROW_BATTLE_PASS, battle_pass)
        )
        if value is None
    ]
    if missing:
        raise RefreshError(f"{name}: tab is missing {missing}")

    # Narrow for the type checker; `missing` above already rejected any None.
    assert f2p is not None
    assert p2p is not None
    assert welkin is not None
    assert battle_pass is not None

    # Invariant 1: the tiers must rebuild the sheet's own paid total.
    derived = f2p + welkin + battle_pass
    if abs(derived - p2p) > TOTAL_TOLERANCE:
        raise RefreshError(
            f"{name}: f2p {f2p:.3f} + welkin {welkin:.3f} + bp {battle_pass:.3f} = "
            f"{derived:.3f} but the sheet's {ROW_P2P} says {p2p:.3f}"
        )

    return VersionIncome(
        version=version, major=major, minor=minor, is_estimate=is_estimate,
        f2p=f2p, welkin=f2p + welkin, welkin_bp=derived,
    )


def fetch_income() -> list[VersionIncome]:
    """Read every patch tab and check all three invariants. Raises rather than degrading."""
    tabs = _tabs()
    patches = [(name, gid) for name, gid in tabs if parse_version(name) is not None]
    if not patches:
        raise RefreshError("workbook has no per-patch tabs")

    with ThreadPoolExecutor(max_workers=8) as pool:
        income = sorted(
            pool.map(lambda pair: _read_patch(*pair), patches),
            key=lambda entry: (entry.major, entry.minor),
        )

    _check_summary(tabs, income)
    _check_subscriptions(income)
    return income


def _check_summary(tabs: list[tuple[str, str]], income: list[VersionIncome]) -> None:
    """Invariant 2: the summary tab must independently agree with the patch tabs.

    The workbook totals every patch twice — once itemised on the patch's own tab and once on
    the summary tab — and the two are maintained separately. Agreement is therefore real
    evidence that the patch tabs were read correctly.

    The summary's per-version rows carry no headers, so the column is **found by agreement**:
    the one column that reproduces the patch tabs across every version. That is not circular.
    A misparse of the patch tabs makes *no* column agree, and the refresh refuses.
    """
    gid = next((gid for name, gid in tabs if name.strip().lower() == "summary"), None)
    if gid is None:
        raise RefreshError("workbook has no `summary` tab to cross-check against")

    summary = _summary_rows(_rows(gid))
    shared = [entry for entry in income if entry.version in summary]
    if len(shared) < MIN_SUMMARY_OVERLAP:
        raise RefreshError(
            f"summary tab names only {len(shared)} of {len(income)} versions; too few to "
            "cross-check, so the patch tabs would be going unverified"
        )

    width = min(len(summary[entry.version]) for entry in shared)
    scored = [
        (
            sum(
                abs(summary[entry.version][column] - entry.f2p) <= SUMMARY_TOLERANCE
                for entry in shared
            ),
            column,
        )
        for column in range(width)
    ]
    agreements, column = max(scored)
    share = agreements / len(shared)
    if share < MIN_SUMMARY_AGREEMENT:
        worst = max(
            shared,
            key=lambda entry: min(
                abs(value - entry.f2p) for value in summary[entry.version][:width]
            ),
        )
        raise RefreshError(
            f"the best-matching column of the summary tab agrees with the patch tabs on only "
            f"{agreements}/{len(shared)} versions ({share:.0%}), below the "
            f"{MIN_SUMMARY_AGREEMENT:.0%} floor — the layout has probably shifted and the "
            f"patch tabs cannot be trusted. Worst version {worst.version}: patch tab says "
            f"{worst.f2p:.2f}, summary row holds "
            f"{[round(value, 2) for value in summary[worst.version][:width]]}"
        )

    differing = [
        f"{entry.version} (patch {entry.f2p:.2f} vs summary {summary[entry.version][column]:.2f})"
        for entry in shared
        if abs(summary[entry.version][column] - entry.f2p) > SUMMARY_TOLERANCE
    ]
    if differing:
        print(f"  note: summary tab differs on {', '.join(differing)} — see MIN_SUMMARY_AGREEMENT")


def _check_subscriptions(income: list[VersionIncome]) -> None:
    """Invariant 3: Welkin and the paid Battle Pass are fixed, so they must not vary."""
    for label, values in (
        ("welkin", [entry.welkin - entry.f2p for entry in income]),
        ("battle pass", [entry.welkin_bp - entry.welkin for entry in income]),
    ):
        spread = max(values) - min(values)
        if spread > SUBSCRIPTION_TOLERANCE:
            raise RefreshError(
                f"{label} is a fixed subscription but varies by {spread:.3f} wishes across "
                f"patches ({min(values):.3f}..{max(values):.3f}); the layout may have shifted"
            )


def write_snapshot(income: list[VersionIncome], fetched_at: datetime) -> None:
    """Rewrite the committed seed so a fresh clone needs no network."""
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(
            {
                "note": (
                    "Wish income per Genshin version at three spending tiers, in wishes. "
                    "Written by scripts/refresh_wish_income.py from the community "
                    "bookkeeping workbook; see that script and "
                    "docs/RESEARCH_wish_planner.md section 10. This file is the committed "
                    "seed so that a fresh clone and the test suite need no network -- the "
                    "live store is the wish_income table, refreshed on a timer."
                ),
                "document_id": DOCUMENT_ID,
                "fetched_at": fetched_at.isoformat(),
                "versions": [
                    {
                        "version": entry.version,
                        "major": entry.major,
                        "minor": entry.minor,
                        "is_estimate": entry.is_estimate,
                        "f2p": round(entry.f2p, 4),
                        "welkin": round(entry.welkin, 4),
                        "welkin_bp": round(entry.welkin_bp, 4),
                    }
                    for entry in income
                ],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


def load_snapshot() -> tuple[list[VersionIncome], datetime]:
    """Read the committed seed. Used to fill an empty table without touching the network."""
    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    income = [
        VersionIncome(
            version=entry["version"], major=entry["major"], minor=entry["minor"],
            is_estimate=entry["is_estimate"],
            f2p=entry["f2p"], welkin=entry["welkin"], welkin_bp=entry["welkin_bp"],
        )
        for entry in raw["versions"]
    ]
    return income, datetime.fromisoformat(raw["fetched_at"])


async def store(
    session: AsyncSession, income: list[VersionIncome], fetched_at: datetime
) -> int:
    """Replace the table with `income`, refusing an implausible shrink."""
    existing = len((await session.execute(WishIncome.__table__.select())).all())
    incoming = len(income) * len(TIERS)
    if existing and incoming < existing * MIN_RETAINED_SHARE:
        raise RefreshError(
            f"REFUSED: the workbook returned {incoming} rows against {existing} stored. "
            "A truncated but valid response looks exactly like a real retraction, so this "
            "writes nothing. Re-run once the source is healthy, or clear the table by hand "
            "if the shrink is genuine."
        )

    await session.execute(delete(WishIncome))
    session.add_all(
        [
            WishIncome(
                version=entry.version, major=entry.major, minor=entry.minor, tier=tier,
                wishes=entry.wishes(tier), is_estimate=entry.is_estimate, fetched_at=fetched_at,
            )
            for entry in income
            for tier in TIERS
        ]
    )
    await session.commit()
    return incoming


async def _main(arguments: argparse.Namespace) -> int:
    fetched_at = datetime.now(UTC)
    if arguments.from_snapshot:
        income, fetched_at = load_snapshot()
        print(f"loaded {len(income)} versions from the committed snapshot")
    else:
        print("reading the bookkeeping workbook…")
        income = fetch_income()
        print(f"read {len(income)} versions, all three invariants hold")

    latest = income[-1]
    print(
        f"  {income[0].version} … {latest.version}"
        f"{' (estimate)' if latest.is_estimate else ''}    "
        f"latest: f2p {latest.f2p:.1f}, welkin {latest.welkin:.1f}, "
        f"welkin+bp {latest.welkin_bp:.1f}"
    )

    if arguments.dry_run:
        print("dry run: nothing written")
        return 0

    if not arguments.from_snapshot:
        write_snapshot(income, fetched_at)
        print(f"wrote {SNAPSHOT.relative_to(SNAPSHOT.parents[3])}")

    if arguments.snapshot_only:
        return 0

    async with async_session_factory() as session:
        written = await store(session, income, fetched_at)
    print(f"stored {written} rows in wish_income")
    return 0


def main() -> int:
    """Entry point: refresh the store, or explain why it refused to."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and check, write nothing"
    )
    parser.add_argument("--snapshot-only", action="store_true", help="skip the database")
    parser.add_argument(
        "--from-snapshot", action="store_true",
        help="seed the database from the committed snapshot, with no network access",
    )
    arguments = parser.parse_args()
    try:
        return asyncio.run(_main(arguments))
    except RefreshError as error:
        print(f"refresh refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
