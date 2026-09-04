"""Pick the `EmailSender` implementation from configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import settings
from app.services.email.console import ConsoleEmailSender
from app.services.email.resend import ResendEmailSender

if TYPE_CHECKING:
    from app.services.email.base import EmailSender

CONSOLE = "console"
RESEND = "resend"


@lru_cache(maxsize=1)
def get_email_sender() -> EmailSender:
    """Return the process-wide sender for `settings.EMAIL_PROVIDER`.

    An unrecognised provider raises rather than falling back to console. A silent
    fallback would mean a typo in the production env turns every verification email
    into a line in the container log — signups would appear to work while no user ever
    receives anything, and nothing would be red.
    """
    provider = settings.EMAIL_PROVIDER.strip().lower()
    if provider == CONSOLE:
        return ConsoleEmailSender()
    if provider == RESEND:
        return ResendEmailSender(
            api_key=settings.RESEND_API_KEY,
            from_address=settings.EMAIL_FROM,
        )
    raise ValueError(
        f"EMAIL_PROVIDER={settings.EMAIL_PROVIDER!r} is not recognised "
        f"(expected {CONSOLE!r} or {RESEND!r})"
    )
