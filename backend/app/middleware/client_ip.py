"""The client's real IP address, once, so every limiter agrees.

`DESIGN_open_registration.md` §2 (fairy's D-OR1). **This is the highest-value item in that
plan and it lands first**, because every IP-keyed defense is decorative until it exists.

## What was wrong

`_owner_key` and `_login_ip_key` both read `request.client.host`. In production the path is:

    browser → Cloudflare edge → cloudflared → nginx → uvicorn

`nginx.prod.conf` sets `X-Real-IP` and `X-Forwarded-For` correctly, but **uvicorn only honours
them when the immediate peer is a trusted proxy**, and the peer is the nginx container's
Docker address, not `127.0.0.1`. Neither compose file passed `--forwarded-allow-ips`. So
`request.client.host` was the nginx container's IP — *identical for every request on the
internet*.

The consequence is not "the limit is loose", it is worse than useless: login's `5/15minutes`
per-IP limit was five attempts per fifteen minutes **for the entire world**, locking out real
users while an attacker burns the same shared budget.

## Why `CF-Connecting-IP` first

Cloudflare **overwrites** that header at its edge, so unlike `X-Forwarded-For` a client cannot
forge it — anything the browser sends is replaced before it reaches us. nginx passes it through
untouched, because nginx only overrides the headers it names.

`X-Forwarded-For` is the fallback and is trusted only positionally: the **leftmost** entry is
the original client, and everything after it is a proxy chain that a client can pad. It is
still spoofable by a client talking directly to a badly-configured origin, which is why the
Cloudflare header is preferred and why `--forwarded-allow-ips *` is only safe while the backend
publishes no host port.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

#: What to key on when nothing identifies the caller.
#:
#: **Never sent to a third party as an IP.** Turnstile's `siteverify` rejects a malformed
#: `remoteip`, and register fails closed — so posting this sentinel would 403 a legitimate
#: signup. Fairy hit exactly that. Callers that forward an IP must check for it.
UNKNOWN = "unknown"


def get_client_ip(request: Request) -> str:
    """The caller's address: `CF-Connecting-IP`, then `X-Forwarded-For`, then the peer.

    One implementation, used by every limiter, so the resolution order cannot be right in
    one place and wrong in another.
    """
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    if cf:
        return cf

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Leftmost is the original client; the rest is the proxy chain.
        first = forwarded.split(",")[0].strip()
        if first:
            return first

    if request.client and request.client.host:
        return request.client.host
    return UNKNOWN
