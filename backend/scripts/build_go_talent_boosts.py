"""Derive which talent each character's C3 and C5 raise, from Genshin Optimizer's sheets.

    cd backend && python -m scripts.build_go_talent_boosts --src /path/to/genshin-optimizer

The second source for `app/services/talent_boosts.py` (math-fallback 9b). gcsim's is in
`app/data/gcsim/keys.json:character_talent_boosts`, derived by
`scripts/gcsim/build_key_snapshot.py`; this one covers the characters gcsim has not
implemented, and is the comparator `tests/unit/test_talent_boosts.py` holds gcsim's against
for every character both know.

GO's character sheets state the boost as a node and a key, in the same file:

    const nodeC3 = greaterEq(input.constellation, 3, 3)
    ...
      burstBoost: nodeC3,

`libs/gi/sheets/src/Characters/<Key>/*.tsx` at `GO_COMMIT`. **Only constellation nodes
count**: Tartaglia's `autoBoost: nodePassive` and the skill boosts two other kits grant the
whole team from a passive are talent-level effects too, but not constellation ones, and they
are not this table's question.

**Committed, never fetched at runtime** — the same rule as every snapshot under `app/data/`.
The clone must be at `GO_COMMIT`, the commit every sheet under `app/data/formula/sheets/`
cites; a snapshot from another commit is refused rather than recorded.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "backend" / "app" / "data" / "formula" / "talent_boosts_go.json"

#: The commit the kit sheets cite (`app/data/formula/sheets/*.json:go_commit`) and D-F4's
#: GO fixtures were worked at.
GO_COMMIT = "2c13fc40c4694fd8beae513493c4c8a7537173c6"
SHEETS = Path("libs/gi/sheets/src/Characters")

_NODE = re.compile(
    r"const (\w+)\s*=\s*greaterEq\(\s*input\.constellation,\s*(\d)\s*,\s*3\s*\)",
)
_USE = re.compile(r"\b(auto|skill|burst)Boost:\s*(\w+)")
_TALENT = {"auto": "normal_attack", "skill": "elemental_skill", "burst": "elemental_burst"}


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def boosts_in(directory: Path, root: Path) -> dict[str, dict[str, object]]:
    """`{talent: {constellation, go}}` for one character's sheet directory."""
    found: dict[str, dict[str, object]] = {}
    for source in sorted(directory.glob("*.tsx")):
        text = source.read_text()
        nodes = {
            m.group(1): (int(m.group(2)), _line(text, m.start())) for m in _NODE.finditer(text)
        }
        for use in _USE.finditer(text):
            node = nodes.get(use.group(2))
            if node is None:
                continue  # a passive's boost, not a constellation's
            talent = _TALENT[use.group(1)]
            if talent in found:
                msg = f"{directory.name}: two constellation boosts to {talent}"
                raise SystemExit(msg)
            constellation, defined = node
            where = source.relative_to(root)
            found[talent] = {
                "constellation": constellation,
                "go": f"{where}:{defined},{_line(text, use.start())}",
            }
    return dict(sorted(found.items()))


def main() -> None:
    """Write the GO talent-boost snapshot from a clone at `GO_COMMIT`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True, help="a genshin-optimizer clone")
    args = parser.parse_args()
    head = subprocess.run(  # noqa: S603 - fixed argv, path from the operator
        ["git", "-C", str(args.src), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if head != GO_COMMIT:
        msg = f"the clone is at {head}; the sheets cite GO {GO_COMMIT}. Check that out."
        raise SystemExit(msg)

    characters: dict[str, dict[str, dict[str, object]]] = {}
    for directory in sorted((args.src / SHEETS).iterdir()):
        if not directory.is_dir():
            continue
        boosts = boosts_in(directory, args.src)
        if directory.name.startswith("Traveler") and not boosts:
            continue  # the shared template, and the M bodies, which reuse the F element file
        if not boosts:
            # Recorded, not skipped: a sheet that models no boost is a statement (Aloy's
            # constellations are placeholders), and the comparison with gcsim must see it.
            characters[directory.name] = {}
            continue
        if sorted(b["constellation"] for b in boosts.values()) != [3, 5]:
            msg = f"{directory.name}: expected one talent at C3 and one at C5, parsed {boosts}"
            raise SystemExit(msg)
        characters[directory.name] = boosts

    snapshot = {
        "go_commit": GO_COMMIT,
        "source": f"github.com/frzyc/genshin-optimizer — {SHEETS}/<Key>/*.tsx (MIT)",
        "note": (
            "Which talent each character's C3 and C5 raise by three, keyed by GO's sheet "
            "directory. `go` is file:line of the `greaterEq(input.constellation, N, 3)` node, "
            "then of the `<talent>Boost:` key it feeds. Generated by "
            "scripts/build_go_talent_boosts.py; do not edit by hand."
        ),
        "characters": characters,
    }
    OUT.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(REPO)} at GO {GO_COMMIT[:12]}: {len(characters)} sheets")


if __name__ == "__main__":
    main()
