"""Unit tests for the EmailSender protocol's dev/test implementations.

`ConsoleEmailSender` is the default (`EMAIL_PROVIDER=console`) so a fresh clone can run
the whole signup flow with no API key and no network, and `RecordingEmailSender` is what
every test asserts against. Neither may touch the network — see
`docs/DESIGN_open_registration.md` §5.4 (D-OR4).
"""

from __future__ import annotations

import pytest

from app.services.email import (
    ConsoleEmailSender,
    EmailMessage,
    EmailSender,
    EmailSendError,
    RecordingEmailSender,
)


def _msg(to: str = "user@example.com") -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Verify your Mistilteinn account",
        text="Open https://mistilteinn.aetherus.dev/verify?token=abc",
        html='<a href="https://mistilteinn.aetherus.dev/verify?token=abc">Verify</a>',
    )


class TestProtocolConformance:
    def test_both_implementations_satisfy_the_protocol(self) -> None:
        """`EmailSender` is runtime-checkable so DI can assert on it, not just type-check."""
        assert isinstance(ConsoleEmailSender(), EmailSender)
        assert isinstance(RecordingEmailSender(), EmailSender)


class TestConsoleEmailSender:
    @pytest.mark.asyncio
    async def test_prints_recipient_subject_and_body(self, capsys) -> None:
        await ConsoleEmailSender().send(_msg())
        out = capsys.readouterr().out
        assert "user@example.com" in out
        assert "Verify your Mistilteinn account" in out
        assert "https://mistilteinn.aetherus.dev/verify?token=abc" in out

    @pytest.mark.asyncio
    async def test_prints_the_text_part_not_the_html(self, capsys) -> None:
        """The console exists so a developer can click the link, not read markup."""
        await ConsoleEmailSender().send(_msg())
        out = capsys.readouterr().out
        assert "<a href=" not in out


class TestRecordingEmailSender:
    @pytest.mark.asyncio
    async def test_captures_messages_in_order(self) -> None:
        sender = RecordingEmailSender()
        await sender.send(_msg("first@example.com"))
        await sender.send(_msg("second@example.com"))

        assert [m.to for m in sender.sent] == ["first@example.com", "second@example.com"]

    @pytest.mark.asyncio
    async def test_prints_nothing(self, capsys) -> None:
        await RecordingEmailSender().send(_msg())
        assert capsys.readouterr().out == ""

    @pytest.mark.asyncio
    async def test_last_returns_none_before_any_send(self) -> None:
        assert RecordingEmailSender().last() is None

    @pytest.mark.asyncio
    async def test_last_returns_the_most_recent_message(self) -> None:
        sender = RecordingEmailSender()
        await sender.send(_msg("first@example.com"))
        await sender.send(_msg("second@example.com"))
        assert sender.last() is not None
        assert sender.last().to == "second@example.com"

    @pytest.mark.asyncio
    async def test_can_be_armed_to_raise(self) -> None:
        """Registration must survive a provider outage (DESIGN §5.4).

        Task 14 asserts a raising sender still yields 202, so the fake needs a way to
        fail on demand rather than that path being untestable.
        """
        sender = RecordingEmailSender(fail_with=EmailSendError("provider down"))
        with pytest.raises(EmailSendError):
            await sender.send(_msg())
        assert sender.sent == []


class TestGetEmailSender:
    """Provider selection. `console` is the default so tests and clones need no key."""

    def _sender_for(self, monkeypatch, **overrides):
        from app.config import Settings
        from app.services.email import factory

        monkeypatch.setattr(factory, "settings", Settings(**overrides))
        factory.get_email_sender.cache_clear()
        try:
            return factory.get_email_sender()
        finally:
            factory.get_email_sender.cache_clear()

    def test_defaults_to_console(self, monkeypatch) -> None:
        assert isinstance(self._sender_for(monkeypatch), ConsoleEmailSender)

    def test_resend_selected_when_configured(self, monkeypatch) -> None:
        from app.services.email.resend import ResendEmailSender

        sender = self._sender_for(
            monkeypatch,
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="re_test_key",
            EMAIL_FROM="Mistilteinn <noreply@mistilteinn.aetherus.dev>",
        )
        assert isinstance(sender, ResendEmailSender)

    def test_unknown_provider_raises_rather_than_falling_back(self, monkeypatch) -> None:
        """A typo in the production env must be loud.

        Falling back to console would mean every verification email becomes a line in
        the container log: signups appear to work, nobody receives anything, and no
        check goes red.
        """
        with pytest.raises(ValueError, match="not recognised"):
            self._sender_for(monkeypatch, EMAIL_PROVIDER="sendgird")

    def test_resend_without_a_key_raises_at_selection(self, monkeypatch) -> None:
        with pytest.raises(ValueError, match="RESEND_API_KEY"):
            self._sender_for(monkeypatch, EMAIL_PROVIDER="resend")
