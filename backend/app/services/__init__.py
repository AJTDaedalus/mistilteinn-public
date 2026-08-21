"""Service layer — business logic for damage/anomaly calculation, buff resolution,
disc optimization/ranking, and combo simulation.

Per CLAUDE.md's layering (routes -> services -> repositories), this package sits
between `app/api/v1/` (thin route handlers) and `app/repositories/` (data access):
it owns all domain logic and never imports SQLAlchemy directly. Routes call into
services and get back Pydantic schemas / dataclasses, not ORM models.
"""
