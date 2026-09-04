"""The account entity: credentials plus the admin-approval status gate for new signups."""

from __future__ import annotations

import datetime  # noqa: TC003 — SQLAlchemy resolves Mapped[datetime.datetime] at runtime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import UserStatus
from app.services.email_policy import normalize


class User(TimestampMixin, Base):
    """Authenticated user — email/password, admin-approval flow."""

    __tablename__ = "users"

    id: Mapped[uuid_pk]
    #: When this user last replaced their inventory from a GOOD export.
    #:
    #: A GOOD import replaces an inventory wholesale, so this is what tells a user whether a
    #: saved optimization result predates their last farming session — the commonest reason a
    #: stored number stops being true. Null until they have imported once.
    gear_imported_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    #: The uniqueness key. `email` keeps the address exactly as typed (and is what we send
    #: to); this folds case everywhere and Gmail's dots and plus-addressing, so one inbox
    #: cannot mint unlimited accounts and bypass every per-email rate limit by adding a dot.
    #: `DESIGN_open_registration.md` §2 (D-OR6).
    #:
    #: **Never assign this directly** — `_derive_email_normalized` keeps it in step with
    #: `email`. It is a derived value, and a unique column with a writable default is a trap:
    #: every call site that forgot it would share one key and collide on the second row, which
    #: is exactly what happened when fairy shipped this with `default=""`.
    email_normalized: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True, default="",
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, 16), nullable=False, default=UserStatus.PENDING,
    )
    #: When this address was proven reachable.
    #:
    #: **A nullable column, not a fourth `UserStatus`.** Verification and approval are
    #: independent facts — "this address is real" and "this account may use the app" — and
    #: every authorization check in the codebase is a `status == APPROVED` comparison. A
    #: fourth enum value would force an audit of every one of those, and the failure mode of
    #: missing one is a privilege check that silently passes. A timestamp adds the fact
    #: without touching a single existing branch, and records *when*, which an enum cannot.
    #:
    #: `DESIGN_open_registration.md` §4.
    email_verified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    approved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_users_status", "status"),)

    @validates("email")
    def _derive_email_normalized(self, _key: str, email: str) -> str:
        """Keep `email_normalized` in step with `email` on every assignment.

        **Derived in the model rather than at each call site**, which makes the invariant
        structural: repositories, migrations, scripts, factories and tests all get a correct
        key without knowing this field exists, and no future code path can create a `User`
        that collides on an empty one.
        """
        self.email_normalized = normalize(email) if email else ""
        return email

    def __repr__(self) -> str:
        return f"<User {self.email} [{self.status}]>"
