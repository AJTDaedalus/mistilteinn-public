"""Refresh the committed reference fixtures the kit validators check against.

The validators (`scripts/validate_kits.py`, L0–L2) must be **hermetic**: no DB, no
network, no ZO clone. They read the two fixtures this script writes:

  app/data/validation/zo_constants.json     — L2 answer key (ZO `dm.*` symbols)
  app/data/validation/kit_descriptions.json — L1 answer key (in-game description text)

Source drift therefore shows up as a **reviewable diff in a PR** (a ZO rebalance or a
re-seeded description becomes a visible fixture change) rather than a silent CI flip.
Output is deterministic — no timestamps — so re-running with unchanged sources is a
no-op. See `docs/DESIGN_kit_validation.md` → Architecture.

This script is the only piece that touches the live sources, and it runs on the
**host** (like `scripts/verify_zo_modifiers.py`): the ZO clone lives at
/tmp/genshin-optimizer and is not mounted into the backend container.

    conda activate fairy
    cd backend && python -m scripts.refresh_kit_refs

ZO constant resolution
----------------------
`mappedStats/char/maps/<Char>.ts` is a flat indirection table:

    core: { atk_: data_gen.coreParams[0], max_atk: data_gen.coreParams[1][0] }

We regex each `dm.<group>.<symbol>` into an index path, then index
`Data/Characters/<Char>.json` to resolve it. Symbols rooted at `skillParams` are
**excluded**: those are per-hit move values (a large, separate validation domain
covered by `verify_mv_vs_nanoka.py`), and no kit modifier can cite one — every agent
modifier's `source` is `core_skill` or `mindscape`. A citation naming a skillParams
symbol resolves to "not in fixture", which L2 reports as a hard failure rather than
silently passing.

Raw `coreParams` / `abilityParams` / `mindscapeParams` arrays are emitted alongside the
symbol map so that citations written as an index path (`coreParams[0][6]`) resolve too —
most of the existing corpus cites that way.

Usage:
    python -m scripts.refresh_kit_refs              # both fixtures
    python -m scripts.refresh_kit_refs --only zo    # ZO constants only (no DB needed)
    python -m scripts.refresh_kit_refs --only db    # descriptions only (no ZO clone needed)
    python -m scripts.refresh_kit_refs --check      # fail if fixtures are stale (CI/pre-commit)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]
MODIFIERS_DIR = REPO_ROOT / "app" / "data" / "modifiers"
OUT_DIR = REPO_ROOT / "app" / "data" / "validation"
ZO_CONSTANTS_PATH = OUT_DIR / "zo_constants.json"
KIT_DESCRIPTIONS_PATH = OUT_DIR / "kit_descriptions.json"
# L3's manifest — generated into the frontend so a spec can import it directly.
STAT_KEYS_TS_PATH = (
    REPO_ROOT.parent / "frontend" / "src" / "app" / "shared" / "stat-keys.generated.ts"
)

ZO_ROOT = Path(os.environ.get("ZO_ROOT", "/tmp/genshin-optimizer"))  # noqa: S108
ZO_PINNED_COMMIT = "0c9bde8f99ec1561e66aa0114668e8cdc0b8aca2"
ZO_CHAR_MAPS = "libs/zzz/stats/src/mappedStats/char/maps"
ZO_CHAR_DATA = "libs/zzz/stats/Data/Characters"
ZO_CHAR_SHEETS = "libs/zzz/formula/src/data/char/sheets"

# Param roots we resolve symbols against. `skillParams` is deliberately absent —
# see the module docstring.
# `potentialParams` joined this list for #90 Track 2. It was excluded on the grounds that
# it was "unused by kit modifiers", which was true when written and stopped being true the
# moment Track 2 started authoring modifiers from it. Its shape is identical to
# `coreParams`' (a list of per-index lists), so `_resolve` handles it unchanged — the only
# difference is what the inner index means: rank (0=Level I .. 5=Level VI) rather than
# core level.
PARAM_ROOTS = ("coreParams", "abilityParams", "mindscapeParams", "potentialParams")
EXCLUDED_ROOTS = ("skillParams", "calcedParams")

DEFAULT_DB_URL = "postgresql://fairy:fairy_dev@localhost:5432/fairy"

# `const dm = { ... } as const` — groups hold flat `name: data_gen.path` entries only.
_DM_BLOCK_RE = re.compile(r"const dm\s*=\s*\{(.*)\}\s*as const", re.DOTALL)
_GROUP_RE = re.compile(r"(\w+)\s*:\s*\{([^{}]*)\}")
_ENTRY_RE = re.compile(r"(\w+)\s*:\s*data_gen\.(\w+)((?:\[[^\]]+\])*)")
_INDEX_RE = re.compile(r"\[([^\]]+)\]")

# The names ZO's sheets give their buffs: `registerBuff('m1_defIgn_', ...)`. These are the
# tokens the kit `notes` actually cite (`ZO: m1_resRed_ = ...`), and they are NOT dm symbols
# — a sheet author invents the buff id, then feeds it a dm constant. Both keys are needed to
# resolve a citation, and both are per-character: `m1_crit_` is real for Ellen and fabricated
# for Lycaon.
_REGISTER_BUFF_RE = re.compile(r"registerBuff\(\s*'([^']+)'")


def _slugify(zo_key: str) -> str:
    """AstraYao -> astra_yao, matching the kit JSON filenames."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", zo_key).lower()


