"""Every resource pool in a simulation -- Energy and the named banks -- behind one API.

``anomaly_simulator`` already maintained named banks (Windbloom, Heat, Rp, ...), but the
arithmetic lived inside the aftershock gate/consume pair and was reachable from nowhere
else. The channel bill (docs/TASKS_channeled_moves.md Task 11) needs the same arithmetic
against the same dicts, and a second copy of "which dict holds this resource, and how do I
clamp it" is exactly how two callers come to disagree about one agent's balance.

**The helper shares the caller's dicts, it does not own them.** ``simulate()`` mutates
``energy`` in a dozen other places -- on-hit gain, the EX spend, the Ultimate path -- so a
copy would silently diverge from the balance the rest of the loop sees. Every method here
reads and writes through the references it was handed.
"""

from __future__ import annotations

# Energy is not a bank like the others: it has its own per-agent dict in `simulate()`
# because it predates the generic pools and half the loop touches it directly. Matching is
# case-insensitive because the two sources disagree on spelling -- aftershock specs author
# "energy", `agent_resource_costs.resource` carries upstream's "Energy". A capitalised row
# falling through to the named-bank path would invent a second, empty Energy pool, and
# every EX would read as unaffordable while the real bank sat full.
_ENERGY = "energy"


class ResourceBanks:
    """Balance / debit / credit over one simulation's resource pools."""

    def __init__(
        self,
        energy: dict[str, float],
        named: dict[str, dict[str, float]],
    ) -> None:
        self._energy = energy
        self._named = named

    @staticmethod
    def _is_energy(resource: str) -> bool:
        return resource.lower() == _ENERGY

    def balance(self, agent_id: str, resource: str) -> float:
        """Current balance. An agent or bank that does not exist yet reads ``0.0``.

        Zero rather than an exception on purpose: a step for an agent with no bank is a data
        gap, and taking the whole request down over it would be an outage rather than a
        corrected number -- the same call the missing-``variant_label`` fallback makes.
        """
        if self._is_energy(resource):
            return self._energy.get(agent_id, 0.0)
        return self._named.get(agent_id, {}).get(resource, 0.0)

    def can_afford(
        self,
        agent_id: str,
        resource: str | None,
        cost: float,
        floor: float | None = None,
    ) -> bool:
        """Is *cost* payable from *resource* right now?

        ``floor`` is an availability threshold distinct from the price -- Orphie requires at
        least 60 Energy to fire but only spends 30. Defaults to the cost itself.

        No resource named, or a zero cost, is always affordable: that is the aftershock
        path's existing behaviour for an ungated spec, preserved verbatim.
        """
        if not resource or cost <= 0:
            return True
        return self.balance(agent_id, resource) >= (floor if floor is not None else cost)

    def debit(self, agent_id: str, resource: str, amount: float) -> float:
        """Spend up to *amount*; returns what was **actually** spent.

        Clamped at zero, verbatim from ``_aftershock_consume``: a bank never goes negative.
        The return value is the truth rather than the request, so a caller can warn about a
        short bank instead of reporting a spend that did not happen.
        """
        if amount <= 0:
            return 0.0
        current = self.balance(agent_id, resource)
        spent = min(current, amount)
        new_balance = current - spent
        if self._is_energy(resource):
            self._energy[agent_id] = new_balance
        else:
            self._named.setdefault(agent_id, {})[resource] = new_balance
        return spent

    def credit(
        self, agent_id: str, resource: str, amount: float, cap: float | None = None
    ) -> None:
        """Add *amount*, optionally capped. No cap means unbounded, matching `initial`/`max`."""
        new_balance = self.balance(agent_id, resource) + amount
        if cap is not None:
            new_balance = min(new_balance, cap)
        if self._is_energy(resource):
            self._energy[agent_id] = new_balance
        else:
            self._named.setdefault(agent_id, {})[resource] = new_balance
