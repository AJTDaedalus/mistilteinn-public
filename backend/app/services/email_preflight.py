"""Refuse to start production with mail settings that cannot work.

`DESIGN_open_registration.md` §7. Every failure named here is **silent** — the app starts, the
endpoint answers `202`, and nothing is red anywhere. Only the person who never received their
link finds out, and they do not tell you; they leave.

That is the shape of the first finding in fairy's pre-merge review of this same feature: no new
setting reached the container, and *"signup looked fine"* while verification mail went to a log
nobody reads and escaped links pointed at `localhost:4200`. The lesson taken from it was to test
the delivery path; this is the other half — checking that what was delivered is usable, at the
one moment a human is watching, which is a deploy.

**Local and test environments are exempt.** `EMAIL_PROVIDER=console` and a `localhost` base URL
are exactly right there, and a check that fires in development is a check people learn to work
around.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

CONSOLE = "console"
RESEND = "resend"

#: Hosts that can never be right in production. A link to any of these is a link the recipient
#: cannot follow — their machine is not ours.
#:
#: **The suppressions are for a false positive in both linters**, and the direction matters:
#: `0.0.0.0` here is a value being *rejected*, not an interface being bound. Both tools pattern
#: match the literal rather than its use, so both flag the exact opposite of a problem.
#:
#: Two directives because they are two tools: `noqa` silences ruff, `nosec` silences bandit.
#: Only the first was written, `ruff check` passed, and the gap surfaced as a red Backend
#: Security Scan — which it should have, since nothing local had run bandit yet.
_LOCAL_HOSTS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104  # nosec B104 — rejected, never bound
    "host.docker.internal",
)


class EmailConfigurationError(RuntimeError):
    """Production mail settings that would fail silently. Raised at startup, never at request."""


def check_production_email(settings: Settings) -> list[str]:
    """Return every reason this configuration cannot deliver mail. Empty means it can.

    Returned rather than raised so the caller decides the severity and so every problem is
    reported at once — a check that stops at the first fault makes an operator fix one thing,
    redeploy, and discover the next.
    """
    problems: list[str] = []
    provider = settings.EMAIL_PROVIDER.strip().lower()

    # 1. A link nobody can follow. Always wrong in production, whatever the provider is,
    #    because the *default* is a localhost URL and a forgotten override inherits it.
    base = settings.PUBLIC_BASE_URL.strip()
    if not base:
        problems.append("PUBLIC_BASE_URL is empty — verification links would have no host.")
    elif any(host in base for host in _LOCAL_HOSTS):
        problems.append(
            f"PUBLIC_BASE_URL is {base!r}, which points at this machine. Every verification "
            f"link would be unfollowable. Set it to the public origin.",
        )
    elif not base.startswith("https://"):
        problems.append(
            f"PUBLIC_BASE_URL is {base!r}. A verification link is a credential in a URL and "
            f"must be https in production.",
        )

    # 2. The combination that makes signup *look* open while nobody can complete it.
    #    On its own, console mail in production is a defensible soft-launch: verification is
    #    recorded and a human still approves. Paired with auto-approval it is a dead end,
    #    because the link is the only way in and it goes to a container log.
    if provider == CONSOLE and settings.AUTO_APPROVE_ON_VERIFY:
        problems.append(
            "EMAIL_PROVIDER=console with AUTO_APPROVE_ON_VERIFY=true: registration would "
            "appear open while every verification link went to the container log. Nobody "
            "outside this machine could ever finish signing up.",
        )

    # 3. Resend selected but unusable. `ResendEmailSender` already refuses to construct
    #    without these — but that happens on the first *request*, as a 500 for whoever
    #    happened to be signing up, long after the deploy that caused it.
    if provider == RESEND:
        if not settings.RESEND_API_KEY.strip():
            problems.append("EMAIL_PROVIDER=resend but RESEND_API_KEY is empty.")
        if not settings.EMAIL_FROM.strip():
            problems.append("EMAIL_PROVIDER=resend but EMAIL_FROM is empty.")

    if provider not in (CONSOLE, RESEND):
        problems.append(
            f"EMAIL_PROVIDER={settings.EMAIL_PROVIDER!r} is not recognised "
            f"(expected {CONSOLE!r} or {RESEND!r}).",
        )

    return problems


def enforce_production_email(settings: Settings) -> None:
    """Raise `EmailConfigurationError` if production mail settings cannot deliver.

    **Refusing to boot is the right severity**, and it is a deliberate choice over logging a
    warning. A warning in a deploy log is read by nobody; the failure it describes is invisible
    for as long as it takes someone to notice they have no new users, which on a small site can
    be weeks. A container that will not start is noticed in seconds, and the previous one keeps
    serving while it is fixed.
    """
    if settings.ENV != "production":
        return
    problems = check_production_email(settings)
    if problems:
        joined = "\n  - ".join(problems)
        raise EmailConfigurationError(
            f"Refusing to start: mail is configured in a way that fails silently.\n"
            f"  - {joined}\n"
            f"The sending domain needs SPF, DKIM and DMARC records for the mail provider "
            f"(Resend lists them under Domains). Set EMAIL_PROVIDER=console and "
            f"AUTO_APPROVE_ON_VERIFY=false to run without mail.",
        )
