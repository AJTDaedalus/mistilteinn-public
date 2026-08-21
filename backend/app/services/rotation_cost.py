"""What a whole rotation costs, derived rather than asked for.

``OptimizerRequest.rotation_energy_cost`` is a number the server already knows: it is the
sum of the per-step bills :mod:`app.services.resource_bill` computes. Asking the caller for
it invites the two to disagree, and on a **channel** the caller cannot compute it at all —
the bill depends on how long each press is held, which is the point of the whole feature.

The derived value feeds ``disc_optimizer``'s energy-feasibility factor, which is what lets
ER% influence rankings (`project_energy_regen`).
"""

from __future__ import annotations

from typing import Any

from app.services.resource_bill import bill_for_move

# Steps that are labels or off-field procs rather than button presses. None of them spends
# the acting agent's Energy, and `simulate()` `continue`s past all four before it bills.
_MARKERS = frozenset({"stun_trigger", "stun_end", "switch", "aftershock"})

# Only an EX press bills the scalar. A Basic Attack has no `cost_key` and no channel, and
# billing it `ex_energy_cost` would inflate the rotation by the whole basic chain -- the
# scalar is the EX's price, not "what any move costs".
_EX_PREFIXES = ("EX Special", "Ex Special")


def _is_ex(move_name: str) -> bool:
    return move_name.startswith(_EX_PREFIXES)


def derive_rotation_energy_cost(
    steps: list[Any],
    snapshots: dict[str, Any],
    moves_by_agent: dict[str, dict[str, Any]],
    owner_id: str = "dps",
) -> float | None:
    """Total Energy *owner_id*'s presses cost over this rotation, or ``None``.

    ``None`` rather than ``0.0`` when there is nothing to bill: ``0.0`` would read as a real
    answer and, because ``disc_optimizer`` gates on ``cost > 0``, would switch energy
    feasibility **off** while looking like it had been computed. ``None`` says "nothing to
    derive" in the one vocabulary the caller already understands.

    Only the scored owner is billed. The feasibility factor credits *that build's* EX
    damage against *its* bank, so a teammate's spend is not its constraint.
    """
    snap = snapshots.get(owner_id)
    if snap is None:
        return None

    costs = getattr(snap, "resource_costs", None) or {}
    moves = moves_by_agent.get(owner_id) or {}

    total = 0.0
    billed_any = False
    for step in steps:
        if getattr(step, "agent_id", owner_id) != owner_id:
            continue
        move_name = str(getattr(step, "move_name", "") or "")
        if not move_name or move_name in _MARKERS:
            continue
        move_spec = moves.get(move_name)
        has_binding = getattr(move_spec, "channel", None) is not None or bool(
            getattr(move_spec, "cost_key", None)
        )
        if not has_binding and not _is_ex(move_name):
            continue
        bill = bill_for_move(
            move_spec,
            costs,
            channel_s=getattr(step, "channel_s", None),
            ex_energy_cost=getattr(snap, "ex_energy_cost", None),
            move_name=move_name,
        )
        total += bill.amount
        billed_any = True

    return total if billed_any else None
