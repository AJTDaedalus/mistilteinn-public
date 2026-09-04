"""Signup flow: issuing verification links, consuming them, and resending them.

Kept out of the route handlers because the interesting decisions here are policy, not
transport — which of two emails to send, whether verification also approves, and what a
failed consume is allowed to disclose. See `docs/DESIGN_open_registration.md` §5.1–5.3.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import quote

from app.models.auth_token import PURPOSE_EMAIL_VERIFY
from app.models.enums import UserStatus
from app.repositories.auth_token import ConsumeOutcome
from app.services.email import EmailSendError, templates
from app.services.email_policy import normalize
from app.services.signup_log import (
    EMAIL_SEND_FAILED,
    REGISTER_EXISTING,
    REGISTER_FAILED,
    domain_of,
    signup_event,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.user import User
    from app.repositories.auth_token import AuthTokenRepository
    from app.repositories.session import SessionRepository
    from app.repositories.user import UserRepository
    from app.services.email import EmailMessage, EmailSender

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 30 * 24 * 3600


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Outcome of consuming a verification link."""

    outcome: ConsumeOutcome
    approved: bool = False
    session_token: str | None = None
    expires_at: datetime | None = None

    @property
    def ok(self) -> bool:
        """True when the link was live and the address is now verified."""
        return self.outcome is ConsumeOutcome.OK


class RegistrationService:
    """Policy for the email-verification half of signup."""

    def __init__(
        self,
        users: UserRepository,
        tokens: AuthTokenRepository,
        sessions: SessionRepository,
        email_sender: EmailSender,
        settings: Settings,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._sessions = sessions
        self._email = email_sender
        self._settings = settings

    # ── issuing ───────────────────────────────────────────────────────────────

    async def send_verification(self, user: User) -> None:
        """Mint a fresh link for *user* and email it. Never raises.

        A provider outage must not fail the caller's request: the user row is already
        written, and a 500 here turns a blip into a failed signup the user reads as
        "this site is broken". The resend path is the remedy, and it is where a user
        whose mail never arrived goes anyway.
        """
        raw = await self._tokens.mint(
            str(user.id), PURPOSE_EMAIL_VERIFY, self._settings.EMAIL_VERIFY_TTL_SECONDS
        )
        link = f"{self._settings.PUBLIC_BASE_URL.rstrip('/')}/verify?token={quote(raw)}"
        await self._send(templates.verify_email(to=user.email, link=link), user.email)

    async def send_already_registered(self, email: str) -> None:
        """Tell an existing account holder that someone tried to register their address."""
        await self._send(templates.already_registered(to=email), email)

    async def _send(self, message: EmailMessage, email: str) -> None:
        try:
            await self._email.send(message)
        except EmailSendError:
            # Domain only — a full address in the logs is a PII incident waiting for a
            # log leak, and the domain is what characterises an attack anyway.
            signup_event(EMAIL_SEND_FAILED, email=email)
            logger.exception("signup email failed to send (domain=%s)", domain_of(email))

    async def register(self, *, email: str, password_hash: str, label: str) -> None:
        """Create the account if the address is new, and send the appropriate email.

        Callers get no return value on purpose. `POST /auth/register` answers identically
        whether or not the address is known (DESIGN §5.3), so there is nothing here for a
        handler to branch on — and a service that returned "existing" would invite one.

        Three cases, one response:
          - new address        → create, send the verification link
          - known, unverified  → send a fresh link, leave the password untouched
          - known, verified    → send "someone tried to register your address"

        The third is what makes silence safe rather than merely quiet: it protects the
        account holder's privacy from the submitter while still telling the *owner* that
        someone is probing their address, and gives the "I forgot I already signed up"
        user their way back in.
        """
        try:
            await self._register(email=email, password_hash=password_hash, label=label)
        except Exception:
            # This runs in a BackgroundTasks callback, after the 202 has been sent. An
            # exception here reaches no user and fails no test — the signup simply does
            # not happen, silently. Logging it is the only thing standing between a bug
            # in this path and "some registrations just don't work".
            signup_event(REGISTER_FAILED, email=email)
            logger.exception("registration failed after the response was sent")

    async def _register(self, *, email: str, password_hash: str, label: str) -> None:
        normalized = normalize(email)
        existing = await self._users.get_by_normalized_email(normalized)

        if existing is None:
            user = await self._users.create(
                {
                    # `email_normalized` is derived by the model from `email`; setting it
                    # here as well would be a second place for the rule to drift.
                    "email": email,
                    "label": label,
                    "password_hash": password_hash,
                    "status": UserStatus.PENDING,
                }
            )
            await self.send_verification(user)
            return

        if existing.email_verified_at is None and existing.status != UserStatus.DISABLED:
            await self.send_verification(existing)
            return

        # Send to the address on the account, never the one just submitted — otherwise
        # this becomes a way to have us mail arbitrary text to an attacker's own inbox.
        signup_event(REGISTER_EXISTING, email=existing.email)
        await self.send_already_registered(existing.email)

    # ── consuming ─────────────────────────────────────────────────────────────

    async def verify(self, raw_token: str) -> VerifyResult:
        """Consume *raw_token*, marking the address verified and maybe approving.

        Returns the specific failure reason on the unhappy paths. The token is a secret
        rather than an identifier, so there is nothing to enumerate by being precise —
        and `expired` is what lets the UI offer a resend instead of a dead end.
        """
        result = await self._tokens.consume(raw_token, PURPOSE_EMAIL_VERIFY)
        if not result.ok or result.token is None:
            return VerifyResult(result.outcome)

        user = await self._users.get_by_id(result.token.user_id)
        if user is None:
            # The FK cascades, so this means the account was deleted between mint and
            # click. Nothing to verify.
            return VerifyResult(ConsumeOutcome.INVALID)

        now = datetime.now(UTC)
        if user.email_verified_at is None:
            user.email_verified_at = now

        # A DISABLED account is never revived by clicking an old link.
        if not self._settings.AUTO_APPROVE_ON_VERIFY or user.status != UserStatus.PENDING:
            await self._users.session.flush()
            return VerifyResult(ConsumeOutcome.OK, approved=user.status == UserStatus.APPROVED)

        user.status = UserStatus.APPROVED
        user.approved_at = now
        await self._users.session.flush()

        raw_session = self._new_session_token()
        session = await self._sessions.create_for_user(
            str(user.id), raw_session, SESSION_TTL_SECONDS
        )
        await self._send(templates.verified_welcome(to=user.email), user.email)
        return VerifyResult(
            ConsumeOutcome.OK,
            approved=True,
            session_token=raw_session,
            expires_at=session.expires_at,
        )

    async def resend(self, email: str) -> None:
        """Re-issue a verification link if *email* has an unverified account.

        Silent for every other case — unknown address, already verified, disabled. The
        caller answers identically regardless, so this endpoint cannot be used to test
        whether an address has an account.
        """
        user = await self._users.get_by_email(email)
        if user is None or user.email_verified_at is not None:
            return
        if user.status == UserStatus.DISABLED:
            return
        await self.send_verification(user)

    @staticmethod
    def _new_session_token() -> str:
        return secrets.token_hex(32)
