"""Dependency injection factories for repositories."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.artifact import ArtifactRepository
from app.repositories.artifact_set import ArtifactSetRepository
from app.repositories.auth_token import AuthTokenRepository
from app.repositories.build import BuildRepository
from app.repositories.character import CharacterRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.optimization_run import OptimizationRunRepository
from app.repositories.owned_weapon import OwnedWeaponRepository
from app.repositories.rotation import RotationLibraryRepository, RotationRepository
from app.repositories.session import SessionRepository
from app.repositories.sim_run import SimRunRepository
from app.repositories.team import TeamRepository
from app.repositories.user import UserRepository
from app.repositories.weapon import WeaponRepository
from app.services.email import EmailSender, get_email_sender
from app.services.registration import RegistrationService
from app.services.turnstile import TurnstileVerifier

DBSession = Annotated[AsyncSession, Depends(get_db)]

#: Runtime configuration, injected rather than imported at module scope.
#:
#: `get_settings` is `lru_cache`d, so a handler that reads a flag through this dependency sees
#: the process's settings and a test can override it with `app.dependency_overrides`. Reading
#: `get_settings()` inline instead would make `REGISTRATION_OPEN` and `AUTO_APPROVE_ON_VERIFY`
#: untestable without mutating a cached singleton.
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_email_sender_dep() -> EmailSender:
    """FastAPI DI factory for the mail sender. Overridable in tests.

    A dependency rather than a direct `get_email_sender()` call so a test can swap in
    `RecordingEmailSender` and assert on what *would* have been sent — which is how every
    test in this feature avoids the network the unit lane blocks anyway.
    """
    return get_email_sender()


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender_dep)]


def get_turnstile(settings: SettingsDep) -> TurnstileVerifier:
    """FastAPI DI factory for `TurnstileVerifier`. Overridable in tests."""
    return TurnstileVerifier(
        secret_key=settings.TURNSTILE_SECRET_KEY,
        expected_hostname=settings.TURNSTILE_EXPECTED_HOSTNAME,
    )


TurnstileDep = Annotated[TurnstileVerifier, Depends(get_turnstile)]


async def get_registration_service(
    session: DBSession,
    settings: SettingsDep,
    email_sender: EmailSenderDep,
) -> RegistrationService:
    """FastAPI DI factory for `RegistrationService`."""
    return RegistrationService(
        users=UserRepository(session),
        tokens=AuthTokenRepository(session),
        sessions=SessionRepository(session),
        email_sender=email_sender,
        settings=settings,
    )


RegistrationServiceDep = Annotated[
    RegistrationService, Depends(get_registration_service)
]

# ── Public (no auth) repo factories ──────────────────────────────────────────
#
# G.6 restored the four catalogue factories above, and **the note that stood here was
# stale in the direction that matters**: it read as twelve pieces of missing wiring waiting
# on chunks F and G, and nine of the twelve had already landed under Genshin names. An
# inventory of open work that counts finished work is worse than no inventory — it is the
# reason to look somewhere else.
#
# B.7 removed the factories for every deleted repository. Where each one went:
#
#   get_agent_repo             → get_character_repo
#   get_w_engine_repo          → get_weapon_repo
#   get_disc_set_repo          → get_artifact_set_repo
#   get_enemy_repo             → get_enemy_profile_repo
#   get_disc_repo              → get_owned_artifact_repo
#   get_combo_repo             → get_owned_rotation_repo
#   get_owned_disc_repo        → get_owned_artifact_repo
#   get_owned_combo_repo       → get_owned_rotation_repo
#   get_owned_build_repo       → get_owned_build_repo   (unchanged; it never left)
#
# Three are genuinely absent, and none of them is waiting on a chunk:
#
#   get_attack_repo            ZZZ. Genshin talent tables live on the character row, so
#                              there is no Attack entity for a repository to serve.
#   get_owned_buff_preset_repo ZZZ. No Genshin model, and the BRIEF says delete rather than
#                              alias.
#   get_build_repo             An *unscoped* build repository. Deliberately not offered:
#                              every build belongs to someone, and an injectable that hands
#                              a route an unscoped one is a tenancy bug a single missing
#                              `Depends` away. `get_owned_build_repo` is the only way in.
#
# The standing rule this note was written to carry still holds: a factory comes back with the
# route that needs it, not before — an injectable for a repository nothing calls is dead
# wiring.


async def get_character_repo(session: DBSession) -> CharacterRepository:
    """FastAPI DI factory for `CharacterRepository` (catalogue — no owner scope)."""
    return CharacterRepository(session)


async def get_weapon_repo(session: DBSession) -> WeaponRepository:
    """FastAPI DI factory for `WeaponRepository` (catalogue — no owner scope)."""
    return WeaponRepository(session)


async def get_artifact_set_repo(session: DBSession) -> ArtifactSetRepository:
    """FastAPI DI factory for `ArtifactSetRepository` (catalogue — no owner scope)."""
    return ArtifactSetRepository(session)


async def get_enemy_profile_repo(session: DBSession) -> EnemyProfileRepository:
    """FastAPI DI factory for `EnemyProfileRepository` (catalogue — no owner scope)."""
    return EnemyProfileRepository(session)


# ── Auth dependency ───────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)
_BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


async def _resolve_session_user(
    db: AsyncSession,
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[SessionRepository, User]:
    """Shared lookup: validate bearer → session → user. Returns (session_repo, user).

    Raises 401 on missing/invalid/expired token. Does NOT check user.status.
    Calls session_repo.touch() before returning.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    session_repo = SessionRepository(db)
    db_session = await session_repo.get_by_token_hash(token_hash)

    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if db_session.expires_at <= datetime.now(UTC):
        await session_repo.delete_by_token_hash(token_hash)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(db_session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await session_repo.touch(db_session)
    return session_repo, user


async def get_current_user(
    session: DBSession,
    credentials: _BearerCredentials,
) -> User:
    """Require an approved session token. 401 if missing/invalid/expired, 403 if not approved."""
    _, user = await _resolve_session_user(session, credentials)

    if user.status != UserStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not approved.",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_user_any_status(
    session: DBSession,
    credentials: _BearerCredentials,
) -> User:
    """Like get_current_user but allows PENDING status. DISABLED still raises 401."""
    _, user = await _resolve_session_user(session, credentials)

    if user.status == UserStatus.DISABLED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account disabled.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


