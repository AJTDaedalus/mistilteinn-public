"""ASGI middleware enforcing per-path request body size limits."""

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Global default: 2 MB.  Tighter per-path overrides are in path_limits.
DEFAULT_MAX_BODY = 2 * 1024 * 1024  # 2 MB
IMPORT_MAX_BODY = 1 * 1024 * 1024  # 1 MB — disc import payloads

PATH_LIMITS: dict[str, int] = {
    "/api/v1/discs/import": IMPORT_MAX_BODY,
}


class _BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject HTTP request bodies that exceed a per-path size cap.

    Checks Content-Length first (fast path).  For chunked / streaming bodies
    without that header, wraps `receive` and raises once accumulated bytes
    exceed the limit.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_size: int = DEFAULT_MAX_BODY,
        path_limits: dict[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_size = max_size
        self.path_limits = path_limits if path_limits is not None else PATH_LIMITS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject the request with 413 if its body exceeds the path's size cap."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        limit = self.path_limits.get(path, self.max_size)

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    response = PlainTextResponse("Request body too large", status_code=413)
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        total_bytes = 0

        async def limited_receive() -> dict:
            nonlocal total_bytes
            message = await receive()
            if message["type"] == "http.request":
                total_bytes += len(message.get("body", b""))
                if total_bytes > limit:
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLargeError:
            response = PlainTextResponse("Request body too large", status_code=413)
            await response(scope, receive, send)
