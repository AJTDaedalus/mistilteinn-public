"""Common schema utilities — pagination wrapper."""

from pydantic import BaseModel


class PaginatedResponse[T](BaseModel):
    """Generic paginated list envelope shared by list endpoints."""

    items: list[T]
    total: int
    offset: int
    limit: int
