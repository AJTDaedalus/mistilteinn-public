"""Build the committed YuanShenResources snapshot (E.4/E.5).

    cd backend && python -m scripts.yuanshen.build_snapshot [--check]

Writes `app/data/yuanshen/snapshot/*.json` — small, derived artifacts the runtime reads —
from the pinned commit's `ExcelBinOutput` tables. **The runtime never fetches.** These
files are the contract; regenerating them is a manual, reviewed step, and `--check` reports
drift without writing.

What is here, and why each is not in nanoka:

* `artifact_main_stat_pools.json` — which main stats each slot can roll. Not in any nanoka
  payload; this is what `app/models/artifact.py:MAIN_STAT_POOL` has been raising for since
  C.5. The derivation is spelled out in `derive_main_stat_pools` and every step cites a
  table.
* `artifact_main_stat_values.json` — `ReliquaryLevelExcelConfigData`: main-stat value by
  rarity and level.
* `artifact_substat_values.json` — `ReliquaryAffixExcelConfigData`: the substat roll values
  by rarity, which is what makes a roll count meaningful in Chunk G.
* `growth_curves.json` — the avatar, weapon and monster level curves. D.6 stored curve
  *names* on `enemy_profiles` because nanoka publishes the name and not the table; this is
  the table. Without it a Hilichurl's `base_hp` of 13.584 cannot be turned into a number.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from scripts.yuanshen.build_table_catalog import table_names
from scripts.yuanshen.fetch import SNAPSHOT_DIR, fetch_json, pinned_sha

#: Slot key → the `equipType` the config tables use. The keys are the values of
#: `app.models.enums.ArtifactSlot`, which are nanoka's `parts` keys — so this file is also
#: the bridge between the two sources' spellings for the same five slots.
SLOT_EQUIP_TYPES: dict[str, str] = {
    "equip_bracer": "EQUIP_BRACER",
    "equip_necklace": "EQUIP_NECKLACE",
    "equip_shoes": "EQUIP_SHOES",
    "equip_ring": "EQUIP_RING",
    "equip_dress": "EQUIP_DRESS",
}

#: Rarity to snapshot the artifact tables at. 5★ is what the optimizer searches; the other
#: ranks are in the source and can be added when something needs them.
ARTIFACT_RANK = 5


class SnapshotError(RuntimeError):
    """A derivation did not hold. Never downgraded to a warning — see the module docstring."""


# -- Main-stat pools ----------------------------------------------------------------

def derive_main_stat_pools(sha: str | None = None) -> dict[str, Any]:
    """Which main stats each artifact slot can roll, derived and cross-checked.

    Four tables, no guesswork, in this order:

    1. **`ReliquarySetSchemeMainPropExcelConfigData`** lists, per `equipType`, the allowed
       main-stat **prop ids** — and `ReliquaryWearMainPropExcelConfigData` lists the same
       thing independently. They agree, which is the first check.
    2. **`ReliquaryExcelConfigData` + `ReliquaryMainPropExcelConfigData`** give the *props*
       each slot's pieces can carry, via `mainPropDepotId`. This is a **superset**: a
       sands' depot contains all seven RES-shred props and flat HP/ATK/DEF, none of which
       any sands can actually roll. There is no `weight` column in this dump to filter it
       with, which is why step 1 exists.
    3. **The ten substat ids and the ten substat props are matched by order**, and the
       match is *checked* rather than trusted — see `_prop_id_map`.
    4. Whatever ids remain are pinned by **elimination against step 2**: an id set that
       only one slot has, against the props only that slot's depots offer.

    The result is then cross-checked against step 1's list lengths, so a derivation that
    resolved an id wrongly fails rather than shipping a plausible pool.
    """
    scheme = _scheme_ids("ReliquarySetSchemeMainPropExcelConfigData", sha)
    wear = _scheme_ids("ReliquaryWearMainPropExcelConfigData", sha)
    corroborated = _cross_check_scheme_tables(scheme, wear)

    depot_props = _depot_props(sha)
    slot_props = _slot_candidate_props(sha, depot_props)
    id_to_prop = _prop_id_map(sha, depot_props)

    pools: dict[str, list[str]] = {}
    resolved: dict[int, str] = {}
    for slot, equip_type in SLOT_EQUIP_TYPES.items():
        ids = scheme[equip_type]
        candidates = slot_props[equip_type]
        pool = _resolve_ids(equip_type, ids, candidates, id_to_prop, resolved)
        if len(pool) != len(ids):
            msg = (
                f"{equip_type}: resolved {len(pool)} props for {len(ids)} allowed ids "
                f"{sorted(ids)} — {sorted(pool)}"
            )
            raise SnapshotError(msg)
        pools[slot] = sorted(pool)

    return {
        "pinned_commit_sha": sha or pinned_sha(),
        "note": (
            "artifact slot -> the main stats it can roll **at `rank`** (5-star). Slot keys "
            "are app.models.enums.ArtifactSlot values (nanoka's `parts` keys); the config "
            "tables spell them EQUIP_*. `corroborated_slots` names the slots the second "
            "scheme table also covers — the others rest on one table. Derived by "
            "scripts/yuanshen/build_snapshot.py:derive_main_stat_pools — read that "
            "docstring before editing this file by hand, which you should not do."
        ),
        "sources": [
            "ReliquarySetSchemeMainPropExcelConfigData",
            "ReliquaryWearMainPropExcelConfigData",
            "ReliquaryWearAppendPropExcelConfigData",
            "ReliquaryExcelConfigData",
            "ReliquaryMainPropExcelConfigData",
            "ReliquaryAffixExcelConfigData",
            "ReliquaryLevelExcelConfigData",
        ],
        "rank": ARTIFACT_RANK,
        "corroborated_slots": corroborated,
        "prop_ids": {
            SLOT_EQUIP_TYPES[slot]: sorted(scheme[SLOT_EQUIP_TYPES[slot]]) for slot in pools
        },
        "prop_id_names": {str(key): value for key, value in sorted(resolved.items())},
        "pools": pools,
    }


def _cross_check_scheme_tables(
    scheme: dict[str, set[int]], wear: dict[str, set[int]],
) -> list[str]:
    """Check the two main-prop tables against each other; return the slots corroborated.

    **A loop over `wear` alone is not a check.** The wear table holds only three rows at
    the pinned commit (shoes, ring, dress), so the flower and plume were never corroborated
    by it — and if a re-pin renamed or emptied that table, `wear` would be `{}`, the loop
    would run zero times, and the build would proceed on a single uncorroborated source
    while reporting that the tables agreed. That is a skipped check reading as a pass.

    So: an empty wear table is a failure, a wear entry naming a slot the scheme table does
    not is a failure, and the slots that *were* corroborated are returned and recorded in
    the snapshot — a shrink then shows up as a diff instead of as silence.
    """
    if not wear:
        msg = (
            "ReliquaryWearMainPropExcelConfigData is empty, so nothing corroborates "
            "ReliquarySetSchemeMainPropExcelConfigData. The pools are derived from one "
            "source or from two; they are not derived from one source called two."
        )
        raise SnapshotError(msg)
    for equip_type, ids in wear.items():
        if equip_type not in scheme:
            msg = (
                f"{equip_type} is in the wear table but not the scheme table; the two no "
                f"longer describe the same slots"
            )
            raise SnapshotError(msg)
        if scheme[equip_type] != ids:
            msg = (
                f"{equip_type}: the two main-prop scheme tables disagree — "
                f"SetScheme={sorted(scheme[equip_type])} vs Wear={sorted(ids)}. "
                f"Both describe the same rule; a disagreement means neither can be trusted."
            )
            raise SnapshotError(msg)
    return sorted(wear)


def _scheme_ids(table: str, sha: str | None) -> dict[str, set[int]]:
    """`equipType -> allowed main-stat prop ids`, from either scheme table.

    Both tables carry the id lists under **obfuscated column names** (`HANABIILGLG`,
    `DFGOJJFJODK`, …) beside a readable `equipType`, and the ring row splits its ids across
    two such columns. So the ids are taken as "every integer list in the row", which is
    stable across a re-obfuscation in a way that hard-coded column names would not be.
    """
    rows = fetch_json(f"ExcelBinOutput/{table}.json", sha)
    scheme: dict[str, set[int]] = {}
    for row in rows:
        equip_type = row.get("equipType")
        if not equip_type:
            continue
        ids: set[int] = set()
        for key, value in row.items():
            if key == "equipType" or not isinstance(value, list):
                continue
            ids.update(entry for entry in value if isinstance(entry, int))
        scheme[equip_type] = ids
    return scheme


def _depot_props(sha: str | None) -> dict[int, set[str]]:
    """`mainPropDepotId -> the props in it`."""
    depots: dict[int, set[str]] = {}
    for row in fetch_json("ExcelBinOutput/ReliquaryMainPropExcelConfigData.json", sha):
        depots.setdefault(row["propDepotId"], set()).add(row["propType"])
    return depots


def _slot_candidate_props(sha: str | None, depots: dict[int, set[str]]) -> dict[str, set[str]]:
    """`equipType -> every prop any of its pieces' depots contains, at `ARTIFACT_RANK`."""
    candidates: dict[str, set[str]] = {}
    for row in fetch_json("ExcelBinOutput/ReliquaryExcelConfigData.json", sha):
        if row.get("rankLevel") != ARTIFACT_RANK:
            continue
        depot = row.get("mainPropDepotId")
        if depot:
            candidates.setdefault(row["equipType"], set()).update(depots.get(depot, ()))
    return candidates


def _prop_id_map(sha: str | None, depots: dict[int, set[str]]) -> dict[int, str]:
    """`prop id -> FIGHT_PROP name` for the ten substat props, matched by order and checked.

    **Not** from `ReliquaryAffixExcelConfigData.group_id`. That column looks like the prop
    id and mostly coincides with it, but it is the affix table's own grouping: Elemental
    Mastery's rows are group 24/25 while its prop id is 28. Building on it would have been
    right sixteen times and wrong twice, which is worse than being obviously wrong.

    The derivation instead uses two orderings that can be cross-checked against each other:

    * `ReliquaryWearAppendPropExcelConfigData` lists the **ten substat prop ids**
      (`[2, 3, 5, 6, 8, 9, 20, 22, 28, 23]`).
    * `ReliquaryLevelExcelConfigData` lists every main-stat prop **in ascending id order**
      — which is exactly what the check below establishes rather than assumes.

    Filtering the level table's ordered props down to the ten that appear as substats and
    zipping them against the sorted ids gives the mapping. Two entries of that mapping are
    independently provable — the flower's depot holds exactly one prop and its allowed-id
    list holds exactly one id, and the same for the plume — so the zip is verified at two
    points before any of it is used. A patch that reorders the level table breaks those two
    assertions and fails the build instead of silently renaming every stat.
    """
    substat_ids = sorted(_append_prop_ids(sha))
    substat_props = _substat_props(sha)
    ordered = [prop for prop in _level_table_props(sha) if prop in substat_props]
    if len(ordered) != len(substat_ids):
        msg = (
            f"{len(substat_ids)} substat ids {substat_ids} against {len(ordered)} substat "
            f"props {ordered} — the two tables no longer describe the same set"
        )
        raise SnapshotError(msg)
    mapping = dict(zip(substat_ids, ordered, strict=True))
    _assert_single_prop_slot(mapping, "EQUIP_BRACER", sha, depots)
    _assert_single_prop_slot(mapping, "EQUIP_NECKLACE", sha, depots)
    return mapping


def _append_prop_ids(sha: str | None) -> set[int]:
    """The substat prop ids, from `ReliquaryWearAppendPropExcelConfigData`.

    One row, one obfuscated column, one integer list — so the ids are read as "every
    integer in the row", the same way the main-prop scheme tables are read.
    """
    rows = fetch_json("ExcelBinOutput/ReliquaryWearAppendPropExcelConfigData.json", sha)
    ids: set[int] = set()
    for row in rows:
        for value in row.values():
            if isinstance(value, list):
                ids.update(entry for entry in value if isinstance(entry, int))
    return ids


def _substat_props(sha: str | None) -> set[str]:
    """The props a real artifact can roll as a **substat**.

    Scoped to the append depots that `ReliquaryExcelConfigData` actually points at:
    `ReliquaryAffixExcelConfigData` also holds rows for depots nothing equips, and taking
    its props wholesale would pull in RES-shred entries that are not substats.
    """
    depot_ids = {
        row["appendPropDepotId"]
        for row in fetch_json("ExcelBinOutput/ReliquaryExcelConfigData.json", sha)
        if row.get("rankLevel") == ARTIFACT_RANK and row.get("appendPropDepotId")
    }
    return {
        row["propType"]
        for row in fetch_json("ExcelBinOutput/ReliquaryAffixExcelConfigData.json", sha)
        if row["depotId"] in depot_ids
    }


def _level_table_props(sha: str | None) -> list[str]:
    """The main-stat props in `ReliquaryLevelExcelConfigData`'s own order."""
    rows = fetch_json("ExcelBinOutput/ReliquaryLevelExcelConfigData.json", sha)
    ordered: list[str] = []
    for prop in rows[0].get("addProps", []):
        name = prop.get("propType")
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _assert_single_prop_slot(
    mapping: dict[int, str], equip_type: str, sha: str | None, depots: dict[int, set[str]],
) -> None:
    """Check the mapping against a slot whose pool is provable without it.

    The flower and the plume each have exactly one allowed id and exactly one prop in their
    depot, so `mapping[that id]` must be `that prop` — no ordering assumption involved. Two
    such checks are what turn the zip above from a guess into a derivation.
    """
    ids = _scheme_ids("ReliquarySetSchemeMainPropExcelConfigData", sha).get(equip_type, set())
    props = _slot_candidate_props(sha, depots).get(equip_type, set())
    if len(ids) != 1 or len(props) != 1:
        msg = (
            f"{equip_type} was expected to have exactly one allowed id and one candidate "
            f"prop; found ids={sorted(ids)} props={sorted(props)}"
        )
        raise SnapshotError(msg)
    prop_id, prop = next(iter(ids)), next(iter(props))
    if mapping.get(prop_id) != prop:
        msg = (
            f"{equip_type}: id {prop_id} maps to {mapping.get(prop_id)} but that slot's "
            f"only prop is {prop}. The substat id/prop ordering no longer lines up, so "
            f"every id resolved through it would be wrong."
        )
        raise SnapshotError(msg)


def _resolve_ids(
    equip_type: str,
    ids: set[int],
    candidates: set[str],
    id_to_prop: dict[int, str],
    resolved: dict[int, str],
) -> set[str]:
    """Map one slot's allowed ids to prop names, eliminating what the mapping cannot.

    An id the substat mapping names is taken from there. The ids left over are matched
    **as a set** against the props this slot's depots offer that no mapped id has claimed:
    if the two counts agree, the pool is determined even though the individual pairing is
    not — and the pool is all this function is asked for. The goblet is the case that
    matters: eight unmapped ids (`30`, `40`-`46`) against exactly eight props no other slot
    offers. Which id is Pyro and which is Cryo is not derivable here and is not needed.

    A count mismatch raises. That is the difference between "the set is determined" and
    "one of these props is in the pool and I picked it".
    """
    pool: set[str] = set()
    unmapped: list[int] = []
    for prop_id in sorted(ids):
        name = id_to_prop.get(prop_id) or resolved.get(prop_id)
        if name is None:
            unmapped.append(prop_id)
            continue
        if name not in candidates:
            msg = (
                f"{equip_type}: id {prop_id} maps to {name}, which none of this slot's "
                f"depots offer ({sorted(candidates)})"
            )
            raise SnapshotError(msg)
        resolved.setdefault(prop_id, name)
        pool.add(name)

    if not unmapped:
        return pool

    # Props this slot offers that no mapped id has claimed — an unmapped id cannot name a
    # prop some other id already is.
    remaining = candidates - pool - set(id_to_prop.values())
    if len(remaining) != len(unmapped):
        msg = (
            f"{equip_type}: {len(unmapped)} unmapped prop id(s) {unmapped} against "
            f"{len(remaining)} unclaimed candidate prop(s) {sorted(remaining)}. The pool "
            f"is only determined when those counts agree; choosing a subset would be a "
            f"guess."
        )
        raise SnapshotError(msg)
    if len(unmapped) == 1:
        # A one-to-one leftover *is* a resolved id, and worth recording as one.
        resolved[unmapped[0]] = next(iter(remaining))
    return pool | remaining


# -- Value tables and curves --------------------------------------------------------

def build_main_stat_values(sha: str | None = None) -> dict[str, Any]:
    """Main-stat value by rarity and level (`ReliquaryLevelExcelConfigData`)."""
    values: dict[str, dict[str, dict[str, float]]] = {}
    for row in fetch_json("ExcelBinOutput/ReliquaryLevelExcelConfigData.json", sha):
        rank = row.get("rank")
        if rank is None:
            continue
        level = values.setdefault(str(rank), {}).setdefault(str(row["level"]), {})
        for prop in row.get("addProps", []):
            if prop.get("propType"):
                level[prop["propType"]] = prop.get("value", 0.0)
    return {
        "pinned_commit_sha": sha or pinned_sha(),
        "sources": ["ReliquaryLevelExcelConfigData"],
        "note": "rarity -> level -> prop -> main-stat value.",
        "values": values,
    }


def build_substat_values(sha: str | None = None) -> dict[str, Any]:
    """Substat roll values by depot (`ReliquaryAffixExcelConfigData`).

    Kept keyed by `depotId` rather than flattened to rarity: the depot is what
    `ReliquaryExcelConfigData.appendPropDepotId` points at, so this stays joinable.
    """
    depots: dict[str, list[dict[str, Any]]] = {}
    for row in fetch_json("ExcelBinOutput/ReliquaryAffixExcelConfigData.json", sha):
        depots.setdefault(str(row["depotId"]), []).append(
            {"id": row["id"], "prop": row["propType"], "value": row["propValue"]},
        )
    for rows in depots.values():
        rows.sort(key=lambda entry: entry["id"])
    return {
        "pinned_commit_sha": sha or pinned_sha(),
        "sources": ["ReliquaryAffixExcelConfigData", "ReliquaryExcelConfigData"],
        "note": (
            "appendPropDepotId -> the substat rolls it offers, plus the rarities that use "
            "each depot. **The rarity map is the point.** Without it the only way to use "
            "this table offline would be to infer `501 == 5-star` from the id pattern — "
            "an uncited derivation from memory, which is exactly what the no-network rule "
            "is supposed to prevent rather than force."
        ),
        "depot_ranks": _depot_ranks(sha),
        "depots": depots,
    }


def _depot_ranks(sha: str | None) -> dict[str, list[int]]:
    """`appendPropDepotId -> the rarities of the pieces that use it`.

    Joined here, at build time, because `ReliquaryExcelConfigData` is 4,352 rows and lives
    only in the gitignored cache. Committing the join is what makes the substat table
    usable by Chunk G without a network call or a guess.
    """
    ranks: dict[str, set[int]] = {}
    for row in fetch_json("ExcelBinOutput/ReliquaryExcelConfigData.json", sha):
        depot, rank = row.get("appendPropDepotId"), row.get("rankLevel")
        if depot and rank:
            ranks.setdefault(str(depot), set()).add(rank)
    return {depot: sorted(values) for depot, values in sorted(ranks.items())}


def build_growth_curves(sha: str | None = None) -> dict[str, Any]:
    """The avatar, weapon and monster level curves: `curve name -> level -> multiplier`."""
    curves: dict[str, dict[str, dict[str, float]]] = {}
    for kind, table in (
        ("avatar", "AvatarCurveExcelConfigData"),
        ("weapon", "WeaponCurveExcelConfigData"),
        ("monster", "MonsterCurveExcelConfigData"),
    ):
        by_name: dict[str, dict[str, Any]] = {}
        for row in fetch_json(f"ExcelBinOutput/{table}.json", sha):
            for info in row.get("curveInfos", []):
                name = info.get("type")
                if not name:
                    continue
                arith = info.get("arith", "ARITH_MULTI")
                entry = by_name.setdefault(name, {"arith": arith, "levels": {}})
                # **How a curve is applied is data, not a constant.** Most are
                # ARITH_MULTI, but `GROW_CURVE_STRIKE` in the monster table is ARITH_ADD —
                # found by asserting uniformity and watching it fail. A curve that changed
                # arith *between levels* would be unusable either way, so that still raises.
                if entry["arith"] != arith:
                    msg = (
                        f"{table}: curve {name} is {entry['arith']} at one level and "
                        f"{arith} at level {row['level']}"
                    )
                    raise SnapshotError(msg)
                entry["levels"][str(row["level"])] = info.get("value", 0.0)
        curves[kind] = by_name
    return {
        "pinned_commit_sha": sha or pinned_sha(),
        "sources": [
            "AvatarCurveExcelConfigData",
            "WeaponCurveExcelConfigData",
            "MonsterCurveExcelConfigData",
        ],
        "note": (
            "kind -> GROW_CURVE_* name -> {arith, levels: {level: value}}. For an "
            "ARITH_MULTI curve a base stat is its curve base times the level value. "
            "`arith` is stored rather than assumed: GROW_CURVE_STRIKE in the monster "
            "table is ARITH_ADD."
        ),
        "curves": curves,
    }


# -- CLI ----------------------------------------------------------------------------

def build_roll_schedule(sha: str | None = None) -> dict[str, Any]:
    """When an artifact gains a substat roll, and how many it starts with (G.9).

    **This is the citation G.9 was blocked on.** Upgrade-potential scoring — "what could this
    +0 piece become at +20" — needs the number of rolls a piece gains as it levels, and the
    task refused to guess it: *"a potential score built on a guessed roll count is a confident
    number with nothing behind it."* Both halves turn out to be published, and neither had
    been read:

    - **`ReliquaryExcelConfigData.addPropLevels`** — the levels at which a piece gains a
      substat, `[5, 9, 13, 17, 21]` wherever it appears.
    - **`ReliquaryExcelConfigData.appendPropNum`** — how many substats it starts with.
    - **`maxLevel`** — which of those upgrade levels a rarity actually reaches. A 3-star caps
      at internal 13, so only three of the five apply. Reading the schedule without this
      would credit a 3-star with a 5-star's upgrades.

    ## Levels are converted here, once

    The tables are **1-indexed** — internal level 1 is the artifact's `+0`, exactly as
    `ReliquaryLevelExcelConfigData` is, which is why
    `app.data.snapshot.artifact_main_stat_value` already shifts by one. The published
    `[5, 9, 13, 17, 21]` therefore means game levels **+4, +8, +12, +16, +20**.
    `raw_add_prop_levels` keeps the unconverted values beside them so the conversion can be
    checked against the source rather than trusted.

    ## The 32 rows that are excluded, and why they are counted rather than dropped

    Rarity 1 publishes **two** kinds of piece: 300 ordinary ones capping at internal 5, and
    32 that cap at 1, carry **no `setId`** and **no `addPropLevels` at all** — the setless
    starter relics, which cannot be upgraded and belong to no set bonus. They are excluded
    from the schedules and reported in `excluded_unupgradable`, because a builder that
    silently dropped 32 rows is a builder whose output nobody can reconcile with the source.
    """
    rows = fetch_json("ExcelBinOutput/ReliquaryExcelConfigData.json", sha)

    schedules: dict[str, dict[str, Any]] = {}
    initial: dict[str, list[int]] = {}
    excluded = 0
    for row in rows:
        rank, max_level = row.get("rankLevel"), row.get("maxLevel")
        if rank is None or max_level is None:
            continue
        raw = [level for level in row.get("addPropLevels", ()) if level <= max_level]
        if not raw:
            excluded += 1
            continue

        key = str(rank)
        entry = {
            "max_level": max_level - 1,
            "raw_max_level": max_level,
            "upgrade_levels": [level - 1 for level in raw],
            "raw_add_prop_levels": list(raw),
        }
        seen = schedules.setdefault(key, entry)
        # Two schedules for one rarity would make "the schedule for 5-star" meaningless, so a
        # disagreement is an error rather than last-write-wins.
        if seen != entry:
            msg = (
                f"rarity {rank} publishes two different upgrade schedules: {seen} and "
                f"{entry}. One rarity cannot have two."
            )
            raise SnapshotError(msg)

        # A missing `appendPropNum` is **zero, not unknown**. These dumps omit zero-valued
        # integers, which is checkable rather than assumed: in
        # `ReliquaryLevelExcelConfigData` exactly one row omits `exp` and exactly one omits
        # `rank` — the same row, `{"level": 1}`, which is rank 0 at zero exp. Reading the
        # omission as "absent" instead would drop the 0-substat variant from every rarity and
        # leave `initial_substat_counts` quietly starting at 1.
        counts = initial.setdefault(key, [])
        num = row.get("appendPropNum", 0)
        if num not in counts:
            counts.append(num)

    for counts in initial.values():
        counts.sort()

    return {
        "pinned_commit_sha": sha or pinned_sha(),
        "sources": ["ReliquaryExcelConfigData"],
        "note": (
            "rarity -> when a piece gains a substat, in the artifact's own +0..+20 levels. "
            "`upgrade_levels` is converted from the 1-indexed `addPropLevels` the table "
            "publishes; `raw_add_prop_levels` is what it published, so the conversion can be "
            "checked rather than trusted. `initial_substat_counts` is every `appendPropNum` "
            "seen at that rarity, treating an omitted key as the zero these dumps do not "
            "write — a piece rolls with one of them, and which one is not knowable from the "
            "catalogue. `excluded_unupgradable` counts the setless starter relics that carry "
            "no addPropLevels at all."
        ),
        "excluded_unupgradable": excluded,
        "schedules": schedules,
        "initial_substat_counts": initial,
    }


BUILDERS = {
    "artifact_main_stat_pools": derive_main_stat_pools,
    "artifact_main_stat_values": build_main_stat_values,
    "artifact_substat_values": build_substat_values,
    "growth_curves": build_growth_curves,
    "artifact_roll_schedule": build_roll_schedule,
}


def main() -> int:
    """Parse arguments and build (or check) every snapshot file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", default=None, help="override the pinned commit SHA")
    parser.add_argument(
        "--check", action="store_true", help="report drift without writing; exit 1 if any",
    )
    args = parser.parse_args()

    known = table_names(args.sha)
    drifted: list[str] = []
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for name, builder in BUILDERS.items():
        payload = builder(args.sha)
        for table in payload["sources"]:
            if table not in known:
                msg = f"{name}: {table} is not in the committed table catalog"
                raise SnapshotError(msg)
        body = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
        path = SNAPSHOT_DIR / f"{name}.json"
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if args.check:
            state = "MATCH" if existing == body else "DRIFT"
            print(f"  {state} {path.name} ({len(body.encode()):,} bytes)")
            if existing != body:
                drifted.append(path.name)
            continue
        path.write_text(body, encoding="utf-8")
        state = "unchanged" if existing == body else ("new" if existing is None else "updated")
        print(f"  {state:>9} {path.name} ({len(body.encode()):,} bytes)")

    if drifted:
        print(f"\n{len(drifted)} snapshot file(s) differ from the pinned commit:", file=sys.stderr)
        for name in drifted:
            print(f"  {name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
