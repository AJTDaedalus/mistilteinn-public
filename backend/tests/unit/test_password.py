"""Unit tests for app.services.password — written before implementation (TDD)."""

import pytest

from app.services.password import (
    DUMMY_HASH,
    hash_password,
    validate_password,
    verify_password,
)

VALID_PW = "correct-horse-battery"
USER_EMAIL = "user@example.com"


# ---------------------------------------------------------------------------
# validate_password — acceptance
# ---------------------------------------------------------------------------


def test_validate_accepts_valid_password():
    validate_password(VALID_PW, email=USER_EMAIL)


def test_validate_accepts_12_char_minimum():
    validate_password("aB3dEf4gHi5j", email=USER_EMAIL)


# ---------------------------------------------------------------------------
# validate_password — rejections
# ---------------------------------------------------------------------------


def test_validate_rejects_under_12_chars():
    with pytest.raises(ValueError, match="12"):
        validate_password("short1234", email=USER_EMAIL)


def test_validate_rejects_exactly_11_chars():
    with pytest.raises(ValueError, match="12"):
        validate_password("a" * 11, email=USER_EMAIL)


def test_validate_rejects_over_72_utf8_bytes():
    # 73 ASCII chars = 73 bytes
    with pytest.raises(ValueError, match="72"):
        validate_password("a" * 73, email=USER_EMAIL)


def test_validate_rejects_over_72_bytes_multibyte():
    # 37 × 2-byte chars = 74 bytes, 37 chars — within char limit but over byte limit
    with pytest.raises(ValueError, match="72"):
        validate_password("é" * 37, email=USER_EMAIL)


def test_validate_rejects_equal_to_email_exact():
    with pytest.raises(ValueError, match="email"):
        validate_password(USER_EMAIL, email=USER_EMAIL)


def test_validate_rejects_equal_to_email_case_insensitive():
    with pytest.raises(ValueError, match="email"):
        validate_password(USER_EMAIL.upper(), email=USER_EMAIL)


@pytest.mark.parametrize(
    "bad_pw",
    [
        "password123456",
        "123456789012",
        "qwertyuiop12",
        "Password12345",
        "iloveyou12345",
        "letmein123456",
    ],
)
def test_validate_rejects_denylist_entry(bad_pw):
    with pytest.raises(ValueError, match="common"):
        validate_password(bad_pw, email=USER_EMAIL)


# ---------------------------------------------------------------------------
# hash_password
# ---------------------------------------------------------------------------


def test_hash_differs_from_input():
    h = hash_password(VALID_PW)
    assert h != VALID_PW


def test_hash_starts_with_bcrypt_identifier():
    h = hash_password(VALID_PW)
    assert h.startswith("$2b$")


def test_hash_uses_cost_12():
    h = hash_password(VALID_PW)
    # bcrypt format: $2b$<cost>$<rest>
    cost = int(h.split("$")[2])
    assert cost == 12


# ---------------------------------------------------------------------------
# verify_password
# ---------------------------------------------------------------------------


def test_verify_returns_true_for_correct_password():
    h = hash_password(VALID_PW)
    assert verify_password(VALID_PW, h) is True


def test_verify_returns_false_for_wrong_password():
    h = hash_password(VALID_PW)
    assert verify_password("wrongpassword!", h) is False


def test_verify_returns_false_for_hash_of_different_password():
    h1 = hash_password(VALID_PW)
    h2 = hash_password("another-valid-pw-42")
    assert verify_password(VALID_PW, h2) is False
    assert verify_password("another-valid-pw-42", h1) is False


# ---------------------------------------------------------------------------
# DUMMY_HASH
# ---------------------------------------------------------------------------


def test_dummy_hash_is_valid_bcrypt():
    assert DUMMY_HASH.startswith("$2b$")


def test_dummy_hash_verify_returns_false_for_random_input():
    # Should never match an attacker-supplied password
    assert verify_password("somepassword123", DUMMY_HASH) is False