def _norm(name: str) -> str:
    return name.replace("_", "").replace(" ", "").lower()


def _zo_commit() -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(ZO_ROOT), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _parse_index_path(suffix: str) -> list[int | str]:
    """`[0][6]` -> [0, 6];  `['basic']['X']` -> ['basic', 'X']."""
    path: list[int | str] = []
    for raw in _INDEX_RE.findall(suffix):
        token = raw.strip().strip("'\"")
        path.append(int(token) if token.lstrip("-").isdigit() else token)
    return path


def _resolve(data: Any, path: list[int | str]) -> Any:
    for key in path:
        if isinstance(key, int):
            if not isinstance(data, list) or key >= len(data):
                return None
            data = data[key]
        else:
            if not isinstance(data, dict) or key not in data:
                return None
            data = data[key]
    return data


def extract_zo_constants() -> dict[str, Any]:
    """Resolve every non-skillParams `dm.*` symbol, and every buff name, per ZO character."""
    maps_dir = ZO_ROOT / ZO_CHAR_MAPS
    data_dir = ZO_ROOT / ZO_CHAR_DATA
    sheets_dir = ZO_ROOT / ZO_CHAR_SHEETS
    if not maps_dir.is_dir():
        sys.exit(f"ZO clone not found at {ZO_ROOT} (set ZO_ROOT or clone it there)")

    commit = _zo_commit()
    if commit != ZO_PINNED_COMMIT:
        print(
            f"WARNING: ZO clone is at {commit[:8]}, not the pinned "
            f"{ZO_PINNED_COMMIT[:8]}. Fixture will record the actual commit.",
            file=sys.stderr,
        )

    agents: dict[str, Any] = {}
    unresolved_total = 0

    for map_file in sorted(maps_dir.glob("*.ts")):
        zo_key = map_file.stem
        if zo_key == "index":
            continue
        char_json = data_dir / f"{zo_key}.json"
        if not char_json.is_file():
            print(f"WARNING: no Data/Characters/{zo_key}.json — skipped", file=sys.stderr)
            continue

        char_data = json.loads(char_json.read_text())
        block = _DM_BLOCK_RE.search(map_file.read_text())
        if not block:
            print(
                f"WARNING: no `const dm = {{...}}` in {map_file.name} — skipped",
                file=sys.stderr,
            )
            continue

        symbols: dict[str, Any] = {}
        excluded: list[str] = []
        unresolved: list[str] = []

        for group, body in _GROUP_RE.findall(block.group(1)):
            for symbol, root, suffix in _ENTRY_RE.findall(body):
                name = f"{group}.{symbol}"
                if root in EXCLUDED_ROOTS:
                    excluded.append(name)
                    continue
                if root not in PARAM_ROOTS:
                    print(
                        f"WARNING: {zo_key}: unknown param root {root!r} on {name}",
                        file=sys.stderr,
                    )
                    continue
                value = _resolve(char_data.get(root), _parse_index_path(suffix))
                if value is None:
                    unresolved.append(f"{name} -> {root}{suffix}")
                    continue
                symbols[name] = value

        sheet = sheets_dir / f"{zo_key}.ts"
        buff_names = (
            sorted(set(_REGISTER_BUFF_RE.findall(sheet.read_text()))) if sheet.is_file() else []
        )

        unresolved_total += len(unresolved)
        agents[zo_key] = {
            "fairy_slug": _slugify(zo_key),
            "symbols": dict(sorted(symbols.items())),
            # Raw arrays so index-path citations (`coreParams[0][6]`) resolve as well.
            "params": {root: char_data.get(root) for root in PARAM_ROOTS},
            # Buff ids from the sheet — what the kit `notes` actually cite.
            "buff_names": buff_names,
            "excluded_symbols": sorted(excluded),
            "unresolved_symbols": sorted(unresolved),
        }

    print(
        f"ZO: {len(agents)} characters, "
        f"{sum(len(a['symbols']) for a in agents.values())} symbols resolved, "
        f"{sum(len(a['buff_names']) for a in agents.values())} buff names, "
        f"{unresolved_total} unresolved"
    )
    return {
        "_meta": {
            "source": "zenless-optimizer",
            "zo_commit": commit,
            "generated_by": "scripts/refresh_kit_refs.py",
            "excluded_symbol_roots": list(EXCLUDED_ROOTS),
            "excluded_rationale": (
                "skillParams are per-hit move values, validated separately by "
                "verify_mv_vs_nanoka.py; no kit modifier can cite one (every agent "
                "modifier's source is core_skill or mindscape). calcedParams are "
                "unused by kit modifiers. potentialParams WAS listed here on the same "
                "grounds until #90 Track 2, which authors modifiers from it — it is now "
                "resolved like any other param root. Note ZO derives potentialParams by "
                "regex over description prose and is wrong once (Jane's 25 for 0.25), so "
                "a citation against it is a cross-reference, not an oracle; nanoka is the "
                "source of truth (docs/RESEARCH_potential_ramps.md)."
            ),
        },
        "agents": dict(sorted(agents.items())),
    }


