"""Import every config in gcsim's database, and report what this app can do with them.

`TASKS_rotation_language.md` Phase 11. **The measurement tool, not a CI gate** — the corpus
is not committed, because gcsim's database states no licence for submitted configs
(`references/gcsim_db/PROVENANCE.md`). CI runs the synthetic construct suite beside this
file plus the five vendored configs; this is what a person runs when they want the real number.

    cd backend && python -m scripts.sweep_gcsim_db --fetch      # pull, then measure
    cd backend && python -m scripts.sweep_gcsim_db              # measure what is cached

**Polite by construction.** The `/api/db` endpoint returns each config inline, so one request
yields a page of them rather than one each: five requests, a second apart, with an identifying
User-Agent. Pulling 500 configs costs gcsim five requests.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from app.schemas.rotation_nodes import RawNode
from app.services.gcsim_emitter import emit_tree
from app.services.gcsim_parser import parse_rotation, split_config
from app.services.rotation_diagnostics import Severity, validate_rotation

#: Where a fetched corpus lives. Gitignored — see the module docstring on licensing.
CORPUS = Path(__file__).resolve().parent.parent / "var" / "gcsim_corpus"

#: The only host this script will open. A constant, checked before every request.
#:
#: `gcsim_share.py` makes the same argument for the import endpoint and it applies here too: a
#: fetcher that will open whatever URL it is handed is a request-forgery primitive, and the
#: fact that this one builds its own URL today is not a property anybody can see from the call
#: site tomorrow.
HOST = "https://gcsim.app/"
UA = "mistilteinn-importer-test/1.0 (+github.com/AJTDaedalus/mistilteinn)"
PAGE = 100
DELAY = 1.0


def fetch(pages: int) -> int:
    """Pull `pages` pages of configs into `CORPUS`, returning how many were saved."""
    CORPUS.mkdir(parents=True, exist_ok=True)
    saved = 0
    for page in range(pages):
        query = {"query": {}, "limit": PAGE, "skip": page * PAGE,
                 "sort": {"create_date": -1}}
        url = f"{HOST}api/db?q=" + urllib.parse.quote(json.dumps(query))
        if not url.startswith(HOST):
            msg = f"refusing to open {url!r}: only {HOST} is allowed"
            raise ValueError(msg)
        request = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310 — host checked above
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            documents = json.loads(response.read()).get("data") or []
        if not documents:
            break
        for document in documents:
            config = document.get("config") or ""
            if config.strip():
                (CORPUS / f"{document['_id']}.txt").write_text(config, encoding="utf-8")
                saved += 1
        print(f"page {page}: {len(documents)} configs", flush=True)
        time.sleep(DELAY)
    return saved


def measure(paths: list[Path]) -> dict[str, object]:
    """Parse, round-trip and validate each config; return the counts worth reporting."""
    totals = Counter()
    reasons = Counter()
    for path in paths:
        source = path.read_text(encoding="utf-8", errors="replace")
        _, rotation = split_config(source)
        tree = parse_rotation(rotation)
        totals["configs"] += 1

        raws = [node for node in tree.nodes if isinstance(node, RawNode)]
        totals["fully structured"] += not raws
        for node in raws:
            reasons[node.reason] += 1

        # The gate this whole design turns on.
        totals["round-trips"] += parse_rotation(emit_tree(tree)) == tree

        _, diagnostics = validate_rotation(rotation)
        errors = [d for d in diagnostics if d.severity is Severity.ERROR]
        totals["no error diagnostics"] += not errors

    return {"totals": totals, "reasons": reasons}


def main() -> int:
    """Fetch if asked, measure, and fail if any config stops round-tripping."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="pull the corpus first")
    parser.add_argument("--pages", type=int, default=5, help="pages of 100 to pull")
    arguments = parser.parse_args()

    if arguments.fetch:
        print(f"fetched {fetch(arguments.pages)} configs into {CORPUS}\n")

    paths = sorted(CORPUS.glob("*.txt")) if CORPUS.exists() else []
    vendored = Path(__file__).resolve().parent.parent.parent / "references" / "gcsim_db"
    paths += sorted(vendored.glob("*.txt"))
    if not paths:
        print("no configs. Run with --fetch first.")
        return 1

    result = measure(paths)
    totals: Counter = result["totals"]  # type: ignore[assignment]
    count = totals["configs"]
    print(f"{count} configs")
    for label in ("fully structured", "round-trips", "no error diagnostics"):
        value = totals[label]
        print(f"  {label:<24} {value:>4}  ({value / count * 100:.1f}%)")

    reasons: Counter = result["reasons"]  # type: ignore[assignment]
    if reasons:
        print("\ncarried rather than understood:")
        for reason, times in reasons.most_common(8):
            print(f"  {times:>4}  {reason}")

    # **Round-tripping is the gate**, and it is the one that must be 100 %.
    return 0 if totals["round-trips"] == count else 1


if __name__ == "__main__":
    sys.exit(main())