CurrentUserAnyStatus = Annotated[User, Depends(get_current_user_any_status)]

# ── Owner-scoped repo factories (require auth) ────────────────────────────────


async def get_owned_team_repo(session: DBSession, current_user: CurrentUser) -> TeamRepository:
    """FastAPI DI factory for a `TeamRepository` scoped to the authenticated user's own rows."""
    return TeamRepository(session, owner_id=str(current_user.id))


async def get_owned_artifact_repo(
    session: DBSession, current_user: CurrentUser
) -> ArtifactRepository:
    """FastAPI DI factory for an `ArtifactRepository` scoped to the current user's pieces."""
    return ArtifactRepository(session, owner_id=str(current_user.id))


async def get_owned_weapon_repo(
    session: DBSession, current_user: CurrentUser
) -> OwnedWeaponRepository:
    """FastAPI DI factory for an `OwnedWeaponRepository` scoped to the caller's inventory."""
    return OwnedWeaponRepository(session, owner_id=str(current_user.id))


async def get_owned_build_repo(
    session: DBSession, current_user: CurrentUser
) -> BuildRepository:
    """FastAPI DI factory for a `BuildRepository` scoped to the current user's builds."""
    return BuildRepository(session, owner_id=str(current_user.id))


async def get_owned_rotation_repo(
    session: DBSession, current_user: CurrentUser
) -> RotationRepository:
    """FastAPI DI factory for a `RotationRepository` scoped to the caller's own rotations."""
    return RotationRepository(session, owner_id=str(current_user.id))


async def get_optimization_run_repo(
    session: DBSession, current_user: CurrentUser
) -> OptimizationRunRepository:
    """FastAPI DI factory for saved optimization runs, scoped to the caller.

    Scoped like `get_owned_rotation_repo` rather than open like the library one: reading
    somebody else's run goes through a **share key**, which is a different question from
    listing your own and deserves a different door.
    """
    return OptimizationRunRepository(session, owner_id=str(current_user.id))


async def get_rotation_library_repo(
    session: DBSession, current_user: CurrentUser
) -> RotationLibraryRepository:
    """FastAPI DI factory for the cross-user view of **published** rotations.

    Deliberately a different repository from `get_owned_rotation_repo` rather than a mode on
    it. That one's owner scope is what stops a user reading another's work, and a "sometimes
    ignore the owner" flag would put the check and its exception in the same object — where the
    exception eventually wins an argument it should not be in.

    Still requires a signed-in caller: `liked_by_me` is a fact about *someone*, and the library
    is a feature of an account rather than a public page.
    """
    del current_user  # required for authentication, not for scoping — see the docstring
    return RotationLibraryRepository(session)


async def get_owned_sim_run_repo(
    session: DBSession, current_user: CurrentUser
) -> SimRunRepository:
    """FastAPI DI factory for a `SimRunRepository` scoped to the current user's cached runs.

    Owner-scoped deliberately: the browser produces these numbers, so a tampered client can
    submit whatever it likes and scoping the rows means it only poisons its own cache. See
    `app/models/sim_run.py` on why sharing runs between users is a separate feature with a
    separate threat model.
    """
    return SimRunRepository(session, owner_id=str(current_user.id))


