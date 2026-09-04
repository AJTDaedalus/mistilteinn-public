"""Cloudflare Turnstile server-side validation.

Chosen over hCaptcha and reCAPTCHA because the site is already behind Cloudflare: no new
vendor, no new billing relationship, free and unmetered, and usually invisible to a real
user. See `docs/DESIGN_open_registration.md` §5.5 Layer 2 (D-OR5).

Three properties that are easy to get wrong and are the reason this is a module rather
than four inline lines:

1. **`success` alone is not enough.** A token minted by the same widget on any other page
   also reports success. `hostname` and `action` are what tie it to *this* form on *this*
   site, and skipping them is the standard bypass.
2. **Fail closed.** If Cloudflare is unreachable, registration is refused. Registration is
   not time-critical, and a vendor outage is precisely the moment an attacker would pick
   to find the door open. (Login would trade the other way — locking every user out
   because a CAPTCHA vendor is down is worse than a few extra password guesses, which the
   rate limiter still bounds. Hence this is applied to register/resend only.)
3. **An empty secret skips verification.** A fresh clone and every test run with no key
   and no network.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid

import httpx

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_TIMEOUT_SECONDS = 10.0


def _is_ip(value: str) -> bool:
    """True if *value* parses as an IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


class TurnstileVerifier:
    """Validates a Turnstile response token against Cloudflare's siteverify API."""

    def __init__(
        self,
        secret_key: str,
        expected_hostname: str = "",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret = secret_key
        self._expected_hostname = expected_hostname
        self._transport = transport

    @property
    def enabled(self) -> bool:
        """False when no secret is configured, in which case `verify` always passes."""
        return bool(self._secret)

    async def verify(self, token: str, *, action: str, remote_ip: str | None = None) -> bool:
        """Return True only if *token* is a live solve of *action* on the expected host."""
        if not self.enabled:
            return True
        if not token:
            # No round-trip for a request that never rendered the widget.
            return False

        body = await self._siteverify(token, remote_ip)
        if body is None:
            return False
        return self._verdict_matches(body, action)

    async def _siteverify(self, token: str, remote_ip: str | None) -> dict | None:
        """POST to Cloudflare; None on any failure to obtain a usable verdict."""
        payload: dict[str, str] = {
            "secret": self._secret,
            "response": token,
            # Cloudflare requires a UUID here and rejects anything else as malformed.
            "idempotency_key": str(uuid.uuid4()),
        }
        # Only send a real address. `get_client_ip` returns the sentinel "unknown" when
        # no header and no peer is available, and `remoteip` is optional — omitting it is
        # explicitly fine, whereas a malformed value risks a rejection from Cloudflare.
        # Because register fails CLOSED, such a rejection would 403 a legitimate signup.
        if remote_ip and _is_ip(remote_ip):
            payload["remoteip"] = remote_ip

        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(SITEVERIFY_URL, json=payload)
            if not response.is_success:
                logger.warning("Turnstile siteverify returned HTTP %s", response.status_code)
                return None
            return response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Turnstile siteverify unreachable — failing closed")
            return None

    def _verdict_matches(self, body: dict, action: str) -> bool:
        """All three checks. `success` alone accepts a token minted on any other page."""
        if not body.get("success"):
            logger.info("Turnstile rejected a token: %s", body.get("error-codes"))
            return False
        if self._expected_hostname and body.get("hostname") != self._expected_hostname:
            logger.warning("Turnstile hostname mismatch: %r", body.get("hostname"))
            return False
        if body.get("action") != action:
            logger.warning("Turnstile action mismatch: %r (wanted %r)", body.get("action"), action)
            return False
        return True
