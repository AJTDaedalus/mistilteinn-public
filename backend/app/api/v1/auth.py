"""Auth endpoints."""

from __future__ import annotations

import hashlib
import json as _json
import secrets

from fastapi import APIRouter, HTTPException, Request, status

from app.dependencies import CurrentUserAnyStatus, DBSession
from app.middleware.rate_limit import limiter
from app.models.enums import UserStatus
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.services.password import DUMMY_HASH, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days
_AUTH_ERROR = "Invalid email or password."


def _login_ip_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_email_key(request: Request) -> str:
    # request._body is populated by FastAPI's body parsing before the handler runs.
    raw: bytes | None = getattr(request, "_body", None)
    if raw:
        try:
            return str(_json.loads(raw).get("email", "unknown"))
        except ValueError:
            pass
    return "unknown"


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(body: RegisterRequest, db: DBSession) -> RegisterResponse:
    """Register a new account. Returns pending status; no session token issued."""
    repo = UserRepository(db)
    if await repo.get_by_email(body.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )
    pw_hash = hash_password(body.password)
    await repo.create(
        {
            "email": body.email,
            "label": body.label,
            "password_hash": pw_hash,
            "status": UserStatus.PENDING,
        }
    )
    return RegisterResponse()


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/15minutes", key_func=_login_ip_key)
@limiter.limit("10/hour", key_func=_login_email_key)
async def login(
    request: Request,
    body: LoginRequest,
    db: DBSession,
) -> LoginResponse:
    """Authenticate with email + password. Returns session token on success."""
    repo = UserRepository(db)
    user = await repo.get_by_email(body.email)

    if user is None or user.password_hash is None:
        # Constant-time path for unknown email — hash runs regardless.
        verify_password(body.password, DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_AUTH_ERROR,
        )

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_AUTH_ERROR,
        )

    if user.status == UserStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"status": "pending"},
        )

    if user.status != UserStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_AUTH_ERROR,
        )

    raw_token = secrets.token_hex(32)
    session_repo = SessionRepository(db)
    session = await session_repo.create_for_user(str(user.id), raw_token, _SESSION_TTL_SECONDS)
    return LoginResponse(token=raw_token, expires_at=session.expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: CurrentUserAnyStatus,
    db: DBSession,
    request: Request,
) -> None:
    """Invalidate the current session. Requires a valid bearer token."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:]
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        session_repo = SessionRepository(db)
        await session_repo.delete_by_token_hash(token_hash)


@router.get("/me", response_model=MeResponse)
async def get_me(current_user: CurrentUserAnyStatus) -> MeResponse:
    """Return the authenticated user's profile. Accessible to PENDING and APPROVED users."""
    return MeResponse(
        email=current_user.email,
        label=current_user.label,
        status=current_user.status,
    )
