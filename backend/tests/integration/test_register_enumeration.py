"""`POST /auth/register` must not disclose whether an address is already registered.

Before this, a duplicate returned 409 and a new address 201 — a free membership-checking
API for anyone who found the URL (`docs/DESIGN_open_registration.md` §4.3, §5.3).

The status-code half is only half the oracle. The other half is timing: bcrypt at cost 12
is ~250 ms, so a handler that skipped the hash for known addresses would still answer
"already registered" measurably faster. That half is enforced by code structure and
`test_the_password_is_hashed_on_every_path`, because asserting on wall-clock in CI is
flaky.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.models.enums import UserStatus
from app.models.user import User
from app.services.email_policy import normalize
from app.services.password import hash_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_PASSWORD = "valid-test-password-1234"  # noqa: S105


async def _seed(
    db: AsyncSession, email: str, *, verified: bool, status: UserStatus = UserStatus.PENDING
) -> User:
    user = User(
        email=email,
        email_normalized=normalize(email),
        label="Existing",
        password_hash=hash_password(_PASSWORD),
        status=status,
    )
    db.add(user)
    await db.flush()
    if verified:
        user.email_verified_at = user.created_at
        await db.flush()
    return user


def _body(email: str) -> dict:
    return {"email": email, "password": _PASSWORD}


async def _count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


class TestResponsesAreIndistinguishable:
    @pytest.mark.asyncio
    async def test_new_and_existing_addresses_answer_identically(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        make, _ = signup_client
        client = make()
        known = f"known_{secrets.token_hex(6)}@example.com"
        await _seed(db_session, known, verified=True)

        fresh_resp = await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body(f"new_{known}"))
        known_resp = await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body(known))

        assert fresh_resp.status_code == known_resp.status_code == 202
        assert fresh_resp.json() == known_resp.json()
        assert known_resp.json() == {"status": "verification_sent"}

    @pytest.mark.asyncio
    async def test_a_gmail_alias_of_a_known_address_is_also_indistinguishable(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """The alias must not become a side channel that the plain address closed."""
        make, _ = signup_client
        client = make()
        await _seed(db_session, "someone@gmail.com", verified=True)

        resp = await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body("some.one+x@gmail.com"))

        assert resp.status_code == 202
        assert resp.json() == {"status": "verification_sent"}


def _caller() -> dict[str, str]:
    """A distinct client address per call.

    `register` is rate limited `3/hour` per IP now, and every test client otherwise shares
    `127.0.0.1` — so the fourth call in a run was a 429 and the assertions that followed were
    about an empty mailbox rather than about enumeration. Randomised so tests stay
    order-independent.
    """
    return {"CF-Connecting-IP": f"203.0.113.{secrets.randbelow(200) + 1}"}


class TestWhichEmailIsSent:
    @pytest.mark.asyncio
    async def test_a_new_address_gets_a_verification_link(self, signup_client) -> None:
        make, mailbox = signup_client
        client = make()

        await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body("brand-new@example.com"))

        assert "/verify?token=" in mailbox.last().text

    @pytest.mark.asyncio
    async def test_a_verified_address_gets_the_someone_tried_notice(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """The account holder is told someone is probing their address.

        Silently dropping the request would protect their privacy from the submitter but
        hide a possible attack from *them*.
        """
        make, mailbox = signup_client
        client = make()
        known = f"known_{secrets.token_hex(6)}@example.com"
        await _seed(db_session, known, verified=True)

        await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body(known))

        msg = mailbox.last()
        assert msg.to == known
        assert "token=" not in msg.text
        assert "already registered" in msg.text.lower()

    @pytest.mark.asyncio
    async def test_an_unverified_address_gets_a_fresh_link_not_the_notice(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """Re-registering an address you never confirmed is the common honest mistake."""
        make, mailbox = signup_client
        client = make()
        known = f"unver_{secrets.token_hex(6)}@example.com"
        await _seed(db_session, known, verified=False)

        await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body(known))

        assert "/verify?token=" in mailbox.last().text

    @pytest.mark.asyncio
    async def test_the_notice_goes_to_the_stored_address_not_the_submitted_one(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """Otherwise this endpoint mails arbitrary text to an attacker's own inbox."""
        make, mailbox = signup_client
        client = make()
        await _seed(db_session, "victim@gmail.com", verified=True)

        await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body("v.i.c.t.i.m+evil@gmail.com"))

        assert mailbox.last().to == "victim@gmail.com"


class TestNoDuplicateAccounts:
    @pytest.mark.asyncio
    async def test_registering_a_known_address_creates_nothing(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        make, _ = signup_client
        client = make()
        known = f"known_{secrets.token_hex(6)}@example.com"
        await _seed(db_session, known, verified=True)
        before = await _count(db_session)

        await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body(known))

        assert await _count(db_session) == before

    @pytest.mark.asyncio
    async def test_a_gmail_alias_does_not_mint_a_second_account(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """Without normalization, one inbox buys unlimited accounts and every per-email
        rate limit is bypassed by typing a dot."""
        make, _ = signup_client
        client = make()
        await _seed(db_session, "person@gmail.com", verified=True)
        before = await _count(db_session)

        await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body("p.e.r.s.o.n+alias@gmail.com"))

        assert await _count(db_session) == before

    @pytest.mark.asyncio
    async def test_a_password_is_never_overwritten_by_re_registration(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """Otherwise anyone could reset a stranger's password by re-registering them."""
        make, _ = signup_client
        client = make()
        known = f"known_{secrets.token_hex(6)}@example.com"
        user = await _seed(db_session, known, verified=False)
        original = user.password_hash

        await client.post(
            "/api/v1/auth/register",
            json={"email": known, "password": "a-completely-different-pw-99"},
        )
        await db_session.refresh(user)

        assert user.password_hash == original


class TestTiming:
    @pytest.mark.asyncio
    async def test_the_password_is_hashed_on_every_path(
        self, signup_client, db_session: AsyncSession
    ) -> None:
        """Guards the timing half of the oracle.

        bcrypt cost 12 is ~250 ms. If the handler ever skips the hash for a known
        address, the identical response body still leaks the answer in wall-clock. This
        asserts the call happens rather than measuring the clock, which would be flaky.
        """
        make, _ = signup_client
        client = make()
        known = f"known_{secrets.token_hex(6)}@example.com"
        await _seed(db_session, known, verified=True)

        with patch("app.api.v1.auth.hash_password", wraps=hash_password) as spy:
            await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body(known))
            assert spy.call_count == 1, "duplicate path skipped bcrypt — timing oracle"

            await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body("fresh@example.com"))
            assert spy.call_count == 2


class TestDisposableDomains:
    @pytest.mark.asyncio
    async def test_a_throwaway_address_is_rejected_visibly(self, signup_client) -> None:
        """One of the few bot rejections worth being explicit about — it is also the
        message a legitimate user who reached for a temp address needs to read."""
        make, _ = signup_client
        client = make()

        resp = await client.post(
            "/api/v1/auth/register", headers=_caller(), json=_body("bot@mailinator.com"))

        assert resp.status_code == 422
        assert "permanent email" in resp.json()["detail"].lower()
