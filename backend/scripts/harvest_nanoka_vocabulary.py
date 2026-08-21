"""Regenerate `tests/fixtures/nanoka_gi/fight_prop_vocabulary.json`.

    cd backend && python -m scripts.harvest_nanoka_vocabulary [--version 7.0.51]

**Why this is a committed script rather than a one-off.** `fight_prop_vocabulary.json` is a
*derived* fixture — it aggregates `affix[].add_props[].prop_type` across all 65 artifact set
detail payloads, and pairs each elemental DMG-bonus prop with the element named in that
affix's own English description. `tests/unit/test_genshin_enums.py` then asserts `StatType`
against it.

Without the derivation in the repo that arrangement is self-confirming: a bug in an
uncommitted script produces a fixture that agrees with the enum it produced, and nobody can
re-check it. Committing the 65 raw payloads is the alternative; this is the cheaper half of
it, and it makes the fixture reproducible by anyone.

**This reaches the network.** It is a manual, reviewed step, never a gate. Nothing in the
test suite calls it — the tests read the committed output. Re-run it deliberately when
pinning a new nanoka version, and commit the resulting diff.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import pathlib
import re
import sys
import time
import urllib.request

_FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nanoka_gi"
_OUT = _FIXTURES / "fight_prop_vocabulary.json"

#: nanoka answers 403 to urllib's default User-Agent. Discovered the hard way in C.2; the
#: Chunk D importer transport needs the same header.
_HEADERS = {"User-Agent": "mistilteinn-dev/0.1 (+https://github.com/AJTDaedalus/mistilteinn)"}

_DMG_BONUS_RE = re.compile(r"([A-Za-z]+) DMG Bonus")


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers=_HEADERS)  # noqa: S310 — https, fixed host
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())


def harvest(version: str) -> dict:
    """Aggregate the artifact affix vocabulary for `version`."""
    set_ids = sorted(json.loads((_FIXTURES / "artifact.json").read_text()))
    counts: collections.Counter[str] = collections.Counter()
    pairs: dict[str, set[str]] = {}

    for set_id in set_ids:
        detail = _get(f"https://static.nanoka.cc/gi/{version}/en/artifact/{set_id}.json")
        for affix in detail.get("affix", []):
            props = [p["prop_type"] for p in affix.get("add_props", [])]
            counts.update(props)

            # Pair a prop with an element only when the affix carries exactly one real prop,
            # so the association is unambiguous. This is what keeps GRASS=Dendro etc. read
            # off the payload rather than asserted from memory.
            named = [p for p in props if p != "FIGHT_PROP_NONE"]
            match = _DMG_BONUS_RE.search(affix.get("desc", ""))
            if match and len(named) == 1:
                pairs.setdefault(named[0], set()).add(match.group(1))
        time.sleep(0.03)

    return {
        "_provenance": {
            "source": f"https://static.nanoka.cc/gi/{version}/en/artifact/{{set_id}}.json,"
                      f" all {len(set_ids)} sets",
            "version": version,
            "fetched": datetime.datetime.now(tz=datetime.UTC).date().isoformat(),
            "task": "C.2",
            "derivation": "affix_prop_counts: every affix[].add_props[].prop_type across "
                          "every artifact set detail payload. element_dmg_bonus: prop_type "
                          "paired with the element named in that affix's own English desc "
                          "text ('<X> DMG Bonus'), for affixes carrying exactly one "
                          "non-NONE prop — so the mapping is read off the payload, never "
                          "asserted from memory.",
            "regenerate": "cd backend && python -m scripts.harvest_nanoka_vocabulary",
        },
        "affix_prop_counts": dict(sorted(counts.items())),
        "element_dmg_bonus": {k: sorted(v) for k, v in sorted(pairs.items())},
    }


def main() -> int:
    """Harvest and write the fixture, reporting what changed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="7.0.51", help="nanoka gi version to pin")
    args = parser.parse_args()

    before = json.loads(_OUT.read_text()) if _OUT.exists() else None
    result = harvest(args.version)
    _OUT.write_text(json.dumps(result, indent=1) + "\n")

    # Compare the data, not the provenance: `fetched` changes on every run by definition,
    # and a script that always reports "CHANGED" is a script whose report gets ignored.
    def _data(doc: dict) -> dict:
        return {k: v for k, v in doc.items() if k != "_provenance"}

    if before is not None and _data(before) != _data(result):
        added = set(result["affix_prop_counts"]) - set(before["affix_prop_counts"])
        removed = set(before["affix_prop_counts"]) - set(result["affix_prop_counts"])
        print(f"CHANGED. new props: {sorted(added) or 'none'}; gone: {sorted(removed) or 'none'}")
        print("Review the diff, then update app/models/enums.py:StatType if needed.")
    else:
        print("No change.")
    print(f"wrote {_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
