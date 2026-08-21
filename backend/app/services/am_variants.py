"""Anomaly Mastery variant helpers for the optimizer pipeline.

Shared by disc_optimizer, disc_scorer, rank_pipeline, and scorer.
Replaces the 4 copy-pasted has_s6_am / am_idx detections with a single
data-driven helper that handles AM-granting disc sets (e.g. Phaethon's Melody).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from app.services.modifiers import Modifier, ModifierSource

__all__ = [
    "build_am_2pc_sets",
    "enumerate_coarse_am_values",
    "resolve_coarse_am",
    "resolve_coarse_am_from_counts",
]

_AM_STATS = frozenset({"anomaly_mastery", "anomaly_mastery_pct"})


def _slot_of(disc: Any) -> int:
    s = getattr(disc, "slot", 0)
    return int(s.value if hasattr(s, "value") else s)


def _stat_of(disc: Any) -> str:
    v = getattr(disc, "main_stat_type", "")
    return v.value if hasattr(v, "value") else str(v)


def build_am_2pc_sets(
    set_modifiers: dict[int, list[Modifier]],
) -> dict[int, list[Modifier]]:
    """Return the subset of set_modifiers that grant AM via their 2pc bonus.

    Scans every set's modifier list and keeps only DISC_SET_2PC entries whose
    stat is ``anomaly_mastery`` (flat) or ``anomaly_mastery_pct``.  All other
    2pc effects (AP, CRIT, etc.) and all 4pc effects are excluded.

    Args:
        set_modifiers: dict[hakushin_set_id, list[Modifier]] as returned by
            ``_load_set_modifiers`` in optimizer_pipeline.

    Returns:
        A filtered dict; sets with no AM 2pc bonus are absent.
    """
    result: dict[int, list[Modifier]] = {}
    for set_id, mods in set_modifiers.items():
        am_mods = [
            m for m in mods if m.source == ModifierSource.DISC_SET_2PC and m.stat in _AM_STATS
        ]
        if am_mods:
            result[set_id] = am_mods
    return result


_SLOT_6 = 6
_MIN_2PC = 2


def _set_id_of(disc: Any) -> int:
    """Extract hakushin set id from DiscCandidate, PlainBuildDisc, or Disc ORM objects."""
    sid = getattr(disc, "set_id", None)
    if sid is None:
        sid = getattr(disc, "set_hakushin_id", None)
    if sid is None:
        ds = getattr(disc, "disc_set", None)
        if ds is not None:
            sid = getattr(ds, "hakushin_id", 0)
    return int(sid or 0)


def resolve_coarse_am(
    base_agent_am: int,
    discs: list[Any],
    am_2pc_sets: dict[int, list[Modifier]],
) -> int:
    """Compute coarse resolved Anomaly Mastery for AM-variant pre-computation.

    Covers:
    - Agent base AM (the stat that scales with AM%)
    - Slot-6 AM main stat value (taken from disc.main_stat_value)
    - Active AM disc-set 2pc bonuses (flat or pct)

    *Coarse* means AM substats are ignored — their contribution is uniform
    across all slot-6 candidates and is handled by the full stat resolver at
    score time.  This coarse value is used only to select the right pre-
    computed simulation bucket.

    The AM% formula matches stat_calculator.compute_total_stats (Task 1.6b):
        floor(base_agent_am * (10000 + am_pct) / 10000) + flat_am

    Args:
        base_agent_am: Agent's base_anomaly_mastery.
        discs: All discs in scope — pass locked + candidate together, or all
            discs of an existing build.  Works with DiscCandidate (.set_id)
            and PlainBuildDisc (.set_hakushin_id) objects interchangeably.
        am_2pc_sets: Output of :func:`build_am_2pc_sets`, pre-computed once
            per optimize call.

    Returns:
        Coarse resolved AM as an integer.
    """
    set_counts: dict[int, int] = Counter(_set_id_of(d) for d in discs)

    slot6_am_flat = 0
    for d in discs:
        if _slot_of(d) == _SLOT_6 and _stat_of(d) == "anomaly_mastery":
            slot6_am_flat = int(getattr(d, "main_stat_value", 0))
            break

    return resolve_coarse_am_from_counts(base_agent_am, slot6_am_flat, set_counts, am_2pc_sets)


def resolve_coarse_am_from_counts(
    base_agent_am: int,
    slot6_am_flat: int,
    set_counts: dict[int, int],
    am_2pc_sets: dict[int, list[Modifier]],
) -> int:
    """Coarse AM resolver using already-computed set_counts and slot-6 flat value.

    Identical math to :func:`resolve_coarse_am` but takes pre-computed inputs
    so callers that already hold ``set_counts`` and know the slot-6 stat avoid
    rebuilding a Counter and iterating discs a second time.

    Args:
        base_agent_am: Agent's base_anomaly_mastery.
        slot6_am_flat: The slot-6 AM main-stat value (0 if slot-6 main is not AM).
        set_counts: ``{set_id: piece_count}`` for the current combo.
        am_2pc_sets: Output of :func:`build_am_2pc_sets`.

    Returns:
        Coarse resolved AM as an integer.
    """
    flat_bonus = slot6_am_flat
    pct_bonus = 0
    for set_id, am_mods in am_2pc_sets.items():
        if set_counts.get(set_id, 0) >= _MIN_2PC:
            for mod in am_mods:
                if mod.stat == "anomaly_mastery":
                    flat_bonus += mod.value
                elif mod.stat == "anomaly_mastery_pct":
                    pct_bonus += mod.value

    return math.floor(base_agent_am * (10000 + pct_bonus) / 10000) + flat_bonus


def enumerate_coarse_am_values(
    base_agent_am: int,
    inventory: list[Any],
    am_2pc_sets: dict[int, list[Modifier]],
) -> list[int]:
    """Return sorted deduped coarse AM values for all source-combinations in inventory.

    Enumerates {slot-6 AM main on/off} × {each achievable AM 2pc set active/not},
    resolves each to a coarse AM via the same formula as :func:`resolve_coarse_am`,
    and deduplicates.  Always includes at least ``base_agent_am`` (the no-bonus case).

    Args:
        base_agent_am: Agent's ``base_anomaly_mastery`` (from BuildSnapshot).
        inventory: DiscCandidate (or PlainBuildDisc) objects to inspect for slot-6
            AM mains and achievable AM 2pc set membership.
        am_2pc_sets: Output of :func:`build_am_2pc_sets`, pre-computed once.

    Returns:
        Sorted list of distinct coarse AM integers.
    """
    # Unique slot-6 AM main values in inventory; 0 = scenario where no slot-6 AM disc is chosen.
    s6_am_values: set[int] = {0}
    for d in inventory:
        if _slot_of(d) == _SLOT_6 and _stat_of(d) == "anomaly_mastery":
            s6_am_values.add(int(getattr(d, "main_stat_value", 0)))

    # AM 2pc sets for which ≥2 inventory discs share the set — these can actually be activated.
    set_counts: dict[int, int] = Counter(_set_id_of(d) for d in inventory)
    achievable_set_ids = [sid for sid in am_2pc_sets if set_counts.get(sid, 0) >= _MIN_2PC]
    n_sets = len(achievable_set_ids)

    coarse_values: set[int] = set()
    for s6_am in s6_am_values:
        for mask in range(1 << n_sets):
            flat_bonus = s6_am
            pct_bonus = 0
            for i, set_id in enumerate(achievable_set_ids):
                if mask & (1 << i):
                    for mod in am_2pc_sets[set_id]:
                        if mod.stat == "anomaly_mastery":
                            flat_bonus += mod.value
                        elif mod.stat == "anomaly_mastery_pct":
                            pct_bonus += mod.value
            coarse_values.add(math.floor(base_agent_am * (10000 + pct_bonus) / 10000) + flat_bonus)

    return sorted(coarse_values)
