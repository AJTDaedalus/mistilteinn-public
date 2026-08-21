"""Task 3 — Resource + cooldown substrate tests.

Tests drive _aftershock_ready and _aftershock_consume with a synthetic spec dict
(not a real AftershockSpec yet; Task 4 adds that model). The spec shape used here
is the minimal dict the helpers need:

  {"resource": str|None, "cost": float, "cooldown_s": float,
   "max_per_window": int|None, "window_s": float|None}

All tests use no real agent — synthetic agent_id "X".
"""

import pytest

from app.services.anomaly_simulator import _aftershock_consume, _aftershock_ready

# ---------------------------------------------------------------------------
# Shared synthetic spec: cost=3, cooldown=3s, max 2 procs per 20s window
# ---------------------------------------------------------------------------

SPEC = {
    "resource": "purge",
    "cost": 3.0,
    "cooldown_s": 3.0,
    "max_per_window": 2,
    "window_s": 20.0,
}

AGENT = "X"


def _fresh_state(initial: float = 10.0):
    """Return (resources, cd_until, window) starting at t=0, resource=initial."""
    resources: dict[str, dict[str, float]] = {AGENT: {"purge": initial}}
    cd_until: dict[str, float] = {AGENT: float("-inf")}
    window: dict[str, list[float]] = {AGENT: []}
    return resources, cd_until, window


# ---------------------------------------------------------------------------
# test_cooldown_gate — ready→consume flips ready False until t+cooldown_s
# ---------------------------------------------------------------------------


def test_cooldown_gate():
    resources, cd_until, window = _fresh_state()
    energy: dict[str, float] = {}

    def ready(t: float) -> bool:
        return _aftershock_ready(
            SPEC, AGENT, t=t, resources=resources, cd_until=cd_until, window=window
        )

    def consume(t: float) -> None:
        _aftershock_consume(
            SPEC, AGENT, t=t, resources=resources, cd_until=cd_until, window=window, energy=energy
        )

    assert ready(0.0)
    consume(0.0)

    # Just before cooldown expires: still blocked
    assert not ready(2.99)

    # At exactly cooldown_s: ready again (>= is inclusive)
    assert ready(3.0)


# ---------------------------------------------------------------------------
# test_window_cap — 3rd proc inside 20s blocked even if cooldown elapsed + resource full
# ---------------------------------------------------------------------------


def test_window_cap():
    resources, cd_until, window = _fresh_state(initial=100.0)
    energy: dict[str, float] = {}

    def ready(t: float) -> bool:
        return _aftershock_ready(
            SPEC, AGENT, t=t, resources=resources, cd_until=cd_until, window=window
        )

    def consume(t: float) -> None:
        _aftershock_consume(
            SPEC, AGENT, t=t, resources=resources, cd_until=cd_until, window=window, energy=energy
        )

    # Proc 1 at t=0
    assert ready(0.0)
    consume(0.0)

    # Proc 2 at t=3 (cooldown elapsed)
    assert ready(3.0)
    consume(3.0)

    # Proc 3 at t=6: cooldown elapsed, resource still ample — but window (2/20s) is full
    assert not ready(6.0)

    # At t=20: the t=0 proc falls out of the window → only 1 of the last 20s → ready
    assert ready(20.0)


# ---------------------------------------------------------------------------
# test_resource_floor — blocked when resource < cost
# ---------------------------------------------------------------------------


def test_resource_floor():
    resources, cd_until, window = _fresh_state(initial=2.9)  # below cost=3

    def ready() -> bool:
        return _aftershock_ready(
            SPEC, AGENT, t=0.0, resources=resources, cd_until=cd_until, window=window
        )

    assert not ready()

    # Refill to exactly cost — should now be ready
    resources[AGENT]["purge"] = 3.0
    assert ready()


# ---------------------------------------------------------------------------
# test_energy_resource_uses_energy_dict — spec with resource="energy" reads/writes
# the energy dict, not resources
# ---------------------------------------------------------------------------


def test_energy_resource_uses_energy_dict():
    energy_spec = {
        "resource": "energy",
        "cost": 30.0,
        "cooldown_s": 5.0,
        "max_per_window": None,
        "window_s": None,
    }
    resources: dict[str, dict[str, float]] = {AGENT: {}}  # no "energy" key here
    cd_until: dict[str, float] = {AGENT: float("-inf")}
    window: dict[str, list[float]] = {AGENT: []}
    energy: dict[str, float] = {AGENT: 60.0}

    def ready(t: float) -> bool:
        return _aftershock_ready(
            energy_spec,
            AGENT,
            t=t,
            resources=resources,
            cd_until=cd_until,
            window=window,
            energy=energy,
        )

    def consume(t: float) -> None:
        _aftershock_consume(
            energy_spec,
            AGENT,
            t=t,
            resources=resources,
            cd_until=cd_until,
            window=window,
            energy=energy,
        )

    # Enough energy — should be ready
    assert ready(0.0)
    consume(0.0)

    # Energy debited from energy dict, not resources
    assert energy[AGENT] == pytest.approx(30.0)

    # resources dict untouched (no "energy" key added)
    assert "energy" not in resources[AGENT]

    # Cooldown blocking
    assert not ready(4.99)
    assert ready(5.0)
