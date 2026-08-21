import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def simple_client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_health_endpoint(simple_client):
    response = await simple_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
