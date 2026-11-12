"""Integration tests for the email-verification flow.

Covers `docs/DESIGN_open_registration.md` §5.1–5.2: the link is minted at registration,
consumed once, and — only when `AUTO_APPROVE_ON_VERIFY` is on — also approves the
account and hands back a session.

Every test drives the real HTTP surface with a `RecordingEmailSender`; nothing here
touches the network.
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.models.enums import UserStatus
from app.models.user import User
from app.services.password import hash_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_PASSWORD = "valid-test-password-1234"  # noqa: S105


def _email() -> str:
    return f"verify_{secrets.token_hex(6)}@example.com"


def _link_token(mailbox) -> str:
    """Pull the raw token out of the most recent verification email."""
    msg = mailbox.last()
    assert msg is not None, "no email was sent"
    match = re.search(r"https?://\S+/verify\?token=\S+", msg.text)
    assert match, f"no verification link in:\n{msg.text}"
    return parse_qs(urlparse(match.group(0)).query)["token"][0]


def _caller() -> dict[str, str]:
    """A distinct client address per call.

    `register` and `resend-verification` are both rate limited per IP now, and every test
    client otherwise shares `127.0.0.1` — so the fourth test in a class was a 429 that had
    nothing to do with what it was asserting. Randomised rather than fixed so tests stay
    order-independent.
    """
    return {"CF-Connecting-IP": f"203.0.113.{secrets.randbelow(200) + 1}"}


async def _register(client, email: str):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD},
        headers={"CF-Connecting-IP": f"203.0.113.{secrets.randbelow(200) + 1}"},
    )


async def _fetch(db: AsyncSession, email: str) -> User:
    return (await db.execute(select(User).where(User.email == email))).scalar_one()


class TestRegistrationSendsALink:
    @pytest.mark.asyncio
    async def test_one_verification_email_per_registration(self, signup_client) -> None:
        make, mailbox = signup_client
        client = make()
        email = _email()

        assert (await _register(client, email)).status_code == 202

        assert len(mailbox.sent) == 1
        assert mailbox.last().to == email
        assert "/verify?token=" in mailbox.last().text

    @pytest.mark.asyncio
    async def test_registration_survives_a_provider_outage(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """The user row is already written; a send failure must not 500 the signup.

        Otherwise a provider blip becomes a failed registration the user reads as
        "this site is broken" (DESIGN §5.4).
        """
        from app.services.email import EmailSendError, RecordingEmailSender

        make, _ = signup_client
        client = make(
            email_sender=RecordingEmailSender(fail_with=EmailSendError("provider down"))
        )
        email = _email()

        assert (await _register(client, email)).status_code == 202
        assert (await _fetch(db_session, email)).email is not None


class TestVerify:
    @pytest.mark.asyncio
    async def test_marks_the_address_verified(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        make, mailbox = signup_client
        client = make()
        email = _email()
        await _register(client, email)

        resp = await client.post(
            "/api/v1/auth/verify-email", json={"token": _link_token(mailbox)}
        )

        assert resp.status_code == 200
        assert (await _fetch(db_session, email)).email_verified_at is not None

    @pytest.mark.asyncio
    async def test_without_auto_approve_the_account_stays_pending(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """The gate stays shut until Phase 4. Verification alone grants nothing."""
        make, mailbox = signup_client
        client = make(AUTO_APPROVE_ON_VERIFY=False)
        email = _email()
        await _register(client, email)

        resp = await client.post(
            "/api/v1/auth/verify-email", json={"token": _link_token(mailbox)}
        )

        assert resp.json()["status"] == "pending"
        assert resp.json()["session_token"] is None
        assert (await _fetch(db_session, email)).status == UserStatus.PENDING

    @pytest.mark.asyncio
    async def test_with_auto_approve_the_user_lands_signed_in(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """One click: verified, approved, and holding a working session.

        The session in this response is the entire UX win of the design — without it
        the user has to go back and type their password again.
        """
        make, mailbox = signup_client
        client = make(AUTO_APPROVE_ON_VERIFY=True)
        email = _email()
        await _register(client, email)

        resp = await client.post(
            "/api/v1/auth/verify-email", json={"token": _link_token(mailbox)}
        )
        body = resp.json()

        assert body["status"] == "approved"
        assert body["session_token"]
        assert (await _fetch(db_session, email)).status == UserStatus.APPROVED

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {body['session_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["status"] == "approved"

    @pytest.mark.asyncio
    async def test_a_disabled_account_is_not_revived_by_an_old_link(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """Banning someone must not be undone by a link they were sent beforehand."""
        make, mailbox = signup_client
        client = make(AUTO_APPROVE_ON_VERIFY=True)
        email = _email()
        await _register(client, email)
        token = _link_token(mailbox)

        user = await _fetch(db_session, email)
        user.status = UserStatus.DISABLED
        await db_session.flush()

        resp = await client.post("/api/v1/auth/verify-email", json={"token": token})

        assert resp.json()["session_token"] is None
        assert (await _fetch(db_session, email)).status == UserStatus.DISABLED


class TestVerifyFailures:
    @pytest.mark.asyncio
    async def test_reused_link_reports_already_used(self, signup_client) -> None:
        make, mailbox = signup_client
        client = make()
        await _register(client, _email())
        token = _link_token(mailbox)

        assert (
            await client.post("/api/v1/auth/verify-email", json={"token": token})
        ).status_code == 200
        second = await client.post("/api/v1/auth/verify-email", json={"token": token})

        assert second.status_code == 400
        assert second.json()["detail"]["reason"] == "already_used"

    @pytest.mark.asyncio
    async def test_forged_link_reports_invalid(self, signup_client) -> None:
        make, _ = signup_client
        client = make()

        resp = await client.post(
            "/api/v1/auth/verify-email", json={"token": "definitely-not-a-real-token"}
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["reason"] == "invalid"

    @pytest.mark.asyncio
    async def test_expired_link_reports_expired_so_the_ui_can_offer_a_resend(
        self, signup_client
    ) -> None:
        """`expired` must be distinguishable from `invalid`.

        A user holding a day-old link needs a resend button, not a dead end that reads
        as "the site is broken".
        """
        make, mailbox = signup_client
        client = make(EMAIL_VERIFY_TTL_SECONDS=-1)
        await _register(client, _email())

        resp = await client.post(
            "/api/v1/auth/verify-email", json={"token": _link_token(mailbox)}
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["reason"] == "expired"


class TestResend:
    @pytest.mark.asyncio
    async def test_sends_a_fresh_link_for_an_unverified_account(self, signup_client) -> None:
        make, mailbox = signup_client
        client = make()
        email = _email()
        await _register(client, email)
        first = _link_token(mailbox)

        resp = await client.post(
            "/api/v1/auth/resend-verification",
            json={"email": email},
            headers=_caller(),
        )

        assert resp.status_code == 202
        assert _link_token(mailbox) != first

    @pytest.mark.asyncio
    async def test_the_previous_link_stops_working(self, signup_client) -> None:
        """A resend must not leave two live credentials in one inbox."""
        make, mailbox = signup_client
        client = make()
        email = _email()
        await _register(client, email)
        old = _link_token(mailbox)

        await client.post(
            "/api/v1/auth/resend-verification",
            json={"email": email},
            headers=_caller(),
        )

        stale = await client.post("/api/v1/auth/verify-email", json={"token": old})
        assert stale.status_code == 400
        assert (
            await client.post(
                "/api/v1/auth/verify-email", json={"token": _link_token(mailbox)}
            )
        ).status_code == 200

    @pytest.mark.asyncio
    async def test_unknown_address_answers_identically_and_sends_nothing(
        self, signup_client
    ) -> None:
        """Anything else would make this the enumeration oracle register stopped being."""
        make, mailbox = signup_client
        client = make()

        resp = await client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "nobody@example.com"},
            headers=_caller(),
        )

        assert resp.status_code == 202
        assert resp.json() == {"status": "verification_sent"}
        assert mailbox.sent == []

    @pytest.mark.asyncio
    async def test_already_verified_address_answers_identically_and_sends_nothing(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        make, mailbox = signup_client
        client = make()
        email = _email()
        user = User(
            email=email,
            label="Verified",
            password_hash=hash_password(_PASSWORD),
            status=UserStatus.APPROVED,
        )
        db_session.add(user)
        await db_session.flush()
        user.email_verified_at = user.created_at
        await db_session.flush()

        resp = await client.post(
            "/api/v1/auth/resend-verification",
            json={"email": email},
            headers=_caller(),
        )

        assert resp.status_code == 202
        assert mailbox.sent == []


async def _register_with(client, email: str, password: str):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
        headers=_caller(),
    )


async def _login(client, email: str, password: str):
    return await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=_caller(),
    )


_FIRST = "first-registrant-pass-111"
_SECOND = "second-registrant-pass-222"


class TestPreRegistrationCannotHijack:
    """The password that becomes active is the one sent with the link that was clicked.

    Security audit F1 (pre-hijacked accounts): re-registering an unverified address used to
    keep the *first* registrant's password, so whoever registered an address before its owner
    held a working password once the owner proved the inbox was theirs.
    """

    @pytest.mark.asyncio
    async def test_with_auto_approve_only_the_clicked_links_password_works(
        self, signup_client
    ) -> None:
        make, mailbox = signup_client
        client = make(AUTO_APPROVE_ON_VERIFY=True)
        email = _email()

        await _register_with(client, email, _FIRST)
        await _register_with(client, email, _SECOND)
        resp = await client.post(
            "/api/v1/auth/verify-email", json={"token": _link_token(mailbox)}
        )
        assert resp.status_code == 200

        assert (await _login(client, email, _FIRST)).status_code == 401
        assert (await _login(client, email, _SECOND)).status_code == 200

    @pytest.mark.asyncio
    async def test_without_auto_approve_the_later_approval_honours_the_clicked_link(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        make, mailbox = signup_client
        client = make(AUTO_APPROVE_ON_VERIFY=False)
        email = _email()

        await _register_with(client, email, _FIRST)
        await _register_with(client, email, _SECOND)
        await client.post("/api/v1/auth/verify-email", json={"token": _link_token(mailbox)})

        user = await _fetch(db_session, email)
        user.status = UserStatus.APPROVED
        await db_session.flush()

        assert (await _login(client, email, _FIRST)).status_code == 401
        assert (await _login(client, email, _SECOND)).status_code == 200

    @pytest.mark.asyncio
    async def test_a_resend_carries_the_latest_registrations_password(
        self, signup_client
    ) -> None:
        """A resend (which takes no password) must not fall back to the first registrant's."""
        make, mailbox = signup_client
        client = make(AUTO_APPROVE_ON_VERIFY=True)
        email = _email()

        await _register_with(client, email, _FIRST)
        await _register_with(client, email, _SECOND)
        await client.post(
            "/api/v1/auth/resend-verification", json={"email": email}, headers=_caller()
        )
        await client.post("/api/v1/auth/verify-email", json={"token": _link_token(mailbox)})

        assert (await _login(client, email, _FIRST)).status_code == 401
        assert (await _login(client, email, _SECOND)).status_code == 200

    @pytest.mark.asyncio
    async def test_a_single_registration_still_verifies_with_its_own_password(
        self, signup_client
    ) -> None:
        make, mailbox = signup_client
        client = make(AUTO_APPROVE_ON_VERIFY=True)
        email = _email()

        await _register_with(client, email, _FIRST)
        await client.post("/api/v1/auth/verify-email", json={"token": _link_token(mailbox)})

        assert (await _login(client, email, _FIRST)).status_code == 200
