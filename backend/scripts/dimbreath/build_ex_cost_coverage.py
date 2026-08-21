"""Locate every agent's EX-Special skill and its resource cost — coverage report.

Motivation (Task 1 extension): the TextMap ``_Property_*SpCostValue*`` mechanism
only covers a subset of agents (recent ones). Older agents (Miyabi, Nekomata,
Soukaku, Piper, …) have **no** ``_Property_`` rows, so their EX cost is not in the
TextMap. This generator pins down, for the full roster:

* the EX-Special **skill id(s)** and title — from ``SkillListConfigTemplateTb``
  (FileCfg), which covers all 56 agents and whose title keys (``{Code}_SkillList_
  N_Title``) also give the code-name ↔ avatar-id link;
* the EX **cost** when the TextMap publishes it (``_Property_ExSpecial…
  SpCostValue_01``);
* a **cost_source** flag: ``textmap_property`` (have it) vs ``MISSING`` (the cost
  is only in the deep ability/buff layer — Tier C — or must come from an external
  reference).

Finding recorded by this script: the EX activation cost is absent from all of
AvatarSkillTemplateTb, AvatarBattleTemplateTb, AvatarSkillInfoTemplateTb,
SkillListConfigTemplateTb, SkillPropertyTemplateTb, ABSkillConfigTemplateTb.

Output: ``app/data/dimbreath/schema/ex_cost_coverage.json``.
Run: ``python -m scripts.dimbreath.build_ex_cost_coverage``
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

from scripts.dimbreath.fetch import SCHEMA_DIR, fetch_json, load_textmap, pinned_sha

# SkillListConfigTemplateTb columns (triangulated; re-derive if hashes rotate by
# matching the title key '*_SkillList_*_Title' and avatar-id range 10xx..15xx).
_SL_SKILL_ID = "LMIJJOPGLDB"
_SL_TITLE_KEY = "ELNIGEBMMMM"
_SL_AVATAR_ID = "PGPBPBAAOJG"
_TITLE_KEY_RE = re.compile(r"^([A-Za-z]+)_SkillList_")


_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:\s*/\s*sec?\b|/s)?", re.IGNORECASE)


def _sibling_desc_says_per_sec(tm: dict[str, str], cost_key: str) -> bool:
    """Norma pattern: Desc_SpCost sibling label contains 'Per Sec/Second'.

    For ``*_SpCostValue`` (no suffix) the descriptor is ``*_Desc_SpCost_01``.
    For ``*_SpCostValue_NN`` the descriptor is ``*_Desc_SpCost_NN``.
    """
    desc_base = cost_key.replace("SpCostValue", "Desc_SpCost")
    if desc_base == cost_key:
        return False
    for candidate in (desc_base, desc_base + "_01"):
        if re.search(r"\bper\s+sec", tm.get(candidate, ""), re.IGNORECASE):
            return True
    return False


def _preceding_label_says_per_sec(all_entries: dict[str, str], cost_key: str) -> bool:
    """Yixuan pattern: SpCostValue_(N-1) is a label row saying 'Per Second'.

    e.g. SpCostValue_03='Consumption Per Second' → SpCostValue_04 is per-sec.
    """
    m = re.match(r"^(.*SpCostValue_)(\d+)$", cost_key)
    if not m:
        return False
    prefix, num_str = m.group(1), m.group(2)
    n = int(num_str)
    if n < 2:  # noqa: PLR2004
        return False
    prev_key = f"{prefix}{n - 1:0{len(num_str)}d}"
    return re.search(r"\bper\s+sec", all_entries.get(prev_key, ""), re.IGNORECASE) is not None




def _load_per_sec_corrections() -> dict[str, bool]:
    """Cited, per-key corrections to the per-second FLAG (Task 21).

    The three automatic patterns below all require the *words* — a ``/s`` token, a "Per Sec"
    ``Desc_SpCost`` sibling, or a "Per Second" preceding label. An agent whose label names
    *what* the cost pays for rather than *how often* it is charged slips all three: Seed's
    reads "Barrage Cost" while her skill text says the barrage "continuously consum[es]
    Energy".

    Deliberately a curation table and not a wider regex. "Barrage Cost" is indistinguishable
    from a genuine flat cost by its own words, so a heuristic tuned to catch it would
    mis-flag real flat costs elsewhere; the disambiguator is the skill text, which is a
    citation rather than a pattern.
    """
    path = SCHEMA_DIR / "manual_cost_overrides.json"
    if not path.exists():
        return {}
    block = json.loads(path.read_text()).get("per_sec_corrections", {})
    return {
        key: bool(entry["per_sec"])
        for key, entry in block.items()
        if isinstance(entry, dict) and "per_sec" in entry
    }


def _resource_costs(tm: dict[str, str], code: str) -> list[dict]:
    """ALL TextMap resource-cost entries for an agent (general algorithm).

    Covers every cost mechanism, not just plain ExSpecial: any
    ``{code}_Property_*`` key that is a cost — ``*CostValue*`` (energy, FengHua,
    Heat, Rp) or a ``*_Desc_*Cost*`` label whose value is the number — across
    modes (ExSpecial / ExSpecial_0M / Branch / EvadeAid). Returns parsed value +
    per-second flag + source key, so "no entries" means genuinely no TextMap cost.

    Three per-sec detection patterns:
    * Value string contains ``/sec`` or ``/s`` (Nicole: "20 Energy/sec").
    * ``Desc_SpCost`` sibling label says "Per Sec" (Norma ExSpecial_02).
    * Preceding ``SpCostValue_(N-1)`` is a label saying "Per Second" (Yixuan ExSpecial_02).
    """
    prefix = code + "_Property_"
    # Collect ALL cost-adjacent entries first so preceding-label check can reference them.
    all_entries: dict[str, str] = {
        k: v
        for k, v in tm.items()
        if k.startswith(prefix) and ("CostValue" in k or re.search(r"_Desc_.*Cost", k))
    }

    corrections = _load_per_sec_corrections()

    out: list[dict] = []
    for k, v in sorted(all_entries.items()):
        if not isinstance(v, str):
            continue
        m = _NUMERIC_RE.match(v.strip())
        if not m:
            continue  # label-only row (e.g. "Energy Cost to Use"); its number is a sibling
        token = m.group(0)
        per_sec = (
            bool(re.search(r"/\s*sec?\b", v, re.IGNORECASE))  # Nicole: "20 Energy/sec"
            or "/s" in token.lower()                           # plain "/s" suffix in token
            or ("SpCostValue" in k and _sibling_desc_says_per_sec(tm, k))  # Norma
            or ("SpCostValue_" in k and _preceding_label_says_per_sec(all_entries, k))  # Yixuan
        )
        # A cited correction wins over the label patterns, in either direction — see
        # `_load_per_sec_corrections`. Applied last so the automatic result stays readable
        # above it rather than being pre-empted.
        if k in corrections:
            per_sec = corrections[k]
        try:
            value = float(re.sub(r"[^\d.\-]", "", token))
        except ValueError:
            continue
        out.append({"key": k, "value": value, "per_sec": per_sec})
    out.sort(key=lambda e: e["key"])
    return out


def _load_overrides() -> dict[str, dict]:
    path = SCHEMA_DIR / "manual_cost_overrides.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("overrides", {})


def build(sha: str | None = None) -> dict:
    """Per-avatar EX-skill and resource-cost coverage, from TextMap plus the roster snapshot.

    *sha* overrides the provenance pin. Needed because the column hashes below
    (``_SL_SKILL_ID`` and friends) **rotate every patch**, so this script only reads a tree
    whose columns it has been re-derived against. Regenerating at the SHA the existing
    artifact was built at keeps a content change isolated from an incidental pin bump —
    which is its own task, with its own column re-derivation.
    """
    sha = sha or pinned_sha()
    tm = load_textmap("en", sha)
    wrapper = fetch_json("FileCfg/SkillListConfigTemplateTb.json", sha)
    # Every FileCfg table is `{one hashed key: [rows]}` and that key rotates too. Taking the
    # sole key is stable across pins where hard-coding it is not.
    sl = wrapper[next(iter(wrapper))]
    snap = json.loads((SCHEMA_DIR / "_db_roster_snapshot.json").read_text())
    db_by_id = {a["hakushin_id"]: a for a in snap["agents"]}
    overrides = _load_overrides()

    # avatar_id -> {code_name, ex_skills:[(id,title)], all_skill_titles}
    per_avatar: dict[int, dict] = defaultdict(
        lambda: {"code_name": None, "ex_skills": [], "n_skills": 0}
    )
    for r in sl:
        av = r[_SL_AVATAR_ID]
        title = tm.get(r[_SL_TITLE_KEY], "")
        m = _TITLE_KEY_RE.match(r[_SL_TITLE_KEY])
        if m:
            per_avatar[av]["code_name"] = m.group(1)
        per_avatar[av]["n_skills"] += 1
        if title.startswith("EX Special Attack"):
            per_avatar[av]["ex_skills"].append({"skill_id": r[_SL_SKILL_ID], "title": title})

    agents = []
    for av in sorted(per_avatar):
        info = per_avatar[av]
        code = info["code_name"]
        costs = _resource_costs(tm, code) if code else []
        db = db_by_id.get(av)
        if costs:
            cost_source = "textmap_property"
        elif code in overrides:
            ov = overrides[code]
            costs = [{
                "key": "manual_override",
                "value": ov["ex_cost"],
                "per_sec": ov.get("per_sec", False),
                "resource": ov.get("resource"),
                "source": ov["source"],
            }]
            cost_source = "manual_override"
        else:
            cost_source = "MISSING"
        agents.append(
            {
                "avatar_id": av,
                "code_name": code,
                "db_name": db["name"] if db else None,
                "in_db": db is not None,
                "ex_skill_ids": [e["skill_id"] for e in info["ex_skills"]],
                "ex_skill_titles": [e["title"] for e in info["ex_skills"]],
                "costs": costs,
                "cost_source": cost_source,
            }
        )

    have = [a for a in agents if a["cost_source"] == "textmap_property"]
    manual = [a for a in agents if a["cost_source"] == "manual_override"]
    missing = [a for a in agents if a["cost_source"] == "MISSING"]
    return {
        "_sha": sha,
        "join_source": "FileCfg/SkillListConfigTemplateTb (covers full roster; "
        "title key {Code}_SkillList_N_Title gives code-name + avatar-id)",
        "finding": (
            "EX activation cost is NOT in AvatarSkillTemplateTb / AvatarBattleTemplateTb / "
            "AvatarSkillInfoTemplateTb / SkillListConfigTemplateTb / SkillPropertyTemplateTb / "
            "ABSkillConfigTemplateTb / AbilityConfigTemplateTb. It is published only as the "
            "TextMap _Property_*SpCostValue* string (partial roster); the key AS_DecreaseSP "
            "covers only special drains (see schema/ability_layer_notes.md). Agents with "
            "neither use manual_cost_overrides.json (provenance required)."
        ),
        "roster_in_skilllist": len(agents),
        "cost_have": len(have),
        "cost_manual_override": len(manual),
        "cost_missing": len(missing),
        "manual_override_agents": [
            {"name": a["db_name"] or a["code_name"], "cost": a["costs"][0]["value"],
             "source": a["costs"][0].get("source")}
            for a in manual
        ],
        "cost_missing_agents": [
            {"avatar_id": a["avatar_id"], "name": a["db_name"] or a["code_name"],
             "ex_skill_ids": a["ex_skill_ids"], "in_db": a["in_db"]}
            for a in missing
        ],
        "agents": agents,
    }


def main() -> int:
    """Regenerate ``schema/ex_cost_coverage.json``. Manual step — it fetches from the mirror."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sha",
        default=None,
        help=(
            "Commit SHA to read (default: the provenance pin). The column constants in this "
            "module are derived per-SHA and rotate every patch, so a newer pin needs them "
            "re-derived first."
        ),
    )
    args = parser.parse_args()
    data = build(args.sha)
    out = SCHEMA_DIR / "ex_cost_coverage.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out.name}: {data['cost_have']} textmap / "
          f"{data['cost_manual_override']} manual / {data['cost_missing']} missing "
          f"(of {data['roster_in_skilllist']} in SkillList)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
