"""
Task 14: /docs, /redoc, /openapi.json are hidden (404) in production;
available in local dev.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def local_client():
    with patch("app.main.settings") as mock_settings:
        mock_settings.ENV = "local"
        mock_settings.CORS_ORIGINS = ["http://localhost:4200"]
        app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def prod_client():
    with patch("app.main.settings") as mock_settings:
        mock_settings.ENV = "production"
        mock_settings.CORS_ORIGINS = ["https://example.pages.dev"]
        app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_docs_available_in_local(local_client, path):
    response = await local_client.get(path)
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_docs_hidden_in_production(prod_client, path):
    response = await prod_client.get(path)
    assert response.status_code == 404
