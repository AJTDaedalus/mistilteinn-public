"""Address hygiene: normalization for uniqueness, and the disposable-domain gate.

`docs/DESIGN_open_registration.md` §5.5 Layer 5 (D-OR6).
"""

from __future__ import annotations

import json
import pathlib
from functools import lru_cache

_BLOCKLIST_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "data/validation/disposable_email_domains.json"
)

# Gmail is dot-insensitive and strips everything after `+`. That is a documented Gmail
# behaviour, NOT a standard — applying it to arbitrary domains would merge addresses at
# other providers that are genuinely distinct people.
_DOT_INSENSITIVE_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
_GMAIL_CANONICAL = "gmail.com"


@lru_cache(maxsize=1)
def _disposable_domains() -> frozenset[str]:
    """Load the committed snapshot once. Never fetched at request time."""
    return frozenset(json.loads(_BLOCKLIST_PATH.read_text())["domains"])


def split_domain(email: str) -> str:
    """Return the lowercased domain part of *email*, or "" if it has none.

    The separator is checked rather than the tail: `rpartition` on a string with no `@`
    returns the whole string as the tail, so a bare word would otherwise be reported as
    its own domain — and then matched against the blocklist.
    """
    _, at, domain = email.strip().rpartition("@")
    return domain.strip().lower() if at else ""


def is_disposable(email: str) -> bool:
    """True if *email* is at a known throwaway provider."""
    domain = split_domain(email)
    return bool(domain) and domain in _disposable_domains()


def normalize(email: str) -> str:
    """Return the uniqueness key for *email*.

    Lowercased for every domain; for Gmail only, dots are stripped from the local part
    and everything from `+` onwards is discarded, and `googlemail.com` folds to
    `gmail.com`.

    Without this, `a.b@gmail.com`, `ab@gmail.com` and `ab+1@gmail.com` are three accounts
    on one inbox, and every per-email rate limit is bypassed by typing a dot.

    The account keeps the address exactly as typed — this is the *uniqueness key* only,
    and mail is still sent to the original. The accepted cost is that one Gmail inbox
    cannot hold two Mistilteinn accounts.
    """
    cleaned = email.strip().lower()
    local, at, domain = cleaned.rpartition("@")
    if not at:
        return cleaned
    if domain in _DOT_INSENSITIVE_DOMAINS:
        local = local.partition("+")[0].replace(".", "")
        domain = _GMAIL_CANONICAL
    return f"{local}@{domain}"
