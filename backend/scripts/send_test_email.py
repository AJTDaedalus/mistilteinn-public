"""Send one real email through the configured provider, and say what happened.

    cd backend && python -m scripts.send_test_email you@example.com

**This exists because the alternative is testing mail by registering an account.** That path
answers `202` whether the send worked or not — deliberately, so a provider outage does not fail
a signup whose row was already written — so it cannot tell you whether delivery works. Every
other check in this feature is offline by design; this is the one that is meant to touch the
network, run by hand, when a human is watching.

What it proves, in order:

1. the settings actually reached this process (`EMAIL_PROVIDER`, the key, `PUBLIC_BASE_URL`);
2. the provider accepted the message;
3. — and only you can check this one — **it arrived in an inbox rather than spam**.

Point 3 is the whole reason Resend was chosen over self-hosted SMTP, and it is not something a
program can assert. A verification mail in spam is indistinguishable from a broken signup flow:
the user never tells you, they just leave. `docs/DEPLOY.md` §4a has the SPF/DKIM/DMARC steps.

The body is a **real verification email** with a fake token rather than a "test" message,
because how it renders and where it lands are what is being tested. Its link goes nowhere: the
token is not in the database, so following it answers `invalid`.
"""

from __future__ import annotations

import asyncio
import sys

from app.config import settings
from app.services.email.factory import get_email_sender
from app.services.email.templates import verify_email
from app.services.email_preflight import check_production_email

_FAKE_TOKEN = "this-token-is-not-real-and-will-report-invalid"  # noqa: S105 — deliberately so


async def _send(recipient: str) -> int:
    link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/verify?token={_FAKE_TOKEN}"

    print(f"provider     {settings.EMAIL_PROVIDER}")
    print(f"from         {settings.EMAIL_FROM or '(unset)'}")
    print(f"base url     {settings.PUBLIC_BASE_URL}")
    print(f"to           {recipient}")

    # The same checks a production boot makes, reported here rather than raised: this script is
    # how someone finds out *before* deploying, and refusing to run would hide the reason.
    for problem in check_production_email(settings):
        print(f"  ! {problem}")
    print()

    try:
        sender = get_email_sender()
    except ValueError as exc:
        print(f"FAILED to build the sender: {exc}")
        return 1

    try:
        await sender.send(verify_email(to=recipient, link=link))
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("The provider accepted it.")
    print()
    print("**That is not the same as delivered.** Check the inbox now, and check spam:")
    print("  - in the inbox      → SPF/DKIM/DMARC are right; open registration is safe to use")
    print("  - in spam           → the DNS records need work first (docs/DEPLOY.md §4a)")
    print("  - nowhere at all    → the provider accepted and dropped it; check their dashboard")
    return 0


def main() -> int:
    """Entry point: one argument, the address to send to."""
    if len(sys.argv) != 2:  # noqa: PLR2004 — the program name plus one address
        print(__doc__)
        return 2
    return asyncio.run(_send(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
