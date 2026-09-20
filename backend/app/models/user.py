"""The account entity: credentials plus the admin-approval status gate for new signups."""

from __future__ import annotations

import datetime  # noqa: TC003 — SQLAlchemy resolves Mapped[datetime.datetime] at runtime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
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

    #: The character whose headshot stands in for this account, or null for nobody yet.
    #:
    #: **A foreign key, not the `UI_AvatarIcon_*` basename.** A stored basename is an
    #: unvalidated string that no constraint keeps true, and nanoka's art names have changed
    #: before — a stale one fails silently, because `CatalogueIcon` hides an image that 404s
    #: and a broken avatar is indistinguishable from no avatar. The key means the picture
    #: always comes from a real catalogue row.
    #:
    #: **`SET NULL`, where `builds.character_id` is `CASCADE`.** A build is *about* its
    #: character; an avatar is decoration on an account, and no `DELETE` against the
    #: catalogue may reach a user row. `DESIGN_user_avatar.md` §3.
    avatar_character_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="SET NULL"), nullable=True,
    )

    #: Mora this account says it holds, or null for "has not said".
    #:
    #: **The one planner quantity nobody can import.** No GOOD scanner reports a currency
    #: balance, so unlike every material it cannot come from an export — which is exactly why
    #: it is stored: it was retyped into every single plan request and thrown away.
    #:
    #: **Null is not zero**, and the planner depends on the difference: a plan that says you
    #: are three million short when you never said what you hold is a worse answer than one
    #: that says nothing. `PlanRead.mora.short` stays null while this is.
    #:
    #: On `users` rather than in `user_materials`, because it is not a material — a row there
    #: would be counted by `stock_is_empty`, which asks whether an inventory was ever
    #: imported, and a typed mora balance is not an imported inventory.
    #: `docs/DESIGN_planner_materials.md` §8 OQ-M1.
    mora: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
