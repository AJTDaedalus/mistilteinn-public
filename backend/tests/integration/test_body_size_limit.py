"""Integration tests: oversized request bodies are rejected with 413."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from app.middleware.body_size import DEFAULT_MAX_BODY, IMPORT_MAX_BODY

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_global_body_limit_returns_413(authed_client: AsyncClient) -> None:
    """POST with body exceeding DEFAULT_MAX_BODY returns 413."""
    oversized = b"x" * (DEFAULT_MAX_BODY + 1)
    r = await authed_client.post(
        "/api/v1/discs/",
        content=oversized,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_import_body_limit_returns_413(authed_client: AsyncClient) -> None:
    """POST /discs/import with body exceeding IMPORT_MAX_BODY returns 413."""
    # Build a payload just over the 1 MB import limit.
    # Use a valid-ish JSON structure so the middleware (not the parser) rejects it.
    filler = "A" * (IMPORT_MAX_BODY + 1)
    payload = json.dumps({"format": "ZOD", "version": 1, "junk": filler})
    r = await authed_client.post(
        "/api/v1/discs/import",
        content=payload.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_import_body_within_limit_is_processed(authed_client: AsyncClient) -> None:
    """POST /discs/import with a small valid body is not rejected by the middleware."""
    # Empty discs list — should pass the size check and return a domain-level response
    # (200 with 0 imports, or 422 for validation, but NOT 413).
    payload = json.dumps({"format": "ZOD", "version": 1, "source": "test", "discs": []})
    r = await authed_client.post(
        "/api/v1/discs/import",
        content=payload.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code != 413


@pytest.mark.asyncio
async def test_global_limit_allows_body_just_under(authed_client: AsyncClient) -> None:
    """POST body exactly at DEFAULT_MAX_BODY bytes passes the size check."""
    at_limit = b"x" * DEFAULT_MAX_BODY
    r = await authed_client.post(
        "/api/v1/discs/",
        content=at_limit,
        headers={"Content-Type": "application/json"},
    )
    # The body is invalid JSON so we expect 422 (validation error), not 413.
    assert r.status_code != 413
