"""Integration tests for the post-seed AM/AP tripwire check.

See docs/RESEARCH_batch32c_followups.md — this is the guard that makes the
recurring seed operation verify itself instead of depending on someone
remembering to re-check AM/AP after every seed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.enums import Element, Rarity, Specialty
from scripts.verify_seed import (
    TRIPWIRES,
    SeedVerificationError,
    verify_every_agent_has_attacks,
    verify_tripwires,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _make_tripwire_agent(
    session: AsyncSession, *, hakushin_id: int, name: str, am: int, ap: int
) -> Agent:
    agent = Agent(
        hakushin_id=hakushin_id,
        name=name,
        full_name=name,
        element=Element.ELECTRIC,
        specialty=Specialty.ANOMALY,
        rarity=Rarity.S,
        faction="Test",
        faction_id=1,
        base_hp=500,
        base_atk=100,
        base_def=50,
        hp_growth=0,
        atk_growth=0,
        def_growth=0,
        base_crit_rate=500,
        base_crit_dmg=5000,
        base_anomaly_mastery=am,
        base_anomaly_proficiency=ap,
    )
    session.add(agent)
    await session.flush()
    return agent


class TestVerifyTripwires:
    async def test_passes_when_all_tripwires_match(self, db_session: AsyncSession) -> None:
        for tw in TRIPWIRES:
            await _make_tripwire_agent(
                db_session,
                hakushin_id=tw.hakushin_id,
                name=tw.name,
                am=tw.expected_am,
                ap=tw.expected_ap,
            )
        await verify_tripwires(db_session)  # must not raise

    async def test_raises_when_am_ap_swapped(self, db_session: AsyncSession) -> None:
        for tw in TRIPWIRES:
            await _make_tripwire_agent(
                db_session,
                hakushin_id=tw.hakushin_id,
                name=tw.name,
                am=tw.expected_ap,  # swapped
                ap=tw.expected_am,
            )
        with pytest.raises(SeedVerificationError, match="RESEARCH_batch32c_followups"):
            await verify_tripwires(db_session)

    async def test_raises_when_tripwire_agent_missing(self, db_session: AsyncSession) -> None:
        with pytest.raises(SeedVerificationError, match="not found in DB"):
            await verify_tripwires(db_session)


async def _make_plain_agent(session: AsyncSession, *, hakushin_id: int, name: str) -> Agent:
    return await _make_tripwire_agent(session, hakushin_id=hakushin_id, name=name, am=100, ap=100)


async def _give_one_attack(session: AsyncSession, agent: Agent) -> None:
    session.add(
        Attack(
            agent_id=agent.id,
            hakushin_skill_id=1,
            skill_key="Basic",
            name=f"Basic Attack: {agent.name}",
            hit_index=0,
            element="physical",
            damage_base=1000,
            damage_growth=0,
            stun_base=0,
            stun_growth=0,
            energy_gain=0,
            anomaly_buildup=0,
        )
    )
    await session.flush()


class TestVerifyEveryAgentHasAttacks:
    """Issue #149 — a seed that lands agents but not their attacks used to pass.

    The simulator's reaction to that state is silent (a step resolving to zero rows
    deals no direct damage, and with a curated move spec still emits anomaly damage),
    so this tripwire is the only thing standing between a partial seed and a user
    reporting "agent X doesn't trigger her attacks".
    """

    async def test_passes_when_every_agent_has_at_least_one_attack(
        self, db_session: AsyncSession
    ) -> None:
        for i, name in enumerate(("Velina", "Burnice"), start=9001):
            agent = await _make_plain_agent(db_session, hakushin_id=i, name=name)
            await _give_one_attack(db_session, agent)

        await verify_every_agent_has_attacks(db_session)  # must not raise

    async def test_raises_and_names_the_agent_with_no_attacks(
        self, db_session: AsyncSession
    ) -> None:
        seeded = await _make_plain_agent(db_session, hakushin_id=9003, name="Burnice")
        await _give_one_attack(db_session, seeded)
        await _make_plain_agent(db_session, hakushin_id=9004, name="Velina")

        with pytest.raises(SeedVerificationError, match="zero attack rows") as exc:
            await verify_every_agent_has_attacks(db_session)

        # Naming the agent is the point — "some agent is broken" is not actionable.
        assert "Velina" in str(exc.value)
        assert "Burnice" not in str(exc.value)

    async def test_an_empty_db_is_not_treated_as_healthy(self, db_session: AsyncSession) -> None:
        """No agents means nothing to report, which must not read as a clean seed —
        the AM/AP tripwires catch that case and must keep doing so."""
        await verify_every_agent_has_attacks(db_session)  # vacuously fine on its own
        with pytest.raises(SeedVerificationError, match="not found in DB"):
            await verify_tripwires(db_session)
