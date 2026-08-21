"""The single expansion of a held move into the hits it actually deals.

Three places turn a rotation step into hits — ``combo_step_resolver`` (saved combos),
``api/v1/simulate`` and ``optimizer_pipeline`` — and before this they each did their own
thing with a channel. Two encodings of one rotation producing different anomaly counts is
exactly the #83 defect, so the arithmetic lives here once and all three read it.

The plan is a flat, temporally-ordered list of :class:`ChannelHit`. Each carries three
things the callers need and cannot re-derive without repeating this logic:

``mv_scale``
    What one hit's authored multiplier is worth. ``1.0`` for entry and release; the tick
    fraction for ticks, which is where the two ``tick_mv_basis`` readings diverge
    (docs/DESIGN_channeled_moves.md §4.3).
``duration_s``
    The slice of sim clock this hit's step occupies. The combo path charges
    ``_StepMoveSpec.duration_s`` *per emitted step*, so a plan whose durations do not sum to
    ``channel_s + tail_s`` puts the whole rotation on a different clock than the direct path
    computes for the same move (Task 10a).
``role``
    Kept on the hit rather than discarded, so a caller can bill, warn or attribute per role
    without re-reading ``spec.roles``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.data.loaders.moves import ChannelSpec

_UNMAPPED_ROLE = "entry"


@dataclass(frozen=True)
class ChannelHit:
    """One hit a channel deals: which row, scaled how much, occupying how much clock."""

    row: Any
    role: str
    mv_scale: float
    duration_s: float


@dataclass(frozen=True)
class ChannelPlan:
    """Every hit one held press deals, in temporal order, plus any authoring gaps found."""

    hits: list[ChannelHit]
    warnings: list[str] = field(default_factory=list)


def channel_tick_plan(spec: ChannelSpec, channel_s: float) -> tuple[int, float]:
    """``(n_ticks, mv_scale)`` for a hold of *channel_s* seconds.

    ``mv_scale`` is what one tick row's authored multiplier is worth for a single tick, and
    it is where the two ``tick_mv_basis`` readings diverge (DESIGN §4.3):

    - ``per_second``    -- the row IS a rate, so one tick is worth ``tick_s`` of it.
    - ``whole_channel`` -- the row is the total over ``nominal_s``, so one tick is worth the
      fraction ``tick_s / nominal_s`` of it.
    - ``per_tick``      -- the row is one occurrence, so a tick is worth ALL of it (D-CH1a).

    The consequence is the whole point of the distinction: on ``per_second`` a longer hold
    scales the spray damage linearly without bound; on ``whole_channel`` holding for exactly
    ``nominal_s`` recovers the authored figure and nothing more.
    """
    n_ticks = round(channel_s / spec.tick_s)
    if spec.tick_mv_basis == "per_tick":
        # The row is already "what one of these does". `tick_s` sets the cadence, i.e. how many
        # occur, and must not also scale what each is worth -- that would be counting it twice.
        mv_scale = 1.0
    elif spec.tick_mv_basis == "whole_channel":
        # nominal_s is guaranteed non-None for this basis by ChannelSpec's validator.
        mv_scale = spec.tick_s / float(spec.nominal_s or 1.0)
    else:
        mv_scale = spec.tick_s
    return n_ticks, mv_scale


def build_channel_plan(
    rows: list[Any],
    spec: ChannelSpec,
    channel_s: float,
    *,
    tail_s: float = 0.0,
    move_name: str = "<move>",
) -> ChannelPlan:
    """Expand *rows* into the hits a *channel_s*-second hold deals.

    *tail_s* is the move's authored ``duration_s``, which on a channel means the **non-held
    tail** (entry + release animation) rather than the whole move's length — the held part
    is the player's to choose and cannot be a constant.
    """
    warnings: list[str] = []
    ordered = sorted(rows, key=lambda a: getattr(a, "hit_index", 0))

    entry_rows: list[Any] = []
    tick_rows: list[Any] = []
    release_rows: list[Any] = []
    unmapped: list[str] = []
    for row in ordered:
        param = getattr(row, "param_name", None)
        role = spec.roles.get(param) if param else None
        if role == "tick":
            tick_rows.append(row)
        elif role == "release":
            release_rows.append(row)
        elif role == "entry":
            entry_rows.append(row)
        else:
            # No role authored for this row. Fire it once — its pre-channel behaviour —
            # rather than dropping it or inventing a cadence for it. LCH is the level that
            # makes this state fail the *build*; here it must not fail the *request*.
            unmapped.append(str(param))
            entry_rows.append(row)

    if unmapped:
        warnings.append(
            f"Move {move_name!r} has rows with no authored channel role: "
            f"{sorted(set(unmapped))}. Each fired once, unscaled by the hold length."
        )

    n_ticks, mv_scale = channel_tick_plan(spec, channel_s)

    hits: list[ChannelHit] = [
        ChannelHit(row=row, role="entry", mv_scale=1.0, duration_s=0.0) for row in entry_rows
    ]
    for _ in range(n_ticks):
        hits.extend(
            ChannelHit(row=row, role="tick", mv_scale=mv_scale, duration_s=spec.tick_s)
            for row in tick_rows
        )
    hits.extend(
        ChannelHit(row=row, role="release", mv_scale=1.0, duration_s=0.0)
        for row in release_rows
    )

    # The tail is *animation*, not a property of the release row, so it must be spent even
    # by a channel that has no release row -- dropping it there would silently shorten the
    # step and put this path on a different clock than `_step_duration_s` computes for the
    # same move. It rides on the release hits when there are any, the entry hits otherwise,
    # and failing both simply lands on the last hit. A plan with no hits at all spends
    # nothing, which is right: the combo path emits no step to charge it to.
    if tail_s and hits:
        carriers = [i for i, h in enumerate(hits) if h.role == "release"]
        carriers = carriers or [i for i, h in enumerate(hits) if h.role == "entry"]
        carriers = carriers or [len(hits) - 1]
        share = tail_s / len(carriers)
        for i in carriers:
            hits[i] = ChannelHit(
                row=hits[i].row,
                role=hits[i].role,
                mv_scale=hits[i].mv_scale,
                duration_s=hits[i].duration_s + share,
            )

    return ChannelPlan(hits=hits, warnings=warnings)


def plan_hit_offsets(plan: ChannelPlan) -> list[float]:
    """Seconds from the step's start at which each hit lands.

    The running sum of ``duration_s``: an ``entry`` at 0.0 lands immediately, each tick lands
    one ``tick_s`` after the last, and the release lands after the non-held tail. That places
    ticks at the **real cadence** rather than spreading every hit evenly across the step, and
    the difference is not cosmetic -- anomaly decay, the 3s per-attribute re-trigger CD, and
    Shock's 1s / Corruption's 0.5s internal proc CDs are all read off these timestamps
    (docs/DESIGN_channeled_moves.md 4.4).

    The combo path does not need this: it emits one step per hit, each already carrying its own
    ``duration_s``, so the simulator's own clock spaces them. This is for the direct paths,
    where every hit shares one step.
    """
    offsets: list[float] = []
    t = 0.0
    for hit in plan.hits:
        t += hit.duration_s
        offsets.append(t)
    return offsets
