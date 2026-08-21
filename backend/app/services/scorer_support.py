"""Pure helper functions shared by the scorer endpoint and disc_ranker service.

These are extracted from app/api/v1/scorer.py so that disc_ranker.py can
import them without depending on an API module.  All outputs are plain
dataclasses / dicts — picklable, required for process-pool use in the rank
pipeline (R2.6).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from app.services.snapshot_builder import applicable_set_modifiers

if TYPE_CHECKING:
    from app.models.disc import Disc
    from app.services.build_damage_service import BuildSnapshot
    from app.services.disc_optimizer import DiscCandidate
    from app.services.modifiers import Modifier

_MIN_2PC = 2
_MIN_4PC = 4


def _disc_stat_dict(disc: Disc) -> dict:
    """Convert a Disc ORM model to the stat-dict shape the snapshot consumes."""
    stat_type = disc.main_stat_type
    if hasattr(stat_type, "value"):
        stat_type = stat_type.value
    return {
        "main_stat_type": stat_type,
        "main_stat_value": disc.main_stat_value,
        "substats": list(disc.substats or []),
    }


def _slot_value(disc: Disc) -> int:
    slot = disc.slot
    if hasattr(slot, "value"):
        return int(slot.value)
    return int(slot)


def _other_disc_stats(build_discs: list[Disc], target_slot: int) -> list[dict]:
    """Stat dicts for the build's discs in slots other than the target's."""
    return [_disc_stat_dict(d) for d in build_discs if _slot_value(d) != target_slot]


def _hypothetical_set_counts(
    build_discs: list[Disc],
    target: DiscCandidate,
) -> dict[int, int]:
    """Set-piece counts for the hypothetical 6-disc inventory: 5 others + target."""
    counts: Counter[int] = Counter()
    for disc in build_discs:
        if _slot_value(disc) == target.slot:
            continue
        if disc.disc_set is None:
            continue
        counts[disc.disc_set.hakushin_id] += 1
    counts[target.set_id] += 1
    return dict(counts)


def _disc_rarity_str(disc: Disc) -> str:
    rarity = disc.rarity
    if hasattr(rarity, "value"):
        return str(rarity.value)
    return str(rarity)


def _build_base_for_target(
    *,
    stripped: BuildSnapshot,
    build_discs: list[Disc],
    target: DiscCandidate,
    disc_set_modifiers: dict[int, list[Modifier]],
) -> BuildSnapshot:
    """Snapshot with the other five discs filled and set bonuses applied.

    The scorer treats this as a fixed base and only varies the target
    disc's substats. Set counts include the target so its 2pc/4pc
    contribution is reflected in the baseline.

    ``stripped`` must be the **scorer's** disc-stripped snapshot, with team
    supports folded in (``SnapshotSplit.scoring_base``, issue #121) — this
    function only re-adds disc stats and disc-set modifiers, so it is the last
    point at which a support's team buff can reach a disc score.
    """
    other_stats = _other_disc_stats(build_discs, target.slot)
    set_counts = _hypothetical_set_counts(build_discs, target)
    set_mods = applicable_set_modifiers(
        set_counts,
        disc_set_modifiers,
        equipper_specialty=stripped.agent_specialty,
        equipper_element=stripped.agent_element,
        equipper_name=stripped.agent_name,
    )
    return replace(
        stripped,
        disc_stats=other_stats,
        modifiers=[*stripped.modifiers, *set_mods],
    )
