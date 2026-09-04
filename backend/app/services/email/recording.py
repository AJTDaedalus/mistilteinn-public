"""In-memory `EmailSender` for tests. Sends nothing, records everything."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.email.base import EmailMessage, EmailSendError


class RecordingEmailSender:
    """Capture messages so tests can assert on what would have been sent.

    `fail_with` arms the sender to raise instead of recording, so the provider-outage
    path is testable — registration must still return 202 when a send fails
    (`docs/DESIGN_open_registration.md` §5.4).
    """

    def __init__(self, fail_with: EmailSendError | None = None) -> None:
        self.sent: list[EmailMessage] = []
        self._fail_with = fail_with

    async def send(self, message: EmailMessage) -> None:
        """Record *message*, or raise if this sender was armed to fail."""
        if self._fail_with is not None:
            raise self._fail_with
        self.sent.append(message)

    def last(self) -> EmailMessage | None:
        """The most recently recorded message, or None if nothing has been sent."""
        return self.sent[-1] if self.sent else None
