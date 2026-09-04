"""AuthToken repository — mint, consume, and purge single-use expiring tokens."""

from __future__ import annotations

import enum
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select

from app.models.auth_token import AuthToken
from app.repositories.base import BaseRepository

# 256 bits. Brute force is not the threat model at that width — the rate limit on the
# verify endpoint exists to suppress log noise and accidental hammering, not entropy.
_TOKEN_BYTES = 32


class ConsumeOutcome(enum.StrEnum):
    """Why a consume attempt did or did not succeed.

    Distinguishable on purpose. The token is a secret, not an identifier, so there is
    nothing to enumerate by telling the truth — and a user holding a day-old link needs
    to be offered a resend rather than a flat "invalid", which reads as "the site is
    broken".
    """

    OK = "ok"
    INVALID = "invalid"
    EXPIRED = "expired"
    ALREADY_USED = "already_used"


@dataclass(frozen=True, slots=True)
class ConsumeResult:
    """Outcome of `consume`, plus the row when it succeeded."""

    outcome: ConsumeOutcome
    token: AuthToken | None = None

    @property
    def ok(self) -> bool:
        """True when the token was live and has now been marked consumed."""
        return self.outcome is ConsumeOutcome.OK


def hash_token(raw: str) -> str:
    """Return the sha256 hex digest stored for *raw*. The raw value is never persisted."""
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthTokenRepository(BaseRepository[AuthToken]):
    """Sole data-access point for `auth_tokens`."""

    model = AuthToken

    async def mint(self, user_id: str, purpose: str, ttl_seconds: int) -> str:
        """Issue a token for (*user_id*, *purpose*) and return the raw value.

        Any live token for the same pair is consumed first. A resend must not leave two
        working links behind: the user will click the newest, and the older one is then
        a live credential sitting in an inbox for no reason.
        """
        await self._invalidate_live(user_id, purpose)

        raw = secrets.token_urlsafe(_TOKEN_BYTES)
        now = datetime.now(UTC)
        await self.create(
            {
                "user_id": user_id,
                "purpose": purpose,
                "token_hash": hash_token(raw),
                "expires_at": now + timedelta(seconds=ttl_seconds),
            }
        )
        return raw

    async def consume(self, raw: str, purpose: str) -> ConsumeResult:
        """Mark the token matching *raw* consumed, or explain why it could not be."""
        stmt = select(AuthToken).where(AuthToken.token_hash == hash_token(raw))
        token = (await self.session.execute(stmt)).scalar_one_or_none()

        # A token minted for a different purpose is not "a password-reset token being
        # misused" to the caller — it is simply not a valid verification token, and
        # saying more would confirm the raw value exists.
        if token is None or token.purpose != purpose:
            return ConsumeResult(ConsumeOutcome.INVALID)
        if token.consumed_at is not None:
            return ConsumeResult(ConsumeOutcome.ALREADY_USED, token)
        if token.expires_at <= datetime.now(UTC):
            return ConsumeResult(ConsumeOutcome.EXPIRED, token)

        token.consumed_at = datetime.now(UTC)
        await self.session.flush()
        return ConsumeResult(ConsumeOutcome.OK, token)

    async def _invalidate_live(self, user_id: str, purpose: str) -> None:
        stmt = select(AuthToken).where(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose,
            AuthToken.consumed_at.is_(None),
        )
        now = datetime.now(UTC)
        for token in (await self.session.execute(stmt)).scalars():
            token.consumed_at = now
        await self.session.flush()

    async def delete_expired(self, now: datetime | None = None) -> int:
        """Purge expired and already-consumed rows; returns the number removed."""
        if now is None:
            now = datetime.now(UTC)
        stmt = delete(AuthToken).where(
            or_(AuthToken.expires_at <= now, AuthToken.consumed_at.is_not(None))
        )
        result = await self.session.execute(stmt)
        return result.rowcount
