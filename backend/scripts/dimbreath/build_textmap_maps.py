"""Generate the Phase-1 TextMap schema artifacts (read-only, reproducible).

Emits, under ``app/data/dimbreath/schema/``:

* ``key_grammar.json``    — key grammar + category/_Property_ family counts (T1.1/T1.2)
* ``value_formats.json``  — value-shape taxonomy with samples + parse rules (T1.3)
* ``codename_map.json``   — avatar_id ↔ internal code-name ↔ DB agent (T1.4)
* ``term_map.json``       — NounPrompts / resource display names + <Term:> note (T1.5)

Inputs: the pinned merged EN TextMap, the committed DB roster snapshot
(``schema/_db_roster_snapshot.json``), and ``FileCfg/SkillListConfigTemplateTb``
(the authoritative avatar_id ↔ internal-codename join — ZZZ keys the TextMap by
internal dev code-names, e.g. Unagi=Miyabi, not by public names). Deterministic
given a fixed SHA + snapshot.

Run: ``python -m scripts.dimbreath.build_textmap_maps``
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from scripts.dimbreath import cal, keys
from scripts.dimbreath.fetch import SCHEMA_DIR, fetch_json, load_textmap, pinned_sha

# SkillListConfigTemplateTb (FileCfg) is the authoritative avatar_id ↔ internal
# code-name link: it covers the full roster and its title keys are
# ``{Code}_SkillList_N_Title``. Columns triangulated (re-derive if hashes rotate
# by matching the '*_SkillList_*_Title' key and the avatar-id range 10xx..15xx).
_SKILLLIST_TABLE = "FileCfg/SkillListConfigTemplateTb.json"
_SL_TITLE_KEY = "ELNIGEBMMMM"
_SL_AVATAR_ID = "PGPBPBAAOJG"
_SL_TITLE_RE = re.compile(r"^([A-Za-z]+)_SkillList_")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _classify_value(v: str) -> str:  # noqa: PLR0911 - flat dispatch over value shapes
    if v is None or v == "":
        return "empty"
    if "{CAL:" in v:
        return "cal"
    if "<Term:" in v:
        return "tagged_term"
    if "<IconMap" in v:
        return "tagged_iconmap"
    if "<color" in v:
        return "tagged_color"
    if re.search(r"/s\b|/Sec|Per Sec", v):
        return "rate"
    if re.fullmatch(r"-?\d+(\.\d+)?%", v):
        return "percent"
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        return "number"
    return "label"


def build_key_grammar(tm: dict[str, str]) -> dict:
    cats = keys.category_counts(tm)
    fam = keys.property_families(tm)
    single = sum(1 for k in tm if "_" not in k)
    # Cost-family breakdown
    cost = keys.cost_value_keys(tm)
    cost_tokens: Counter = Counter()
    for k in cost:
        tail = k.split("_Property_", 1)[1]
        cost_tokens[tail.split("_")[0]] += 1
    return {
        "grammar": "{Entity}_{Category}_{Sub...}_{NN}",
        "total_keys": len(tm),
        "single_segment_unparsed": single,
        "unparsed_pct": round(100 * single / len(tm), 3),
        "top_categories": dict(cats.most_common(30)),
        "property_family_head_tokens": dict(fam.most_common()),
        "property_total": sum(1 for k in tm if "_Property_" in k),
        "cost_value_keys": len(cost),
        "cost_value_mode_tokens": dict(cost_tokens.most_common()),
    }


def build_value_formats(tm: dict[str, str]) -> dict:
    prop = {k: v for k, v in tm.items() if "_Property_" in k and isinstance(v, str)}
    counts: Counter = Counter()
    samples: dict[str, str] = {}
    for k, v in prop.items():
        c = _classify_value(v)
        counts[c] += 1
        if c not in samples:
            samples[c] = f"{k} = {v!r}"
    rules = {
        "number": r"^-?\d+(\.\d+)?$  → int/float literal (costs are constants)",
        "percent": r"^-?\d+(\.\d+)?%$  → strip % → float",
        "rate": r"has '/s'|'/Sec'|'Per Sec'  → magnitude + per-second flag",
        "label": "free text; resolve resource name from *_Cost_Title / *_Desc_*Cost*",
        "cal": r"{CAL:expr,scale,decimals}[suffix]  → see cal.py / MAP_cal_grammar.md",
        "tagged_color": r"<color=#RRGGBB>..</color>  → strip tags for plain text",
        "tagged_iconmap": r"<IconMap:Icon_*>  → inline icon placeholder",
        "tagged_term": r"<Term:NNNN>  → narrative noun ref; resolved outside TextMap",
        "empty": "empty string (stub/placeholder key)",
    }
    return {
        "scope": "values of *_Property_* keys",
        "counts": dict(counts.most_common()),
        "samples": samples,
        "parse_rules": rules,
    }


def _has_textmap_cost(tm: dict[str, str], code: str) -> bool:
    """True if the agent has any ``{code}_Property_*`` cost key (CostValue or a
    numeric ``_Desc_*Cost*`` row) — the general cost test, all mechanisms."""
    prefix = code + "_Property_"
    for k, v in tm.items():
        if not k.startswith(prefix):
            continue
        if ("CostValue" in k or re.search(r"_Desc_.*Cost", k)) and re.match(
            r"^-?\d", str(v).strip()
        ):
            return True
    return False


def build_codename_map(tm: dict[str, str]) -> dict:
    """Authoritative avatar_id ↔ internal code-name ↔ DB agent, from
    SkillListConfigTemplateTb. ZZZ uses **internal dev code-names** that differ
    from public names (Unagi=Miyabi, Tsubaki=Nekomata, Aokaku=Soukaku, …); the
    TextMap is keyed by those, so name-string matching is unreliable. avatar_id
    == our DB hakushin_id."""
    snap = json.loads((SCHEMA_DIR / "_db_roster_snapshot.json").read_text())
    db_by_id = {a["hakushin_id"]: a for a in snap["agents"]}

    sl = fetch_json(_SKILLLIST_TABLE)["JKMFEMCLDNN"]
    av2code: dict[int, str] = {}
    for r in sl:
        m = _SL_TITLE_RE.match(r[_SL_TITLE_KEY])
        if m:
            av2code.setdefault(r[_SL_AVATAR_ID], m.group(1))

    mapping: dict[str, dict] = {}
    for av in sorted(av2code):
        code = av2code[av]
        db = db_by_id.get(av)
        is_internal = bool(
            db and _norm(code) not in {_norm(db["full_name"]), _norm(db["name"])}
        )
        mapping[code] = {
            "avatar_id": av,
            "hakushin_id": av if db else None,
            "db_name": db["name"] if db else None,
            "db_full_name": db["full_name"] if db else None,
            "is_internal_codename": is_internal,
            "has_textmap_cost": _has_textmap_cost(tm, code),
        }

    internal = sorted(c for c, v in mapping.items() if v["is_internal_codename"])
    no_cost = sorted(c for c, v in mapping.items() if not v["has_textmap_cost"])
    db_not_in_skilllist = sorted(
        a["name"] for a in snap["agents"] if a["hakushin_id"] not in av2code
    )
    return {
        "join_source": "FileCfg/SkillListConfigTemplateTb (avatar_id == DB hakushin_id; "
        "title key {Code}_SkillList_N_Title gives the internal code-name)",
        "roster_snapshot": "_db_roster_snapshot.json",
        "total_codenames": len(mapping),
        "mapped_to_db": sum(1 for v in mapping.values() if v["hakushin_id"]),
        "internal_codenames": internal,
        "agents_without_textmap_cost": no_cost,
        "db_agents_absent_from_skilllist": db_not_in_skilllist,
        "mapping": dict(sorted(mapping.items())),
    }


def build_term_map(tm: dict[str, str]) -> dict:
    nouns: dict[str, dict[str, str]] = {}
    for k, v in tm.items():
        m = re.match(r"^([A-Za-z]+)_NounPrompts_(\d+)(_Des)?$", k)
        if m and not k.startswith(("Bangboo", "Common")):
            ent = m.group(1)
            nouns.setdefault(ent, {})[k.split("_", 1)[1]] = v
    term_refs = Counter()
    for v in tm.values():
        if isinstance(v, str):
            for tid in re.findall(r"<Term:(\d+)>", v):
                term_refs[tid] += 1
    return {
        "resource_display_source": "{Code}_NounPrompts_NN  (NN_Des = mechanic description)",
        "term_tag_note": (
            "<Term:NNNN> is a narrative noun/name ref, NOT resolved by any TextMap "
            "Term_* key (none exist). The id embeds in narrative key names (e.g. "
            "Main_Chat_Chapter210_32<id>); resolution lives outside TextMap (FileCfg). "
            "Resource costs do NOT use <Term:>."
        ),
        "term_ids_referenced": dict(term_refs.most_common()),
        "velina_resources": nouns.get("Velina", {}),
        "noun_prompt_entities": sorted(nouns),
        "drift_note": (
            "Velina resource = 'Windbloom' (NounPrompts_01) + 'Windbite' (02); "
            "FengHuaCost_Title = 'Windbloom Cost'. The earlier 'Windblight'/'Windshear' "
            "note was stale base-layer terminology — overwrite layer says Windbloom."
        ),
        "noun_prompts": nouns,
    }


def build_cal_inventory(tm: dict[str, str]) -> dict:
    out = {}
    for k, v in tm.items():
        if isinstance(v, str) and "{CAL:" in v:
            c = cal.parse(v)
            out[k] = {
                "raw": v,
                "expr": c.expr if c else None,
                "scale": c.scale if c else None,
                "decimals": c.decimals if c else None,
                "suffix": c.suffix if c else None,
                "slots": sorted(c.slots) if c else None,
            }
    return out


def main() -> int:
    tm = load_textmap("en")
    sha = pinned_sha()
    out_dir = Path(SCHEMA_DIR)

    artifacts = {
        "key_grammar.json": {"_sha": sha, **build_key_grammar(tm)},
        "value_formats.json": {"_sha": sha, **build_value_formats(tm)},
        "codename_map.json": {"_sha": sha, **build_codename_map(tm)},
        "term_map.json": {"_sha": sha, **build_term_map(tm)},
        "cal_inventory.json": {"_sha": sha, "formulas": build_cal_inventory(tm)},
    }
    for name, data in artifacts.items():
        (out_dir / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
