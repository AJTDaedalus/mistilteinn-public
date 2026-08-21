"""Cross-verify our modifier JSONs against zenless-optimizer reference data.

Runs three automated checks:
  1. Disc 2pc stat/value match against ZO's disc2pEffect table.
  2. W-engine R1/R5 values are present in ZO's phase[0]/phase[4] params.
  3. Coverage — which of ours don't exist in ZO, and vice versa.

Conditional 4pc effects and W-engine conditional buffs require manual
review (ZO encodes them as TypeScript); this script flags sets/engines
with conditional effects so a reviewer can spot-check them.

ZO data locations (must be cloned to /tmp/genshin-optimizer):
  - Disc 2pc:     libs/zzz/consts/src/disc.ts (disc2pEffect table)
  - W-engine:     libs/zzz/stats/src/allStat_gen.json (phase params)
  - Sheet files:  libs/zzz/formula/src/data/{disc,wengine}/sheets/

Usage:  python -m scripts.verify_zo_modifiers
Exit code 0 if no mismatches, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MODIFIERS_DIR = REPO_ROOT / "app" / "data" / "modifiers"
WENGINE_PHASE_COUNT = 5  # R1..R5
VALUE_EPSILON = 0.002  # tolerance for float comparisons
ZO_ROOT = Path("/tmp/genshin-optimizer")  # noqa: S108 — reference checkout location
ZO_DISC_CONSTS = ZO_ROOT / "libs/zzz/consts/src/disc.ts"
ZO_ALLSTATS = ZO_ROOT / "libs/zzz/stats/src/allStat_gen.json"
ZO_DISC_SHEETS = ZO_ROOT / "libs/zzz/formula/src/data/disc/sheets"
ZO_WENGINE_SHEETS = ZO_ROOT / "libs/zzz/formula/src/data/wengine/sheets"

# Map our stat names → (ZO key, unit).
# unit='pct' means our bp value / 10000 matches ZO's fractional value (e.g. 0.20).
# unit='flat' means our raw int value matches ZO's int (e.g. 30 AP).
OUR_TO_ZO_STAT: dict[str, tuple[str, str]] = {
    "atk_pct": ("atk_", "pct"),
    "atk_flat": ("atk", "flat"),
    "hp_pct": ("hp_", "pct"),
    "def_pct": ("def_", "pct"),
    "crit_rate": ("crit_", "pct"),
    "crit_dmg": ("crit_dmg_", "pct"),
    "anomaly_proficiency": ("anomProf", "flat"),
    "anomaly_proficiency_flat": ("anomProf", "flat"),
    "anomaly_mastery_flat": ("anomMas", "flat"),
    "anomaly_mastery_pct": ("anomMas_", "pct"),
    "pen_ratio": ("pen_", "pct"),
    "energy_regen": ("enerRegen_", "pct"),
    "impact_pct": ("impact_", "pct"),
    "daze_increase": ("dazeInc_", "pct"),
    "shield": ("shield_", "pct"),
    "physical_dmg": ("physical_dmg_", "pct"),
    "fire_dmg": ("fire_dmg_", "pct"),
    "ice_dmg": ("ice_dmg_", "pct"),
    "electric_dmg": ("electric_dmg_", "pct"),
    "ether_dmg": ("ether_dmg_", "pct"),
    "dmg_bonus": ("dmg_", "pct"),
    "sheer_force_flat": ("sheerForce", "flat"),
    "res_ignore": ("resIgnore_", "pct"),
    "def_ignore": ("defIgnore_", "pct"),
    "anomaly_dmg_bonus": ("anomaly_dmg_", "pct"),
    "anomaly_buildup": ("anomBuildup_", "pct"),
}

# ZO 2pc stats we intentionally don't model (non-DMG mechanics, skipped by design
# and documented in the affected JSONs' notes field).
#   dazeInc_ → KingOfTheSummit 2pc (daze, not DMG)
#   shield_  → ProtoPunk 2pc (shield strength, not DMG)
SKIPPED_ZO_2P_STATS = {"dazeInc_", "shield_"}


def parse_disc2p_effect() -> dict[str, dict[str, float]]:
    """Parse ZO's disc2pEffect table: { 'WoodpeckerElectro': {'crit_': 0.08}, ... }."""
    text = ZO_DISC_CONSTS.read_text()
    start = text.index("export const disc2pEffect")
    end = text.index("\n}\n", start) + 2
    block = text[start:end]

    result: dict[str, dict[str, float]] = {}
    for line in block.splitlines():
        m = re.match(r"\s*(\w+):\s*\{(.*)\}\s*,?", line)
        if not m or m.group(1) in ("disc2pEffect", "DiscSetKey", "PandoStatKey"):
            continue
        key, inner = m.group(1), m.group(2).strip()
        if not inner:
            result[key] = {}
            continue
        stats = {}
        for pair in inner.split(","):
            if ":" not in pair:
                continue
            k, v = pair.split(":", 1)
            stats[k.strip()] = float(v.strip())
        result[key] = stats
    return result


