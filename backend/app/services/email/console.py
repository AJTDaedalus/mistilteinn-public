"""Prints mail to stdout instead of sending it. The default provider for local dev."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.email.base import EmailMessage

_RULE = "─" * 72


class ConsoleEmailSender:
    """Write the message to stdout so a developer can click the link.

    Prints the text part only: this exists so someone can copy a verification URL out
    of `docker compose logs`, not so they can read markup.
    """

    async def send(self, message: EmailMessage) -> None:
        """Print *message* to stdout. Never raises.

        **`flush=True` is load-bearing, not tidiness.** Python buffers stdout when it is not a
        TTY, and in a container it never is — so without the flush this printed into a buffer
        that `docker compose logs` never showed. The whole point of this sender is that a
        developer can copy a verification URL out of the log, and it is the *default* provider,
        so the silent failure lands on every fresh clone and all of local development.

        Found by registering a real account and looking for the link: the row and the token
        were both in the database and the log had nothing in it. The tests could not catch it —
        they assert against `RecordingEmailSender`, and `capsys` reads the same buffer this was
        stuck in.
        """
        print(
            f"\n{_RULE}\n[email] to: {message.to}\n[email] subject: {message.subject}",
            flush=True,
        )
        print(f"{_RULE}\n{message.text}\n{_RULE}\n", flush=True)
