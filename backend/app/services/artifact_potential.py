"""How much upgrading an artifact has left. A.5, closing G.9.

**Potential, not value** (OQ-A1). With no build there are no substat weights, and inventing
them would produce a ranking that looks authoritative and answers nobody's question. A
build-relative score arrives with the optimizer, where the weights come from.

## What is claimed, and what is not

Everything here comes from `artifact_roll_schedule.json`, derived from
`ReliquaryExcelConfigData.addPropLevels` at the pinned commit: a 5-star gains a substat at
+4/+8/+12/+16/+20, a 4-star at +4/+8/+12/+16, a 3-star at +4/+8/+12.

**Where a roll lands is deliberately not claimed.** The schedule says *when* a piece gains a
substat, not *which* one a roll enhances, and that rule is not in the committed data. So this
reports the substats a piece **has** rather than asserting what will happen to them. Writing
the placement rule from memory would be a confident number with nothing behind it — the
failure G.9 stayed blocked to avoid, and it would be perverse to commit it in the task that
finally unblocks it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.data.snapshot import (
    artifact_max_level,
    artifact_rolls_remaining,
    artifact_upgrade_levels,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class UpgradePotential:
    """What a piece has left, and the parts it was worked out from.

    The parts are here because **a score is a claim**, and this repo's standing rule is that a
    number must be able to explain itself. "Potential: 3" alone is a figure a reader has to
    take on trust; three rolls of a possible five, at +9 of a possible +20, is one they can
    check.
    """

    #: Substat rolls still to come, from the schedule for this rarity.
    rolls_remaining: int
    #: How many that rarity gets in total — the denominator that makes the first meaningful.
    rolls_total: int
    level: int
    max_level: int
    #: The substats the piece **has**. Not a claim about which will grow; see the module
    #: docstring.
    substats: tuple[str, ...]

    @property
    def levels_to_max(self) -> int:
        """How far from maximum, in the piece's own `+N` levels."""
        return self.max_level - self.level


def upgrade_potential(
    *, stars: int, level: int, substats: Sequence[object] = (),
) -> UpgradePotential:
    """The upgrade potential of one piece.

    Three values rather than a row: this is arithmetic over a committed table, and taking an
    object would make it look like it needed a database. It also keeps `app/models` free of
    an import from `app/services`, which is the wrong way round.

    Raises `SnapshotUnavailableError` for a rarity the schedule does not cover, or a level
    that rarity cannot reach. A 3-star cannot be +20, and reporting zero rolls for one would
    be a plausible number for an impossible piece.
    """
    stars = int(stars)
    level = int(level)
    return UpgradePotential(
        rolls_remaining=artifact_rolls_remaining(stars, level),
        rolls_total=len(artifact_upgrade_levels(stars)),
        level=level,
        max_level=artifact_max_level(stars),
        substats=_named(substats),
    )


def _named(substats: Sequence[object]) -> tuple[str, ...]:
    """The `stat` key of each substat, skipping anything shaped wrong.

    `substats` is a JSONB column with no schema behind it, so a row written by an older
    importer or by hand can hold anything. A piece that cannot list its substats can still say
    how many rolls it has left, and refusing to answer either would lose the useful half with
    the useless one.
    """
    return tuple(
        entry["stat"]
        for entry in substats or ()
        if isinstance(entry, dict) and isinstance(entry.get("stat"), str)
    )
