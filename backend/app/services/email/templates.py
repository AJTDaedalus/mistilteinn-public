"""The three signup emails, as plain functions returning `EmailMessage`.

No template engine: three static bodies with one interpolated link do not justify
Jinja in the dependency list, and inlining them keeps the exact wording reviewable in
a diff — which matters most for `already_registered`, whose whole job is to say as
little as possible.

See `docs/DESIGN_open_registration.md` §5.3 and §5.4.
"""

from __future__ import annotations

from app.config import settings
from app.services.email.base import EmailMessage

_PRODUCT = "Mistilteinn"
_EXPIRY = "24 hours"
_RESET_EXPIRY = "1 hour"


def _login_url() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/login"


def _wrap(body_html: str) -> str:
    """Minimal inline-styled HTML. No remote assets — they trip spam heuristics and
    render as broken images for the many clients that block them by default."""
    return (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
        'font-size:15px;line-height:1.6;color:#1a1a1a;max-width:540px">'
        f"{body_html}"
        '<hr style="border:none;border-top:1px solid #ddd;margin:24px 0">'
        f'<p style="font-size:12px;color:#666">{_PRODUCT} — Genshin Impact build optimizer</p>'
        "</div>"
    )


def verify_email(*, to: str, link: str) -> EmailMessage:
    """The verification link. One click from here to a usable account."""
    text = (
        f"Welcome to {_PRODUCT}.\n\n"
        f"Confirm this address to finish setting up your account:\n\n"
        f"{link}\n\n"
        f"The link is valid for {_EXPIRY}. If it expires, request a new one from the "
        f"sign-in page.\n\n"
        f"If you did not sign up for {_PRODUCT}, ignore this email — no account will be "
        f"activated without this confirmation."
    )
    html = _wrap(
        f"<p>Welcome to {_PRODUCT}.</p>"
        f"<p>Confirm this address to finish setting up your account:</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:10px 18px;'
        f'background:#1a1a1a;color:#fff;text-decoration:none;border-radius:6px">'
        f"Confirm my email</a></p>"
        f'<p style="font-size:13px;color:#666">Or paste this into your browser:<br>'
        f'<span style="word-break:break-all">{link}</span></p>'
        f"<p>The link is valid for {_EXPIRY}. If it expires, request a new one from the "
        f"sign-in page.</p>"
        f"<p>If you did not sign up for {_PRODUCT}, ignore this email — no account will "
        f"be activated without this confirmation.</p>"
    )
    return EmailMessage(to=to, subject=f"Confirm your {_PRODUCT} account", text=text, html=html)


def already_registered(*, to: str) -> EmailMessage:
    """Sent when someone submits the register form with an address that already has a
    verified account.

    Registration answers identically whether or not the address is known, so this is
    what the *existing* account holder gets instead of a verification link. Two rules
    it must not break:

    - **No account details.** The reader may not be the person who submitted the form,
      so status, label, and anything else about the account stay out.
    - **No verification link.** Sending one would let anyone who knows an address mint
      a working credential straight into that person's inbox.
    """
    login = _login_url()
    text = (
        f"Someone just tried to create a {_PRODUCT} account with this email address.\n\n"
        f"This address is already registered, so nothing has changed and no new account "
        f"was created.\n\n"
        f"If that was you, sign in instead: {login}\n"
        f"Forgotten your password? Use the reset link on that page.\n\n"
        f"If you did not do this, no action is needed — whoever submitted the form was "
        f"not told whether this address has an account."
    )
    html = _wrap(
        f"<p>Someone just tried to create a {_PRODUCT} account with this email address.</p>"
        f"<p>This address is already registered, so nothing has changed and no new "
        f"account was created.</p>"
        f'<p>If that was you, <a href="{login}">sign in instead</a>. Forgotten your '
        f"password? Use the reset link on that page.</p>"
        f"<p>If you did not do this, no action is needed — whoever submitted the form "
        f"was not told whether this address has an account.</p>"
    )
    return EmailMessage(
        to=to,
        subject=f"Someone tried to register your email with {_PRODUCT}",
        text=text,
        html=html,
    )


def verified_welcome(*, to: str) -> EmailMessage:
    """Confirmation that the address is verified and the account is usable."""
    login = _login_url()
    text = (
        f"Your email is confirmed and your {_PRODUCT} account is ready.\n\n"
        f"Sign in: {login}\n\n"
        f"If you did not confirm this address, reply to this email."
    )
    html = _wrap(
        f"<p>Your email is confirmed and your {_PRODUCT} account is ready.</p>"
        f'<p><a href="{login}">Sign in</a></p>'
        f"<p>If you did not confirm this address, reply to this email.</p>"
    )
    return EmailMessage(to=to, subject=f"Your {_PRODUCT} account is ready", text=text, html=html)


def password_reset(*, to: str, link: str) -> EmailMessage:
    """The reset link.

    Shorter-lived than the verification link (1 hour, not 24): the user is actively
    waiting for this one, so the usual argument for a generous window does not apply, and
    the credential is more dangerous.
    """
    text = (
        f"Someone asked to reset the password for this {_PRODUCT} account.\n\n"
        f"Set a new password:\n\n{link}\n\n"
        f"The link is valid for {_RESET_EXPIRY} and can only be used once.\n\n"
        f"If you did not ask for this, ignore this email — your password has not changed, "
        f"and nobody was told whether this address has an account."
    )
    html = _wrap(
        f"<p>Someone asked to reset the password for this {_PRODUCT} account.</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:10px 18px;'
        f'background:#1a1a1a;color:#fff;text-decoration:none;border-radius:6px">'
        f"Set a new password</a></p>"
        f'<p style="font-size:13px;color:#666">Or paste this into your browser:<br>'
        f'<span style="word-break:break-all">{link}</span></p>'
        f"<p>The link is valid for {_RESET_EXPIRY} and can only be used once.</p>"
        f"<p>If you did not ask for this, ignore this email — your password has not "
        f"changed, and nobody was told whether this address has an account.</p>"
    )
    return EmailMessage(to=to, subject=f"Reset your {_PRODUCT} password", text=text, html=html)


def password_changed(*, to: str) -> EmailMessage:
    """Sent after a successful reset.

    Not a courtesy. This is the one message that reaches the real account holder if
    somebody else completed a reset, and it is what makes the silence of
    `forgot-password` safe rather than merely quiet.
    """
    text = (
        f"Your {_PRODUCT} password was just changed, and every signed-in device has been "
        f"signed out.\n\n"
        f"If that was you, there is nothing to do.\n\n"
        f"If it was not, reply to this email immediately — someone else has access to "
        f"this inbox or to your old password."
    )
    html = _wrap(
        f"<p>Your {_PRODUCT} password was just changed, and every signed-in device has "
        f"been signed out.</p>"
        f"<p>If that was you, there is nothing to do.</p>"
        f"<p>If it was not, <strong>reply to this email immediately</strong> — someone "
        f"else has access to this inbox or to your old password.</p>"
    )
    return EmailMessage(
        to=to, subject=f"Your {_PRODUCT} password was changed", text=text, html=html
    )
