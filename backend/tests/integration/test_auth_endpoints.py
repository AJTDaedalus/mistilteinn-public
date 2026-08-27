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
#
# **This list is checked against the app, not maintained by memory.** It used to carry a
# `TODO` asking that every restored route be added here in the same commit — and Chunks G and
# D then added six owned routes without it. The instruction was right and following it was
# optional, which is the same thing as not having it.
#
# `test_the_sweep_covers_every_owned_route` walks the app's dependency graph for
# `get_current_user` and fails if this table misses one. Adding a route with auth now breaks
# the suite until it is listed.
_OWNED_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/auth/me", None),
    ("POST", "/api/v1/auth/logout", {}),
    # teams
    ("GET", "/api/v1/teams", None),
    ("POST", "/api/v1/teams", {}),
    ("GET", "/api/v1/teams/00000000-0000-0000-0000-000000000001", None),
    ("PATCH", "/api/v1/teams/00000000-0000-0000-0000-000000000001", {}),
    ("DELETE", "/api/v1/teams/00000000-0000-0000-0000-000000000001", None),
    # builds — G.6c
    ("GET", "/api/v1/builds", None),
    ("GET", "/api/v1/builds/options", None),  # T.3
    ("POST", "/api/v1/builds", {}),
    ("GET", "/api/v1/builds/00000000-0000-0000-0000-000000000001", None),
    ("PATCH", "/api/v1/builds/00000000-0000-0000-0000-000000000001", {}),
    ("DELETE", "/api/v1/builds/00000000-0000-0000-0000-000000000001", None),
    ("GET", "/api/v1/builds/00000000-0000-0000-0000-000000000001/hits", None),  # M.2
    ("POST", "/api/v1/builds/00000000-0000-0000-0000-000000000001/explain", {}),
    ("POST", "/api/v1/builds/00000000-0000-0000-0000-000000000001/search-context", {}),  # O.1
    ("POST", "/api/v1/builds/00000000-0000-0000-0000-000000000001/compare-weapons", {}),
    (
        "POST",
        "/api/v1/builds/00000000-0000-0000-0000-000000000001/compare-weapons/gcsim",
        {},
    ),
    (
        "POST",
        "/api/v1/builds/00000000-0000-0000-0000-000000000001/calibrate",
        {},
    ),
    # artifacts — G.6b and D.1
    ("GET", "/api/v1/artifacts", None),
    ("GET", "/api/v1/artifacts/inventory", None),
    ("GET", "/api/v1/artifacts/options", None),  # A.3
    ("GET", "/api/v1/artifacts/00000000-0000-0000-0000-000000000001", None),
    ("PATCH", "/api/v1/artifacts/00000000-0000-0000-0000-000000000001", {}),  # A.1
    ("DELETE", "/api/v1/artifacts/00000000-0000-0000-0000-000000000001", None),
    ("POST", "/api/v1/artifacts/import/good", {}),
    # rotations — R.4
    ("GET", "/api/v1/rotations", None),
    ("GET", "/api/v1/rotations/options", None),  # R.5
    ("POST", "/api/v1/rotations", {}),
    ("GET", "/api/v1/rotations/00000000-0000-0000-0000-000000000001", None),
    ("PATCH", "/api/v1/rotations/00000000-0000-0000-0000-000000000001", {}),
    ("DELETE", "/api/v1/rotations/00000000-0000-0000-0000-000000000001", None),
    ("POST", "/api/v1/rotations/00000000-0000-0000-0000-000000000001/compile", {}),
    ("POST", "/api/v1/rotations/00000000-0000-0000-0000-000000000001/context-key", {}),  # R.6
    # the run corpus — D.1 and D.3
    ("GET", "/api/v1/sim-runs", None),
    ("POST", "/api/v1/sim-runs", {}),
    ("GET", "/api/v1/sim-runs/retrieve", None),
    ("GET", f"/api/v1/sim-runs/{'a' * 64}/180", None),
]


def _routes_requiring_auth() -> set[tuple[str, str]]:
    """Every `(method, path)` whose dependency graph reaches the auth dependency.

    Read off the running app rather than a list someone keeps up to date, because the thing
    being guarded is precisely that a route can be added without anyone remembering.
    """
    from app.dependencies import get_current_user, get_current_user_any_status
    from app.main import create_app

    def needs_auth(dependant: object) -> bool:
        if dependant.call in (get_current_user, get_current_user_any_status):
            return True
        return any(needs_auth(child) for child in dependant.dependencies)

    return {
        (method, route.path)
        for route in create_app().routes
        if getattr(route, "dependant", None) is not None and needs_auth(route.dependant)
        for method in (route.methods or set())
    }


def test_the_sweep_covers_every_owned_route() -> None:
    """The table only proves what it lists, so what it lists is checked against the app.

    A handler that forgets its auth dependency is invisible to every other test in this
    suite — it simply works, for everyone. That is the failure this sweep exists for, and a
    sweep that silently stops covering new routes is the same failure wearing a green tick.
    """
    template = "00000000-0000-0000-0000-000000000001"
    listed = set()
    for method, path, _ in _OWNED_ENDPOINTS:
        # Concrete ids in the table map back to the route's parameter names.
        parts = []
        for segment in path.split("/"):
            if segment == template or len(segment) == 64 or segment == "180":
                parts.append("{}")
            else:
                parts.append(segment)
        listed.add((method, "/".join(parts)))

    actual = {
        (method, "/".join("{}" if s.startswith("{") else s for s in path.split("/")))
        for method, path in _routes_requiring_auth()
    }

    missing = sorted(actual - listed)
    assert not missing, (
        f"these routes require auth and the 401 sweep does not cover them: {missing}. "
        f"Add them to _OWNED_ENDPOINTS — a handler that forgets its auth dependency is "
        f"invisible to every other test in this suite."
    )



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
