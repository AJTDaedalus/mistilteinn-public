"""Outbound email: the `EmailSender` seam and its implementations."""

from app.services.email.base import EmailMessage, EmailSender, EmailSendError
from app.services.email.console import ConsoleEmailSender
from app.services.email.factory import get_email_sender
from app.services.email.recording import RecordingEmailSender

__all__ = [
    "ConsoleEmailSender",
    "EmailMessage",
    "EmailSendError",
    "EmailSender",
    "RecordingEmailSender",
    "get_email_sender",
]
