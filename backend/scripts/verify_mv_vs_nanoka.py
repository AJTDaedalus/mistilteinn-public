"""Task F2 (F-33) — bulk MV/daze diff harness: DB `attacks` vs live nanoka.cc data.

Pulls skill params fresh from nanoka.cc for every seeded agent, re-derives the
per-hit (damage_base, damage_growth) pairs the same way
`NanokaImporter._import_attacks` does, and diffs the result against the
`attacks` table. Closes the F-33 residual risk cheaply and becomes a
regression harness other patches can re-run.

This intentionally re-implements the importer's extraction logic rather than
importing it, mirroring the existing `verify_zo_modifiers.py` precedent
(independent re-derivation catches import-path regressions that reusing the
same code path would mask). The one exception is the Potential classifier
(`_potential_tag` / `_visible_in`, #85 and #90): those are imported directly
rather than copied, so this harness can't drift out of sync with the
importer's classifier and start reporting base-kit ids as "missing from DB".

Runs at `PotentialVariant.BOTH` (#90). This is an auditing tool that diffs the
*whole* `attacks` table, and since #90 that table holds both Potential states —
so expecting one kit would flag every row of the other as an extra. BOTH is
never valid on a calc path; see docs/RESEARCH_potential_call_sites.md.

Usage:
    docker compose exec backend python -m scripts.verify_mv_vs_nanoka
    docker compose exec backend python -m scripts.verify_mv_vs_nanoka --agent Yanagi

Exit code 0 if no mismatches, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio

import httpx
from sqlalchemy import select

from app.data.importers.nanoka_importer import (
    BASE_URL,
    SKILL_TYPE_MAP,
    _potential_tag,
    _visible_in,
)
from app.database import async_session_factory
from app.models.agent import Agent, Attack
from app.models.enums import PotentialVariant

_TIMEOUT = 30.0

# See the module docstring: this harness diffs the entire table, so it wants every
# row of both Potential states.
_VARIANT = PotentialVariant.BOTH


async def _resolve_version(client: httpx.AsyncClient) -> str:
    resp = await client.get(f"{BASE_URL}/manifest.json")
    resp.raise_for_status()
    return resp.json()["zzz"]["latest"]


async def _fetch_character(client: httpx.AsyncClient, version: str, hakushin_id: int) -> dict:
    url = f"{BASE_URL}/zzz/{version}/en/character/{hakushin_id}.json"
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()


def extract_expected_rows(data: dict) -> dict[int, tuple[int, int]]:
    """Re-derive {hakushin_skill_id: (damage_base, damage_growth)} from raw nanoka data.

    Mirrors `NanokaImporter._import_attacks`'s DMG-param extraction, including:

    - its per-param same-value dedup: nanoka reuses "bookkeeping" skill_ids
      that share identical (damage_percentage, damage_percentage_growth)
      within one param (e.g. Nicole's Dodge Counter lists both 1031205 and
      1031206 with the same values) — the importer keeps only the
      first-seen id per distinct value and silently drops the rest, so this
      harness must too or it flags the intentionally-dropped duplicate as
      "missing from DB".
    - its Potential classifier (#85, #90): entries are tagged rather than
      dropped, and this harness runs at BOTH, so a base skill_id and its
      Potential sibling are both expected -- matching a DB that now stores
      both states.
    """
    skill_data = data.get("skill", {})
    expected: dict[int, tuple[int, int]] = {}

    for skill_key, skill_info in skill_data.items():
        if skill_key not in SKILL_TYPE_MAP:
            continue
        for desc_entry in skill_info.get("description", []):
            if not _visible_in(_potential_tag(desc_entry), _VARIANT):
                continue
            params = desc_entry.get("param", [])
            if not isinstance(params, list):
                continue
            for param in params:
                if not _visible_in(_potential_tag(param), _VARIANT):
                    continue
                outer_name = param.get("name", "")
                if "DMG" not in outer_name or "Daze" in outer_name:
                    continue
                param_dict = param.get("param", {})
                seen_values: set[tuple[int, int]] = set()
                for sid_str, values in param_dict.items():
                    key = (
                        values.get("damage_percentage", 0),
                        values.get("damage_percentage_growth", 0),
                    )
                    if key in seen_values:
                        continue
                    seen_values.add(key)
                    expected[int(sid_str)] = key
    return expected


def diff_agent(
    agent_name: str, expected: dict[int, tuple[int, int]], attacks: list[Attack]
) -> list[str]:
    """Diff one agent's fresh-nanoka MV pairs against its DB `attacks` rows, by skill_id.

    A single skill_id can have multiple DB rows (curated `variant`/`sequential`
    overrides, e.g. Ye Shunguang's Soaring Light 1-sword/6-sword split, where
    one row is synthetic and only the other is nanoka-sourced) — a skill_id
    matches as long as ONE of its DB rows equals the nanoka value.
    """
    errors: list[str] = []
    actual: dict[int, list[tuple[int, int]]] = {}
    for a in attacks:
        actual.setdefault(a.hakushin_skill_id, []).append((a.damage_base, a.damage_growth))

    for sid, exp_vals in expected.items():
        if sid not in actual:
            errors.append(
                f"[{agent_name}] skill_id {sid}: in nanoka but missing from DB {exp_vals}"
            )
            continue
        if exp_vals not in actual[sid]:
            errors.append(
                f"[{agent_name}] skill_id {sid}: DB={actual[sid]} nanoka={exp_vals} MISMATCH"
            )

    missing_in_nanoka = sorted(set(actual) - set(expected))
    errors.extend(
        f"[{agent_name}] skill_id {sid}: in DB {actual[sid]} but not found in fresh nanoka pull"
        for sid in missing_in_nanoka
    )

    return errors


async def run(agent_filter: str | None) -> int:
    """Fetch nanoka data for each seeded agent, diff against DB attacks, print a report."""
    all_errors: list[str] = []
    checked = 0

    async with async_session_factory() as session, httpx.AsyncClient(timeout=_TIMEOUT) as client:
        version = await _resolve_version(client)

        query = select(Agent)
        if agent_filter:
            query = query.where(Agent.name == agent_filter)
        agents = (await session.execute(query)).scalars().all()

        for agent in agents:
            try:
                data = await _fetch_character(client, version, agent.hakushin_id)
            except httpx.HTTPStatusError as exc:
                all_errors.append(f"[{agent.name}] fetch failed: {exc}")
                continue

            expected = extract_expected_rows(data)
            attacks = (
                (await session.execute(select(Attack).where(Attack.agent_id == agent.id)))
                .scalars()
                .all()
            )
            errors = diff_agent(agent.name, expected, attacks)
            all_errors.extend(errors)
            checked += 1

    print(f"Checked {checked} agent(s) against nanoka.")
    if all_errors:
        for e in all_errors:
            print(f"  MISMATCH: {e}")
    else:
        print("  all attacks.damage_base/damage_growth match live nanoka data")
    print(f"Total mismatches: {len(all_errors)}")
    return 0 if not all_errors else 1


def main() -> int:
    """CLI entry point: parse args and run the diff, returning the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", help="Only check this agent (by name)")
    args = parser.parse_args()
    return asyncio.run(run(args.agent))


if __name__ == "__main__":
    raise SystemExit(main())
