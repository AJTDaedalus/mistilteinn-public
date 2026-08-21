"""Generic async repository with common CRUD operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models.base import Base

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository[T: Base]:
    """Base repository providing async CRUD for a SQLAlchemy model."""

    model: type[T]

    def __init__(self, session: AsyncSession, owner_id: str | None = None) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get_by_id(self, entity_id: str) -> T | None:
        """Fetch a single row by primary key, scoped to ``owner_id`` when set."""
        if self.owner_id is not None and hasattr(self.model, "owner_id"):
            stmt = select(self.model).where(
                self.model.id == entity_id,
                self.model.owner_id == self.owner_id,
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        return await self.session.get(self.model, entity_id)

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[T]:
        """List rows, paginated and scoped to ``owner_id`` when set."""
        stmt = select(self.model)
        if self.owner_id is not None and hasattr(self.model, "owner_id"):
            stmt = stmt.where(self.model.owner_id == self.owner_id)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """Row count for the model, scoped to ``owner_id`` when set.

        The owner filter here matters as much as the one on ``get_all``: this value is
        returned as ``total`` in the paginated list envelope. Unscoped it reported the
        whole table's row count next to one user's page of items — broken pagination and
        a cross-tenant count leak from an ordinary, correctly-written route handler.
        Inherited unscoped from fairy; caught in the Chunk A+B review.
        """
        stmt = select(func.count()).select_from(self.model)
        if self.owner_id is not None and hasattr(self.model, "owner_id"):
            stmt = stmt.where(self.model.owner_id == self.owner_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def create(self, data: dict[str, Any]) -> T:
        """Insert a new row, stamping ``owner_id`` onto owned models."""
        if self.owner_id is not None and hasattr(self.model, "owner_id"):
            data = {**data, "owner_id": self.owner_id}
        instance = self.model(**data)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, entity_id: str, data: dict[str, Any]) -> T | None:
        """Patch an existing row's fields; returns None if not found."""
        instance = await self.get_by_id(entity_id)
        if instance is None:
            return None
        for key, value in data.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, entity_id: str) -> bool:
        """Delete a row by ID; returns False if it didn't exist."""
        instance = await self.get_by_id(entity_id)
        if instance is None:
            return False
        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def get_by_filters(
        self,
        filters: dict[str, Any],
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[T]:
        """List rows matching an arbitrary equality filter dict, paginated."""
        stmt = select(self.model)
        for attr, value in filters.items():
            stmt = stmt.where(getattr(self.model, attr) == value)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
