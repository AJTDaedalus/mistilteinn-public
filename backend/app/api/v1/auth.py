"""Auth endpoints."""

from __future__ import annotations

import hashlib
import json as _json
import secrets

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.dependencies import (
    CurrentUser,
    CurrentUserAnyStatus,
    DBSession,
    RegistrationServiceDep,
    SettingsDep,
    TurnstileDep,
)
from app.middleware.client_ip import get_client_ip
from app.middleware.rate_limit import limiter
from app.models.character import Character
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.character import CharacterRepository
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    SetAvatarRequest,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.services.email_policy import is_disposable, normalize
from app.services.password import DUMMY_HASH, hash_password, verify_password
from app.services.practice_dummies import is_practice_dummy
from app.services.signup_log import (
    REGISTER_ACCEPTED,
    REGISTER_CAPTCHA_FAILED,
    REGISTER_CLOSED,
    REGISTER_DISPOSABLE,
    REGISTER_HONEYPOT,
    RESEND_REQUESTED,
    VERIFY_FAILED,
    VERIFY_OK,
    signup_event,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days
_AUTH_ERROR = "Invalid email or password."

#: Turnstile mints a token *for an action*, and the verifier checks it. Getting these wrong is
#: fairy's review finding 3: forgot-password sent a `register`-action token and 403'd the
#: moment Turnstile was configured.
_ACTION_REGISTER = "register"
_ACTION_RESEND = "resend-verification"

_CAPTCHA_ERROR = "Could not verify that you are human. Please try again."


def _login_ip_key(request: Request) -> str:
    # See `middleware/client_ip.py`: this read `request.client.host`, which behind nginx is
    # the same value for every request on the internet — so `5/15minutes` per IP was five
    # attempts per fifteen minutes for everyone at once.
    return get_client_ip(request)


def _register_ip_key(request: Request) -> str:
    return get_client_ip(request)


def _resend_email_key(request: Request) -> str:
    """Key on the **normalized** address, which is the whole point.

    Fairy's review finding 4: the per-email limits keyed on the raw body while identity
    resolved on the normalized column, so rotating Gmail dots bought unlimited resend budget
    aimed at one inbox — and this endpoint mails the address on the *account*, so our server
    becomes a free email cannon and our sending domain takes the reputational damage.
    """
    raw: bytes | None = getattr(request, "_body", None)
    if raw:
        try:
            return normalize(str(_json.loads(raw).get("email", "")))
        except ValueError:
            pass
    return "unknown"


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
    # **202, not 201.** Nothing is created synchronously any more: the row and the mail are
    # both queued behind the response, and for an address that already exists nothing is
    # created at all. "Accepted" is the only code that is true for every outcome — and saying
    # "Created" for the duplicate case would be the enumeration oracle wearing a status code.
    status_code=status.HTTP_202_ACCEPTED,
)
# **This endpoint had no rate limit at all.** That was survivable only because a registered
# account was inert until a human approved it — which is precisely the gate
# `DESIGN_open_registration.md` removes. Per IP; the per-email limit arrives with
# `email_normalized`, because keying the raw address lets rotating Gmail dots buy unlimited
# budget against one inbox (fairy's review, finding 4).
@limiter.limit("3/hour", key_func=_register_ip_key)
@limiter.limit("10/day", key_func=_register_ip_key)
async def register(
    request: Request,
    body: RegisterRequest,
    background: BackgroundTasks,
    registration: RegistrationServiceDep,
    turnstile: TurnstileDep,
    settings: SettingsDep,
) -> RegisterResponse:
    """Begin registration. **The same 202 for every well-formed request.**

    What it used to do — 409 on a duplicate — was a free membership-checking API for anyone
    who found the URL. `DESIGN_open_registration.md` §2.
    """
    # **Read, not merely defined.** Fairy shipped this flag documented in its runbook as *the*
    # response to a bot wave and wired to nothing — an operator would have flipped it
    # mid-incident, restarted, and watched signups continue with nothing red. A documented
    # control that does nothing is worse than no control, because it is trusted.
    if not settings.REGISTRATION_OPEN:
        signup_event(REGISTER_CLOSED, ip=get_client_ip(request))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration is temporarily closed. Existing accounts are unaffected.",
        )

    # **Honeypot: answer exactly as success would.** Create nothing, send nothing, never an
    # error — a distinguishable rejection tells the bot's author which field to skip, and the
    # trap is worth more than the block.
    if body.website:
        signup_event(REGISTER_HONEYPOT, ip=get_client_ip(request), email=body.email)
        return RegisterResponse()

    if not await turnstile.verify(
        body.turnstile_token, action=_ACTION_REGISTER, remote_ip=get_client_ip(request),
    ):
        signup_event(REGISTER_CAPTCHA_FAILED, ip=get_client_ip(request), email=body.email)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_CAPTCHA_ERROR)

    if is_disposable(body.email):
        signup_event(REGISTER_DISPOSABLE, ip=get_client_ip(request), email=body.email)
        # One of the few bot rejections worth making **visible**: it is also the message a
        # legitimate user who reached for a throwaway address needs to read.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please use a permanent email address.",
        )

    # **Hashed unconditionally, before the existence check, and deliberately so.** Returning
    # the same body for a known and an unknown address closes the status oracle but not the
    # timing one: bcrypt at cost 12 is ~250 ms, so a handler that skipped the hash for
    # duplicates would still answer "already registered" measurably faster. Do not "optimise"
    # this into the new-account branch.
    pw_hash = hash_password(body.password)

    signup_event(REGISTER_ACCEPTED, ip=get_client_ip(request), email=body.email)
    # Out of band: a slow provider must not hold the request open, and a provider outage must
    # not 500 a signup whose user row was already written.
    background.add_task(
        registration.register, email=body.email, password_hash=pw_hash, label=body.label,
    )
    return RegisterResponse()


