"""Auth schemas for registration and login flows."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — needed at runtime for Pydantic field validation
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import UserStatus
from app.services.password import validate_password

if TYPE_CHECKING:
    from app.models.character import Character
    from app.models.user import User

PasswordStr = Annotated[str, Field(min_length=12, max_length=72)]


class RegisterRequest(BaseModel):
    """Body for `POST /auth/register`."""

    email: EmailStr
    password: PasswordStr
    # Bounded to match `users.label` (String(200)). Unbounded, an over-long label passed
    # validation and then blew up inside the *background* task in fairy, after the 202 had
    # already gone out: no account, no email, no visible error anywhere.
    label: str = Field(default="", max_length=200)
    # Empty by default so local dev and tests, where `TURNSTILE_SECRET_KEY` is unset and
    # verification is skipped entirely, need not send a field that means nothing there.
    turnstile_token: str = ""
    # **Honeypot.** Real users never see this field; naive form-filling bots populate every
    # input they find. A filled value gets the ordinary success response — see the handler for
    # why the trap is worth more than a visible rejection.
    website: str = ""

    @model_validator(mode="after")
    def check_password_policy(self) -> RegisterRequest:
        """Reject registration if the password fails the policy checked by `validate_password`."""
        validate_password(self.password, email=self.email)
        return self


class RegisterResponse(BaseModel):
    """Response for `POST /auth/register` — always pending until email verification."""

    # **Says nothing about whether the address was already registered.** That
    # duplicate-vs-new distinction was a free membership-checking API for anyone who found the
    # URL. `DESIGN_open_registration.md` §2.
    status: Literal["verification_sent"] = "verification_sent"


class LoginRequest(BaseModel):
    """Body for `POST /auth/login`."""

    email: EmailStr
    password: PasswordStr


class LoginResponse(BaseModel):
    """Response for `POST /auth/login` — bearer token and its expiry."""

    token: str
    expires_at: datetime


class AvatarRead(BaseModel):
    """The character standing in for an account, as the client needs it to draw one.

    **One optional object rather than three flat nullable fields.** `avatar_character_id`,
    `avatar_name` and `avatar_icon` side by side are three things that can disagree; this is
    either present or it is not.

    `name` is here because the client needs it for the image's `alt` text and for the line
    naming who is shown — and a bare id would make the account page fetch the whole catalogue
    before it could name what it is already displaying. `icon` may still be null: it is a
    seeding gap for a handful of rows, and `CatalogueIcon` renders nothing at all for one.
    """

    character_id: str
    name: str
    icon: str | None = None


class MeResponse(BaseModel):
    """Response for `GET /auth/me` — the current user's identity and account status."""

    email: EmailStr
    label: str
    status: UserStatus
    #: Null until the user picks one, which is every account that existed before this field.
    avatar: AvatarRead | None = None

    @classmethod
    def for_user(cls, user: User, character: Character | None) -> MeResponse:
        """Build the response for `user`, showing `character` as their avatar if there is one.

        The character is passed in rather than read off the user, because `User` deliberately
        has no ORM relationship to it: lazy loading is refused repo-wide
        (`test_lazy_loads_are_refused.py`), and one nullable column plus one explicit fetch is
        less machinery than a guarded relationship that only ever loads one row.
        """
        return cls(
            email=user.email,
            label=user.label,
            status=user.status,
            avatar=(
                AvatarRead(
                    character_id=str(character.id), name=character.name, icon=character.icon,
                )
                if character is not None
                else None
            ),
        )


class SetAvatarRequest(BaseModel):
    """Body for `PUT /auth/me/avatar`.

    `None` clears the avatar, so setting and unsetting are one code path with one shape — a
    separate `DELETE` route would be a second path to keep honest for no gain.

    **Required, and unknown fields are refused**, which for a nullable field is not
    belt-and-braces. With a `None` default and Pydantic's `extra="ignore"`, a client sending
    `{"characterId": "…"}` — one camelCase slip — validates, lands in the clear branch, and
    **erases the avatar with a 200**. The handler's own docstring refuses to no-op on an
    unknown id for a weaker version of this reason; here the 200 changed something nobody
    asked to change. Both shapes are a 422 now. Same rule as `BuildCreate`.
    """

    model_config = {"extra": "forbid"}

    character_id: str | None


class VerifyEmailRequest(BaseModel):
    """Body for `POST /auth/verify-email`.

    **The token arrives in a POST body rather than a query string**, for two reasons and the
    second is the one people miss. Secrets in URLs leak — into Referer headers, browser
    history, nginx access logs and Cloudflare analytics — and a live account-takeover
    credential should not be in an access log. And a `GET`-consumes endpoint is burned by the
    mail scanners that fetch every link in an email before the human does: Outlook Safe Links,
    corporate gateways, Slack unfurls. Against those, the scanner spends the single-use token
    and the user's own click fails — a bug that reproduces only for users at companies you
    cannot test against.

    A scanner fetching the SPA route instead gets an HTML shell and does not execute Angular,
    so the token survives to the real click. `DESIGN_open_registration.md` §2 (D-OR3).
    """

    token: str = Field(min_length=1, max_length=512)


class VerifyEmailResponse(BaseModel):
    """Response for `POST /auth/verify-email`.

    `session_token` is populated only when verification also approved the account, so the user
    lands verified *and* signed in from one click with no password re-entry. That is the whole
    UX win of this design and it costs one field.
    """

    status: Literal["approved", "pending"]
    session_token: str | None = None
    expires_at: datetime | None = None


class ResendVerificationRequest(BaseModel):
    """Body for `POST /auth/resend-verification`."""

    email: EmailStr
    turnstile_token: str = ""


class ResendVerificationResponse(BaseModel):
    """Response for `POST /auth/resend-verification` — identical for every address.

    Answering differently for a known and an unknown address would make this endpoint the
    account-enumeration oracle that `register` just stopped being.
    """

    status: Literal["verification_sent"] = "verification_sent"
