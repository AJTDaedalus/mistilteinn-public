"""The `EmailSender` seam: one protocol, several implementations, no network in tests.

This repo had no mail infrastructure before open registration — no SMTP, no provider SDK,
nothing in `pyproject.toml`. Rather than let a provider SDK spread through the registration
path, everything that sends mail depends on this protocol; `get_email_sender()` picks the
implementation from `EMAIL_PROVIDER`, which defaults to `console`. A fresh clone therefore
runs the whole signup flow with no API key and no network, and every test asserts against
`RecordingEmailSender`.

**Ported from fairy**, which shipped this design in 2026-08. The seam is the reason no test
here makes a network call: the unit lane blocks `socket.connect` outright (E.6), so a live
provider call would fail loudly rather than flakily.

This mirrors how the rest of the repo treats external dependencies — committed
snapshots and offline determinism over live fetches (root `CLAUDE.md`, the L6/LU gates).
See `docs/DESIGN_open_registration.md` §5.4 (D-OR4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class EmailSendError(RuntimeError):
    """A message could not be handed to the provider.

    Callers in the registration path must treat this as non-fatal: the user row is
    already written, and failing the request would turn a provider blip into a failed
    signup. Log it and let the user use the resend path (DESIGN §5.4).
    """


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """One outbound message.

    Both parts are required rather than optional. A text/plain alternative is not a
    nicety: HTML-only mail scores worse with spam filters, and deliverability is the
    difference between a working signup flow and one that looks broken to the user.
    """

    to: str
    subject: str
    text: str
    html: str


@runtime_checkable
class EmailSender(Protocol):
    """Anything that can deliver an `EmailMessage`."""

    async def send(self, message: EmailMessage) -> None:
        """Deliver *message*, or raise `EmailSendError`."""
        ...
