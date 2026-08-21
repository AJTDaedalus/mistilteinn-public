"""Per-patch check — sweep nanoka.cc for `potential` field shapes (issue #85).

`NanokaImporter` filters on `entry.get("potential")` with a total classifier:
a value is either `[]` (present in both kits), exactly `[0]` (base-kit-only),
or a pure list of Potential-node ids (Potential-unlocked-only). That
assumption was verified once, by hand, over the full 58-agent roster at
`3.1.12+17625891` (`docs/RESEARCH_potential_sweep_85.md`). This script makes
the check re-runnable at every future patch rather than trusting a one-off
snapshot — a new patch could in principle introduce a mixed shape (`0`
alongside other ids) or a non-list `potential` value, either of which would
silently break `_in_unlocked_kit`'s predicate.

Usage:
    docker compose exec backend python -m scripts.sweep_nanoka_potential
    docker compose exec backend python -m scripts.sweep_nanoka_potential --version 3.1.12+17625891

Exit code 0 if every non-empty `potential` value is `[0]` or a pure id list;
1 if any value is a mixed shape (`0` alongside other ids) or not a list at all.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

import httpx

from app.data.importers.nanoka_importer import BASE_URL

_TIMEOUT = 30.0


async def _resolve_version(client: httpx.AsyncClient, version: str | None) -> str:
    if version:
        return version
    resp = await client.get(f"{BASE_URL}/manifest.json")
    resp.raise_for_status()
    return resp.json()["zzz"]["latest"]


async def _fetch_character_index(client: httpx.AsyncClient, version: str) -> dict:
    resp = await client.get(f"{BASE_URL}/zzz/{version}/character.json")
    resp.raise_for_status()
    return resp.json()


async def _fetch_character(client: httpx.AsyncClient, version: str, hakushin_id: int) -> dict:
    url = f"{BASE_URL}/zzz/{version}/en/character/{hakushin_id}.json"
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()


def _classify(value: object) -> str:
    """Bucket one `potential` value into the shapes `_in_unlocked_kit` assumes."""
    if not isinstance(value, list):
        return "OTHER (non-list)"
    if len(value) == 0:
        return "empty"
    if value == [0]:
        return "base-only [0]"
    if 0 in value:
        return "MIXED (0 alongside other ids)"
    return "potential-only (id list)"

_INVALID_SHAPES = {"OTHER (non-list)", "MIXED (0 alongside other ids)"}


def _walk(node: object, agent_name: str, shapes: Counter, invalid: list[str]) -> None:
    """Recurse through one agent's JSON, classifying every `potential` key found."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "potential":
                shape = _classify(val)
                shapes[shape] += 1
                if shape in _INVALID_SHAPES:
                    invalid.append(f"[{agent_name}] potential={val!r}")
            else:
                _walk(val, agent_name, shapes, invalid)
    elif isinstance(node, list):
        for item in node:
            _walk(item, agent_name, shapes, invalid)


async def run(version: str | None) -> int:
    """Sweep every seeded-index agent's JSON for `potential` shapes and report."""
    shapes: Counter[str] = Counter()
    invalid: list[str] = []
    affected_agents: list[str] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resolved_version = await _resolve_version(client, version)
        index = await _fetch_character_index(client, resolved_version)

        for char_id_str in index:
            data = await _fetch_character(client, resolved_version, int(char_id_str))
            name = data.get("name", char_id_str)

            agent_shapes: Counter[str] = Counter()
            _walk(data, name, agent_shapes, invalid)
            shapes.update(agent_shapes)

            non_empty = sum(count for shape, count in agent_shapes.items() if shape != "empty")
            if non_empty:
                affected_agents.append(name)

    print(f"nanoka version: {resolved_version}")
    print(f"agents swept: {len(index)}")
    print(f"agents with any non-empty `potential`: {len(affected_agents)}")
    if affected_agents:
        print("  " + ", ".join(sorted(affected_agents)))
    print("\nshape counts:")
    for shape, count in shapes.most_common():
        print(f"  {count:6d}  {shape}")

    if invalid:
        print(f"\nINVALID shapes found ({len(invalid)}) — _in_unlocked_kit's assumption is stale:")
        for line in invalid:
            print(f"  {line}")
        return 1

    print("\nAll non-empty `potential` values are [0] or a pure id list — predicate still holds.")
    return 0


def main() -> int:
    """CLI entry point: parse args and run the sweep, returning the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        help="nanoka ZZZ version to sweep (default: manifest's latest, same as the importer)",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.version))


if __name__ == "__main__":
    raise SystemExit(main())
