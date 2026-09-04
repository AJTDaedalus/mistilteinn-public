"""Unit tests for the three signup email bodies.

The `already_registered` assertions are the load-bearing ones: that message goes to an
address whose owner may not be the person who triggered it, so it must not disclose
anything about the account (`docs/DESIGN_open_registration.md` §5.3).
"""

from __future__ import annotations

import pytest

from app.services.email.templates import (
    already_registered,
    verified_welcome,
    verify_email,
)

_LINK = "https://mistilteinn.aetherus.dev/verify?token=abc123"
_TO = "user@example.com"


class TestVerifyEmail:
    def test_link_appears_in_both_parts(self) -> None:
        """A text/plain alternative that omits the link is a dead email for anyone
        reading in plain-text mode, and HTML-only mail scores worse with spam filters."""
        msg = verify_email(to=_TO, link=_LINK)
        assert _LINK in msg.text
        assert _LINK in msg.html

    def test_addressed_to_the_recipient(self) -> None:
        assert verify_email(to=_TO, link=_LINK).to == _TO

    def test_states_the_expiry_window(self) -> None:
        """A user who clicks a day-old link needs to know why it failed before they
        conclude the site is broken."""
        msg = verify_email(to=_TO, link=_LINK)
        assert "24 hours" in msg.text
        assert "24 hours" in msg.html

    def test_html_link_is_an_anchor_not_bare_text(self) -> None:
        assert f'href="{_LINK}"' in verify_email(to=_TO, link=_LINK).html


class TestAlreadyRegistered:
    """Goes to the *address owner*, who may not be whoever submitted the form."""

    def test_discloses_no_account_details(self) -> None:
        msg = already_registered(to=_TO)
        body = f"{msg.text}\n{msg.html}".lower()
        for leak in ("password_hash", "pending", "approved", "disabled", "label"):
            assert leak not in body, f"{leak!r} must not appear in this message"

    def test_carries_no_verification_link(self) -> None:
        """Sending a live verification link here would let anyone who knows an address
        mint a working credential into someone else's inbox."""
        msg = already_registered(to=_TO)
        assert "token=" not in msg.text
        assert "token=" not in msg.html

    def test_tells_the_owner_someone_tried(self) -> None:
        msg = already_registered(to=_TO)
        assert "did not" in msg.text.lower() or "wasn't you" in msg.text.lower()

    def test_points_at_sign_in_and_reset_routes(self) -> None:
        msg = already_registered(to=_TO)
        assert "/login" in msg.text
        assert "/login" in msg.html


class TestVerifiedWelcome:
    def test_addressed_and_non_empty(self) -> None:
        msg = verified_welcome(to=_TO)
        assert msg.to == _TO
        assert msg.subject
        assert msg.text.strip()
        assert msg.html.strip()


class TestAllTemplates:
    @pytest.mark.parametrize(
        "make",
        [
            lambda: verify_email(to=_TO, link=_LINK),
            lambda: already_registered(to=_TO),
            lambda: verified_welcome(to=_TO),
        ],
    )
    def test_both_parts_are_populated(self, make) -> None:
        msg = make()
        assert msg.text.strip()
        assert msg.html.strip()
        assert msg.subject.strip()
