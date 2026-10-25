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
from functools import cache

from app.data.external import (
    GO_KEY_TO_PROPERTY,
    MAIN_STAT_GO_KEY_TO_PROPERTY,
    ExternalDataUnavailableError,
    domain_drop_model,
    main_stat_probabilities,
    sets_without_domain_five_star,
    substat_weights,
)
from app.data.snapshot import (
    artifact_main_stat_value,
    artifact_max_level,
    artifact_rolls_remaining,
    artifact_upgrade_levels,
)
from app.models.enums import ArtifactSlot
from app.services.planner.economy import economy
from app.services.stat_calculator import _quantity_for_prop

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


@cache
def substat_weights_by_quantity() -> dict[str, int]:
    """The draw weights, rekeyed into the vocabulary the rest of the app reads.

    Lives in the service layer rather than beside the data: `app/data/` importing
    `app/services/` is the wrong way round, and the translation needs
    `stat_calculator._quantity_for_prop` — which stays the **single** definition of what a
    property means. `GO_KEY_TO_PROPERTY` maps only GO's spelling onto a raw property; a second
    key-to-quantity table would be a second chance to place `critRate_` on the wrong stat,
    silently optimising for something nobody has.

    The API emits this rather than GO's raw keys. A client handed `critRate_` beside roll
    ladders keyed `crit_rate` would have to hold both spellings and join them, and a join
    written twice is a join that disagrees with itself once.

    **Refuses on a key it cannot place.** A dropped weight is not a smaller model — it is a
    stat the draw treats as impossible, which hands its probability to the others.
    """
    out: dict[str, int] = {}
    for key, weight in substat_weights().items():
        prop = GO_KEY_TO_PROPERTY.get(key)
        quantity = _quantity_for_prop(prop) if prop else None
        if quantity is None:
            msg = (
                f"{key!r} in the draw model maps to no known property. A weight that cannot "
                f"be placed must not be dropped: the draw would then treat that stat as "
                f"impossible and hand its probability to the others."
            )
            raise ExternalDataUnavailableError(msg)
        out[quantity] = weight
    return out


#: The rarity the upgrade estimator models. A 4-star cannot beat a 5-star in any slot worth
#: asking about (`DESIGN_upgrade_estimator.md` §8), so a fresh drop is a 5-star by definition.
FRESH_DROP_RARITY = 5

#: GOOD's slot name, as the draw model spells it, onto the payload key the kernel reads.
_SLOT_KEYS = {
    "flower": ArtifactSlot.FLOWER.value,
    "plume": ArtifactSlot.PLUME.value,
    "sands": ArtifactSlot.SANDS.value,
    "goblet": ArtifactSlot.GOBLET.value,
    "circlet": ArtifactSlot.CIRCLET.value,
}


@dataclass(frozen=True)
class FreshDropModel:
    """Everything the upgrade estimator needs that is the same for every build.

    `docs/DESIGN_upgrade_estimator.md` §§3-4 and §6. Keyed by **kernel quantity** and by the
    kernel's slot keys, so the client joins it to the recipe without a second vocabulary.
    """

    five_star_per_run: float
    four_line_share: float
    set_share: float
    slot_share: float
    #: Read from the planner's derived economy, never restated here.
    resin_per_run: int
    #: `equip_*` -> quantity -> probability, summing to 1 per slot.
    main_stat_probabilities: dict[str, dict[str, float]]
    #: quantity -> the main stat's value on a 5-star at +20.
    main_stat_values: dict[str, float]
    #: Nanoka set ids no domain drops at 5 stars, sorted. A slot needing one is "never".
    sets_without_domain_drop: list[int]


@cache
def fresh_drop_model() -> FreshDropModel:
    """The domain drop model in the app's vocabulary.

    **Refuses on any main stat it cannot place**, for the reason `substat_weights_by_quantity`
    does: a dropped main stat is not a smaller model, it hands its probability to the others,
    and a goblet that quietly lost Pyro DMG would make a Pyro DPS's goblet unreachable.
    """
    drops = domain_drop_model()
    max_level = artifact_max_level(FRESH_DROP_RARITY)
    probabilities: dict[str, dict[str, float]] = {}
    values: dict[str, float] = {}
    for slot, slot_key in _SLOT_KEYS.items():
        by_quantity: dict[str, float] = {}
        for key, p in main_stat_probabilities(slot).items():
            prop = MAIN_STAT_GO_KEY_TO_PROPERTY.get(key)
            quantity = _quantity_for_prop(prop) if prop else None
            if prop is None or quantity is None:
                msg = f"main stat {key!r} on {slot} maps to no known property"
                raise ExternalDataUnavailableError(msg)
            by_quantity[quantity] = by_quantity.get(quantity, 0.0) + float(p)
            values[quantity] = artifact_main_stat_value(FRESH_DROP_RARITY, max_level, prop)
        probabilities[slot_key] = by_quantity
    return FreshDropModel(
        five_star_per_run=drops["five_star_per_run"],
        four_line_share=drops["four_line_share"],
        set_share=drops["set_share"],
        slot_share=drops["slot_share"],
        resin_per_run=economy().domain_resin_per_run(),
        main_stat_probabilities=probabilities,
        main_stat_values=values,
        sets_without_domain_drop=sorted(sets_without_domain_five_star()),
    )