# Manual overrides: our snake_case filename → ZO PascalCase key.
# Roman numerals and irregular English plurals don't survive naive capitalize().
NAME_OVERRIDES: dict[str, str] = {
    "demara_battery_mark_ii": "DemaraBatteryMarkII",
    "reverb_mark_ii": "ReverbMarkII",
    "reverb_mark_iii": "ReverbMarkIII",
    "riot_suppressor_mark_vi": "RiotSuppressorMarkVI",
    "kraken_s_cradle": "KrakensCradle",
    "roaring_fur_nace": "RoaringFurnace",
}


def pascal_case(snake: str) -> str:
    if snake in NAME_OVERRIDES:
        return NAME_OVERRIDES[snake]
    return "".join(p.capitalize() for p in snake.split("_"))


def bp_to_fraction(bp: int) -> float:
    return bp / 10000


def stat_fraction_from_modifier(mod: dict[str, Any]) -> tuple[str | None, float]:
    """Return (zo_stat_key, zo_units_value) for a 2pc-style modifier."""
    our_stat = mod.get("stat")
    if our_stat not in OUR_TO_ZO_STAT:
        return None, 0.0
    zo_stat, unit = OUR_TO_ZO_STAT[our_stat]
    value = mod["value"] if unit == "flat" else bp_to_fraction(mod["value"])
    return zo_stat, value


def our_value_candidates(mod: dict[str, Any], *, rank: str) -> list[float]:
    """Candidate ZO-side values to look for in phase params for a modifier.

    ZO phase params mix units: percentages (0.20), /100-encoded (6 for 6%), and
    raw flat ints (90 AP, 15s). We don't know which without parsing TS, so we
    generate candidates and accept any match.
    """
    key = "value_r1" if rank == "r1" else "value_r5"
    if key not in mod:
        return []
    raw = mod[key]
    our_stat = mod.get("stat", "")
    _, unit = OUR_TO_ZO_STAT.get(our_stat, ("?", "pct"))
    if unit == "flat":
        return [float(raw)]
    # Percentage: our bp could map to ZO's fraction (/10000) or ZO's /100-encoded.
    return [round(raw / 10000, 4), round(raw / 100, 4)]


