"""Integration tests for SessionRepository."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.session import SessionRepository


@pytest.fixture
async def user(db_session):
    u = User(
        email=f"sesstest_{secrets.token_hex(4)}@example.com",
        label="Session Test User",
        password_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        status=UserStatus.APPROVED,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.fixture
async def repo(db_session):
    return SessionRepository(db_session)


@pytest.fixture
async def raw_token():
    return secrets.token_hex(32)


@pytest.fixture
async def session(repo, user, raw_token):
    return await repo.create_for_user(user.id, raw_token, ttl_seconds=3600)


class TestCreateForUser:
    async def test_creates_session(self, session, user, raw_token):
        assert session.id is not None
        assert session.user_id == user.id

    async def test_hashes_token(self, session, raw_token):
        expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        assert session.token_hash == expected_hash

    async def test_sets_expires_at(self, session):
        now = datetime.now(UTC)
        assert session.expires_at > now
        assert session.expires_at < now + timedelta(seconds=7200)

    async def test_sets_last_used_at(self, session):
        now = datetime.now(UTC)
        assert session.last_used_at <= now
        assert session.last_used_at > now - timedelta(seconds=5)


class TestGetByTokenHash:
    async def test_finds_existing_session(self, repo, session, raw_token):
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        found = await repo.get_by_token_hash(token_hash)
        assert found is not None
        assert found.id == session.id

    async def test_returns_none_for_unknown_hash(self, repo):
        found = await repo.get_by_token_hash("a" * 64)
        assert found is None


class TestTouch:
    async def test_updates_last_used_at(self, repo, session, db_session):
        # Set last_used_at to a known past time so touch() moves it forward
        past = datetime.now(UTC) - timedelta(seconds=60)
        session.last_used_at = past
        await db_session.flush()

        before_touch = datetime.now(UTC)
        await repo.touch(session)

        await db_session.refresh(session)
        assert session.last_used_at >= before_touch


class TestDeleteByTokenHash:
    async def test_deletes_existing_session(self, repo, session, raw_token):
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        deleted = await repo.delete_by_token_hash(token_hash)
        assert deleted is True
        assert await repo.get_by_token_hash(token_hash) is None

    async def test_returns_false_for_unknown_hash(self, repo):
        deleted = await repo.delete_by_token_hash("b" * 64)
        assert deleted is False


class TestDeleteExpired:
    async def test_deletes_expired_sessions(self, repo, user):
        past = datetime.now(UTC) - timedelta(hours=1)
        await repo.create(
            {
                "user_id": user.id,
                "token_hash": hashlib.sha256(b"expired1").hexdigest(),
                "expires_at": past,
                "last_used_at": past,
            }
        )
        await repo.create(
            {
                "user_id": user.id,
                "token_hash": hashlib.sha256(b"expired2").hexdigest(),
                "expires_at": past,
                "last_used_at": past,
            }
        )

        count = await repo.delete_expired()
        assert count == 2

    async def test_keeps_active_sessions(self, repo, session):
        count = await repo.delete_expired()
        assert count == 0
        found = await repo.get_by_id(session.id)
        assert found is not None

    async def test_returns_row_count(self, repo, user):
        past = datetime.now(UTC) - timedelta(hours=2)
        for i in range(3):
            await repo.create(
                {
                    "user_id": user.id,
                    "token_hash": hashlib.sha256(f"exp{i}".encode()).hexdigest(),
                    "expires_at": past,
                    "last_used_at": past,
                }
            )
        count = await repo.delete_expired()
        assert count == 3

    async def test_custom_now_cutoff(self, repo, user):
        future_expiry = datetime.now(UTC) + timedelta(hours=1)
        await repo.create(
            {
                "user_id": user.id,
                "token_hash": hashlib.sha256(b"future_session").hexdigest(),
                "expires_at": future_expiry,
                "last_used_at": datetime.now(UTC),
            }
        )
        # Passing a now in the far future treats active sessions as expired
        far_future = datetime.now(UTC) + timedelta(days=365)
        count = await repo.delete_expired(now=far_future)
        assert count >= 1
