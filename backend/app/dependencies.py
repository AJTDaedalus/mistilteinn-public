"""Dependency injection factories for repositories."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from app.services.job_runner import JobRunner
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.artifact import ArtifactRepository
from app.repositories.artifact_set import ArtifactSetRepository
from app.repositories.build import BuildRepository
from app.repositories.character import CharacterRepository
from app.repositories.enemy import EnemyProfileRepository
from app.repositories.optimization_job import OptimizationJobRepository
from app.repositories.session import SessionRepository
from app.repositories.team import TeamRepository
from app.repositories.user import UserRepository
from app.repositories.weapon import WeaponRepository

DBSession = Annotated[AsyncSession, Depends(get_db)]

# ── Public (no auth) repo factories ──────────────────────────────────────────
#
# G.6 restores the four catalogue factories above. The rest are still absent:
#
# TODO(chunk-F/G): B.7 removed the factories for every deleted repository —
# get_agent_repo, get_attack_repo, get_w_engine_repo, get_disc_set_repo,
# get_disc_repo, get_build_repo, get_combo_repo, get_enemy_repo, and the owned
# variants get_owned_build_repo / get_owned_disc_repo / get_owned_combo_repo /
# get_owned_buff_preset_repo. Each comes back with the route that needs it, not
# before: an injectable for a repository nothing calls is dead wiring.
#
# Chunk D is done and added none of them: it seeds the catalogue but exposes nothing over
# HTTP, so the read surface — and its factories — is G.6's.


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


async def get_optimization_job_repo(session: DBSession) -> OptimizationJobRepository:
    """FastAPI DI factory for `OptimizationJobRepository` (unscoped — see the owned variant)."""
    return OptimizationJobRepository(session)


def get_job_runner(request: Request) -> JobRunner:
    """Return the app-wide `JobRunner` stashed on `app.state` at startup."""
    return request.app.state.job_runner


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


async def get_owned_build_repo(
    session: DBSession, current_user: CurrentUser
) -> BuildRepository:
    """FastAPI DI factory for a `BuildRepository` scoped to the current user's builds."""
    return BuildRepository(session, owner_id=str(current_user.id))


async def get_owned_optimization_job_repo(
    session: DBSession, current_user: CurrentUser
) -> OptimizationJobRepository:
    """FastAPI DI factory for an `OptimizationJobRepository` scoped to the current user's rows."""
    return OptimizationJobRepository(session, owner_id=str(current_user.id))
