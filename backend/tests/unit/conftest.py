"""Unit-lane fixtures — including the one that makes E.6 an assertion rather than a claim.

Chunk E's rule is **committed snapshots only**: no gate, test or importer may reach the
network at run time. The unit lane needs no sockets at all — it uses ASGI transports and
fixture-backed adapters throughout — so it runs with outbound connections blocked. A test
that quietly grew a live fetch fails here loudly, rather than passing on a laptop with a
network and going red in a sandbox without one.

The integration lane is deliberately *not* covered by this: it connects to Postgres, and a
guard that had to special-case the database host would be a guard with a hole in it.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest


class NetworkAccessDeniedError(RuntimeError):
    """A unit test tried to open a socket."""


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block every socket connection for the duration of a unit test."""

    def _denied(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> None:
        msg = (
            f"unit tests must not reach the network (tried to connect to {address!r}). "
            f"Committed fixtures and snapshots are the contract — see "
            f"docs/TASKS_mistilteinn.md E.6. If this is a live-data test, it belongs in "
            f"the integration lane and must be able to explain why."
        )
        raise NetworkAccessDeniedError(msg)

    monkeypatch.setattr(socket.socket, "connect", _denied)
    monkeypatch.setattr(socket.socket, "connect_ex", _denied)
