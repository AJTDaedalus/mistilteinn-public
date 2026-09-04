"""Production `EmailSender` — Resend's REST API over the `httpx` we already depend on.

Chosen over raw SMTP because deliverability *is* the problem: mail sent directly from an
Oracle Free-tier IP lands in spam, and a verification mail in spam is indistinguishable
from a broken signup flow — the user never tells you, they just leave. Chosen over
SendGrid/SES for the alpha because `aetherus.dev` is already on Cloudflare, so the
SPF/DKIM records are a DNS edit in a console the owner already has open, and the free
tier (3,000/month) is an order of magnitude above any plausible signup rate.

See `docs/DESIGN_open_registration.md` §5.4 (D-OR4). SES is the right migration if
volume ever justifies it; nothing above this seam changes when it happens.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import httpx

from app.services.email.base import EmailSendError

if TYPE_CHECKING:
    from app.services.email.base import EmailMessage

_ENDPOINT = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 10.0
_ATTEMPTS = (1, 2)  # the original plus one retry; see the class docstring
_IDEMPOTENCY_KEY_BYTES = 16  # Resend caps the header at 256 chars; this is 22


class ResendEmailSender:
    """Send mail through Resend.

    One retry on 5xx and none on 4xx: a rejected key or a malformed address will be
    rejected again identically, so retrying only doubles the rate a misconfiguration
    burns the provider's limits.

    The retry carries the same `Idempotency-Key` as the original. A 5xx does not mean
    the message was not sent — it can equally mean the provider accepted it and the
    response was lost — so a bare retry risks delivering the same verification email
    twice. Resend deduplicates on that header for 24 hours.
    """

    def __init__(
        self,
        api_key: str,
        from_address: str,
        *,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Fail here rather than on the first real signup, which is when a blank key
        # would otherwise surface — as a provider 401, long after the deploy that
        # introduced it.
        if not api_key:
            raise ValueError("RESEND_API_KEY is empty; cannot construct ResendEmailSender")
        if not from_address:
            raise ValueError("EMAIL_FROM is empty; cannot construct ResendEmailSender")
        self._api_key = api_key
        self._from = from_address
        self._transport = transport

    async def send(self, message: EmailMessage) -> None:
        """Deliver *message*, retrying once on a 5xx. Raises `EmailSendError` otherwise."""
        payload = {
            "from": self._from,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            # One key per logical send, reused across the retry — that is the whole
            # point. Regenerating it per attempt would defeat the deduplication.
            "Idempotency-Key": secrets.token_urlsafe(_IDEMPOTENCY_KEY_BYTES),
        }

        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=_TIMEOUT_SECONDS,
        ) as client:
            last_detail = ""
            for attempt in _ATTEMPTS:
                try:
                    response = await client.post(_ENDPOINT, json=payload, headers=headers)
                except httpx.HTTPError as exc:
                    # Never let an httpx exception escape this seam: callers catch one
                    # type, and a leaked transport error defeats that.
                    raise EmailSendError(f"transport error talking to Resend: {exc}") from exc

                if response.is_success:
                    return

                last_detail = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code < httpx.codes.INTERNAL_SERVER_ERROR:
                    break
                if attempt == _ATTEMPTS[-1]:
                    break

        raise EmailSendError(f"Resend rejected the message — {last_detail}")