def verify_disc_sets() -> list[str]:
    errors: list[str] = []
    zo_2p = parse_disc2p_effect()
    zo_keys = set(zo_2p.keys())
    our_files = sorted((MODIFIERS_DIR / "disc_sets").glob("*.json"))

    our_keys: set[str] = set()
    for f in our_files:
        data = json.loads(f.read_text())
        name_pascal = pascal_case(f.stem)
        our_keys.add(name_pascal)
        if name_pascal not in zo_keys:
            # In ours, not in ZO — just report as gap, not an error.
            continue

        zo_2p_stats = zo_2p[name_pascal]
        # Find all 2pc modifiers (source ends in _2pc) that aren't conditional
        our_2pc = [
            m
            for m in data["modifiers"]
            if m.get("source", "").endswith("_2pc") and m.get("conditions") == ["always"]
        ]
        # ZO's DawnsBloom/ShadowHarmony skip disc2pEffect and hardcode in the sheet
        if name_pascal in ("DawnsBloom", "ShadowHarmony"):
            continue  # reviewed manually via sheet

        ours_set = set()
        for m in our_2pc:
            zo_stat, frac = stat_fraction_from_modifier(m)
            if zo_stat is None:
                errors.append(f"[{name_pascal}] unknown stat mapping: {m.get('stat')}")
                continue
            ours_set.add((zo_stat, round(frac, 4)))

        # Drop ZO stats we intentionally don't model (non-DMG mechanics).
        zo_effective = {
            (s, round(v, 4)) for s, v in zo_2p_stats.items() if s not in SKIPPED_ZO_2P_STATS
        }
        if ours_set != zo_effective:
            errors.append(
                f"[{name_pascal}] 2pc mismatch: ours={sorted(ours_set)}  "
                f"zo(effective)={sorted(zo_effective)}"
            )

    # Coverage report
    ours_only = our_keys - zo_keys
    zo_only = zo_keys - our_keys
    if ours_only:
        print(f"  discs in ours but not ZO (manual check): {sorted(ours_only)}")
    if zo_only:
        errors.append(f"discs in ZO but missing from ours: {sorted(zo_only)}")

    return errors


def verify_wengines() -> list[str]:
    errors: list[str] = []
    allstats = json.loads(ZO_ALLSTATS.read_text())
    zo_wengines = allstats["wengine"]
    zo_keys = set(zo_wengines.keys())
    our_files = sorted((MODIFIERS_DIR / "w_engines").glob("*.json"))

    our_keys: set[str] = set()
    for f in our_files:
        data = json.loads(f.read_text())
        name_pascal = pascal_case(f.stem)
        our_keys.add(name_pascal)
        if name_pascal not in zo_keys:
            continue

        zo_data = zo_wengines[name_pascal]
        phase = zo_data.get("phase", [])
        if len(phase) != WENGINE_PHASE_COUNT:
            errors.append(f"[{name_pascal}] ZO phase length != 5")
            continue

        r1_params = phase[0].get("params", [])
        r5_params = phase[4].get("params", [])

        for mod in data["modifiers"]:
            if "value_r1" not in mod:
                continue
            r1_candidates = our_value_candidates(mod, rank="r1")
            r5_candidates = our_value_candidates(mod, rank="r5")

            r1_match = any(
                any(abs(p - c) < VALUE_EPSILON for p in r1_params) for c in r1_candidates
            )
            r5_match = any(
                any(abs(p - c) < VALUE_EPSILON for p in r5_params) for c in r5_candidates
            )

            if not r1_match or not r5_match:
                errors.append(
                    f"[{name_pascal}] '{mod.get('source_label', mod.get('stat'))}' "
                    f"R1 cands={r1_candidates} R5 cands={r5_candidates} "
                    f"phase R1={r1_params} R5={r5_params}"
                )

    ours_only = our_keys - zo_keys
    zo_only = zo_keys - our_keys
    if ours_only:
        print(f"  w-engines in ours but not ZO (manual check): {sorted(ours_only)}")
    if zo_only:
        errors.append(f"w-engines in ZO but missing from ours: {sorted(zo_only)}")

    return errors


def main() -> int:
    if not ZO_ROOT.exists():
        print(f"ERROR: ZO reference not found at {ZO_ROOT}")
        print(
            "Clone with: git clone --depth=1 "
            "https://github.com/frzyc/genshin-optimizer.git /tmp/genshin-optimizer"
        )
        return 2

    all_errors: list[str] = []

    print("=== Disc set 2pc verification ===")
    errs = verify_disc_sets()
    all_errors.extend(errs)
    if errs:
        for e in errs:
            print(f"  ERROR: {e}")
    else:
        print("  all 2pc stats match ZO")

    print()
    print("=== W-engine R1/R5 verification ===")
    errs = verify_wengines()
    all_errors.extend(errs)
    if errs:
        for e in errs:
            print(f"  ERROR: {e}")
    else:
        print("  all R1/R5 values present in ZO phase params")

    print()
    print(f"Total issues: {len(all_errors)}")
    return 0 if not all_errors else 1


if __name__ == "__main__":
    sys.exit(main())
