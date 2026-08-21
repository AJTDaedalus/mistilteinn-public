"""
Task 15: Security headers middleware.
Every response must carry X-Content-Type-Options, X-Frame-Options,
Referrer-Policy, and Content-Security-Policy.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health",
        "/nonexistent-path",
    ],
)
async def test_x_content_type_options(client, path):
    response = await client.get(path)
    assert response.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health",
        "/nonexistent-path",
    ],
)
async def test_x_frame_options(client, path):
    response = await client.get(path)
    assert response.headers.get("x-frame-options") == "DENY"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health",
        "/nonexistent-path",
    ],
)
async def test_referrer_policy(client, path):
    response = await client.get(path)
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health",
        "/nonexistent-path",
    ],
)
async def test_content_security_policy(client, path):
    response = await client.get(path)
    assert "content-security-policy" in response.headers
