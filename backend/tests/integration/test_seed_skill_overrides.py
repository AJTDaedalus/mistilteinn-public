"""Integration tests for apply_skill_overrides."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.loaders.skill_overrides import AgentOverride, MoveOverride, VariantSpec
from app.database import engine as _app_engine
from app.models.agent import Agent, Attack
from app.models.enums import Element, HitMode, Rarity, RowCondition, Specialty
from scripts.seed_skill_overrides import UnresolvableOverrideError, apply_skill_overrides

pytestmark = pytest.mark.asyncio


async def _make_agent(session: AsyncSession, name: str = "Test Agent") -> Agent:
    agent = Agent(
        hakushin_id=88880,
        name=name,
        full_name=name,
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
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
    )
    session.add(agent)
    await session.flush()
    return agent


async def _make_attacks(
    session: AsyncSession, agent: Agent, name: str, count: int, start_index: int = 0
) -> list[Attack]:
    attacks = []
    for i in range(count):
        atk = Attack(
            agent_id=agent.id,
            hakushin_skill_id=1000 + start_index + i,
            skill_key="Basic",
            name=name,
            hit_index=start_index + i,
            element=Element.FIRE,
            damage_base=1000 + (i * 500),
            damage_growth=0,
            stun_base=100,
            stun_growth=0,
            energy_gain=0,
            anomaly_buildup=0,
        )
        session.add(atk)
        attacks.append(atk)
    await session.flush()
    return attacks


async def _get_attacks(session: AsyncSession, agent_id: str, name: str) -> list[Attack]:
    result = await session.execute(
        select(Attack)
        .where(Attack.agent_id == agent_id, Attack.name == name)
        .order_by(Attack.hit_index)
    )
    return list(result.scalars().all())


async def test_sequential_move_gets_hit_mode(db_session: AsyncSession) -> None:
    agent = await _make_agent(db_session)
    await _make_attacks(db_session, agent, "Sequential Move", count=4)

    overrides = {
        "test_agent": AgentOverride(
            agent_name=agent.name,
            moves={"Sequential Move": MoveOverride(hit_mode=HitMode.SEQUENTIAL)},
        )
    }
    await apply_skill_overrides(db_session, overrides)

    updated = await _get_attacks(db_session, agent.id, "Sequential Move")
    assert len(updated) == 4
    assert all(a.hit_mode == HitMode.SEQUENTIAL for a in updated)
    assert all(a.variant_label is None for a in updated)


async def test_variant_move_gets_labels_and_renumbered(db_session: AsyncSession) -> None:
    agent = await _make_agent(db_session)
    # 3 rows: original hit_index 0, 1, 2
    await _make_attacks(db_session, agent, "Variant Move", count=3)

    overrides = {
        "test_agent": AgentOverride(
            agent_name=agent.name,
            moves={
                "Variant Move": MoveOverride(
                    hit_mode=HitMode.VARIANT,
                    variants=[
                        VariantSpec(label="Low", hit_indices=[0, 1]),
                        VariantSpec(label="High", hit_indices=[2]),
                    ],
                )
            },
        )
    }
    await apply_skill_overrides(db_session, overrides)

    updated = await _get_attacks(db_session, agent.id, "Variant Move")
    low = sorted([a for a in updated if a.variant_label == "Low"], key=lambda a: a.hit_index)
    high = [a for a in updated if a.variant_label == "High"]

    assert len(low) == 2
    assert len(high) == 1
    # hit_index renumbered 0-based within each variant
    assert [a.hit_index for a in low] == [0, 1]
    assert high[0].hit_index == 0
    assert all(a.hit_mode == HitMode.VARIANT for a in updated)


async def test_apply_is_idempotent(db_session: AsyncSession) -> None:
    agent = await _make_agent(db_session)
    await _make_attacks(db_session, agent, "Sequential Move", count=4)

    overrides = {
        "test_agent": AgentOverride(
            agent_name=agent.name,
            moves={"Sequential Move": MoveOverride(hit_mode=HitMode.SEQUENTIAL)},
        )
    }
    await apply_skill_overrides(db_session, overrides)
    # Second run should not raise and not change state
    await apply_skill_overrides(db_session, overrides)

    updated = await _get_attacks(db_session, agent.id, "Sequential Move")
    assert all(a.hit_mode == HitMode.SEQUENTIAL for a in updated)


async def test_unknown_agent_name_skips_gracefully(db_session: AsyncSession) -> None:
    overrides = {
        "nonexistent_agent": AgentOverride(
            agent_name="Nonexistent Agent",
            moves={"Some Move": MoveOverride(hit_mode=HitMode.SEQUENTIAL)},
        )
    }
    # Should not raise
    await apply_skill_overrides(db_session, overrides)


# --------------------------------------------------------------------------
# Task 7, docs/TASKS_move_key_resolution.md — Norma/Velina actually land.
#
# Requires the SEEDED PRODUCTION DB (not the isolated `fairy_test` DB the `db_session`
# fixture above uses), same as test_zo_crossval.py / test_abloom_crossval.py. Run
# manually: docker compose exec backend python -m pytest \
#     tests/integration/test_seed_skill_overrides.py::TestNormaVelinaLand -v
#
# Uses flush(), never commit() — same pattern as test_abloom_crossval.py's throwaway
# EnemyProfile rows — so nothing persists once the session closes. Safe to run
# repeatedly against the real seeded DB.
# --------------------------------------------------------------------------


@pytest.fixture
async def real_app_db():
    """AsyncSession on the seeded app DB; skips if not reachable or empty."""
    try:
        async with AsyncSession(_app_engine) as session:
            result = await session.execute(select(Agent).limit(1))
            if result.scalar_one_or_none() is None:
                pytest.skip("App DB has no agents — seeded DB required")
            yield session
    except Exception as exc:
        pytest.skip(f"App DB not reachable: {exc}")


class TestNormaVelinaLand:
    """Before Task 7: zero non-atomic hit_mode rows for either agent (DESIGN §1.1)."""

    async def test_norma_engineering_insurance_becomes_sequential(
        self, real_app_db: AsyncSession
    ) -> None:
        result = await real_app_db.execute(select(Agent).where(Agent.name == "Norma"))
        agent = result.scalar_one()

        await apply_skill_overrides(real_app_db, strict=True)

        result = await real_app_db.execute(
            select(Attack).where(
                Attack.agent_id == agent.id, Attack.name == "Basic Attack: Engineering Insurance"
            )
        )
        rows = list(result.scalars().all())
        assert rows, "Expected 'Basic Attack: Engineering Insurance' rows for Norma"
        assert all(a.hit_mode == HitMode.SEQUENTIAL for a in rows)

    async def test_velina_dancing_fans_becomes_sequential(self, real_app_db: AsyncSession) -> None:
        result = await real_app_db.execute(select(Agent).where(Agent.name == "Velina"))
        agent = result.scalar_one()

        await apply_skill_overrides(real_app_db, strict=True)

        result = await real_app_db.execute(
            select(Attack).where(
                Attack.agent_id == agent.id, Attack.name == "Basic Attack: Dancing Fans"
            )
        )
        rows = list(result.scalars().all())
        assert rows, "Expected 'Basic Attack: Dancing Fans' rows for Velina"
        assert all(a.hit_mode == HitMode.SEQUENTIAL for a in rows)

    async def test_strict_mode_succeeds_over_the_full_real_corpus(
        self, real_app_db: AsyncSession
    ) -> None:
        """--strict must not raise over the real, currently-shipped skill_overrides/.

        This is the regression guard: if a future edit reintroduces an unresolvable
        agent_name or move key anywhere in the directory, --strict (which a release
        seed should use) fails loudly instead of silently skipping it.
        """
        await apply_skill_overrides(real_app_db, strict=True)  # must not raise


async def test_channel_override_is_applied_not_silently_dropped(
    db_session: AsyncSession,
) -> None:
    """`hit_mode: channel` must reach the DB.

    The dispatch was `if SEQUENTIAL / elif VARIANT` with no else, so a channel override
    parsed, validated, logged nothing, and left every row `atomic` — the move file would
    describe a channel while the engine ran the old instantaneous path, and every test that
    reads the JSON rather than the DB would still pass. Task 12 hit exactly this.
    """
    agent = await _make_agent(db_session, name="Channel Agent")
    await _make_attacks(db_session, agent, "EX Special Attack: Spray", 2)

    await apply_skill_overrides(
        db_session,
        {
            "channel_agent": AgentOverride(
                agent_name="Channel Agent",
                moves={"EX Special Attack: Spray": MoveOverride(hit_mode=HitMode.CHANNEL)},
            )
        },
    )

    rows = (
        (
            await db_session.execute(
                select(Attack).where(Attack.name == "EX Special Attack: Spray")
            )
        )
        .scalars()
        .all()
    )
    assert rows
    assert all(r.hit_mode == HitMode.CHANNEL for r in rows)
    assert all(r.variant_label is None for r in rows)


async def test_row_conditions_land_on_the_named_rows_only(db_session: AsyncSession) -> None:
    """`row_conditions` gates rows by `param_name`; every other row stays unconditional.

    NULL must keep meaning "always fires" — that is what makes a migrated-but-not-re-seeded
    DB degrade to today's behaviour instead of to silently-dropped hits, and it is why an
    absent entry can never hide a row.
    """
    agent = await _make_agent(db_session, name="Conditional Agent")
    attacks = await _make_attacks(db_session, agent, "EX Special Attack: Turret", 3)
    for atk, param in zip(attacks, ["Shot", "AP Warhead", "HE Warhead"], strict=True):
        atk.param_name = param
    await db_session.flush()

    await apply_skill_overrides(
        db_session,
        {
            "conditional_agent": AgentOverride(
                agent_name="Conditional Agent",
                moves={
                    "EX Special Attack: Turret": MoveOverride(
                        hit_mode=HitMode.CHANNEL,
                        row_conditions={
                            "AP Warhead": RowCondition.ENEMY_NOT_STUNNED,
                            "HE Warhead": RowCondition.ENEMY_STUNNED,
                        },
                    )
                },
            )
        },
    )

    rows = (
        (
            await db_session.execute(
                select(Attack).where(Attack.name == "EX Special Attack: Turret")
            )
        )
        .scalars()
        .all()
    )
    by_param = {r.param_name: r.select_when for r in rows}
    assert by_param["Shot"] is None
    assert by_param["AP Warhead"] == RowCondition.ENEMY_NOT_STUNNED
    assert by_param["HE Warhead"] == RowCondition.ENEMY_STUNNED


async def test_a_row_condition_naming_no_row_is_not_silent(db_session: AsyncSession) -> None:
    """A typo'd `param_name` must be visible, not a no-op.

    The whole point of keying by label is that labels are stable; a label that matches
    nothing means the curator is wrong about this agent's rows, which is exactly the
    per-agent-scoping error #77 shipped.
    """
    agent = await _make_agent(db_session, name="Typo Agent")
    attacks = await _make_attacks(db_session, agent, "EX Special Attack: Turret", 1)
    attacks[0].param_name = "Shot"
    await db_session.flush()

    with pytest.raises(UnresolvableOverrideError, match="row_conditions"):
        await apply_skill_overrides(
            db_session,
            {
                "typo_agent": AgentOverride(
                    agent_name="Typo Agent",
                    moves={
                        "EX Special Attack: Turret": MoveOverride(
                            hit_mode=HitMode.CHANNEL,
                            row_conditions={"Shoot": RowCondition.ENEMY_STUNNED},
                        )
                    },
                )
            },
            strict=True,
        )


async def test_split_moves_lifts_a_row_into_its_own_move(db_session: AsyncSession) -> None:
    """The row leaves; the rest of the move stays resolvable under its original name."""
    agent = await _make_agent(db_session, name="Split Agent")
    attacks = await _make_attacks(db_session, agent, "Basic Attack: Stance", 3)
    for atk, param in zip(attacks, ["Shot", "Counter", "Finishing Move"], strict=True):
        atk.param_name = param
    await db_session.flush()

    await apply_skill_overrides(
        db_session,
        {
            "split_agent": AgentOverride(
                agent_name="Split Agent",
                moves={
                    "Basic Attack: Stance": MoveOverride(
                        hit_mode=HitMode.CHANNEL,
                        split_moves={"Counter": "Basic Attack: Stance - Counter"},
                    )
                },
            )
        },
    )

    rows = (
        (await db_session.execute(select(Attack).where(Attack.agent_id == agent.id)))
        .scalars()
        .all()
    )
    by_name: dict[str, list[str]] = {}
    for r in rows:
        by_name.setdefault(r.name, []).append(r.param_name or "")
    assert sorted(by_name["Basic Attack: Stance"]) == ["Finishing Move", "Shot"]
    assert by_name["Basic Attack: Stance - Counter"] == ["Counter"]
    moved = next(r for r in rows if r.name == "Basic Attack: Stance - Counter")
    assert moved.hit_index == 0


async def test_a_split_that_would_empty_the_parent_raises(db_session: AsyncSession) -> None:
    """That is a rename, not a split, and it breaks every step naming the original."""
    agent = await _make_agent(db_session, name="Empty Split Agent")
    attacks = await _make_attacks(db_session, agent, "Basic Attack: Solo", 1)
    attacks[0].param_name = "Only"
    await db_session.flush()

    with pytest.raises(UnresolvableOverrideError, match="rename, not a split"):
        await apply_skill_overrides(
            db_session,
            {
                "empty_split_agent": AgentOverride(
                    agent_name="Empty Split Agent",
                    moves={
                        "Basic Attack: Solo": MoveOverride(
                            hit_mode=HitMode.ATOMIC,
                            split_moves={"Only": "Basic Attack: Solo - Elsewhere"},
                        )
                    },
                )
            },
        )


async def test_a_split_naming_no_row_is_not_silent(db_session: AsyncSession) -> None:
    agent = await _make_agent(db_session, name="Typo Split Agent")
    attacks = await _make_attacks(db_session, agent, "Basic Attack: Stance", 2)
    for atk, param in zip(attacks, ["Shot", "Counter"], strict=True):
        atk.param_name = param
    await db_session.flush()

    with pytest.raises(UnresolvableOverrideError, match="split_moves"):
        await apply_skill_overrides(
            db_session,
            {
                "typo_split_agent": AgentOverride(
                    agent_name="Typo Split Agent",
                    moves={
                        "Basic Attack: Stance": MoveOverride(
                            hit_mode=HitMode.CHANNEL,
                            split_moves={"Countre": "Basic Attack: Stance - Counter"},
                        )
                    },
                )
            },
            strict=True,
        )


async def test_a_split_row_does_not_inherit_the_parents_hit_mode(
    db_session: AsyncSession,
) -> None:
    """The split must run BEFORE the mode branch, not after.

    Ordered after, the dispatch stamps `hit_mode` on a row that is about to become a different
    move — and that is not hypothetical: the first run of this code left Trigger's `Counter`
    carrying `hit_mode='channel'` after it had been split out of `Silenced Shot`, so a
    standalone move claimed to be a channel with no spec behind it. The symptom downstream is a
    warning and an atomic fallback, i.e. quiet.
    """
    agent = await _make_agent(db_session, name="Order Agent")
    attacks = await _make_attacks(db_session, agent, "Basic Attack: Stance", 2)
    for atk, param in zip(attacks, ["Shot", "Counter"], strict=True):
        atk.param_name = param
    await db_session.flush()

    await apply_skill_overrides(
        db_session,
        {
            "order_agent": AgentOverride(
                agent_name="Order Agent",
                moves={
                    "Basic Attack: Stance": MoveOverride(
                        hit_mode=HitMode.CHANNEL,
                        split_moves={"Counter": "Basic Attack: Stance - Counter"},
                    )
                },
            )
        },
    )

    rows = (
        (await db_session.execute(select(Attack).where(Attack.agent_id == agent.id)))
        .scalars()
        .all()
    )
    kept = next(r for r in rows if r.name == "Basic Attack: Stance")
    moved = next(r for r in rows if r.name == "Basic Attack: Stance - Counter")
    assert kept.hit_mode == HitMode.CHANNEL
    assert moved.hit_mode == HitMode.ATOMIC, (
        "the split row inherited the parent's hit_mode — the split ran after the mode branch"
    )


async def test_applying_a_split_twice_is_a_no_op(db_session: AsyncSession) -> None:
    """A split must be idempotent, and "already split" must not read as "typo".

    `apply_skill_overrides` runs on every seed and can be run standalone against a DB that has
    already been through it. Every other override is idempotent for free — re-setting a column to
    the value it holds does nothing — but a rename cannot find its own source a second time.
    By `param_name` alone that is indistinguishable from a curator typo, so the second pass has
    to look for the row at its destination.
    """
    agent = await _make_agent(db_session, name="Twice Agent")
    attacks = await _make_attacks(db_session, agent, "Basic Attack: Stance", 2)
    for atk, param in zip(attacks, ["Shot", "Counter"], strict=True):
        atk.param_name = param
    await db_session.flush()

    overrides = {
        "twice_agent": AgentOverride(
            agent_name="Twice Agent",
            moves={
                "Basic Attack: Stance": MoveOverride(
                    hit_mode=HitMode.CHANNEL,
                    split_moves={"Counter": "Basic Attack: Stance - Counter"},
                )
            },
        )
    }

    await apply_skill_overrides(db_session, overrides, strict=True)
    # Second pass, strict: must not raise, and must not move anything else.
    await apply_skill_overrides(db_session, overrides, strict=True)

    rows = (
        (await db_session.execute(select(Attack).where(Attack.agent_id == agent.id)))
        .scalars()
        .all()
    )
    names = sorted(r.name for r in rows)
    assert names == ["Basic Attack: Stance", "Basic Attack: Stance - Counter"]
