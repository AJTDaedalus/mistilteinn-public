"""What one move costs, and how much of a channel the bank can fund.

``simulate()`` used to bill every EX Special the same way: one scalar,
``Agent.ex_energy_cost``. That is one price for one mode, and several agents have more
than one -- Burnice's Tossing Method costs 10 and was billed 40 -- while a per-second
drain cannot be expressed by a scalar at all.

The dispatch (docs/DESIGN_channeled_moves.md 4.5):

===================  ==========================================================
move has a channel   ``entry + drain_per_s * channel_s + release``
move binds a key     that mode's own cost
neither              ``Agent.ex_energy_cost``  -- unchanged, ~50 agents
===================  ==========================================================

Deciding and spending are deliberately separate. :func:`bill_for_move` returns a value
object and mutates nothing, so the arithmetic is testable without a simulation around it;
the caller debits through :class:`~app.services.resource_banks.ResourceBanks`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.data.loaders.moves import ChannelSpec
    from app.services.resource_banks import ResourceBanks

# Frozen from energy_costs.py: what an EX costs when the DB says nothing. Kept as the
# last resort rather than removed -- `ex_energy_cost` is NULL on any DB migrated but not
# re-seeded from nanoka, which is the normal state of a dev box that pulled a migration.
EX_COST_DEFAULT = 60.0

# (value, per_sec, resource), keyed by `agent_resource_costs.cost_key`.
CostTable = dict[str, tuple[float, bool, str]]


@dataclass(frozen=True)
class ResourceBill:
    """What a step owes, and out of which bank."""

    amount: float
    resource: str = "Energy"
    warnings: list[str] = field(default_factory=list)


def _lookup(
    costs: CostTable, key: str | None, move_name: str, warnings: list[str]
) -> tuple[float, bool, str] | None:
    """One cost key -> its row, or ``None`` with a warning.

    An unresolved key is a data gap -- the agent was not re-seeded, or the curator bound a
    key that upstream renamed. Returning 0.0 silently would make the move *free*, which is
    a plausible wrong number rather than a visible failure; the same reason `L4` exists.
    """
    if key is None:
        return None
    row = costs.get(key)
    if row is None:
        warnings.append(
            f"Move {move_name!r} binds cost key {key!r} but no agent_resource_costs row "
            f"resolves it; that portion of the bill was skipped (the move is billed as if "
            f"it were free). Re-seed, or fix the binding."
        )
        return None
    return row


def bill_for_move(
    move_spec: object | None,
    costs: CostTable,
    *,
    channel_s: float | None,
    ex_energy_cost: float | None,
    move_name: str = "<move>",
) -> ResourceBill:
    """Price one step. Pure: decides, never debits."""
    warnings: list[str] = []
    channel: ChannelSpec | None = getattr(move_spec, "channel", None)

    if channel is not None:
        held_s = channel_s if channel_s is not None else channel.default_s
        total = 0.0
        resource = "Energy"
        for key, per_sec_expected in (
            (channel.entry_cost_key, False),
            (channel.drain_cost_key, True),
            (channel.release_cost_key, False),
        ):
            row = _lookup(costs, key, move_name, warnings)
            if row is None:
                continue
            value, per_sec, res = row
            resource = res
            # Trust the DB's `per_sec`, not the slot the curator put the key in. If the two
            # disagree the binding is wrong, and billing a per-second rate once (or a flat
            # cost every second) is a large silent error in either direction.
            if per_sec != per_sec_expected:
                warnings.append(
                    f"Move {move_name!r} binds {key!r} as "
                    f"{'a drain' if per_sec_expected else 'a flat cost'} but the DB row says "
                    f"per_sec={per_sec}; billed per the DB."
                )
            total += value * held_s if per_sec else value
        return ResourceBill(amount=total, resource=resource, warnings=warnings)

    cost_key = getattr(move_spec, "cost_key", None)
    if cost_key:
        row = _lookup(costs, cost_key, move_name, warnings)
        if row is not None:
            value, per_sec, res = row
            if per_sec:
                warnings.append(
                    f"Move {move_name!r} binds per-second key {cost_key!r} but declares no "
                    f"channel, so there is no duration to bill it over; charged once."
                )
            return ResourceBill(amount=value, resource=res, warnings=warnings)
        return ResourceBill(amount=0.0, resource="Energy", warnings=warnings)

    if ex_energy_cost is None:
        warnings.append(
            f"ex_energy_cost is NULL in DB for {move_name!r}; falling back to default "
            f"{EX_COST_DEFAULT}"
        )
        return ResourceBill(amount=EX_COST_DEFAULT, warnings=warnings)
    return ResourceBill(amount=float(ex_energy_cost), warnings=warnings)


def clamp_channel_to_bank(
    channel: ChannelSpec,
    costs: CostTable,
    banks: ResourceBanks,
    agent_id: str,
    *,
    requested_s: float,
    move_name: str = "<move>",
) -> tuple[float, str | None]:
    """How long the bank can actually fund. Returns ``(effective_s, warning)``.

    ``affordable_s = (balance - entry - release) / drain_per_s`` (DESIGN 4.6). This is the
    mechanic that makes ER% and on-hit energy gain buy *damage* rather than merely gating
    whether an EX fires -- a known modelling gap (`project_energy_regen`).

    A channel with **no drain** is never clamped. Promeia and Pryce channel for free, and
    dividing by a zero drain is the obvious bug to write here.
    """
    warnings: list[str] = []
    drain_row = _lookup(costs, channel.drain_cost_key, move_name, warnings)
    capped_s = min(requested_s, channel.max_s)
    if drain_row is None or drain_row[0] <= 0:
        return capped_s, None

    drain_per_s, _, resource = drain_row
    fixed = 0.0
    for key in (channel.entry_cost_key, channel.release_cost_key):
        row = _lookup(costs, key, move_name, warnings)
        if row is not None:
            fixed += row[0]

    balance = banks.balance(agent_id, resource)
    affordable_s = (balance - fixed) / drain_per_s
    effective_s = max(0.0, min(capped_s, affordable_s))
    if effective_s < capped_s:
        return effective_s, (
            f"{move_name!r} was held for {capped_s}s but the {resource} bank only funds "
            f"{effective_s:.2f}s ({balance:.1f} available, {fixed:.1f} fixed + "
            f"{drain_per_s}/s); the hold was cut."
        )
    return effective_s, None
