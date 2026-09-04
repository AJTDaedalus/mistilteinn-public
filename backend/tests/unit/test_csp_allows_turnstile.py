"""The CSP lets Turnstile load — in **both** copies.

`DESIGN_open_registration.md` §3.4. `nginx.prod.conf` writes its Content-Security-Policy
twice: once at server level and once inside a location block. Amending one and not the other
leaves the widget working on some paths and silently dead on others, which is the hardest
version of this bug to notice — a CSP violation is a console message on a page that otherwise
renders fine, and the visible symptom is "the CAPTCHA never appeared".

There is no test that could catch it in the SPA, because dev has no nginx at all. So this
reads the file.
"""

from __future__ import annotations

import re
from pathlib import Path

NGINX = Path(__file__).resolve().parents[3] / "frontend" / "nginx.prod.conf"

TURNSTILE = "https://challenges.cloudflare.com"


def _policies() -> list[str]:
    return re.findall(r"Content-Security-Policy\s+\"([^\"]+)\"", NGINX.read_text())


def test_the_policy_really_is_written_more_than_once() -> None:
    """Guards the guard. If nginx.prod.conf were ever restructured to one policy, the
    assertions below would still pass while silently checking half of what they claim to."""
    assert len(_policies()) >= 2


def test_every_copy_allows_the_turnstile_script() -> None:
    for policy in _policies():
        assert TURNSTILE in policy, f"script-src missing Turnstile in: {policy[:80]}…"


def test_every_copy_allows_the_turnstile_frame() -> None:
    """`script-src` alone is not enough — the widget renders in an iframe, and a missing
    `frame-src` fails *after* the script loads, which looks like a different bug."""
    for policy in _policies():
        frame = re.search(r"frame-src ([^;]+);", policy)
        assert frame is not None, f"no frame-src at all in: {policy[:80]}…"
        assert TURNSTILE in frame.group(1)


def test_the_wasm_exception_survived() -> None:
    """gcsim is compiled to wasm and runs in the browser; dropping `wasm-unsafe-eval` while
    editing this line would break every search on the site."""
    for policy in _policies():
        assert "'wasm-unsafe-eval'" in policy
