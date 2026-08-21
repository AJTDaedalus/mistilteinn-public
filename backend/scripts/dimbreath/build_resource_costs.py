"""T4.1 — Validate the cartography map by example: resource-cost re-derivation.

This is the *proof* that the Dimbreath map (Phase 1-3 artifacts) is correct and
that the current ``app/data/energy_costs.py`` table has drifted. It consumes ONLY
schema artifacts — ``schema/ex_cost_coverage.json`` (the resource-cost extract
produced by ``build_ex_cost_coverage.py`` per the T3.2 ``resource_costs`` recipe)
plus the merged TextMap (for resource *names*) — and produces:

* ``schema/resource_costs.json`` — a clean, preview-only resource-cost table for
  the full roster (energy + named per-use / per-second resources). NOT wired into
  the app; it hands off to the already-scoped resource-cost feature.
* ``schema/resource_costs_diff.md`` — a diff of the re-derived energy cost against
  the live ``energy_costs.py`` table, listing every change (this is where the
  Anby 40→60 drift surfaces).

Run: ``python -m scripts.dimbreath.build_resource_costs``
"""

from __future__ import annotations

import argparse
import json
import re

from scripts.dimbreath.fetch import SCHEMA_DIR, load_textmap, pinned_sha

# Frozen pre-rework snapshot of energy_costs.py (as of feat/resource-costs
# Task 6). This is intentionally a historical baseline for the diff report
# only — do not extend or treat as a live data source.
_LEGACY_EX_COSTS: dict[str, int] = {
    "anby": 40,
    "burnice": 40,
}
_LEGACY_EX_COST_DEFAULT: int = 60


def _legacy_get_ex_cost(agent_name: str) -> int:
    return _LEGACY_EX_COSTS.get(agent_name.lower(), _LEGACY_EX_COST_DEFAULT)


def _resource_label(tm: dict[str, str], key: str) -> str:
    """Human resource name for a cost key, via the sibling label/title row.

    Two TextMap mechanisms (per the T3.2 recipe):
      * ``*_SpCostValue_NN`` → ``*_Desc_SpCost_NN``  (e.g. Burnice "Fire Blast
        Energy Cost"); these are all Energy (SP) costs.
      * ``*CostValue_NN``    → ``*Cost_Title_NN``     (e.g. Velina
        ``FengHuaCost_Title`` = "Windbloom Cost").
    Falls back to "Energy" for SP keys with no descriptor (e.g. Anby), else the
    raw key segment before "CostValue".
    """
    desc_key = key.replace("SpCostValue", "Desc_SpCost")
    if desc_key != key and tm.get(desc_key):
        # descriptors are all Energy (SP) costs; normalise to the resource word
        return "Energy"
    title_key = key.replace("CostValue", "Cost_Title")
    if title_key != key and (title := tm.get(title_key)):
        return re.sub(r"\s*Cost$", "", title).strip()  # "Windbloom Cost" → "Windbloom"
    if "SpCost" in key:
        return "Energy"
    seg = re.search(r"_([A-Za-z]+)CostValue", key)  # e.g. FengHua
    return seg.group(1) if seg else "Energy"


def _is_primary_energy(cost: dict) -> bool:
    """A non-per-second EX-Special SP (energy) activation cost."""
    return (
        not cost["per_sec"]
        and "ExSpecial" in cost["key"]
        and "SpCostValue" in cost["key"]
    )


def _load_existing_provenance() -> dict[str, str]:
    """Read provenance notes from the committed extract for carry-forward."""
    path = SCHEMA_DIR / "resource_costs.json"
    if not path.exists():
        return {}
    try:
        existing = json.loads(path.read_text())
        return {
            name: data["provenance"]
            for name, data in existing.get("agents", {}).items()
            if "provenance" in data
        }
    except Exception:
        return {}


