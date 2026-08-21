"""Task 11, docs/TASKS_nanoka_potential.md — assert the #85 fix's expected data deltas.

Runs against the real seeded app DB (not the isolated `fairy_test` DB — see
`test_move_key_resolution.py` for the same pattern), after
`python -m scripts.seed_db` has re-imported every agent through the fixed
`NanokaImporter`. Skips automatically if the DB is unreachable or unseeded.

The two "unchanged" assertions (18 Potential-only moves resolve — the 16
that carry DMG params plus 2 pure-description dodge moves — and total
distinct move-name counts) are the important ones: they prove the fix
dropped `potential: [0]` entries specifically, rather than the "keep only
`[]`" mis-implementation that would have deleted all 18 live moves
(docs/DESIGN_nanoka_potential.md, "Expected data deltas"). The row-count
totals asserted here were confirmed unchanged from the pre-fix DB by a
separate before/after table dump (Task 14, docs/LOG_nanoka_potential.md).
"""

from __future__ import annotations

import pytest
from sqlalchemy import distinct, func, or_, select

from app.database import async_session_factory
from app.models.agent import Agent, AgentSkill, Attack, CoreSkill
from app.models.enums import PotentialVariant


def _visible(model: type, variant: PotentialVariant):
    """SQL predicate for the rows one Potential state sees."""
    wanted = "unlocked" if variant is PotentialVariant.UNLOCKED else "base"
    return or_(model.potential.is_(None), model.potential == wanted)

# (agent, move) pairs that exist only when Potential is unlocked
# (docs/RESEARCH_potential_sweep_85.md §5) — must still resolve post-fix.
POTENTIAL_ONLY_MOVES = [
    ("Nekomata", "Dodge: Disappearing Tail"),
    ("Nekomata", "Dodge Counter: Fluffy Piercing Claw"),
    ("Soldier 11", "Basic Attack: Fire Assault"),
    ("Lycaon", "Assist Follow-Up: Vengeful Counterattack - Glacial Waltz"),
    ("Burnice", "EX Special Attack: Intense Heat Tossing Method"),
    ("Grace", "Pulse"),
    ("Grace", "Special Attack: Obstruction Removal - Cycle"),
    ("Grace", "Vortex Cluster Grenade Base Multiplier"),
    ("Grace", "Pulse Grenade Multiplier"),
    ("Ellen", "Basic Attack: Glacial Blade Wave"),
    ("Ellen", "Basic Attack: Icy Blade"),
    ("Harumasa", "Chasing Thunder"),
    ("Harumasa", "EX Special Attack: Nowhere to Run - Patrol"),
    ("Harumasa", "Zanshin - Scattered Blossoms"),
    ("Rina", "Basic Attack: Morning Cleanup"),
    ("Rina", "Basic Attack: Midnight Cleanup"),
    ("Jane", "EX Special Attack: Aerial Sweep - Onslaught"),
    ("Soldier 0 - Anby", "Special Attack: Azure Flash - Boundary"),
]


@pytest.fixture
async def db_reachable() -> bool:
    try:
        async with async_session_factory() as session:
            count = (await session.execute(select(func.count()).select_from(Agent))).scalar_one()
    except Exception:
        return False
    return count > 0


async def _skip_unless_seeded(db_reachable: bool) -> None:
    if not db_reachable:
        pytest.skip("App DB not reachable or not seeded — seeded DB required")


async def _agent_id(session, name: str) -> str:
    return (
        await session.execute(select(Agent.id).where(Agent.name == name))
    ).scalar_one()


