"""Unit tests for address normalization and the disposable-domain gate.

The non-Gmail assertions are the load-bearing ones: over-normalizing merges two real
people's accounts, which is a much worse failure than letting a duplicate signup through.
"""

from __future__ import annotations

import pytest

from app.services.email_policy import is_disposable, normalize, split_domain


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("USER@Example.COM", "user@example.com"),
            ("  user@example.com  ", "user@example.com"),
        ],
    )
    def test_case_and_whitespace_folded_for_every_domain(self, raw, expected) -> None:
        assert normalize(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "a.b@gmail.com",
            "ab@gmail.com",
            "a.b+mist@gmail.com",
            "A.B@GoogleMail.com",
            "a...b@googlemail.com",
        ],
    )
    def test_every_gmail_alias_collapses_to_one_key(self, raw) -> None:
        """One inbox, one account — otherwise a dot buys another signup."""
        assert normalize(raw) == "ab@gmail.com"

    def test_dots_are_preserved_at_other_providers(self) -> None:
        """The regression that would silently merge two real users.

        Dot-insensitivity is a Gmail behaviour, not a standard. `a.b@fastmail.com` and
        `ab@fastmail.com` can be different people.
        """
        assert normalize("a.b@fastmail.com") != normalize("ab@fastmail.com")

    def test_plus_addressing_is_preserved_at_other_providers(self) -> None:
        assert normalize("user+mist@fastmail.com") == "user+mist@fastmail.com"

    def test_a_plus_in_a_gmail_address_does_not_eat_the_domain(self) -> None:
        assert normalize("user+a@b.com@gmail.com").endswith("@gmail.com")

    def test_handles_a_string_with_no_at_sign_without_raising(self) -> None:
        assert normalize("not-an-email") == "not-an-email"


class TestSplitDomain:
    def test_returns_the_lowercased_domain(self) -> None:
        assert split_domain("User@Example.COM") == "example.com"

    def test_returns_empty_for_a_bare_string(self) -> None:
        assert split_domain("nope") == ""


class TestIsDisposable:
    def test_rejects_a_known_throwaway_provider(self) -> None:
        assert is_disposable("bot@mailinator.com")

    def test_is_case_insensitive(self) -> None:
        assert is_disposable("bot@MAILINATOR.com")

    @pytest.mark.parametrize(
        "email",
        ["real@gmail.com", "real@fastmail.com", "real@proton.me", "real@aetherus.dev"],
    )
    def test_accepts_real_providers(self, email) -> None:
        assert not is_disposable(email)

    def test_a_bare_string_is_not_disposable(self) -> None:
        """Malformed input is Pydantic's problem; this gate must not claim it as a hit."""
        assert not is_disposable("nope")


class TestModelDerivesTheKey:
    """`User.email_normalized` must never be settable-and-forgotten.

    It shipped briefly as a unique column with `default=""`, so every call site that did
    not set it shared one key and the second row collided. Deriving it in the model makes
    the invariant structural rather than a rule each caller has to remember.
    """

    def test_assigning_email_sets_the_normalized_key(self) -> None:
        from app.models.user import User

        user = User(email="A.B+tag@GMail.com", password_hash="x")  # noqa: S106
        assert user.email_normalized == "ab@gmail.com"

    def test_reassigning_email_updates_the_key(self) -> None:
        from app.models.user import User

        user = User(email="first@example.com", password_hash="x")  # noqa: S106
        user.email = "second@example.com"
        assert user.email_normalized == "second@example.com"

    def test_two_users_with_different_addresses_do_not_share_a_key(self) -> None:
        from app.models.user import User

        a = User(email="alice@example.com", password_hash="x")  # noqa: S106
        b = User(email="bob@example.com", password_hash="x")  # noqa: S106
        assert a.email_normalized != b.email_normalized
