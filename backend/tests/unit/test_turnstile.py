"""Unit tests for the Cloudflare Turnstile verifier.

Mocked transport only — no network, per D-OR4. The three-field check
(`success` + `hostname` + `action`) is the substance here: verifying only `success` is
the standard bypass, because a token minted by the same widget on any other page still
reports success. See `docs/DESIGN_open_registration.md` §5.5 Layer 2.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.turnstile import TurnstileVerifier

_SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_HOSTNAME = "mistilteinn.aetherus.dev"
_ACTION = "register"
# Cloudflare's documented always-passes test key; not a credential.
_TEST_SECRET = "1x00000000000000000000AA"  # noqa: S105


def _ok_body(**overrides) -> dict:
    body = {
        "success": True,
        "hostname": _HOSTNAME,
        "action": _ACTION,
        "challenge_ts": "2026-08-28T10:00:00.000Z",
        "error-codes": [],
    }
    body.update(overrides)
    return body


def _verifier(handler, *, secret: str = _TEST_SECRET, hostname: str = _HOSTNAME):
    return TurnstileVerifier(
        secret_key=secret,
        expected_hostname=hostname,
        transport=httpx.MockTransport(handler),
    )


def _responds(body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return handler


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_accepts_a_token_matching_hostname_and_action(self) -> None:
        assert await _verifier(_responds(_ok_body())).verify("tok", action=_ACTION)

    @pytest.mark.asyncio
    async def test_posts_secret_response_and_a_uuid_idempotency_key(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_body())

        await _verifier(handler).verify("tok-abc", action=_ACTION, remote_ip="203.0.113.9")

        assert seen["url"] == _SITEVERIFY
        assert seen["body"]["secret"] == _TEST_SECRET
        assert seen["body"]["response"] == "tok-abc"
        assert seen["body"]["remoteip"] == "203.0.113.9"
        # Cloudflare requires a UUID here; anything else is rejected as malformed.
        assert len(seen["body"]["idempotency_key"]) == 36


class TestRejection:
    @pytest.mark.asyncio
    async def test_rejects_when_success_is_false(self) -> None:
        body = _ok_body(success=False)
        body["error-codes"] = ["invalid-input-response"]
        assert not await _verifier(_responds(body)).verify("tok", action=_ACTION)

    @pytest.mark.asyncio
    async def test_rejects_a_token_minted_on_another_host(self) -> None:
        """The standard bypass: a token from the same widget embedded elsewhere.

        `success` is true for it — only the hostname distinguishes it from a real one.
        """
        body = _ok_body(hostname="evil.example.com")
        assert not await _verifier(_responds(body)).verify("tok", action=_ACTION)

    @pytest.mark.asyncio
    async def test_rejects_a_token_minted_for_another_action(self) -> None:
        """A token solved on the login form must not be replayable at registration."""
        body = _ok_body(action="login")
        assert not await _verifier(_responds(body)).verify("tok", action=_ACTION)

    @pytest.mark.asyncio
    async def test_rejects_an_empty_token_without_calling_the_api(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=_ok_body())

        assert not await _verifier(handler).verify("", action=_ACTION)
        assert calls["n"] == 0


class TestFailureModes:
    @pytest.mark.asyncio
    async def test_transport_error_fails_closed(self) -> None:
        """Registration is not time-critical; an open door during an outage is worse.

        An attacker picks the moment, and a vendor outage is exactly the moment they
        would pick. Login stays fail-open — that trade runs the other way.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        assert not await _verifier(handler).verify("tok", action=_ACTION)

    @pytest.mark.asyncio
    async def test_non_200_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        assert not await _verifier(handler).verify("tok", action=_ACTION)

    @pytest.mark.asyncio
    async def test_malformed_json_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        assert not await _verifier(handler).verify("tok", action=_ACTION)


class TestConfiguration:
    @pytest.mark.asyncio
    async def test_empty_secret_skips_verification_entirely(self) -> None:
        """Local dev and every test run with no key and no network."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=_ok_body())

        verifier = _verifier(handler, secret="")
        assert await verifier.verify("", action=_ACTION)
        assert calls["n"] == 0

    @pytest.mark.asyncio
    async def test_blank_expected_hostname_skips_the_hostname_check(self) -> None:
        """Dev serves on localhost and preview deploys get generated hostnames.

        Production sets TURNSTILE_EXPECTED_HOSTNAME; leaving it blank there is the
        misconfiguration, and it is called out at the setting.
        """
        body = _ok_body(hostname="localhost")
        assert await _verifier(_responds(body), hostname="").verify("tok", action=_ACTION)


class TestRemoteIp:
    """`remoteip` is optional; a malformed value is worse than an absent one.

    `get_client_ip` returns the sentinel "unknown" when there is no proxy header and no
    peer address. Register fails CLOSED, so a Cloudflare rejection of a malformed
    `remoteip` would turn that sentinel into a 403 on a legitimate signup.
    """

    @pytest.mark.asyncio
    async def test_a_real_address_is_forwarded(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_ok_body())

        await _verifier(handler).verify("tok", action=_ACTION, remote_ip="203.0.113.9")
        assert seen["remoteip"] == "203.0.113.9"

    @pytest.mark.asyncio
    async def test_an_ipv6_address_is_forwarded(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_ok_body())

        await _verifier(handler).verify("tok", action=_ACTION, remote_ip="2001:db8::1")
        assert seen["remoteip"] == "2001:db8::1"

    @pytest.mark.asyncio
    async def test_the_unknown_sentinel_is_omitted_not_sent(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_ok_body())

        assert await _verifier(handler).verify("tok", action=_ACTION, remote_ip="unknown")
        assert "remoteip" not in seen
