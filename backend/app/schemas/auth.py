"""Auth schemas for registration and login flows."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — needed at runtime for Pydantic field validation
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import UserStatus
from app.services.password import validate_password

PasswordStr = Annotated[str, Field(min_length=12, max_length=72)]


class RegisterRequest(BaseModel):
    """Body for `POST /auth/register`."""

    email: EmailStr
    password: PasswordStr
    label: str = ""

    @model_validator(mode="after")
    def check_password_policy(self) -> RegisterRequest:
        """Reject registration if the password fails the policy checked by `validate_password`."""
        validate_password(self.password, email=self.email)
        return self


class RegisterResponse(BaseModel):
    """Response for `POST /auth/register` — always pending until email verification."""

    status: Literal["pending"] = "pending"


class LoginRequest(BaseModel):
    """Body for `POST /auth/login`."""

    email: EmailStr
    password: PasswordStr


class LoginResponse(BaseModel):
    """Response for `POST /auth/login` — bearer token and its expiry."""

    token: str
    expires_at: datetime


class MeResponse(BaseModel):
    """Response for `GET /auth/me` — the current user's identity and account status."""

    email: EmailStr
    label: str
    status: UserStatus
