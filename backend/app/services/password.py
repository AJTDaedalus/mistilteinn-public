"""Password hashing and validation utilities (NIST 800-63B-aligned).

Uses the `bcrypt` library directly — passlib 1.7.4 is incompatible with
bcrypt 4+, so we bypass it and call bcrypt.hashpw / bcrypt.checkpw.
"""

import secrets

import bcrypt

_ROUNDS = 12
_MIN_CHARS = 12
_MAX_BYTES = 72

_DENYLIST = frozenset(
    [
        "password123456",
        "123456789012",
        "qwertyuiop12",
        "password12345",
        "iloveyou12345",
        "letmein123456",
        "admin123456789",
        "welcome123456",
        "monkey123456",
        "dragon123456",
        "master123456",
        "sunshine12345",
        "princess12345",
        "football12345",
        "shadow123456",
        "superman12345",
        "michael12345",
        "jessica12345",
        "passw0rd12345",
        "abc123456789",
    ]
)

# Pre-computed hash for constant-time response on unknown-email login path.
DUMMY_HASH: str = bcrypt.hashpw(
    secrets.token_hex(16).encode(),
    bcrypt.gensalt(rounds=_ROUNDS),
).decode()


def validate_password(password: str, *, email: str) -> None:
    """Raise ValueError if *password* violates any policy rule."""
    if len(password) < _MIN_CHARS:
        raise ValueError("Password must be at least 12 characters.")
    if len(password.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("Password must not exceed 72 bytes (UTF-8 encoded).")
    if password.lower() == email.lower():
        raise ValueError("Password must not match your email address.")
    if password.lower() in _DENYLIST:
        raise ValueError("Password is too common. Please choose a less common password.")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    salt = bcrypt.gensalt(rounds=_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode()


def verify_password(password: str, pw_hash: str) -> bool:
    """Return True if *password* matches *pw_hash*."""
    return bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))
