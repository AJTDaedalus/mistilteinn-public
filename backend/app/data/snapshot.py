"""The one reader of the committed YuanShenResources snapshot.

`app/data/yuanshen/snapshot/*.json` holds what nanoka does not publish: growth curves,
artifact main-stat and substat value tables, and the per-slot main-stat pools (Chunk E).
This module is the only thing that opens those files.

**One reader, on purpose** (DESIGN §1 A6). Before this existed, `app/models/artifact.py`
parsed the main-stat pools itself; a second parser for the substat table would have been the
obvious next step, and then the two would have disagreed about what a missing file means.
Here, "the snapshot is missing" has exactly one answer and one message.

Everything is cached at first use: the four files total ~300 KB and never change at run
time, and re-reading them inside an optimizer's inner loop would be the kind of accidental
cost A6's "efficiency comes from structure" is about.

Nothing here reaches the network — the files are committed, and E.6's unit-lane socket guard
is what keeps that true.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

SNAPSHOT_DIR = Path(__file__).resolve().parent / "yuanshen" / "snapshot"

#: Which curve table a growth curve belongs to. The three are separate tables upstream and
#: their names overlap (`GROW_CURVE_HP` exists for monsters and `GROW_CURVE_HP_S5` for
#: avatars), so the caller says which it means rather than the lookup guessing.
CurveKind = str


class SnapshotUnavailableError(RuntimeError):
    """A committed snapshot file is missing, unreadable, or lacks what was asked of it."""


@cache
def _load(name: str) -> dict[str, Any]:
    path = SNAPSHOT_DIR / f"{name}.json"
    if not path.exists():
        msg = (
            f"{path} is missing. It is a committed artifact, not a cache — rebuild it with "
            f"`cd backend && python -m scripts.yuanshen.build_snapshot` and commit the "
            f"result, or check out a tree that has it."
        )
        raise SnapshotUnavailableError(msg)
    return json.loads(path.read_text(encoding="utf-8"))


def growth_curve(kind: CurveKind, name: str, level: int) -> float:
    """The multiplier curve `name` applies at `level`.

    `kind` is `"avatar"`, `"weapon"` or `"monster"`. A base stat is its published base value
    times this — see `app.services.stat_calculator`, which is the only place that
    multiplication happens.

    Raises rather than returning 1.0 for an unknown curve or an out-of-range level: a
    multiplier that silently defaults to "no growth" turns a level-90 character into a
    level-1 one, and every number downstream stays plausible.
    """
    curves = _load("growth_curves")["curves"]
    table = curves.get(kind)
    if table is None:
        msg = f"no curve table named {kind!r}; the snapshot has {sorted(curves)}"
        raise SnapshotUnavailableError(msg)
    curve = table.get(name)
    if curve is None:
        msg = (
            f"{kind} curve {name!r} is not in the snapshot. Either the payload names a "
            f"curve this pin does not have, or the pin needs refreshing."
        )
        raise SnapshotUnavailableError(msg)
    value = curve["levels"].get(str(level))
    if value is None:
        levels = curve["levels"]
        msg = (
            f"{kind} curve {name!r} has no level {level} (it covers 1..{len(levels)}). "
            f"A level outside the published range is a caller bug, not a value to clamp."
        )
        raise SnapshotUnavailableError(msg)
    if curve["arith"] != "ARITH_MULTI":
        msg = (
            f"{kind} curve {name!r} is {curve['arith']}, which is not a multiplier. "
            f"Applying it as one would be wrong in a way no test downstream would catch."
        )
        raise SnapshotUnavailableError(msg)
    return float(value)


def artifact_main_stat_value(rarity: int, level: int, prop: str) -> float:
    """The value an artifact's main stat has at `rarity` and `level`.

    Level is the artifact's own 0-20 upgrade level; the table is published 1-indexed with
    level 1 meaning +0, so this shifts by one. That off-by-one is here, once, rather than
    at each call site.
    """
    values = _load("artifact_main_stat_values")["values"]
    by_level = values.get(str(rarity))
    if by_level is None:
        msg = f"no main-stat values for rarity {rarity}; the snapshot has {sorted(values)}"
        raise SnapshotUnavailableError(msg)
    row = by_level.get(str(level + 1))
    if row is None:
        msg = (
            f"rarity {rarity} has no main-stat row for artifact level {level} "
            f"(published levels cover +0 to +{len(by_level) - 1})"
        )
        raise SnapshotUnavailableError(msg)
    value = row.get(prop)
    if value is None:
        msg = f"{prop!r} is not a main stat at rarity {rarity}, so it has no value table"
        raise SnapshotUnavailableError(msg)
    return float(value)


def main_stat_pools() -> dict[str, list[str]]:
    """Slot key → the main stats it can roll, as the snapshot spells them."""
    return _load("artifact_main_stat_pools")["pools"]


def substat_rolls(depot_id: int) -> list[dict[str, Any]]:
    """The substat rolls an append depot offers: `[{id, prop, value}, …]`."""
    depots = _load("artifact_substat_values")["depots"]
    rolls = depots.get(str(depot_id))
    if rolls is None:
        msg = f"no substat depot {depot_id}; the snapshot has {sorted(depots)[:8]}…"
        raise SnapshotUnavailableError(msg)
    return rolls


def substat_depots_for_rarity(rarity: int) -> list[int]:
    """The append depots used by artifacts of `rarity`.

    Committed by E.5's review round precisely so this join needs no network and no guess
    about what `501` means.
    """
    ranks = _load("artifact_substat_values")["depot_ranks"]
    return sorted(int(depot) for depot, values in ranks.items() if rarity in values)


def pinned_commit() -> str:
    """The YuanShenResources commit every snapshot file was built from."""
    return str(_load("growth_curves")["pinned_commit_sha"])
