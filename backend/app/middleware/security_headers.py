"""ASGI middleware adding security response headers and a catch-all exception handler."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on every response.

    HSTS is intentionally omitted here — it must be set by the
    terminating proxy (Caddy / Cloudflare) which handles TLS.

    Also acts as the outermost catch-all for unhandled exceptions — a known
    Starlette BaseHTTPMiddleware limitation means app-level exception handlers
    cannot intercept exceptions that propagate back through call_next.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """Run the request, tag the response with security headers, and catch stray exceptions."""
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
            response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Restrictive CSP for a pure JSON API — no scripts, images, or frames needed.
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        return response
