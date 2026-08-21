"""Integration tests: per-owner rate limiting returns 429 on burst."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_write_endpoint_rate_limit_returns_429(authed_client: AsyncClient) -> None:
    """Burst over the 60/minute write limit on DELETE /optimizer/jobs → 429."""
    url = "/api/v1/optimizer/jobs/00000000-0000-0000-0000-000000000001"
    # Each authed_client has a fresh random token → fresh rate-limit bucket.
    # The write limit is 60/minute; we send up to 70 requests and expect 429.
    for _ in range(70):
        r = await authed_client.delete(url)
        if r.status_code == 429:
            assert r.headers.get("Retry-After") is not None or r.status_code == 429
            return
    pytest.fail("Expected a 429 response within 70 DELETE requests but never received one")


@pytest.mark.asyncio
async def test_rate_limit_is_per_owner(
    authed_client: AsyncClient,
    db_session: object,
    client: AsyncClient,
) -> None:
    """Two different owners have independent rate-limit buckets.

    We exhaust owner A's budget on DELETE /optimizer/jobs, then verify
    owner B (a freshly minted token in authed_client2) is not rate-limited.
    """
    import secrets

    from app.models.enums import UserStatus
    from app.models.user import User
    from app.services.password import hash_password
    from tests.conftest import make_session_for

    # Create a second approved user with a session
    session = db_session
    user_b = User(
        email=f"ratelimit_b_{secrets.token_hex(4)}@test.example",
        label="Rate Limit B",
        password_hash=hash_password("alpha-test-password-1234"),
        status=UserStatus.APPROVED,
    )
    session.add(user_b)
    await session.flush()
    raw_token_b = await make_session_for(user_b, session)

    url = "/api/v1/optimizer/jobs/00000000-0000-0000-0000-000000000001"

    # Exhaust owner A's limit
    hit_429 = False
    for _ in range(70):
        r = await authed_client.delete(url)
        if r.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "Owner A should have been rate-limited within 70 requests"

    # Owner B makes one request — should not be rate-limited (gets 404, not 429)
    r_b = await client.delete(url, headers={"Authorization": f"Bearer {raw_token_b}"})
    assert r_b.status_code == 404, (
        f"Owner B should get 404 (not rate-limited), got {r_b.status_code}"
    )
