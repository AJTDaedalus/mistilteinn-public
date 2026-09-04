"""One structured line per signup event.

Defences you cannot see are defences you cannot tune. The numbers in
`docs/DESIGN_open_registration.md` §5.5 and §6 are judgement calls until there is real
traffic to check them against, and the response to an attack ("flip
`AUTO_APPROVE_ON_VERIFY` off") depends on noticing one.

**Never log a full email address.** The domain is what characterises an attack — a wave of
signups from one throwaway provider, or one IP — and the local part adds nothing to that
while turning any log leak into a PII incident. `tests/integration/test_signup_logging.py`
asserts this rather than trusting it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("mistilteinn.signup")

# Event names. Kept as constants so `scripts/signup_report.py` and the log lines cannot
# drift apart.
REGISTER_ACCEPTED = "register.accepted"
REGISTER_EXISTING = "register.existing"
REGISTER_HONEYPOT = "register.honeypot"
REGISTER_CAPTCHA_FAILED = "register.captcha_failed"
REGISTER_DISPOSABLE = "register.disposable_domain"
REGISTER_CLOSED = "register.closed"
REGISTER_FAILED = "register.failed"
VERIFY_OK = "verify.ok"
VERIFY_FAILED = "verify.failed"
RESEND_REQUESTED = "resend.requested"
FORGOT_REQUESTED = "forgot.requested"
RESET_OK = "reset.ok"
RESET_FAILED = "reset.failed"
EMAIL_SEND_FAILED = "email.send_failed"


def domain_of(email: str) -> str:
    """The domain part of *email*, lowercased — the only part safe to log."""
    _, at, domain = email.strip().rpartition("@")
    return domain.strip().lower() if at else "unknown"


def signup_event(event: str, *, ip: str = "-", email: str = "", **fields: object) -> None:
    """Emit one `key=value` line for *event*.

    key=value rather than JSON because these are read with `grep` and `awk` on a box with
    no log aggregator; `scripts/signup_report.py` parses the same shape.
    """
    parts = [f"event={event}", f"ip={ip}", f"domain={domain_of(email) if email else '-'}"]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    logger.info(" ".join(parts))
