"""Integration tests: auth enforcement on all user-data endpoints.

Every route that touches owned rows (builds, discs, teams, combos,
optimizer jobs) must return 401 when no bearer token is supplied.
Public routes (health, auth/request-access, agents, disc-sets,
w-engines, enemies, damage, scorer) must remain accessible.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from app.models.enums import UserStatus
from app.models.session import Session
from app.models.user import User
from app.services.password import hash_password

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_TEST_PASSWORD = "alpha-test-password-1234"  # noqa: S105
_SESSION_TTL_SECONDS = 30 * 24 * 3600


# ── helpers ───────────────────────────────────────────────────────────────────


async def _make_approved_user(db_session: AsyncSession) -> tuple[User, str]:
    """Create an approved user with a session; return (user, raw_token)."""
    user = User(
        email="authtest@example.com",
        label="Auth Test",
        password_hash=hash_password(_TEST_PASSWORD),
        status=UserStatus.APPROVED,
    )
    db_session.add(user)
    await db_session.flush()

    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(UTC)
    session = Session(
        user_id=str(user.id),
        token_hash=token_hash,
        expires_at=now + timedelta(seconds=_SESSION_TTL_SECONDS),
        last_used_at=now,
    )
    db_session.add(session)
    await db_session.flush()

    return user, raw_token


# ── 401 sweep ─────────────────────────────────────────────────────────────────

# (method, path, body) for every user-data endpoint.
# Body only needs to be syntactically valid JSON; the auth check fires first.
_OWNED_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    # teams — the only owner-scoped surface left after B.6.
    ("GET", "/api/v1/teams", None),
    ("POST", "/api/v1/teams", {}),
    ("GET", "/api/v1/teams/00000000-0000-0000-0000-000000000001", None),
    ("PATCH", "/api/v1/teams/00000000-0000-0000-0000-000000000001", {}),
    ("DELETE", "/api/v1/teams/00000000-0000-0000-0000-000000000001", None),
    # TODO(chunk-F/G): this table is a 401 sweep over *every* user-data endpoint, and it
    # only proves what it lists. B.12 removed the builds, discs, combos and optimizer-jobs
    # rows because those routes were deleted in B.6. **Every route restored in Chunk F or G
    # must be added back here in the same commit that adds the route** — a handler that
    # forgets its auth dependency is invisible to every other test in this suite.
    # Chunk D is done and added no routes: it seeds the catalogue and exposes none of it.
]


@pytest.mark.parametrize(("method", "path", "body"), _OWNED_ENDPOINTS)
@pytest.mark.asyncio
async def test_owned_endpoint_requires_auth(
    client: AsyncClient,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """No bearer token → 401 on every owned-data route."""
    send = getattr(client, method.lower())
    if body is not None:
        resp = await send(path, json=body)
    else:
        resp = await send(path)
    assert resp.status_code == 401, (
        f"{method} {path} returned {resp.status_code}, expected 401.\nBody: {resp.text[:200]}"
    )


# ── public endpoints still work ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_is_public(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_register_is_public(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "public@example.com", "label": "Test", "password": _TEST_PASSWORD},
    )
    assert resp.status_code == 201


# ── token accepted ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_teams_list_with_valid_token(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _, raw_token = await _make_approved_user(db_session)
    resp = await client.get(
        "/api/v1/teams",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
