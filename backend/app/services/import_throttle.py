"""Burst first, then one a minute — the shape of throttle the owner asked for.

Owner, 2026-09-04: *"we don't need to put a limit on daily cap, but if a user does more than 5
rotation imports in 5 minutes we should give them a warning and rate limit them to one rotation
per minute."*

## Why this is not two `@limiter.limit` decorators

The obvious spelling is `5/5minutes` plus `1/minute`, and it is wrong. slowapi applies every
decorator to every request, so `1/minute` would bind *immediately* — the fifth import of a
legitimate burst would be refused at second four, and the burst allowance would never exist.
The requirement is sequential: five freely, and only *then* a floor between requests.

That is a leaky bucket with a burst allowance, and it needs to be written rather than composed.

## What it is and is not

It is a **courtesy throttle**, not a security boundary. `POST /rotations/import/link` fetches
from gcsim's own servers and the owner's standing ruling is that this project does not push
compute to them — so the job here is to keep an enthusiastic user from hammering somebody
else's site, and to *tell them* that is what happened. It is deliberately generous: five back
to back, then a minute apart, with a message rather than a wall.

**State is per worker and in memory**, like slowapi's own. Production runs two workers, so a
determined user gets roughly twice these numbers, and a deploy forgets everything. Both are
acceptable for a courtesy throttle and neither would be for a security control — said here so
nobody later mistakes this for one. The real bound on abuse is that the endpoint requires a
signed-in account.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

#: Imports allowed back-to-back before the throttle engages.
BURST = 5
#: The window the burst is measured over.
BURST_WINDOW_SECONDS = 5 * 60
#: Once throttled, the minimum gap between imports.
THROTTLED_INTERVAL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether this import may proceed, and what to tell the user either way."""

    allowed: bool
    #: Set once the burst is spent — on the *allowed* requests too, which is the "warning"
    #: half of the ask. A user only learns about a throttle from being refused by it
    #: otherwise, which is the moment it is least welcome.
    warning: str | None = None
    #: Seconds until the next import would be accepted. Only meaningful when refused.
    retry_after: int = 0


class ImportThrottle:
    """Per-account burst-then-interval throttle.

    Keyed by whatever the caller passes — the owner id in practice. Timestamps older than the
    burst window are dropped on every check, so memory is bounded by active users rather than
    by total requests.
    """

    def __init__(
        self,
        burst: int = BURST,
        window_seconds: int = BURST_WINDOW_SECONDS,
        interval_seconds: int = THROTTLED_INTERVAL_SECONDS,
    ) -> None:
        self._burst = burst
        self._window = window_seconds
        self._interval = interval_seconds
        self._seen: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, now: float | None = None) -> Decision:
        """Decide, and record the request if it is allowed.

        Recording only on success is deliberate: a refused request did not reach gcsim, so
        counting it would push the user further from the allowance they are waiting for and
        turn repeated polling into an ever-longer lockout.
        """
        moment = time.monotonic() if now is None else now
        recent = self._seen[key]

        while recent and moment - recent[0] > self._window:
            recent.popleft()

        if len(recent) < self._burst:
            recent.append(moment)
            return Decision(allowed=True)

        since_last = moment - recent[-1]
        if since_last < self._interval:
            wait = int(self._interval - since_last) + 1
            return Decision(
                allowed=False,
                warning=(
                    f"That is more than {self._burst} rotation imports in "
                    f"{self._window // 60} minutes. Each one fetches from gcsim's own "
                    f"servers, so further imports are limited to one a minute. "
                    f"Try again in {wait}s."
                ),
                retry_after=wait,
            )

        recent.append(moment)
        return Decision(
            allowed=True,
            warning=(
                f"You have imported more than {self._burst} rotations in "
                f"{self._window // 60} minutes. Each one fetches from gcsim's own servers, "
                f"so further imports are limited to one a minute."
            ),
        )

    def forget(self, key: str) -> None:
        """Drop one key's history. For an operator clearing a mistake."""
        self._seen.pop(key, None)

    def reset(self) -> None:
        """Drop every key's history.

        For tests. The instance is process-wide, so a test that spends the allowance leaks
        into the next one — and a test which *thinks* it reset by passing the wrong key looks
        like it is isolated while depending on execution order.
        """
        self._seen.clear()


#: Process-wide, because it is per worker by design — see the module docstring.
import_throttle = ImportThrottle()
