"""Re-sync `builds.mindscape_level` from a scanner agent export (issue #156).

Sixteen of 39 live builds were found carrying a mindscape *below* the scanner's —
every mismatch an understatement, never the reverse. `mindscape_level` gates kit
modifiers via `min_mindscape`, so those builds compute **without** the rows they
should have: Anby was missing all six of hers, and Jane sat at M0 against a real M2.

Deliberately surgical. A full eZOD re-import would also rewrite w-engine and disc
assignments (`build_conflict="overwrite"` detaches and re-attaches discs), which is a
much larger blast radius than the defect warrants — and the agent-only export this
reads has no disc data to re-attach *from*, so a naive re-import would strip them.
This touches **one column** and nothing else.

Dry-run by default. Pass --apply to write.

    cd backend
    python -m scripts.sync_build_mindscapes --export /path/to/agents.json
    python -m scripts.sync_build_mindscapes --export /path/to/agents.json --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.agent import Agent
from app.models.build import Build


def _norm(name: str) -> str:
    """Scanner keys are PascalCase and unspaced; DB names are display names."""
    return name.lower().replace(" ", "").replace("-", "").replace("&", "").replace("'", "")


async def main(export_path: Path, apply: bool) -> int:
    """Compare every build's mindscape against the export; optionally raise the stale ones."""
    scanned = json.loads(export_path.read_text())
    by_key = {_norm(a["key"]): int(a.get("constellation", 0) or 0) for a in scanned}
    print(f"scanner export: {len(by_key)} agents")

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    behind: list[tuple[str, int, int]] = []
    ahead: list[tuple[str, int, int]] = []
    unmatched: list[str] = []

    async with session_factory() as session:
        rows = (
            await session.execute(select(Build, Agent).join(Agent, Agent.id == Build.agent_id))
        ).all()
        for build, agent in rows:
            scanned_mc = by_key.get(_norm(agent.name))
            if scanned_mc is None:
                unmatched.append(agent.name)
                continue
            current = build.mindscape_level or 0
            if scanned_mc > current:
                behind.append((agent.name, current, scanned_mc))
                if apply:
                    build.mindscape_level = scanned_mc
            elif scanned_mc < current:
                # Mindscapes only ever increase in game, so this direction means the
                # export is older than the build — NEVER auto-lower. Report and skip.
                ahead.append((agent.name, current, scanned_mc))

        print(f"\nbuilds compared: {len(rows)}  behind: {len(behind)}  "
              f"ahead-of-export: {len(ahead)}  not in export: {len(unmatched)}")
        for name, cur, new in sorted(behind, key=lambda r: -(r[2] - r[1])):
            print(f"  {'UPDATE' if apply else 'would update'} {name:18s} M{cur} -> M{new}")
        for name, cur, new in ahead:
            print(f"  SKIP (build ahead of export) {name:18s} DB M{cur} > export M{new}")
        if unmatched:
            print(f"  not in export: {', '.join(sorted(unmatched))}")

        if apply and behind:
            await session.commit()
            print(f"\ncommitted {len(behind)} mindscape update(s)")
        elif not apply:
            print("\ndry run — pass --apply to write")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", required=True, type=Path, help="scanner agents.json")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args()
    if not args.export.is_file():
        print(f"no such export: {args.export}", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(args.export, args.apply)))