@router.post("/verify-email", response_model=VerifyEmailResponse)
@limiter.limit("20/hour", key_func=_register_ip_key)
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    registration: RegistrationServiceDep,
) -> VerifyEmailResponse:
    """Consume a verification link, verifying the address and possibly approving.

    **Failures name their reason.** The token is a secret rather than an identifier, so there
    is nothing to enumerate by being precise — and `expired` is what lets the UI offer a
    resend instead of a dead end.
    """
    result = await registration.verify(body.token)
    if not result.ok:
        signup_event(VERIFY_FAILED, ip=get_client_ip(request), reason=str(result.outcome))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": str(result.outcome)},
        )
    signup_event(VERIFY_OK, ip=get_client_ip(request), approved=result.approved)
    return VerifyEmailResponse(
        status="approved" if result.approved else "pending",
        session_token=result.session_token,
        expires_at=result.expires_at,
    )


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("3/hour", key_func=_register_ip_key)
@limiter.limit("3/hour", key_func=_resend_email_key)
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    registration: RegistrationServiceDep,
    turnstile: TurnstileDep,
) -> ResendVerificationResponse:
    """Re-issue a verification link. **Answers identically for every address.**

    An unknown address, an already-verified one, and a genuinely unverified one all get the
    same 202. Anything else makes this the enumeration oracle `register` was changed to stop
    being.
    """
    if not await turnstile.verify(
        body.turnstile_token, action=_ACTION_RESEND, remote_ip=get_client_ip(request),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_CAPTCHA_ERROR)

    signup_event(RESEND_REQUESTED, ip=get_client_ip(request), email=body.email)
    await registration.resend(body.email)
    return ResendVerificationResponse()


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


async def _avatar_character(user: User, db: DBSession) -> Character | None:
    """The character this user has chosen, or `None` — including when they have chosen nobody.

    One query, and only for an account that has picked something. `User` carries no ORM
    relationship to `Character` on purpose (`DESIGN_user_avatar.md` §3), so this is the single
    place that resolves the column.
    """
    if user.avatar_character_id is None:
        return None
    return await CharacterRepository(db).get_by_id(user.avatar_character_id)


@router.get("/me", response_model=MeResponse)
async def get_me(current_user: CurrentUserAnyStatus, db: DBSession) -> MeResponse:
    """Return the authenticated user's profile. Accessible to PENDING and APPROVED users."""
    return MeResponse.for_user(current_user, await _avatar_character(current_user, db))


@router.put("/me/avatar", response_model=MeResponse)
async def set_avatar(
    body: SetAvatarRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> MeResponse:
    """Choose the character whose headshot stands in for this account, or clear it.

    **A 404 for an id that names nothing, rather than a quiet no-op.** Accepting it would answer
    200 to a save that changed nothing, and the page would go on showing the avatar the user
    had just replaced with no indication of why.

    `character_id: null` clears it — the *Clear* button — so setting and unsetting are one
    code path. `DESIGN_user_avatar.md` §4.
    """
    character: Character | None = None
    if body.character_id is not None:
        character = await CharacterRepository(db).get_by_id(body.character_id)
        # **A practice mannequin is not a character you can be.** `get_by_id` is the plain
        # primary-key fetch and so skips the exclusion `CharacterRepository._filtered` applies
        # to every list and count — meaning an id the picker cannot offer would validate here.
        # The picker would then have no card matching the saved value and read "Choose a
        # character…" while the page above it said "Manekin".
        if character is None or is_practice_dummy(character.nanoka_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No such character.",
            )

    current_user.avatar_character_id = None if character is None else str(character.id)
    await db.commit()

    return MeResponse.for_user(current_user, character)
