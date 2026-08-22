"""FastAPI app factory: lifespan startup/shutdown, middleware, and router wiring."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import v1_router
from app.config import settings
from app.database import async_session_factory, wait_for_db
from app.middleware.body_size import BodySizeLimitMiddleware
from app.middleware.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.repositories.session import SessionRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Wait for the database and purge expired sessions.

    C.6 removed the background job runner along with the endpoints it served. The orphan
    sweep went with it: it existed to fail jobs a restart had interrupted, and there are no
    jobs. Searching moved to the browser (DESIGN §3.5), where a search interrupted by a
    closed tab needs no server-side reconciliation.
    """
    await wait_for_db()
    async with async_session_factory() as db:
        deleted = await SessionRepository(db).delete_expired()
        if deleted:
            logger.info("Startup: purged %d expired sessions", deleted)
    yield


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def create_app() -> FastAPI:
    """Build the FastAPI app: exception handlers, middleware stack, and v1 router."""
    is_local = settings.ENV == "local"
    application = FastAPI(
        title="Mistilteinn - Genshin Optimizer",
        description="Genshin Impact build optimizer and rotation simulator",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if is_local else None,
        redoc_url="/redoc" if is_local else None,
        openapi_url="/openapi.json" if is_local else None,
    )

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_exception_handler(Exception, _unhandled_exception_handler)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(BodySizeLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    application.include_router(v1_router)

    return application


app = create_app()
