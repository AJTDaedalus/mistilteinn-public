"""`REGISTRATION_OPEN` actually closes registration, and `register` is rate limited.

`TASKS_open_registration.md` 1 and 3.

**This file exists because of what fairy shipped.** Its pre-merge review found
`REGISTRATION_OPEN` documented in the deploy runbook and the design as *the* response to a bot
wave still creating accounts — and read by nothing. An operator would have flipped it during an
incident, restarted, and watched signups continue with nothing red anywhere.

A documented control that does nothing is worse than no control, because it is trusted.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.database import get_db
from app.main import create_app

pytestmark = pytest.mark.asyncio

REGISTER = "/api/v1/auth/register"


def _body(email: str = "gate@example.com") -> dict[str, str]:
    return {"email": email, "password": "a-long-enough-password", "label": "Gate"}


def _from(ip: str) -> dict[str, str]:
    """Register as a distinct caller.

    Necessary because `register` is now rate limited `3/hour` per IP and every test client
    otherwise shares `127.0.0.1` — the fourth test in this file was a 429 before this. That is
    the limiter working, and setting the header exercises `get_client_ip`'s Cloudflare branch
    on the real request path rather than only in a unit test.

    **`198.51.100.x`, deliberately not `203.0.113.x`.** The limiter's counters are
    process-global across the whole test session, and the other signup test files randomise a
    caller in `203.0.113.1-200` — so a fixed address there was eventually collided with by an
    unrelated test and the burst assertions failed on somebody else's traffic.
    """
    return {"CF-Connecting-IP": ip}


async def _client_with(db_session, **overrides) -> AsyncClient:
    """A client whose app sees `overrides` on top of the test settings."""
    from tests.conftest import TEST_DATABASE_URL

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        DATABASE_URL=TEST_DATABASE_URL, TESTING=True, **overrides,
    )

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_registration_is_open_by_default(db_session) -> None:
    """The default has to be the open one, or turning the feature on is a code change."""
    async with await _client_with(db_session) as client:
        response = await client.post(REGISTER, json=_body(), headers=_from("198.51.100.1"))

    assert response.status_code != 503


async def test_closing_registration_refuses_new_accounts(db_session) -> None:
    async with await _client_with(db_session, REGISTRATION_OPEN=False) as client:
        response = await client.post(
            REGISTER, json=_body("closed@example.com"), headers=_from("198.51.100.2"),
        )

    assert response.status_code == 503


async def test_closing_registration_does_not_touch_existing_users(
    db_session, authed_client,
) -> None:
    """The flag is an incident control, not a shutdown. Locking out everyone who already has
    an account would make an operator hesitate to use it, which defeats the point."""
    async with await _client_with(db_session, REGISTRATION_OPEN=False):
        response = await authed_client.get("/api/v1/auth/me")

    assert response.status_code == 200


async def test_the_flag_is_read_rather_than_merely_defined(db_session) -> None:
    """The regression this file is named for.

    Asserted as a *difference* between two settings values rather than as a status code, so a
    handler that hardcodes 503 — or ignores the flag entirely — cannot pass.
    """
    async with await _client_with(db_session, REGISTRATION_OPEN=True) as open_client:
        opened = await open_client.post(
            REGISTER, json=_body("a@example.com"), headers=_from("198.51.100.3"),
        )
    async with await _client_with(db_session, REGISTRATION_OPEN=False) as shut_client:
        shut = await shut_client.post(
            REGISTER, json=_body("b@example.com"), headers=_from("198.51.100.4"),
        )

    assert (opened.status_code, shut.status_code) != (shut.status_code, opened.status_code)
    assert shut.status_code == 503
    assert opened.status_code != 503


async def test_the_fourth_registration_from_one_address_is_refused(db_session) -> None:
    """`3/hour` per IP — the limit this endpoint did not have at all.

    Keyed on `CF-Connecting-IP`, so this also proves the limiter reads the resolved client
    address rather than the peer: before `get_client_ip`, every one of these requests keyed on
    the same value and the limit was global.
    """
    async with await _client_with(db_session) as client:
        codes = [
            (await client.post(
                REGISTER, json=_body(f"burst{i}@example.com"), headers=_from("198.51.100.99"),
            )).status_code
            for i in range(4)
        ]

    assert codes[3] == 429
    assert 429 not in codes[:3]


async def test_a_different_address_has_its_own_budget(db_session) -> None:
    """The half that makes the limit useful rather than merely present. With the old
    `request.client.host` these two callers shared one bucket, so one attacker locked out
    everyone."""
    async with await _client_with(db_session) as client:
        for i in range(3):
            await client.post(
                REGISTER, json=_body(f"noisy{i}@example.com"), headers=_from("198.51.100.50"),
            )
        other = await client.post(
            REGISTER, json=_body("quiet@example.com"), headers=_from("198.51.100.51"),
        )

    assert other.status_code != 429
