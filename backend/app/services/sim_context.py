"""What makes two simulations the same simulation.

A cached gcsim result is only reusable if the thing it simulated is the thing being asked
about. `context_key` decides that, and getting it wrong is not a performance bug — it serves
a confident number computed for a different build.

## What is in the key

Everything that changes the answer **except the artifacts being searched**: character,
weapon, refinement, constellation, talent levels, the rotation, and the target. Those are all
inputs the user arrives with (DESIGN §3.5); only the artifacts vary during a search.

## What is not, and why that is safe

Artifact stats are excluded, with **one exception**: energy recharge, which is bucketed
separately. ER is the only artifact-borne stat that changes *whether the rotation happens*
rather than how hard it hits — everything else is a multiplier the search applies itself.

## Why it is a hash rather than a row of columns

Because a cache key must be all-or-nothing. Storing the parts would invite querying by some
of them, and a lookup that matched on a subset would return a run for a different context
while looking like a hit. The hash cannot be partially matched.

**Canonicalisation is the whole job.** Two descriptions of the same context must produce the
same key, and two different contexts must not collide. So the input is JSON with sorted keys
and no insignificant whitespace, and floats are rounded to a fixed precision — otherwise
`0.1 + 0.2` and `0.30000000000000004` describe the same build and miss each other's cache.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Decimal places floats are rounded to before hashing. Six is far finer than any stat this
#: describes and coarse enough that float arithmetic cannot produce two keys for one build.
_PRECISION = 6

#: ER is bucketed in whole percent: `100` is 1.00 ER. Coarse on purpose — the question is
#: which side of the burst-uptime cliff a build sits on, not its exact value, and a key per
#: 0.1% would cache nothing twice.
_ER_BUCKET_PERCENT = 5


def er_bucket(energy_recharge: float) -> int:
    """The bucket an ER value falls in, as whole percent, rounded **down**.

    Down rather than nearest: a build at 179% ER must not be told about a run at 180% that
    got its burst off when this one may not. Rounding toward the pessimistic side means a
    cache hit never claims more uptime than the build has earned.
    """
    percent = int(energy_recharge * 100)
    return percent - (percent % _ER_BUCKET_PERCENT)


def _canonical(value: Any) -> Any:
    """Round floats and sort mappings, so equal contexts serialise identically."""
    if isinstance(value, float):
        return round(value, _PRECISION)
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def context_key(
    *,
    character_key: str,
    weapon_key: str | None,
    character_level: int,
    constellation: int,
    weapon_level: int,
    refinement: int,
    talent_levels: dict[str, int],
    rotation: list[str],
    target: dict[str, Any],
    gcsim_pin: str,
    team: list[str] | None = None,
) -> str:
    """A stable hash of everything that makes this simulation what it is.

    `gcsim_pin` is inside the hash as well as being stored beside it. Belt and braces on
    purpose: a lookup that forgot the pin column would still miss, rather than return a
    result from a different simulator.
    """
    payload = _canonical({
        "character": character_key,
        "weapon": weapon_key,
        "character_level": character_level,
        "constellation": constellation,
        "weapon_level": weapon_level,
        "refinement": refinement,
        "talents": talent_levels,
        # Order matters: a rotation is a sequence, and reordering it is a different rotation.
        "rotation": list(rotation),
        "target": target,
        # Sorted: a team is a set of members, and listing them in another order is the same
        # team. This is the one place ordering is deliberately discarded.
        "team": sorted(team or []),
        "gcsim_pin": gcsim_pin,
    })
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
