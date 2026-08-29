"""How much upgrading an artifact has left. A.5, closing G.9.

**Potential, not value** (OQ-A1). With no build there are no substat weights, and inventing
them would produce a ranking that looks authoritative and answers nobody's question. A
build-relative score arrives with the optimizer, where the weights come from.

## What is claimed, and what is not

Everything here comes from `artifact_roll_schedule.json`, derived from
`ReliquaryExcelConfigData.addPropLevels` at the pinned commit: a 5-star gains a substat at
+4/+8/+12/+16/+20, a 4-star at +4/+8/+12/+16, a 3-star at +4/+8/+12.

**Where a roll lands is deliberately not claimed.** The schedule says *when* a piece gains a
substat, not *which* one a roll enhances, and that rule is not in the committed data. Writing
it from memory would be a confident number with nothing behind it — the failure G.9 stayed
blocked to avoid, and it would be perverse to commit it in the task that finally unblocks it.

**Nor are the piece's own substats repeated here.** `ArtifactRead` already carries them in
full, with values and roll counts; listing their names again inside the potential report is
the same answer in a worse form. What this adds is rolls and levels, and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data.snapshot import (
    artifact_max_level,
    artifact_rolls_remaining,
    artifact_upgrade_levels,
)

#: Genshin gives an artifact four substats at most. Stated rather than derived: the committed
#: schedule describes *levels*, not line counts, and this is the shape of the game.
MAX_SUBSTATS = 4


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
    #: True when one of those rolls will **create the fourth substat** rather than deepen an
    #: existing one.
    #:
    #: Most of why a three-line piece is a lottery ticket and a four-line one is a known
    #: quantity: one of its upgrades is spent making a line rather than improving the ones its
    #: owner is hoping for. `None` when the substat count was not supplied, which is honest —
    #: this cannot be inferred from rarity and level alone.
    gains_a_substat: bool | None = None

    @property
    def levels_to_max(self) -> int:
        """How far from maximum, in the piece's own `+N` levels."""
        return self.max_level - self.level


def upgrade_potential(
    *, stars: int, level: int, substats: int | None = None,
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
    remaining = artifact_rolls_remaining(stars, level)
    return UpgradePotential(
        rolls_remaining=remaining,
        # `None`, not `False`, when the caller did not say how many lines the piece has. A
        # piece with four already cannot gain one; a piece with three will. Defaulting to
        # `False` would answer a question nobody asked, for every caller that predates this.
        gains_a_substat=(
            None if substats is None else remaining > 0 and substats < MAX_SUBSTATS
        ),
        rolls_total=len(artifact_upgrade_levels(stars)),
        level=level,
        max_level=artifact_max_level(stars),
    )
