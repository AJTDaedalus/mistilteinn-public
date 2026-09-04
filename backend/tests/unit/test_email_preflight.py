"""Production refuses to start when mail cannot work.

`app/services/email_preflight.py`. Every case here is a configuration that **starts cleanly and
delivers nothing** — the app boots, `register` answers 202, and nothing is red. Only the person
who never received their link finds out, and they do not report it.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.email_preflight import (
    EmailConfigurationError,
    check_production_email,
    enforce_production_email,
)


def _prod(**over) -> Settings:
    base = {
        "ENV": "production",
        "PUBLIC_BASE_URL": "https://mistilteinn.aetherus.dev",
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": "re_live_key",
        "EMAIL_FROM": "Mistilteinn <noreply@mistilteinn.aetherus.dev>",
    }
    return Settings(**{**base, **over})


def test_a_correct_production_configuration_passes() -> None:
    assert check_production_email(_prod()) == []


def test_a_localhost_link_is_refused() -> None:
    """**The single most likely mistake**, because it is the default. The prod compose passes
    `${PUBLIC_BASE_URL:-http://localhost:4201}`, so a forgotten override inherits a link
    nobody outside the machine can follow."""
    problems = check_production_email(_prod(PUBLIC_BASE_URL="http://localhost:4201"))

    assert len(problems) == 1
    assert "points at this machine" in problems[0]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:4201",
        "http://0.0.0.0:8000",
        "http://host.docker.internal:4201",
    ],
)
def test_every_local_host_form_is_refused(url: str) -> None:
    """`localhost` is not the only spelling, and the others are what a copied dev `.env`
    actually contains."""
    assert check_production_email(_prod(PUBLIC_BASE_URL=url)) != []


def test_an_empty_base_url_is_refused() -> None:
    assert check_production_email(_prod(PUBLIC_BASE_URL="")) != []


def test_plain_http_is_refused() -> None:
    """A verification link is a credential in a URL. Over http it is readable in transit."""
    problems = check_production_email(_prod(PUBLIC_BASE_URL="http://mistilteinn.example"))

    assert any("https" in p for p in problems)


def test_console_mail_with_auto_approval_is_refused() -> None:
    """The combination that makes signup *look* open while nobody can complete it: the link
    is the only way in and it goes to a container log."""
    problems = check_production_email(
        _prod(EMAIL_PROVIDER="console", AUTO_APPROVE_ON_VERIFY=True),
    )

    assert any("Nobody outside this machine" in p for p in problems)


def test_console_mail_without_auto_approval_is_allowed() -> None:
    """A defensible soft launch: verification is recorded and a human still approves, so
    nobody is stranded. Refusing this would make the check something to work around."""
    assert check_production_email(
        _prod(EMAIL_PROVIDER="console", AUTO_APPROVE_ON_VERIFY=False),
    ) == []


def test_resend_without_a_key_is_refused() -> None:
    """`ResendEmailSender` already refuses to construct — but on the first *request*, as a
    500 for whoever happened to be signing up, long after the deploy that caused it."""
    assert check_production_email(_prod(RESEND_API_KEY="")) != []


def test_resend_without_a_from_address_is_refused() -> None:
    assert check_production_email(_prod(EMAIL_FROM="   ")) != []


def test_an_unknown_provider_is_refused() -> None:
    """A typo must not fall back to console, which would turn every verification email into
    a line in a log while signups appeared to work."""
    assert check_production_email(_prod(EMAIL_PROVIDER="resend ")) == [], "whitespace is fine"
    assert check_production_email(_prod(EMAIL_PROVIDER="resnd")) != []


def test_every_problem_is_reported_at_once() -> None:
    """Stopping at the first fault makes an operator fix one thing, redeploy, and discover
    the next — three deploys for one edit."""
    problems = check_production_email(
        _prod(PUBLIC_BASE_URL="http://localhost:4201", RESEND_API_KEY="", EMAIL_FROM=""),
    )

    assert len(problems) == 3


def test_local_development_is_exempt() -> None:
    """`console` and a localhost URL are exactly right here. A check that fires in
    development is a check people learn to work around."""
    local = Settings(ENV="local", EMAIL_PROVIDER="console", AUTO_APPROVE_ON_VERIFY=True)

    enforce_production_email(local)  # does not raise


def test_production_refuses_to_boot() -> None:
    with pytest.raises(EmailConfigurationError) as caught:
        enforce_production_email(_prod(PUBLIC_BASE_URL="http://localhost:4201"))

    # The message has to carry the fix, not just the fault: whoever sees it is mid-deploy.
    assert "DEPLOY.md" in str(caught.value)


def test_a_good_production_configuration_boots() -> None:
    enforce_production_email(_prod())  # does not raise
