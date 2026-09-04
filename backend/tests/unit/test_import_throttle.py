"""Five back to back, then one a minute, with a warning either way.

Owner, 2026-09-04: *"if a user does more than 5 rotation imports in 5 minutes we should give
them a warning and rate limit them to one rotation per minute."*

Time is injected rather than slept, so these run in milliseconds and cannot flake on a slow
machine — a throttle test that sleeps is a throttle test people delete.
"""

from __future__ import annotations

from app.services.import_throttle import BURST, ImportThrottle

USER = "owner-1"


def _fresh() -> ImportThrottle:
    return ImportThrottle()


def test_the_burst_is_allowed_back_to_back() -> None:
    """No gap enforced inside the allowance — importing a team's five rotations in one
    sitting is the ordinary case, not abuse."""
    throttle = _fresh()

    decisions = [throttle.check(USER, now=100.0) for _ in range(BURST)]

    assert all(d.allowed for d in decisions)
    assert all(d.warning is None for d in decisions)


def test_the_sixth_import_in_the_window_is_refused() -> None:
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)

    sixth = throttle.check(USER, now=101.0)

    assert sixth.allowed is False
    assert sixth.retry_after > 0


def test_the_refusal_explains_itself_and_names_gcsim() -> None:
    """The 'warning' half of the ask. A bare 429 tells the user they are broken; this tells
    them what happened and, more to the point, that the cost lands on somebody else."""
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)

    refused = throttle.check(USER, now=101.0)

    assert refused.warning is not None
    assert "gcsim" in refused.warning
    assert "one a minute" in refused.warning


def test_a_minute_later_it_is_allowed_again() -> None:
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)

    later = throttle.check(USER, now=161.0)

    assert later.allowed is True


def test_an_allowed_import_after_the_burst_still_warns() -> None:
    """**The warning arrives before the refusal does.** A user who only ever imports slowly
    would otherwise first learn about the throttle by being blocked by it, which is the
    moment it is least welcome."""
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)

    later = throttle.check(USER, now=161.0)

    assert later.allowed is True
    assert later.warning is not None


def test_being_refused_does_not_extend_the_wait() -> None:
    """A refused request never reached gcsim, so counting it would push the user further from
    the allowance they are waiting for — polling would become an ever-longer lockout."""
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)
    for moment in (101.0, 102.0, 103.0, 104.0):
        assert throttle.check(USER, now=moment).allowed is False

    assert throttle.check(USER, now=161.0).allowed is True


def test_the_window_slides() -> None:
    """Five imports five minutes ago must not hold anyone back now — this is a rolling
    window, not a fixed bucket that only empties on the hour."""
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)

    assert throttle.check(USER, now=100.0 + 5 * 60 + 1).allowed is True


def test_a_full_burst_is_available_again_after_the_window() -> None:
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)
    base = 100.0 + 5 * 60 + 1

    decisions = [throttle.check(USER, now=base) for _ in range(BURST)]

    assert all(d.allowed for d in decisions)


def test_accounts_do_not_share_an_allowance() -> None:
    """The obvious way to get this wrong is a single global counter, which would let one
    enthusiastic user throttle everybody else."""
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check("noisy", now=100.0)

    assert throttle.check("quiet", now=100.0).allowed is True


def test_retry_after_is_a_usable_number_of_seconds() -> None:
    """It goes out as a `Retry-After` header, so it has to be a positive whole number and it
    must not undershoot — a client obeying it exactly should not be refused again."""
    throttle = _fresh()
    for _ in range(BURST):
        throttle.check(USER, now=100.0)

    refused = throttle.check(USER, now=130.0)

    assert refused.retry_after >= 1
    assert throttle.check(USER, now=130.0 + refused.retry_after).allowed is True