async def extract_kit_descriptions(db_url: str) -> dict[str, Any]:
    """Pull skill / core / mindscape description text for every agent from the DB.

    All three pools are emitted. L1 needs all of them: the in-game "Additional
    Ability" text is **not** a row of its own — for Astra Yao the team DMG% and
    CRIT DMG buffs (`source: core_skill` in the kit JSON) are described in the
    *Special* skill's "Idyllic Cadenza" text. Pooling only core_skills would
    false-flag those modifiers.
    """
    conn = await asyncpg.connect(db_url)
    try:
        agent_rows = await conn.fetch(
            "SELECT id, hakushin_id, name FROM agents ORDER BY hakushin_id"
        )
        agents: dict[str, Any] = {}
        for agent in agent_rows:
            skills = await conn.fetch(
                "SELECT skill_key, name, description FROM agent_skills "
                "WHERE agent_id = $1 ORDER BY skill_key, name",
                agent["id"],
            )
            cores = await conn.fetch(
                "SELECT level, name, description FROM core_skills "
                "WHERE agent_id = $1 ORDER BY level, name",
                agent["id"],
            )
            minds = await conn.fetch(
                "SELECT level, name, description FROM mindscapes "
                "WHERE agent_id = $1 ORDER BY level, name",
                agent["id"],
            )

            core_by_level: dict[str, list[dict[str, str]]] = {}
            for row in cores:
                core_by_level.setdefault(str(row["level"]), []).append(
                    {"name": row["name"], "description": row["description"] or ""}
                )
            mind_by_level: dict[str, list[dict[str, str]]] = {}
            for row in minds:
                mind_by_level.setdefault(str(row["level"]), []).append(
                    {"name": row["name"], "description": row["description"] or ""}
                )

            agents[str(agent["hakushin_id"])] = {
                "name": agent["name"],
                "slug": _norm(agent["name"]),
                "skills": [
                    {
                        "skill_key": row["skill_key"],
                        "name": row["name"],
                        "description": row["description"] or "",
                    }
                    for row in skills
                ],
                "core_skills": dict(sorted(core_by_level.items(), key=lambda kv: int(kv[0]))),
                "mindscapes": dict(sorted(mind_by_level.items(), key=lambda kv: int(kv[0]))),
            }
    finally:
        await conn.close()

    print(
        f"DB: {len(agents)} agents, "
        f"{sum(len(a['core_skills']) for a in agents.values())} core levels, "
        f"{sum(len(a['mindscapes']) for a in agents.values())} mindscapes"
    )
    return {
        "_meta": {
            "source": "fairy postgres (seeded from nanoka.cc)",
            "generated_by": "scripts/refresh_kit_refs.py",
            "note": (
                "The in-game 'Additional Ability' has no row of its own; its text is "
                "carried by the relevant skill description. L1 must pool skills + "
                "core_skills + mindscapes, not core_skills alone."
            ),
        },
        "agents": agents,
    }


