"""Heavy requests are bounded and kept off the event loop (security audit F4).

`/rotations/validate` parsed on the event loop with no rate limit, and bcrypt hashed and
checked on it too, so a handful of requests stalled every other request the worker held.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from tests.integration.test_rotation_library import AYAKA, BARBARA, ROTATIONS, _party, _roster

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

VALIDATE = f"{ROTATIONS}/validate"


async def _validator(db_session: AsyncSession):
    return await _party(db_session, await _roster(db_session), holding=(AYAKA, BARBARA))


@pytest.mark.parametrize(
    "source",
    [
        "if " + "1+" * 20_000 + "1 { }\n",
        "x = " + "(" * 2_000 + "1" + ")" * 2_000 + ";\n",
        "if 1 {" * 1_000 + "}" * 1_000 + "\n",
    ],
    ids=["operator chain", "parentheses", "blocks"],
)
async def test_deeply_nested_source_is_a_422_not_a_500(db_session: AsyncSession, source: str):
    party = await _validator(db_session)

    refused = await party.client.post(
        VALIDATE, json={"team_id": party.team_id, "source": source},
    )

    assert refused.status_code == 422, refused.text[:300]
    assert "deep" in refused.text or "operators" in refused.text


async def test_ordinary_source_still_validates(db_session: AsyncSession):
    party = await _validator(db_session)

    ok = await party.client.post(
        VALIDATE, json={"team_id": party.team_id, "source": "barbara skill;"},
    )

    assert ok.status_code == 200, ok.text


async def test_validate_is_rate_limited(db_session: AsyncSession):
    """Generous enough for keystrokes, but not unbounded."""
    party = await _validator(db_session)
    body = {"team_id": party.team_id, "source": "barbara skill;"}

    codes = [(await party.client.post(VALIDATE, json=body)).status_code for _ in range(130)]

    assert 429 in codes
    assert 429 not in codes[:100]


#: The blocking stand-in for CPU work, and how soon after it starts an unrelated request must
#: answer. On the loop, the unrelated request cannot run at all until the blocking call returns.
_BLOCK_SECONDS = 0.6
_PROMPT_SECONDS = 0.3


class _Blocker:
    """Wraps a function so it blocks the calling thread, recording when it began."""

    def __init__(self) -> None:
        self.began: float | None = None

    def wrap(self, real):
        def blocking(*args, **kwargs):
            self.began = time.monotonic()
            time.sleep(_BLOCK_SECONDS)  # blocking, as CPU-bound work is
            return real(*args, **kwargs)

        return blocking


async def _latency_while_blocked(blocker: _Blocker, slow, fast_request) -> float:
    """Seconds from the blocking call starting to `fast_request` answering beside it."""
    answered: dict[str, float] = {}

    async def fast() -> None:
        while blocker.began is None:
            await asyncio.sleep(0.005)
        await fast_request()
        answered["at"] = time.monotonic()

    response, _ = await asyncio.gather(slow, fast())
    assert response.status_code < 500, response.text[:300]
    assert blocker.began is not None
    return answered["at"] - blocker.began


async def test_validate_does_not_hold_the_event_loop(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """While a slow validation runs, an unrelated request still answers."""
    from app.api.v1 import rotations

    blocker = _Blocker()
    monkeypatch.setattr(rotations, "validate_rotation", blocker.wrap(rotations.validate_rotation))
    party = await _validator(db_session)

    latency = await _latency_while_blocked(
        blocker,
        party.client.post(VALIDATE, json={"team_id": party.team_id, "source": "barbara skill;"}),
        lambda: party.client.get("/api/v1/health"),
    )

    assert latency < _PROMPT_SECONDS


async def test_login_does_not_hold_the_event_loop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
):
    """bcrypt is ~250 ms of CPU; on the loop, sixteen logins stalled every other request."""
    from app.api.v1 import auth

    blocker = _Blocker()
    monkeypatch.setattr(auth, "verify_password", blocker.wrap(lambda *_: False))

    latency = await _latency_while_blocked(
        blocker,
        client.post(
            "/api/v1/auth/login",
            json={"email": "nobody-heavy@example.com", "password": "some-password-1234"},
            headers={"CF-Connecting-IP": "198.19.7.7"},
        ),
        lambda: client.get("/api/v1/health"),
    )

    assert latency < _PROMPT_SECONDS


async def test_register_does_not_hold_the_event_loop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
):
    from app.api.v1 import auth

    blocker = _Blocker()
    monkeypatch.setattr(auth, "hash_password", blocker.wrap(auth.hash_password))

    latency = await _latency_while_blocked(
        blocker,
        client.post(
            "/api/v1/auth/register",
            json={"email": "heavy-register@example.com", "password": "some-password-1234"},
            headers={"CF-Connecting-IP": "198.19.8.8"},
        ),
        lambda: client.get("/api/v1/health"),
    )

    assert latency < _PROMPT_SECONDS
