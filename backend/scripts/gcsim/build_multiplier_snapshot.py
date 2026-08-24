"""Derive gcsim's talent-multiplier tables from the pinned source, as a committed snapshot.

    cd backend && python -m scripts.gcsim.build_multiplier_snapshot --src /path/to/gcsim

**What this is for.** `app/services/talent_scaling.py` parses multipliers out of nanoka's
`desc` format strings, and the rule that decides which rows are damage is *"the label contains
DMG"* — a heuristic over English text. gcsim implements the same characters independently, so
agreeing with it turns that heuristic into a checked claim (`TASKS_multipliers.md` M.4).

**The comment is the anchor, not the variable.** gcsim's per-character data files are
generated, and each table carries the row it came from:

    // burst: KamisatoArtSoumetsu - Cutting DMG: {0}
    burstCut = []float64{ 1.123, 1.207225, … }

    // attack: KamisatoArtKabuki - Low/High Plunge DMG: {10}/{11}
    lowPlunge  = []float64{ 1.278377, … }
    highPlunge = []float64{ 1.596762, … }

That comment names the action, the source label, the **0-based** param index and any tail.
Anchoring on it handles both shapes uniformly — a top-level `= []float64{…}` and a block
nested inside `attack = [][][]float64{`, where there is no variable to key on at all.

**Committed, never fetched at runtime.** The rule `app/data/yuanshen/` and the key snapshot
both follow: this reads a local clone at the pin and writes a JSON artifact that ships with
the repo, so no test needs gcsim's source or the network.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CROSSVAL_DOC = REPO / "docs" / "CROSSVAL_gcsim.md"
OUT = REPO / "backend" / "app" / "data" / "gcsim" / "talent_multipliers.json"

#: `// attack: KamisatoArtKabuki - Low/High Plunge DMG: {10}/{11}`
_COMMENT = re.compile(r"//\s*(\w+):\s*(\w+)\s*-\s*(.+?):\s*\{(\d+)\}(.*)$")
#: One value of a `[]float64` literal, one per line as the generator writes them.
_FLOAT = re.compile(r"^\s*(-?\d+(?:\.\d+)?(?:e-?\d+)?),?\s*$")
#: How far past the comment the values may start: `name = []float64{` or a bare `{`.
_DECLARATION_LINES = 2


def declared_pin() -> str:
    """The gcsim commit `docs/CROSSVAL_gcsim.md` pins."""
    found = re.search(r"\b([0-9a-f]{40})\b", CROSSVAL_DOC.read_text())
    if found is None:
        msg = f"no 40-character commit sha found in {CROSSVAL_DOC}"
        raise SystemExit(msg)
    return found.group(1)


def _tables(path: Path) -> list[dict]:
    """Every multiplier table in one character's generated file.

    Duplicates are kept out: gcsim writes a `×3` hit as three identical frames, each with the
    same comment, and three copies of one array is not three tables.
    """
    lines = path.read_text().splitlines()
    seen: set[tuple] = set()
    found: list[dict] = []
    for index, line in enumerate(lines):
        comment = _COMMENT.search(line)
        if comment is None:
            continue
        action, skill, label, param_index, tail = comment.groups()

        # Collect the numbers that follow. A declaration line — `name = []float64{`, or a
        # bare `{` inside the nested attack table — may sit between the comment and them, so
        # a bounded number of non-numeric lines is tolerated **before** the first value and
        # none after it.
        values: list[float] = []
        skipped = 0
        for follow in lines[index + 1 :]:
            number = _FLOAT.match(follow)
            if number is not None:
                values.append(float(number.group(1)))
                continue
            if values:
                break
            skipped += 1
            if skipped > _DECLARATION_LINES:
                break
        if not values:
            continue

        key = (action, label.strip(), int(param_index), tuple(values))
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "action": action,
            "skill": skill,
            "label": label.strip(),
            # gcsim's index is **0-based**; nanoka's `paramN` is 1-based. Recorded as gcsim
            # writes it, and converted where it is compared, so neither side is silently
            # rewritten here.
            "param_index": int(param_index),
            "tail": tail.strip(),
            "values": values,
        })
    return found


def main() -> None:
    """Write the multiplier snapshot from a gcsim clone."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True, help="a gcsim clone")
    args = parser.parse_args()

    pin = declared_pin()
    head = subprocess.run(  # noqa: S603 - fixed argv, path from the operator
        ["git", "-C", str(args.src), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if head != pin:
        msg = (
            f"the clone is at {head} but docs/CROSSVAL_gcsim.md pins {pin}. "
            f"Check out the pin, or re-pin deliberately."
        )
        raise SystemExit(msg)

    characters: dict[str, list[dict]] = defaultdict(list)
    for data_file in sorted((args.src / "internal" / "characters").glob("*/zz_*.dm.go")):
        # The file is named for gcsim's config key: `zz_kamisatoayaka.dm.go`.
        key = data_file.name.removeprefix("zz_").removesuffix(".dm.go")
        tables = _tables(data_file)
        if tables:
            characters[key] = tables

    if not characters:
        msg = f"no multiplier tables found under {args.src}/internal/characters"
        raise SystemExit(msg)

    snapshot = {
        "pinned_commit_sha": pin,
        "source": "github.com/genshinsim/gcsim — internal/characters/*/zz_*.dm.go",
        "note": (
            "Talent multiplier tables, one row per talent level, keyed by gcsim's config key. "
            "`param_index` is gcsim's own 0-based index into nanoka's `param` list; nanoka "
            "spells the same thing 1-based as `paramN`. Generated by "
            "scripts/gcsim/build_multiplier_snapshot.py; do not edit by hand."
        ),
        "characters": dict(sorted(characters.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, separators=(",", ":"), sort_keys=False) + "\n")

    tables = sum(len(v) for v in characters.values())
    print(f"wrote {OUT.relative_to(REPO)} at {pin}: {len(characters)} characters, {tables} tables")


if __name__ == "__main__":
    main()