def collect_stat_keys() -> list[str]:
    """Every `stat` key used by any kit / W-Engine / disc-set modifier."""
    keys = {
        mod["stat"]
        for path in sorted(MODIFIERS_DIR.rglob("*.json"))
        for mod in json.loads(path.read_text()).get("modifiers", [])
        if mod.get("stat")
    }
    return sorted(keys)


def render_stat_keys_module(keys: list[str]) -> str:
    """The manifest L3 checks STAT_META against.

    Generated rather than hand-written, and generated as **TypeScript** rather than JSON so
    the frontend can import it with no resolver config. The freshness of this file is itself
    enforced by a backend test — otherwise a new stat key could be added to a kit and the
    display check would keep passing against a stale list, which is the failure mode the
    whole harness exists to prevent.
    """
    lines = "\n".join(f"  '{key}'," for key in keys)
    return (
        "// GENERATED by backend/scripts/refresh_kit_refs.py — do not edit by hand.\n"
        "// Every `stat` key used by any kit / W-Engine / disc-set modifier JSON.\n"
        "// `stat-meta.spec.ts` (L3) asserts STAT_META covers all of them, so an unmapped\n"
        "// key renders as a raw `FINAL_ATK_PCT +1000` chip in the UI (issue #62) and fails\n"
        "// CI instead of shipping.\n"
        "export const STAT_KEYS_IN_USE: readonly string[] = [\n"
        f"{lines}\n"
        "];\n"
    )


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _write_text(path: Path, text: str, *, check: bool) -> bool:
    """Write a generated text file. Returns True if content changed (or would change)."""
    current = path.read_text() if path.is_file() else None
    if current == text:
        print(f"  unchanged: {path}")
        return False
    if check:
        print(f"  STALE: {path}", file=sys.stderr)
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"  wrote: {path}")
    return True


def _write(path: Path, payload: dict[str, Any], *, check: bool) -> bool:
    """Write the fixture. Returns True if content changed (or would change)."""
    text = _dump(payload)
    current = path.read_text() if path.is_file() else None
    if current == text:
        print(f"  unchanged: {path.relative_to(REPO_ROOT)}")
        return False
    if check:
        print(f"  STALE: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"  wrote: {path.relative_to(REPO_ROOT)}")
    return True


def main() -> int:
    """Regenerate (or `--check`) the committed validation fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("zo", "db", "stats", "all"), default="all")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if a fixture is stale instead of rewriting it",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("REFRESH_DATABASE_URL", DEFAULT_DB_URL),
        help=f"asyncpg DSN (default: {DEFAULT_DB_URL})",
    )
    args = parser.parse_args()

    stale = False
    if args.only in ("zo", "all"):
        stale |= _write(ZO_CONSTANTS_PATH, extract_zo_constants(), check=args.check)
    if args.only in ("db", "all"):
        payload = asyncio.run(extract_kit_descriptions(args.database_url))
        stale |= _write(KIT_DESCRIPTIONS_PATH, payload, check=args.check)
    if args.only in ("stats", "all"):
        keys = collect_stat_keys()
        print(f"stats: {len(keys)} stat keys in use across the modifier JSONs")
        stale |= _write_text(
            STAT_KEYS_TS_PATH, render_stat_keys_module(keys), check=args.check
        )

    if args.check and stale:
        print("\nFixtures are stale — run `python -m scripts.refresh_kit_refs`.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
