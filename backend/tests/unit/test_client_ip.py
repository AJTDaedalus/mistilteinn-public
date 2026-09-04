"""The client's real IP, and the order the headers are trusted in.

`DESIGN_open_registration.md` §2. The defect this replaces was not "the limit is loose": with
`request.client.host` behind nginx, login's `5/15minutes` per-IP limit was five attempts per
fifteen minutes **for the entire internet** — it locked out real users while an attacker with
one address burned the same shared budget.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.middleware.client_ip import UNKNOWN, get_client_ip


def _request(headers: dict[str, str] | None = None, peer: str | None = None):
    """A stand-in carrying only what `get_client_ip` reads."""
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=peer) if peer else None,
    )


def test_cloudflares_header_wins() -> None:
    """Cloudflare **overwrites** it at the edge, so a client cannot forge it."""
    request = _request({"CF-Connecting-IP": "203.0.113.7"}, peer="172.18.0.5")

    assert get_client_ip(request) == "203.0.113.7"


def test_a_spoofed_forwarded_for_loses_to_cloudflare() -> None:
    """The whole reason for the ordering.

    `X-Forwarded-For` is client-settable; `CF-Connecting-IP` is not. Reversing these would
    let anyone choose their own rate-limit bucket, which is the same as having none.
    """
    request = _request(
        {"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4"},
        peer="172.18.0.5",
    )

    assert get_client_ip(request) == "203.0.113.7"


def test_forwarded_for_is_used_when_cloudflare_is_absent() -> None:
    request = _request({"X-Forwarded-For": "198.51.100.9"}, peer="172.18.0.5")

    assert get_client_ip(request) == "198.51.100.9"


def test_the_leftmost_forwarded_entry_is_the_client() -> None:
    """Everything after the first entry is a proxy chain a client can pad."""
    request = _request(
        {"X-Forwarded-For": "198.51.100.9, 172.18.0.5, 10.0.0.1"}, peer="172.18.0.5",
    )

    assert get_client_ip(request) == "198.51.100.9"


def test_it_falls_back_to_the_peer() -> None:
    """Local development, where there is no proxy at all."""
    request = _request({}, peer="127.0.0.1")

    assert get_client_ip(request) == "127.0.0.1"


def test_an_empty_header_does_not_win() -> None:
    """nginx can pass an empty header through; an empty string is not an address, and
    returning it would put every such caller in one bucket — the bug, restated."""
    request = _request({"CF-Connecting-IP": "", "X-Forwarded-For": "  "}, peer="127.0.0.1")

    assert get_client_ip(request) == "127.0.0.1"


def test_no_headers_and_no_peer_is_the_sentinel() -> None:
    assert get_client_ip(_request()) == UNKNOWN


def test_the_sentinel_is_not_an_ip_shaped_string() -> None:
    """It is forwarded to Turnstile's `siteverify`, which rejects a malformed `remoteip` —
    and register fails closed, so sending it would 403 a legitimate signup. Callers must be
    able to recognise it; a plausible-looking default would hide that."""
    assert UNKNOWN == "unknown"
