"""Build the committed catalog of `ExcelBinOutput/` tables at the pinned commit.

    cd backend && python -m scripts.yuanshen.build_table_catalog [--check]

**Why a catalog rather than a list in someone's head.** There are **1,935** tables. DESIGN
§3's Chunk E sketch names five it expects to want (`AvatarExcelConfigData`,
`WeaponExcelConfigData`, `ReliquaryExcelConfigData`, `AvatarSkillExcelConfigData`,
`AvatarTalentExcelConfigData`) and the instruction beside them is "build the table catalog
first rather than guessing names" — because a guessed table name that does not exist is a
404 you notice, and a guessed table name that *does* exist and holds something else is a
bug you ship. E.5's snapshot builder resolves every table it reads through this file.

Each entry records the blob id GitLab reports, so re-pinning shows **which tables changed**
rather than only that the commit did. `--check` reports drift without writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from scripts.yuanshen.fetch import SCHEMA_DIR, list_tree, pinned_sha

CATALOG_PATH = SCHEMA_DIR / "table_catalog.json"

#: The directory this catalogs. TextMap is handled by `fetch.load_textmap`, and the other
#: four top-level directories (`BinOutput`, `Readables`, `DialogsText`, `Subtitle`) hold
#: no config tables.
TABLE_DIR = "ExcelBinOutput"

_SUFFIX = ".json"


def build(sha: str | None = None) -> dict[str, Any]:
    """Fetch the tree and shape it into the catalog record."""
    sha = sha or pinned_sha()
    entries = list_tree(TABLE_DIR, sha)
    tables = {
        entry["name"].removesuffix(_SUFFIX): entry["id"]
        for entry in sorted(entries, key=lambda item: item["name"])
        if entry["type"] == "blob" and entry["name"].endswith(_SUFFIX)
    }
    non_json = sorted(
        entry["name"] for entry in entries
        if entry["type"] != "blob" or not entry["name"].endswith(_SUFFIX)
    )
    return {
        "pinned_commit_sha": sha,
        "directory": TABLE_DIR,
        "table_count": len(tables),
        "note": (
            "table name (without .json) -> the blob id GitLab reports at this commit. "
            "Re-pinning and re-running shows which tables changed, not just that the "
            "commit did. Built by scripts/yuanshen/build_table_catalog.py; do not edit."
        ),
        "non_table_entries": non_json,
        "tables": tables,
    }


def table_names(sha: str | None = None) -> set[str]:
    """Every table name in the committed catalog, for callers that resolve names."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if sha is not None and catalog["pinned_commit_sha"] != sha:
        msg = (
            f"table_catalog.json is for {catalog['pinned_commit_sha'][:12]}, not "
            f"{sha[:12]} — rebuild it before resolving names against another commit."
        )
        raise ValueError(msg)
    return set(catalog["tables"])


def main() -> int:
    """Parse arguments and build (or check) the catalog."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", default=None, help="override the pinned commit SHA")
    parser.add_argument(
        "--check", action="store_true", help="report drift without writing; exit 1 if any",
    )
    args = parser.parse_args()

    catalog = build(args.sha)
    body = json.dumps(catalog, indent=1, ensure_ascii=False) + "\n"
    print(f"{catalog['directory']}: {catalog['table_count']:,} tables at "
          f"{catalog['pinned_commit_sha'][:12]}")

    existing = CATALOG_PATH.read_text(encoding="utf-8") if CATALOG_PATH.exists() else None
    if args.check:
        if existing == body:
            print("catalog matches upstream")
            return 0
        _report_drift(existing, catalog)
        return 1
    CATALOG_PATH.write_text(body, encoding="utf-8")
    print(f"  {'unchanged' if existing == body else 'written'}: {CATALOG_PATH.name}")
    return 0


def _report_drift(existing: str | None, catalog: dict[str, Any]) -> None:
    if existing is None:
        print("no committed catalog to compare against", file=sys.stderr)
        return
    before = json.loads(existing)["tables"]
    after = catalog["tables"]
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    print(
        f"DRIFT: +{len(added)} tables, -{len(removed)} tables, {len(changed)} changed",
        file=sys.stderr,
    )
    for label, names in (("added", added), ("removed", removed), ("changed", changed)):
        for name in names[:20]:
            print(f"  {label}: {name}", file=sys.stderr)
        if len(names) > 20:  # noqa: PLR2004 - a display cutoff
            print(f"  … {len(names) - 20} more {label}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
