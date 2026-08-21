"""
Task 28: Confirm no error leakage.
FastAPI debug is off; unhandled exceptions return a sanitized 500 with no
stack trace or internal detail in the response body.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def leaky_client():
    """Client against an app that has one route wired to blow up."""
    app = create_app()

    @app.get("/test/force-500")
    async def _force_500():
        raise RuntimeError("secret internal detail: db_password=hunter2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_forced_exception_returns_500(leaky_client):
    response = await leaky_client.get("/test/force-500")
    assert response.status_code == 500


async def test_forced_exception_body_is_generic(leaky_client):
    response = await leaky_client.get("/test/force-500")
    body = response.json()
    assert body == {"detail": "Internal server error"}


async def test_forced_exception_no_stack_trace_in_body(leaky_client):
    response = await leaky_client.get("/test/force-500")
    text = response.text
    assert "Traceback" not in text
    assert "RuntimeError" not in text
    assert "hunter2" not in text


async def test_debug_mode_off():
    """FastAPI debug must be False — never expose internal frames."""
    app = create_app()
    assert app.debug is False
