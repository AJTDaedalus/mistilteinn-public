"""Build the FileCfg table catalog (Phase 2, T2.1).

For every table under ``FileCfg/`` in the pinned Dimbreath snapshot, record:

* ``name``           — file name (table names are **not** obfuscated)
* ``size_bytes``     — from the contents-API listing (no download needed)
* ``row_count``      — length of the row list
* ``column_count``   — number of columns in a representative row
* ``key_column``     — inferred primary-key column (unique, non-empty, first)
* ``purpose``        — inferred from the table name (keyword map) or "unknown"
* ``priority``       — combat-modeling relevance flag (bool)
* ``shape``          — structural note ("wrapped-list" / "empty" / "multi-list" / "list" / "other")

Columns are hash-obfuscated, so ``key_column`` is detected structurally
(first column whose values are unique and non-empty across all rows). The
recurring ``DBPDHPIBGHA`` first column is the de-facto id across most tables.

Output: ``app/data/dimbreath/schema/table_catalog.json``.

This is read-only cartography. Fetches are cached (sha-pinned) under
``app/data/dimbreath/cache/`` so the 184 MB of FileCfg is downloaded at most
once. Run::

    python -m scripts.dimbreath.build_table_catalog            # full build
    python -m scripts.dimbreath.build_table_catalog --no-fetch # parse cache only
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

from scripts.dimbreath.fetch import (
    SCHEMA_DIR,
    _cache_path,
    _http_get,
    fetch_raw,
    load_provenance,
    pinned_sha,
)

CATALOG_PATH = SCHEMA_DIR / "table_catalog.json"

# ── Purpose inference ────────────────────────────────────────────────────────
# Ordered keyword → purpose. First match wins, so put specific before generic.
# Tokens are matched case-insensitively against the table name.
_PURPOSE_RULES: list[tuple[str, str]] = [
    ("AvatarSkill", "agent skills (multipliers, levels, descriptions)"),
    ("AvatarBattle", "agent battle stats (base ATK/HP/DEF, growth)"),
    ("AvatarSpecialAwaken", "agent mindscape / awakening"),
    ("AvatarLevel", "agent level / ascension"),
    ("AvatarPassive", "agent core passive"),
    ("Avatar", "agent metadata"),
    ("ABBuff", "ability-block buff config"),
    ("ABGlobalBuff", "ability-block global buff"),
    ("ABSkill", "ability-block skill config"),
    ("AbilityProperty", "ability property bindings"),
    ("AbilityServerVariable", "ability server variables"),
    ("Ability", "ability layer (logic graph)"),
    ("LevelAbility", "level-scoped ability config"),
    ("CommonBuff", "shared buff definitions"),
    ("GlobalBuff", "global buff definitions"),
    ("Buff", "buff / debuff definitions"),
    ("SkillList", "skill-id ↔ avatar/codename roster"),
    ("SkillDescInfo", "skill description text bindings"),
    ("SkillInform", "skill UI inform text"),
    ("SkillProperty", "skill property bindings"),
    ("SkillReco", "skill recommendation"),
    ("Skill", "skill definitions"),
    ("Monster", "enemy / monster config"),
    ("Anomaly", "anomaly / attribute mechanics"),
    ("Element", "element definitions"),
    ("Weapon", "w-engine definitions"),
    ("Equip", "disc / equipment config"),
    ("Property", "property / stat definitions"),
    ("Damage", "damage config"),
    ("Stun", "stun / daze config"),
    ("Decibel", "decibel / ultimate energy"),
    ("Item", "inventory items"),
    ("MainCity", "hub / overworld objects"),
    ("Quest", "quest / story config"),
    ("Dungeon", "dungeon / stage config"),
    ("Battle", "battle / combat stage config"),
    ("Message", "in-game message / chat"),
    ("Tips", "loading / help tips"),
    ("Dialog", "dialogue text"),
    ("Perform", "cutscene / performance sequencing"),
    ("Audio", "audio bindings"),
    ("Post", "post-processing / VFX"),
    ("Shop", "shop / store config"),
    ("Gacha", "gacha / signal search"),
    ("Reward", "reward tables"),
    ("Unlock", "feature unlock gating"),
    ("Tutorial", "tutorial config"),
    ("Achievement", "achievement config"),
    ("UI", "UI layout / config"),
    ("Icon", "icon resource bindings"),
    ("HollowZero", "Hollow Zero mode"),
    ("Hollow", "Hollow exploration"),
    ("Bangboo", "Bangboo companion config"),
    ("Buddy", "Bangboo / buddy config"),
    ("Partner", "companion / partner config"),
    ("Camera", "camera config"),
    ("Effect", "effect bindings"),
    # ── Game modes / meta (non-combat) ──
    ("Abyss", "Abyss / endgame mode"),
    ("Activity", "limited-time activity mode"),
    ("Challenge", "challenge mode"),
    ("Card", "card minigame"),
    ("Fish", "fishing minigame"),
    ("Fashion", "outfit / cosmetic"),
    ("Backflow", "returning-player config"),
    ("Cinema", "cinema / cutscene"),
    ("Collection", "collection / archive"),
    ("Store", "store / shop"),
    ("Camp", "camp / faction config"),
    ("Talent", "talent config"),
    ("Event", "event trigger / config"),
    ("Newbie", "new-player onboarding"),
    ("Guide", "guide / onboarding"),
    ("Notice", "notice / announcement"),
    ("Area", "world area config"),
    ("Scene", "scene config"),
    ("Map", "map config"),
    ("Group", "entity grouping config"),
]

# Name tokens that mark a table as combat-modeling relevant (priority).
_PRIORITY_TOKENS = (
    "AvatarSkill",
    "AvatarBattle",
    "AvatarSpecialAwaken",
    "AvatarPassive",
    "Buff",
    "Ability",
    "Skill",
    "Monster",
    "Anomaly",
    "Element",
    "Property",
    "Damage",
    "Stun",
    "Decibel",
    "Weapon",
    "Equip",
)


def infer_purpose(name: str) -> str:
    stem = name.removesuffix(".json")
    for token, purpose in _PURPOSE_RULES:
        if token.lower() in stem.lower():
            return purpose
    return "unknown"


def infer_priority(name: str) -> bool:
    stem = name.removesuffix(".json").lower()
    return any(tok.lower() in stem for tok in _PRIORITY_TOKENS)


# ── Structural parsing ───────────────────────────────────────────────────────
def unwrap_rows(data: Any) -> tuple[list[dict[str, Any]], str]:
    """Return (rows, shape) from a FileCfg table.

    FileCfg tables are ``{"<hash>": [ {row}, ... ]}``; some may be a bare list.
    """
    if isinstance(data, dict):
        list_vals = [v for v in data.values() if isinstance(v, list)]
        if len(list_vals) == 1:
            return list_vals[0], "wrapped-list"
        if not list_vals:
            # Stub table: a single scalar (e.g. {"JKMFEMCLDNN": 4}, a schema-version
            # marker) — genuinely empty of rows.
            return [], "empty"
        # Multiple list values: pick the longest as the row set.
        return max(list_vals, key=len), "multi-list"
    if isinstance(data, list):
        return data, "list"
    return [], "other"


def detect_key_column(rows: list[dict[str, Any]]) -> str | None:
    """First column whose values are unique and non-empty across all rows."""
    if not rows or not isinstance(rows[0], dict):
        return None
    cols = list(rows[0])
    n = len(rows)
    for col in cols:
        seen: set[Any] = set()
        ok = True
        for r in rows:
            v = r.get(col)
            if v is None or v == "" or isinstance(v, (list, dict)):
                ok = False
                break
            try:
                seen.add(v)
            except TypeError:
                ok = False
                break
        if ok and len(seen) == n:
            return col
    return None


# ── Build ────────────────────────────────────────────────────────────────────
def list_filecfg() -> list[dict[str, Any]]:
    prov = load_provenance()
    url = prov["access"]["contents_api"].format(path="FileCfg")
    entries = json.loads(_http_get(url))
    return [e for e in entries if e["type"] == "file"]


def build(*, no_fetch: bool = False) -> dict[str, Any]:
    sha = pinned_sha()
    listing = list_filecfg()
    listing.sort(key=lambda e: e["name"])

    tables: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for i, entry in enumerate(listing, 1):
        name = entry["name"]
        size = entry.get("size", 0)
        repo_path = f"FileCfg/{name}"
        rec: dict[str, Any] = {
            "name": name.removesuffix(".json"),
            "size_bytes": size,
            "purpose": infer_purpose(name),
            "priority": infer_priority(name),
        }
        cached = _cache_path(repo_path, sha)
        if no_fetch and not cached.exists():
            rec.update(row_count=None, column_count=None, key_column=None, shape="not-cached")
            tables.append(rec)
            continue
        try:
            raw = fetch_raw(repo_path, sha)
            data = json.loads(raw)
            rows, shape = unwrap_rows(data)
            rec["row_count"] = len(rows)
            rec["column_count"] = len(rows[0]) if rows and isinstance(rows[0], dict) else 0
            rec["key_column"] = detect_key_column(rows) if rows else None
            rec["shape"] = shape
        except Exception as exc:
            rec.update(row_count=None, column_count=None, key_column=None, shape="error")
            errors.append({"table": name, "error": f"{type(exc).__name__}: {exc}"})
        tables.append(rec)
        if i % 100 == 0:
            print(f"  ...{i}/{len(listing)} tables", file=sys.stderr)

    priority = [t for t in tables if t["priority"]]
    return {
        "_meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "pinned_commit_sha": sha,
            "table_count": len(tables),
            "descriptive_count": sum(1 for t in tables if not t["name"].isdigit()),
            "hash_named_count": sum(1 for t in tables if t["name"].isdigit()),
            "priority_count": len(priority),
            "unknown_purpose_count": sum(1 for t in tables if t["purpose"] == "unknown"),
            "total_bytes": sum(t["size_bytes"] for t in tables),
            "errors": errors,
            "notes": (
                "Table names are not obfuscated; purpose inferred from name keywords. "
                "Columns ARE hash-obfuscated; key_column detected structurally "
                "(first all-unique non-empty column). Column meanings → T2.2. "
                "hash_named_count tables have purely numeric file names (sidecar / "
                "alternate-id copies, all non-priority); the descriptive_count "
                "'*TemplateTb' tables are the human-named data tables. shape='empty' "
                "is a stub table whose wrapper value is a scalar version marker."
            ),
        },
        "tables": tables,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build FileCfg table catalog (T2.1).")
    ap.add_argument("--no-fetch", action="store_true", help="parse only cached files")
    args = ap.parse_args(argv)

    catalog = build(no_fetch=args.no_fetch)
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    m = catalog["_meta"]
    print(f"wrote {CATALOG_PATH.relative_to(SCHEMA_DIR.parents[3])}")
    print(f"  tables          = {m['table_count']}")
    print(f"  priority        = {m['priority_count']}")
    print(f"  unknown purpose = {m['unknown_purpose_count']}")
    print(f"  total size      = {m['total_bytes']/1e6:.1f} MB")
    if m["errors"]:
        print(f"  parse errors    = {len(m['errors'])} (see _meta.errors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
