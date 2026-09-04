"""Per-owner rate limiting via slowapi."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from slowapi import Limiter

from app.middleware.client_ip import get_client_ip

if TYPE_CHECKING:
    from fastapi import Request

WRITE_LIMIT = "60/minute"
JOB_LIMIT = "10/minute"
COMPUTE_LIMIT = "20/minute"


def _owner_key(request: Request) -> str:
    """Key rate-limit buckets by bearer token (per-owner), falling back to IP."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        return hashlib.sha256(token.encode()).hexdigest()[:32]
    # **`get_client_ip`, not `request.client.host`.** Behind nginx the peer is the nginx
    # container, so the raw attribute was one shared bucket for every anonymous caller on the
    # internet — see `client_ip.py`.
    return get_client_ip(request)


limiter = Limiter(key_func=_owner_key)
