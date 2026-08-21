"""Re-capture the committed nanoka GI fixtures from the pinned upstream version.

    cd backend && python -m scripts.capture_nanoka_fixtures [--version 7.0.51] [--check]

`tests/fixtures/nanoka_gi/` is ground truth for every enum, model and mapping in this
repo: C.2's enums, C.3-C.6's columns and D.3-D.6's mappings are all derived from those
files rather than from a live call or from memory. That only works if the derivation is
reproducible, so the capture is a script rather than a shell history — the same reason
`harvest_nanoka_vocabulary.py` exists, and the reason re-running it and getting a
byte-identical file was the check that C.2's vocabulary was derived correctly.

**What gets captured is the list below, not whatever the script is asked for.** Adding a
fixture means editing `INDEXES` / `DETAILS` in a reviewable commit that says why the new
payload is needed, which keeps the fixture directory from accreting drive-by downloads.

`--check` re-fetches and reports whether the committed bytes still match upstream without
writing anything. A mismatch is a *finding*, not a failure: nanoka republishes payloads
within a patch. Refresh deliberately, as its own commit, with `PROVENANCE.md` updated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.data.importers.nanoka_gi_importer import HttpNanokaTransport

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nanoka_gi"

#: The entity indexes committed under `tests/fixtures/nanoka_gi/`.
INDEXES: tuple[str, ...] = ("character", "weapon", "artifact", "monster")

#: The detail payloads committed under `tests/fixtures/nanoka_gi/detail/`, with the reason
#: each one is there. Every mapping task reads these instead of guessing at the shape.
DETAILS: tuple[tuple[str, str, str], ...] = (
    ("character", "10000002", "Ayaka — four skills, so talent type cannot be positional"),
    ("character", "10000005-2", "Pyro Traveler — the 28 string-keyed variant entries"),
    ("weapon", "11501", "Aquila Favonia — 5-star sword, full refinement ladder"),
    ("artifact", "15025", "Marechaussee Hunter — an ordinary [2, 4] set"),
    ("monster", "21010101", "Hilichurl — the baseline enemy shape, uniform 10% RES"),
    ("monster", "24010101", "Ruin Guard — 70% physical RES, so RES is not a constant"),
)

#: How C.1/C.2 wrote the committed files, recovered by matching their bytes rather than
#: assumed: indexes are `indent=2, ensure_ascii=False`, details `indent=1,
#: ensure_ascii=True`, and **neither ends in a newline**. The two differ because they were
#: captured by different one-off commands; reproducing them byte for byte is what makes a
#: re-capture a diff of the *data* rather than a diff of the formatting, which matters more
#: than the inconsistency does. Normalising them would be a whitespace-only diff across
#: 900 KB of ground truth.
_INDEX_DUMP = {"indent": 2, "ensure_ascii": False}
_DETAIL_DUMP = {"indent": 1, "ensure_ascii": True}


def _serialize(payload: dict, style: dict) -> str:
    return json.dumps(payload, **style)  # type: ignore[arg-type]


def _index_path(entity: str) -> Path:
    return FIXTURE_DIR / f"{entity}.json"


def _detail_path(entity: str, key: str) -> Path:
    return FIXTURE_DIR / "detail" / f"{entity}_{key}.json"


async def capture(version: str | None, *, check_only: bool) -> int:
    """Fetch every declared fixture; write it, or report drift. Returns an exit code."""
    transport = HttpNanokaTransport(version=version)
    drifted: list[str] = []
    try:
        pinned = await transport.resolve_version()
        print(f"nanoka GI version {pinned}")
        for entity in INDEXES:
            payload = await transport.fetch_index(entity)
            drifted += _emit(
                _index_path(entity),
                _serialize(payload, _INDEX_DUMP),
                len(payload),
                check_only=check_only,
            )
        for entity, key, _why in DETAILS:
            payload = await transport.fetch_detail(entity, key)
            drifted += _emit(
                _detail_path(entity, key),
                _serialize(payload, _DETAIL_DUMP),
                None,
                check_only=check_only,
            )
    finally:
        await transport.close()

    if check_only and drifted:
        print(f"\n{len(drifted)} fixture(s) differ from upstream:", file=sys.stderr)
        for name in drifted:
            print(f"  {name}", file=sys.stderr)
        print(
            "\nThis is a finding, not a failure: refresh deliberately, as its own commit, "
            "with PROVENANCE.md updated.",
            file=sys.stderr,
        )
        return 1
    return 0


def _emit(path: Path, body: str, entries: int | None, *, check_only: bool) -> list[str]:
    """Write `body` to `path`, or compare against it. Returns the drifted paths."""
    label = path.relative_to(FIXTURE_DIR)
    count = "" if entries is None else f", {entries} entries"
    existing = path.read_text() if path.exists() else None
    if check_only:
        state = "MATCH" if existing == body else "DRIFT"
        print(f"  {state} {label} ({len(body):,} bytes{count})")
        return [] if existing == body else [str(label)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    state = "unchanged" if existing == body else ("new" if existing is None else "updated")
    print(f"  {state:>9} {label} ({len(body):,} bytes{count})")
    return []


def main() -> int:
    """Parse arguments and run the capture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=None,
        help="nanoka GI version to capture (default: pin manifest.json -> gi.latest)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift against upstream without writing; exits 1 if anything differs",
    )
    args = parser.parse_args()
    return asyncio.run(capture(args.version, check_only=args.check))


if __name__ == "__main__":
    raise SystemExit(main())
