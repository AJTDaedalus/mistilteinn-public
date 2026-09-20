"""Check the committed implemented-action table by asking gcsim, one action at a time.

    cd backend && python -m scripts.gcsim.probe_implemented_actions --bin /path/to/gcsim

`build_key_snapshot` derives `character_implemented_actions` by reading which action methods
each character's Go package defines. That is a parse, and a parse can be confidently wrong:
gcsim refuses some actions at **run time**, inside a method that exists
(`traveler/common/cryo/plunge.go:67` — `if c.gender == 0`). Those cases are carried as
`_RUNTIME_REFUSALS` in the builder, and **this script is where that list comes from**.

Run it at every re-pin, after rebuilding the snapshot. It needs a native gcsim binary built
at the pin:

    git -C <clone> checkout <the pin in docs/CROSSVAL_gcsim.md>
    go build -o /tmp/gcsim ./cmd/gcsim

**Read the message, do not match on it.** gcsim's own refusal text is not always right —
pyro's *high* plunge refuses with `action low_plunge not implemented`
(`common/pyro/plunge.go:128`), so a probe that matches the action it asked about records that
one as working. This script reports any "not implemented" refusal and prints the message it
got, so the reader sees the mismatch rather than a boolean that has already swallowed it.

Exit code is 1 if gcsim and the committed table disagree, so it can gate a re-pin.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO / "backend" / "app" / "data" / "gcsim" / "keys.json"

#: The seven a character's package can override. `dash`, `jump`, `walk` and `swap` are
#: handled outside the character, so no character can fail to implement one.
CHECKABLE = ("attack", "aim", "charge", "high_plunge", "low_plunge", "skill", "burst")

#: A one-action config. The weapon is a Dull Blade because every character can hold one for
#: the purpose of this question, and no passive can change whether an action exists.
_CONFIG = """options iteration=1 duration=1 debug=false;
{key} char lvl=90/90 cons=0 talent=1,1,1;
{key} add weapon="dullblade" lvl=1/20 refine=1;
target lvl=90 resist=0.1 pos=0,1;
active {key};
{key} {action};
"""


def _probe(binary: str, key: str, action: str) -> tuple[str, str, bool, str]:
    """`(key, action, refused_as_unimplemented, gcsim's message)`."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write(_CONFIG.format(key=key, action=action))
        path = handle.name
    run = subprocess.run(  # noqa: S603 — a local binary the caller named
        [binary, "-c", path, "-nb", "-out", "/dev/null"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    message = ((run.stdout or "") + (run.stderr or "")).strip().splitlines()
    first = message[0] if message else ""
    # Any "not implemented" refusal counts, whichever action it names — see the module
    # docstring. A sequencing complaint ("need to use attack right before charge", "can only
    # be used while airborne") means the action exists.
    return key, action, "not implemented" in first, first


def main() -> int:
    """Probe every pair and report where gcsim disagrees with the committed table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", required=True, help="a gcsim binary built at the pin")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    table = json.loads(SNAPSHOT.read_text())["character_implemented_actions"]
    jobs = [(key, action) for key in sorted(table) for action in CHECKABLE]
    print(f"probing {len(jobs)} character/action pairs against {args.bin}")

    disagreements = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for key, action, refused, message in pool.map(
            lambda job: _probe(args.bin, *job), jobs,
        ):
            committed = action in table[key]
            if committed is refused:
                disagreements.append((key, action, committed, message))

    if not disagreements:
        print(f"the committed table matches gcsim on all {len(jobs)} pairs")
        return 0

    print(f"\n{len(disagreements)} disagreements — the snapshot says one thing, gcsim another:")
    for key, action, committed, message in disagreements:
        says = "implements" if committed else "does not implement"
        print(f"  {key:22} {action:12} snapshot {says}; gcsim said: {message}")
    print(
        "\nIf gcsim refuses an action whose method exists, add it to `_RUNTIME_REFUSALS` in "
        "scripts/gcsim/build_key_snapshot.py with the file and line that refuses it.",
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
