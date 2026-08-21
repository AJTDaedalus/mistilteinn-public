"""Post-seed sanity checks — tripwire values that catch a field-mapping
regression (like the AM/AP swap, docs/RESEARCH_batch32c_followups.md) before
it reaches prod silently, the way the original bug did. `seed_db.py` had no
post-seed assertions at all until this existed.

Keep the tripwire list short and comment *why* each entry is trustworthy —
a long list of unverified expectations rots and gets deleted instead of fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.agent import Agent, Attack

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class _Tripwire:
    hakushin_id: int
    name: str
    expected_am: int
    expected_ap: int
    reason: str


TRIPWIRES = [
    _Tripwire(
        hakushin_id=1511,
        name="Nangong Yu",
        expected_am=90,
        expected_ap=93,
        reason="in-game confirmed, ungeared Lv1 (AM/AP do not scale with level)",
    ),
    _Tripwire(
        hakushin_id=1091,
        name="Miyabi",
        expected_am=116,
        expected_ap=148,
        reason="cross-checked against ZO character.ts:226-227 and wiki stat tables",
    ),
]


class SeedVerificationError(RuntimeError):
    """Raised when a post-seed tripwire check fails."""


async def verify_every_agent_has_attacks(session: AsyncSession) -> None:
    """Every agent must own at least one `attacks` row (issue #149).

    The stat tripwires above check *values* on a handful of agents; nothing checked
    that the attack rows arrived at all. A seed that lands agents but not their
    attacks therefore passed silently, and the simulator's own reaction to it is
    just as quiet — a step resolving to zero rows deals no direct damage and, when
    a curated move spec supplies buildup, still emits anomaly damage, so the
    timeline looks healthy. That combination is how "agent X doesn't trigger her
    attacks" reaches a user with nothing anywhere saying why.

    Agent-count is deliberately not asserted here: a *new* agent legitimately
    appears between patches, whereas an agent with no attacks is never legitimate.
    """
    rows = (
        (
            await session.execute(
                select(Agent.name)
                .outerjoin(Attack, Attack.agent_id == Agent.id)
                .group_by(Agent.id, Agent.name)
                .having(func.count(Attack.id) == 0)
                .order_by(Agent.name)
            )
        )
        .scalars()
        .all()
    )

    if rows:
        raise SeedVerificationError(
            f"Post-seed sanity check failed — {len(rows)} agent(s) have zero attack "
            f"rows, so every combo step naming one of their moves will silently deal "
            f"no direct damage (issue #149):\n" + "\n".join(f"  - {name}" for name in rows)
        )


async def verify_tripwires(session: AsyncSession) -> None:
    """Check known-good stat values survived the seed. Raises on mismatch.

    This does not prove the importer is correct in general, only that it has
    not regressed on these specific, previously-verified agents.
    """
    failures: list[str] = []
    for tw in TRIPWIRES:
        result = await session.execute(
            select(Agent.base_anomaly_mastery, Agent.base_anomaly_proficiency).where(
                Agent.hakushin_id == tw.hakushin_id
            )
        )
        row = result.first()
        if row is None:
            failures.append(f"{tw.name} (hakushin_id={tw.hakushin_id}): not found in DB")
            continue
        am, ap = row
        if am != tw.expected_am or ap != tw.expected_ap:
            failures.append(
                f"{tw.name}: expected AM={tw.expected_am}/AP={tw.expected_ap} "
                f"({tw.reason}), got AM={am}/AP={ap}"
            )

    if failures:
        raise SeedVerificationError(
            "Post-seed sanity check failed — see docs/RESEARCH_batch32c_followups.md:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )
