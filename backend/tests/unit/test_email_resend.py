"""Unit tests for `ResendEmailSender`.

Every request is served by `httpx.MockTransport` — this suite makes no network call,
which is a hard rule for the whole open-registration feature
(`docs/DESIGN_open_registration.md` §5.4, D-OR4).
"""

from __future__ import annotations

import httpx
import pytest

from app.services.email import EmailMessage, EmailSender, EmailSendError
from app.services.email.resend import ResendEmailSender

_MSG = EmailMessage(
    to="user@example.com",
    subject="Verify your Mistilteinn account",
    text="Open https://mistilteinn.aetherus.dev/verify?token=abc",
    html='<a href="https://mistilteinn.aetherus.dev/verify?token=abc">Verify</a>',
)


def _sender(handler) -> ResendEmailSender:
    return ResendEmailSender(
        api_key="re_test_key",
        from_address="Mistilteinn <noreply@mistilteinn.aetherus.dev>",
        transport=httpx.MockTransport(handler),
    )


class TestConformance:
    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(_sender(lambda r: httpx.Response(200, json={"id": "x"})), EmailSender)


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_posts_both_parts_and_the_bearer_key(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization")
            seen["body"] = __import__("json").loads(request.content)
            return httpx.Response(200, json={"id": "abc-123"})

        await _sender(handler).send(_MSG)

        assert seen["url"] == "https://api.resend.com/emails"
        assert seen["auth"] == "Bearer re_test_key"
        assert seen["body"]["to"] == ["user@example.com"]
        assert seen["body"]["from"] == "Mistilteinn <noreply@mistilteinn.aetherus.dev>"
        assert seen["body"]["subject"] == _MSG.subject
        assert seen["body"]["text"] == _MSG.text
        assert seen["body"]["html"] == _MSG.html


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_retries_once_on_5xx_then_succeeds(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="upstream unavailable")
            return httpx.Response(200, json={"id": "abc-123"})

        await _sender(handler).send(_MSG)
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_the_retry_reuses_the_original_idempotency_key(self) -> None:
        """A 5xx does not mean the message was not sent.

        It can equally mean the provider accepted it and the response was lost, so a
        bare retry risks delivering the same verification email twice. Resend
        deduplicates on this header — but only if the retry carries the same value,
        which is exactly the thing a future refactor could break invisibly.
        """
        keys: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers.get("Idempotency-Key"))
            if len(keys) == 1:
                return httpx.Response(503, text="upstream unavailable")
            return httpx.Response(200, json={"id": "abc-123"})

        await _sender(handler).send(_MSG)

        assert len(keys) == 2
        assert keys[0] is not None
        assert keys[0] == keys[1]

    @pytest.mark.asyncio
    async def test_separate_sends_get_separate_keys(self) -> None:
        """Deduplication must not swallow a genuine second email to the same person."""
        keys: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers.get("Idempotency-Key"))
            return httpx.Response(200, json={"id": "abc-123"})

        sender = _sender(handler)
        await sender.send(_MSG)
        await sender.send(_MSG)

        assert keys[0] != keys[1]

    @pytest.mark.asyncio
    async def test_raises_after_the_retry_also_5xxs(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(500, text="boom")

        with pytest.raises(EmailSendError):
            await _sender(handler).send(_MSG)
        assert calls["n"] == 2, "one retry, not an unbounded loop"

    @pytest.mark.asyncio
    async def test_does_not_retry_a_4xx(self) -> None:
        """A rejected key or a malformed address will be rejected again identically.

        Retrying it wastes the caller's time and doubles the rate a bad key burns the
        provider's own limits.
        """
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(422, json={"message": "invalid to address"})

        with pytest.raises(EmailSendError):
            await _sender(handler).send(_MSG)
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_transport_error_raises_email_send_error_not_httpx_error(self) -> None:
        """Callers catch one exception type; an httpx error escaping the seam defeats it."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with pytest.raises(EmailSendError):
            await _sender(handler).send(_MSG)


class TestConfiguration:
    def test_refuses_to_construct_without_an_api_key(self) -> None:
        """Fail at construction, not at the first signup.

        A blank key would otherwise surface as a 401 from the provider on the first
        real registration, long after the misconfiguration was introduced.
        """
        with pytest.raises(ValueError, match="RESEND_API_KEY"):
            ResendEmailSender(api_key="", from_address="a@b.com")

    def test_refuses_to_construct_without_a_from_address(self) -> None:
        with pytest.raises(ValueError, match="EMAIL_FROM"):
            ResendEmailSender(api_key="re_test_key", from_address="")