def build(sha: str | None = None) -> dict:
    """Per-agent resource costs, from ``ex_cost_coverage.json`` plus TextMap for names.

    *sha* overrides the provenance pin, and should normally be set to the SHA the
    ``ex_cost_coverage.json`` input was built at. Otherwise ``_sha`` records the tree this
    run *read names from* while the cost values came from a different one — a provenance
    claim that is quietly false, which for a schema artifact is worse than being stale.
    """
    sha = sha or pinned_sha()
    tm = load_textmap("en", sha)
    cov = json.loads((SCHEMA_DIR / "ex_cost_coverage.json").read_text())
    provenance = _load_existing_provenance()

    agents: dict[str, dict] = {}
    for a in cov["agents"]:
        name = (a["db_name"] or a["code_name"]).lower()
        costs = []
        for c in a["costs"]:
            key = c.get("key", "")
            resource = (
                c["resource"] if c.get("resource") else _resource_label(tm, key)
            )
            costs.append(
                {
                    "value": c["value"],
                    "per_sec": c["per_sec"],
                    "resource": resource,
                    "key": key,
                }
            )
        # Candidate activation costs: non-per-second ExSpecial SP (energy) values.
        # A 0-cost mode is never the headline activation cost (some agents have a
        # conditional free variant) — pick the first non-zero, but flag when modes
        # disagree so there is explicit curation on the ambiguous agents.
        energy_modes = [c["value"] for c in costs if _is_primary_energy(c)]
        if not energy_modes:  # manual overrides etc. — first non-per-sec Energy
            energy_modes = [
                c["value"]
                for c in costs
                if not c["per_sec"] and c["resource"] == "Energy"
            ]
        nonzero = [v for v in energy_modes if v]
        primary = (nonzero or energy_modes or [None])[0]
        ambiguous = len({v for v in energy_modes if v}) > 1
        entry: dict = {
            "avatar_id": a["avatar_id"],
            "db_name": a["db_name"],
            "code_name": a["code_name"],
            "ex_energy_cost": primary,
            "ex_energy_ambiguous": ambiguous,
            "costs": costs,
            "cost_source": a["cost_source"],
        }
        if name in provenance:
            entry["provenance"] = provenance[name]
        agents[name] = entry

    return {
        "_sha": sha,
        "_derived_from": "schema/ex_cost_coverage.json + merged EN TextMap (names)",
        "roster": len(agents),
        "agents": dict(sorted(agents.items())),
    }


def _diff_against_energy_costs(data: dict) -> str:
    """Diff re-derived EX energy cost vs the frozen legacy energy_costs.py baseline."""
    lines: list[str] = []
    changes: list[tuple[str, object, object, str]] = []
    for name, a in data["agents"].items():
        mapped = a["ex_energy_cost"]
        if mapped is None:
            continue
        current = _legacy_get_ex_cost(name)
        explicit = name in _LEGACY_EX_COSTS
        basis = "table" if explicit else f"default({_LEGACY_EX_COST_DEFAULT})"
        if int(mapped) != int(current):
            changes.append((name, current, mapped, basis))

    lines.append("# T4.1 — resource_costs re-derivation diff vs energy_costs.py\n")
    lines.append(f"- map SHA: `{data['_sha']}`")
    lines.append(f"- roster re-derived: **{data['roster']}**")
    lines.append(f"- explicit table entries: {sorted(_LEGACY_EX_COSTS)}")
    lines.append(f"- table default fallback: **{_LEGACY_EX_COST_DEFAULT}**")
    lines.append(f"- **{len(changes)} agents differ** from the live table\n")
    lines.append("| agent | current (energy_costs.py) | map (Dimbreath) | basis |")
    lines.append("|---|---|---|---|")
    for name, cur, mapped, basis in changes:
        flag = " ⚠️ DRIFT" if basis == "table" else ""
        lines.append(f"| {name} | {cur} | {int(mapped)} | {basis}{flag} |")

    # explicit-table drift callout (Anby is the headline)
    drift = [c for c in changes if c[3] == "table"]
    lines.append("")
    if drift:
        lines.append("## ⚠️ Explicit-table drift (wrong values shipped today)")
        for name, cur, mapped, _ in drift:
            lines.append(f"- **{name}**: table says {cur}, map says {int(mapped)}")
    else:
        lines.append("## No explicit-table drift detected")

    # multi-mode agents: the primary energy cost is a judgment call (first
    # non-zero mode) — list them so the resource-cost feature reviews them.
    ambiguous = [n for n, a in data["agents"].items() if a["ex_energy_ambiguous"]]
    lines.append("")
    lines.append("## Multi-mode EX (primary = first non-zero mode — verify on handoff)")
    for name in ambiguous:
        modes = [
            (c["value"], "/s" if c["per_sec"] else "")
            for c in data["agents"][name]["costs"]
            if c["resource"] == "Energy"
        ]
        rendered = ", ".join(f"{v}{s}" for v, s in modes)
        lines.append(f"- **{name}**: energy modes [{rendered}] → primary "
                     f"{int(data['agents'][name]['ex_energy_cost'])}")
    return "\n".join(lines) + "\n"


def main() -> int:
    """Regenerate ``schema/resource_costs.json``. Manual step — it fetches from the mirror."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sha",
        default=None,
        help=(
            "Commit SHA to read (default: the provenance pin). Set it to match the SHA "
            "ex_cost_coverage.json was built at, or _sha will misreport this file's origin."
        ),
    )
    args = parser.parse_args()
    data = build(args.sha)
    out = SCHEMA_DIR / "resource_costs.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    diff = _diff_against_energy_costs(data)
    diff_path = SCHEMA_DIR / "resource_costs_diff.md"
    diff_path.write_text(diff)
    print(f"wrote {out.name}: {data['roster']} agents")
    print(f"wrote {diff_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
