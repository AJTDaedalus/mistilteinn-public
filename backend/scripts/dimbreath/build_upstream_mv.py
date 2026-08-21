"""Snapshot the upstream multipliers that kit JSONs hand-transcribe (issue #165).

Some damage-bearing skill rows exist upstream but are **never seeded**: nanoka publishes
only the moves the in-game skill panel lists, so a move that has no panel entry has no
`attacks` row, and every DB-backed check is structurally unable to see it. Remielle's
Phase Flow flight attacks are the case that surfaced this — `lumiflux.flight_attack_mv_bp`
is a hand-copy of upstream rows 1581022/1581023/1581024, and L4/L5 cannot verify a number
whose DB row does not exist. Right today, and nothing catches it drifting.

This script closes that by turning the hand-copy into a *checked* copy: it reads the
`upstream_mv_checks` declarations out of the kit JSONs, pulls those skill rows from
Dimbreath at the **pinned** SHA, and writes them to
`app/data/validation/upstream_skill_mv.json`. `validate_kits.py`'s L6 then diffs the
authored tuples against that snapshot on every run — offline, no DB, no network.

The split matters: fetching is a manual step with a network dependency, so it must not
sit inside the gate (a flaky gate trains reviewers to wave it through — CLAUDE.md). The
gate reads a committed artifact; only regeneration touches the network.

Nothing here is hand-written. The column hashes rotate per patch, so the value columns are
re-derived every run by value-matching against DB attack anchors, and the script refuses
to write a snapshot if any of them fails to reproduce its anchor (a wrong column would
publish plausible wrong numbers into the gate, which is worse than no gate).

Run::

    cd backend && python -m scripts.dimbreath.build_upstream_mv          # write
    cd backend && python -m scripts.dimbreath.build_upstream_mv --check  # verify, no write
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.dimbreath.columns import (
    MATCH_THRESHOLD,
    column_value_match,
    confident_map,
    unique_key_column,
    wrapper_rows,
)
from scripts.dimbreath.fetch import SCHEMA_DIR, fetch_json, pinned_sha

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODIFIERS_DIR = BACKEND_ROOT / "app" / "data" / "modifiers"
OUT_PATH = BACKEND_ROOT / "app" / "data" / "validation" / "upstream_skill_mv.json"

TABLE = "FileCfg/AvatarSkillTemplateTb.json"
_ANCHOR_PATH = SCHEMA_DIR / "_db_attack_anchors.json"

# The declaration key a kit uses to say "these numbers are copied from upstream".
DECLARATION_KEY = "upstream_mv_checks"

# Every field the snapshot carries per skill row. `damage_*` and `stun_*` are what L6
# compares against; the other two are recorded because they are the fields that would
# tell a future reader whether an unseeded row is inert (see the 1581001 / 1581025
# ledger entries) — snapshotting them costs nothing and re-deriving them costs a fetch.
VALUE_FIELDS = [
    "damage_base",
    "damage_growth",
    "stun_base",
    "stun_growth",
    "energy_gain",
    "anomaly_buildup",
]


def _load_anchors() -> dict[int, dict[str, Any]]:
    doc = json.loads(_ANCHOR_PATH.read_text())
    return {a["skill_id"]: a for a in doc["attacks"]}


def declared_skill_ids() -> tuple[set[int], list[str]]:
    """Every skill id any kit declares, plus the kits that declared them.

    Derived from the kits rather than hand-listed: a snapshot whose contents are
    maintained separately from its consumers drifts out from under them, and the failure
    is silent (the id simply stops being checked).
    """
    ids: set[int] = set()
    sources: list[str] = []
    for path in sorted(MODIFIERS_DIR.rglob("*.json")):
        kit = json.loads(path.read_text())
        checks = kit.get(DECLARATION_KEY) or []
        if not checks:
            continue
        sources.append(str(path.relative_to(MODIFIERS_DIR)))
        for check in checks:
            ids.update(int(sid) for sid in check.get("skill_ids", []))
    return ids, sources


def build_snapshot() -> dict[str, Any]:
    """Fetch, re-derive the column map, and assemble the snapshot document."""
    ids, sources = declared_skill_ids()
    if not ids:
        raise SystemExit(
            f"no kit declares `{DECLARATION_KEY}` — nothing to snapshot "
            "(the snapshot's contents come from the kits that consume it)"
        )

    rows = wrapper_rows(fetch_json(TABLE))
    anchors = _load_anchors()
    key_col = unique_key_column(rows, anchors)

    report = column_value_match(rows, key_col, anchors, VALUE_FIELDS)
    field_to_col = {field: col for col, field in confident_map(report).items()}
    missing = [f for f in VALUE_FIELDS if f not in field_to_col]
    if missing:
        raise SystemExit(
            f"could not re-derive {missing} against DB anchors at or above "
            f"{MATCH_THRESHOLD:.0%} — refusing to write a snapshot from an unverified "
            "column map (the hashes rotate; re-capture anchors after a reseed)"
        )

    by_id = {row[key_col]: row for row in rows}
    unknown = sorted(sid for sid in ids if sid not in by_id)
    if unknown:
        raise SystemExit(
            f"declared skill ids absent from {TABLE} at {pinned_sha()[:12]}: {unknown} — "
            "either the citation is wrong or the pin predates the patch that added them"
        )

    skills = {
        str(sid): {field: by_id[sid][col] for field, col in field_to_col.items()}
        for sid in sorted(ids)
    }
    return {
        "_meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "pinned_sha": pinned_sha(),
            "table": "AvatarSkillTemplateTb",
            "key_column": key_col,
            "columns": field_to_col,
            "anchor_ratios": {
                field: round(report[col]["ratio"], 4) for field, col in field_to_col.items()
            },
            "anchor_source": "schema/_db_attack_anchors.json (DB Attack rows)",
            "declared_by": sources,
            "note": (
                "Upstream multipliers for skill rows that are cited by a kit but never "
                "seeded (nanoka publishes only panel-listed moves). Read by "
                "validate_kits L6. Regenerate with "
                "`python -m scripts.dimbreath.build_upstream_mv`; never hand-edit — the "
                "column hashes rotate per patch and are re-derived from anchors on "
                "every run."
            ),
        },
        "skills": skills,
    }


def main() -> int:
    """Write (or, with ``--check``, verify) the committed upstream snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-derive and compare against the committed snapshot; write nothing",
    )
    args = parser.parse_args()

    doc = build_snapshot()
    if args.check:
        if not OUT_PATH.is_file():
            print(f"{OUT_PATH.name} does not exist", file=sys.stderr)
            return 1
        current = json.loads(OUT_PATH.read_text())
        drifted = current.get("skills") != doc["skills"] or current["_meta"].get(
            "pinned_sha"
        ) != doc["_meta"]["pinned_sha"]
        if drifted:
            print(
                "upstream snapshot is out of date — re-run without --check",
                file=sys.stderr,
            )
            return 1
        print(f"upstream snapshot matches Dimbreath at {doc['_meta']['pinned_sha'][:12]}")
        return 0

    OUT_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(
        f"wrote {OUT_PATH.relative_to(BACKEND_ROOT)}: {len(doc['skills'])} skill row(s) "
        f"at {doc['_meta']['pinned_sha'][:12]}, declared by "
        f"{', '.join(doc['_meta']['declared_by'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