class TestExpectedDataDeltas:
    async def test_jane_salchow_jump_is_two_rows_in_each_kit(self, db_reachable: bool) -> None:
        """Two hits per kit, three rows stored (#90).

        Under #85 this was "2 rows, full stop", because only the unlocked kit was
        imported. Both are now stored -- 1 base + 1 unlocked + 1 shared -- and the
        *per-kit* count is what must be 2. That is the stronger claim: it pins both
        states rather than one, and it is still the assertion that catches the phantom
        3-hit sequence which exists in neither kit.
        """
        await _skip_unless_seeded(db_reachable)
        async with async_session_factory() as session:
            agent_id = await _agent_id(session, "Jane")
            rows = (
                await session.execute(
                    select(Attack).where(
                        Attack.agent_id == agent_id,
                        Attack.name == "Basic Attack: Salchow Jump",
                    )
                )
            ).scalars().all()

        assert len(rows) == 3
        for variant in (PotentialVariant.LOCKED, PotentialVariant.UNLOCKED):
            visible = [r for r in rows if variant.includes(r.potential)]
            assert len(visible) == 2, variant
            assert sorted(r.hit_index for r in visible) == [0, 1]

        unlocked = [r for r in rows if PotentialVariant.UNLOCKED.includes(r.potential)]
        assert sum(r.anomaly_buildup for r in unlocked) == 51232

    async def test_s0_anby_penetrating_shock_is_six_rows_in_each_kit(
        self, db_reachable: bool
    ) -> None:
        """Six hits per kit, seven rows stored -- and 004/005/006 sit at 3/4/5 in BOTH.

        The index assertion is the point: a merged numbering pass puts them at 4/5/6 and
        leaves the locked kit reading [0,1,2,4,5,6] (DESIGN_potential_toggle.md §4.2).
        """
        await _skip_unless_seeded(db_reachable)
        async with async_session_factory() as session:
            agent_id = await _agent_id(session, "Soldier 0 - Anby")
            rows = (
                await session.execute(
                    select(Attack).where(
                        Attack.agent_id == agent_id,
                        Attack.name == "Basic Attack: Penetrating Shock",
                    )
                )
            ).scalars().all()

        assert len(rows) == 7
        for variant in (PotentialVariant.LOCKED, PotentialVariant.UNLOCKED):
            visible = [r for r in rows if variant.includes(r.potential)]
            assert len(visible) == 6, variant
            assert sorted(r.hit_index for r in visible) == [0, 1, 2, 3, 4, 5]

        unlocked = [r for r in rows if PotentialVariant.UNLOCKED.includes(r.potential)]
        assert sum(r.anomaly_buildup for r in unlocked) == 44536

    @pytest.mark.parametrize(
        "variant", [PotentialVariant.LOCKED, PotentialVariant.UNLOCKED]
    )
    async def test_no_agent_has_more_than_seven_core_skills_per_kit(
        self, db_reachable: bool, variant: PotentialVariant
    ) -> None:
        """Seven core-skill rows per kit (#90).

        The 6 agents who restate their whole core passive under Potential now store 14
        rows -- 7 base + 7 unlocked, with `level` 1..7 twice. That is correct, and the
        #85-era "never more than 7 in total" assertion would forbid it. What must still
        hold is 7 *per state*: the two halves carry identical `name` arrays, so a
        resolver that ignored `potential` would pick between them non-deterministically,
        which is the defect this replaces.
        """
        await _skip_unless_seeded(db_reachable)
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(Agent.name, func.count(CoreSkill.id))
                    .join(CoreSkill, CoreSkill.agent_id == Agent.id)
                    .where(_visible(CoreSkill, variant))
                    .group_by(Agent.name)
                    .having(func.count(CoreSkill.id) > 7)
                )
            ).all()

        assert rows == []

    @pytest.mark.parametrize(
        "variant", [PotentialVariant.LOCKED, PotentialVariant.UNLOCKED]
    )
    async def test_no_duplicate_core_skill_level_within_a_kit(
        self, db_reachable: bool, variant: PotentialVariant
    ) -> None:
        """`level` is unique per agent *within* one Potential state (#90).

        Duplicates across the two states are the intended shape; duplicates inside one
        are the non-deterministic pick #85 found.
        """
        await _skip_unless_seeded(db_reachable)
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(Agent.name, CoreSkill.level, func.count(CoreSkill.id))
                    .join(CoreSkill, CoreSkill.agent_id == Agent.id)
                    .where(_visible(CoreSkill, variant))
                    .group_by(Agent.name, CoreSkill.level)
                    .having(func.count(CoreSkill.id) > 1)
                )
            ).all()

        assert rows == []

    @pytest.mark.parametrize(("agent_name", "move_name"), POTENTIAL_ONLY_MOVES)
    async def test_potential_only_move_still_resolves(
        self, db_reachable: bool, agent_name: str, move_name: str
    ) -> None:
        """Every Potential-only move name must still import (agent_skills) —
        the invariant that catches a "keep only []" mis-implementation."""
        await _skip_unless_seeded(db_reachable)
        async with async_session_factory() as session:
            agent_id = await _agent_id(session, agent_name)
            row = (
                await session.execute(
                    select(AgentSkill).where(
                        AgentSkill.agent_id == agent_id, AgentSkill.name == move_name
                    )
                )
            ).scalar_one_or_none()

        assert row is not None, f"{agent_name}: {move_name!r} did not resolve"

    async def test_unlocked_view_is_exactly_what_85_stored(self, db_reachable: bool) -> None:
        """#90 must not change what an unlocked build sees — only add the locked view.

        True by construction: #85 kept entries where `0 not in potential`, which is
        precisely `potential IS NULL OR potential = 'unlocked'`. So the unlocked view
        must still cover every distinct move name in the table; if it does not, tagging
        has lost a move rather than partitioning the rows.

        The #85-era test asserted absolute literals here (699 attack names, 842 skill
        names). Those were measured at nanoka 3.1.12 with 58 agents and are now stale
        for reasons unrelated to Potential — the roster is 60. Absolute per-agent counts
        moved to `test_potential_seed_deltas.py`, where the snapshot is version-stamped
        so a patch bump is a reviewable regeneration rather than a literal someone edits.
        """
        await _skip_unless_seeded(db_reachable)
        async with async_session_factory() as session:
            for model in (Attack, AgentSkill):
                total = (
                    await session.execute(
                        select(func.count(distinct(func.concat(model.agent_id, model.name))))
                    )
                ).scalar_one()
                unlocked = (
                    await session.execute(
                        select(func.count(distinct(func.concat(model.agent_id, model.name))))
                        .where(_visible(model, PotentialVariant.UNLOCKED))
                    )
                ).scalar_one()
                assert unlocked == total, (
                    f"{model.__tablename__}: the unlocked view sees {unlocked} distinct "
                    f"move names but the table holds {total} — tagging has hidden a move "
                    f"from the state #85 modelled"
                )

    async def test_potential_only_move_name_counts_match_the_sweep(
        self, db_reachable: bool
    ) -> None:
        """The locked/unlocked name gap equals the sweep's independently-counted totals.

        `docs/RESEARCH_potential_sweep_85.md` §5 counted **18** move names that exist
        only with Potential unlocked, **16** of which also carry DMG params and so
        produce Attack rows. Those numbers were derived by a separate path (a direct
        sweep of the nanoka payloads) from the tagging under test here, so agreement is
        real corroboration rather than a restatement.
        """
        await _skip_unless_seeded(db_reachable)
        expected = {Attack: 16, AgentSkill: 18}

        async with async_session_factory() as session:
            for model, gap in expected.items():
                counts = {}
                for variant in (PotentialVariant.LOCKED, PotentialVariant.UNLOCKED):
                    counts[variant] = (
                        await session.execute(
                            select(func.count(distinct(func.concat(model.agent_id, model.name))))
                            .where(_visible(model, variant))
                        )
                    ).scalar_one()
                actual = counts[PotentialVariant.UNLOCKED] - counts[PotentialVariant.LOCKED]
                assert actual == gap, (
                    f"{model.__tablename__}: {actual} Potential-only move names, "
                    f"but the sweep counted {gap}"
                )
