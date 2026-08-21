"""Parity tests across simulate / optimizer / damage / rank for identical buff state.

TDD per docs/TASKS_buff_context.md. DESIGN_buff_context.md §2.1 is the rule
under test: the server should resolve buff state from the request and only
from the request. Split into two concerns, deliberately not bundled into one
number, so each endpoint's fix (Tasks A2-A5) can turn its own case green
independently of the other:

- ``TestActiveConditionsAndStacks`` — active_conditions + stack_counts
  precedence. One case per endpoint; each goes green as its own task lands
  (A2 simulate, A3 optimizer, A4 damage, A5 rank).
- ``TestDisabledBuffsFromRequest`` — whether a request-level ``disabled_buffs``
  reaches the calc at all. None of the four endpoints have this field today
  (only ``build.disabled_buffs`` is ever read) — pinned to Task A6's decision;
  expected to stay red until A6 either wires it up or escalates it away from
  BuffContext per DESIGN §7 Q1.

Do not fix any endpoint in Task A1 — that task exists only to record this
red state in docs/LOG_buff_context.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.enums import Element, Rarity, Specialty
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.team import TeamRepository
from app.schemas.optimizer import DiscOptimizeRequest
from app.schemas.scorer import RankContextSchema, RankRequest
from app.services.build_damage_service import resolve_build_stats
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.optimizer_pipeline import resolve_optimize_payload
from app.services.rank_pipeline import resolve_rank_payload
from app.services.snapshot_builder import buff_id, build_snapshot_from_db

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_AGENT_HAKUSHIN_ID = 96900
_BASE_ATK = 1000

_CONTEXT_ACTIVE_CONDITIONS = ["always", "hp_above_50"]
_CONTEXT_STACK_COUNTS = {"test:stack_atk": 2}

_MODULE_TARGET = "app.services.snapshot_builder.load_agent_modifiers"
_SUPPORT_MODULE_TARGET = "app.services.support_recompute.load_agent_modifiers"

_CONDITIONAL_ATK = Modifier(
    stat="atk_pct",
    value=5000,
    source=ModifierSource.EXTERNAL,
    source_label="test:conditional_atk",
    target=ModifierTarget.SELF,
    conditions=(Condition.HP_ABOVE_50,),
    scopes=(AttackScope.ALL,),
    max_stacks=1,
)
_STACK_ATK = Modifier(
    stat="atk_pct",
    value=1000,
    source=ModifierSource.EXTERNAL,
    source_label="test:stack_atk",
    target=ModifierTarget.SELF,
    conditions=(Condition.ALWAYS,),
    scopes=(AttackScope.ALL,),
    max_stacks=4,
)
_DISABLE_ME = Modifier(
    stat="atk_pct",
    value=2000,
    source=ModifierSource.EXTERNAL,
    source_label="test:disable_me",
    target=ModifierTarget.SELF,
    conditions=(Condition.ALWAYS,),
    scopes=(AttackScope.ALL,),
    max_stacks=1,
)


def _base_modifiers() -> list[Modifier]:
    """Conditional + stackable only -- isolates active_conditions/stack_counts."""
    return [_CONDITIONAL_ATK, _STACK_ATK]


def _all_modifiers() -> list[Modifier]:
    """Base + a disableable buff -- isolates the disabled_buffs question."""
    return [*_base_modifiers(), _DISABLE_ME]


async def _seed(authed_client: AsyncClient, db: AsyncSession) -> dict:
    agent = Agent(
        hakushin_id=_AGENT_HAKUSHIN_ID,
        name="BuffContextParityAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=_BASE_ATK,
        base_hp=8000,
        base_def=600,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    enemy = EnemyProfile(name="BuffContextParityDummy", level=60, defense=50, fire_res=0)
    db.add_all([agent, enemy])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=300,
        skill_key="Basic",
        name="BuffContextParityHit",
        hit_index=0,
        element=Element.FIRE,
        damage_base=10000,
        damage_growth=0,
    )
    db.add(attack)
    await db.flush()

    build_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "ParityBuild", "agent_id": str(agent.id)},
    )
    assert build_resp.status_code == 201, build_resp.text
    build_id = build_resp.json()["id"]

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "ParityTeam", "build1_id": build_id},
    )
    assert team_resp.status_code == 201, team_resp.text
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "ParityCombo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(attack.id), "label": "hit"}],
        },
    )
    assert combo_resp.status_code == 201, combo_resp.text
    combo_id = combo_resp.json()["id"]

    return {
        "hakushin_id": _AGENT_HAKUSHIN_ID,
        "agent_id": str(agent.id),
        "enemy_id": str(enemy.id),
        "attack_id": str(attack.id),
        "attack_name": attack.name,
        "build_id": build_id,
        "team_id": team_id,
        "combo_id": combo_id,
    }


async def _expected_base_atk(db: AsyncSession, build_id: str) -> int:
    """atk a correctly-implemented server resolves for _base_modifiers().

    HP_ABOVE_50 active (conditional buff on), 2 of 4 stacks (partial stack
    buff) -- what Tasks A2-A5 should make every endpoint converge on,
    independent of the disabled_buffs question.
    """
    build_repo = BuildRepository(db)
    build = await build_repo.get_by_id(build_id)
    with patch(_MODULE_TARGET, return_value=_base_modifiers()):
        snap = build_snapshot_from_db(build, build.agent, support_builds=[])
    stats = resolve_build_stats(
        snap,
        ActiveConditions(
            active={Condition.ALWAYS, Condition.HP_ABOVE_50},
            stack_counts=dict(_CONTEXT_STACK_COUNTS),
        ),
    )
    return stats.atk


async def _damage_atk(
    authed_client: AsyncClient,
    db: AsyncSession,
    seed: dict,
    active_conditions: list[str],
    stack_counts: dict[str, int],
    disabled_buffs: list[str] | None = None,
    custom_buffs: list[dict] | None = None,
) -> int:
    resp = await authed_client.post(
        "/api/v1/damage/build",
        json={
            "build_id": seed["build_id"],
            "attack_id": seed["attack_id"],
            "enemy_profile_id": seed["enemy_id"],
            "buff_context": {
                "active_conditions": active_conditions,
                "stack_counts": stack_counts,
                "disabled_buffs": disabled_buffs or [],
                "custom_buffs": custom_buffs or [],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["total_atk"]


async def _simulate_atk(
    authed_client: AsyncClient,
    db: AsyncSession,
    seed: dict,
    active_conditions: list[str],
    stack_counts: dict[str, int],
    disabled_buffs: list[str] | None = None,
    custom_buffs: list[dict] | None = None,
) -> int:
    resp = await authed_client.post(
        "/api/v1/simulate",
        json={
            "team_builds": {"dps": seed["build_id"]},
            "steps": [{"agent_id": "dps", "move_name": seed["attack_name"]}],
            "enemy_profile_id": seed["enemy_id"],
            "buff_context": {
                "active_conditions": active_conditions,
                "stack_counts": stack_counts,
                "disabled_buffs": disabled_buffs or [],
                "custom_buffs": custom_buffs or [],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    hit_ev = next(e for e in resp.json()["events"] if e["kind"] == "hit")
    return hit_ev["detail"]["effective_atk"]


async def _optimizer_atk(
    authed_client: AsyncClient,
    db: AsyncSession,
    seed: dict,
    active_conditions: list[str],
    stack_counts: dict[str, int],
    disabled_buffs: list[str] | None = None,
    custom_buffs: list[dict] | None = None,
) -> int:
    # Calls resolve_optimize_payload directly (service layer) rather than the
    # HTTP endpoint, avoiding the full CPU-bound disc search for a stat-only
    # check -- an established pattern (test_optimizer_priority_pool.py).
    body = DiscOptimizeRequest(
        team_id=seed["team_id"],
        combo_id=seed["combo_id"],
        enemy_profile_id=seed["enemy_id"],
        active_conditions=active_conditions,
        stack_counts=stack_counts,
        disabled_buffs=disabled_buffs or [],
        custom_buffs=custom_buffs or [],
    )
    payload = await resolve_optimize_payload(
        db,
        body,
        ComboRepository(db),
        BuildRepository(db),
        AttackRepository(db),
        EnemyProfileRepository(db),
        team_repo=TeamRepository(db),
    )
    return resolve_build_stats(payload.scoring_snap, payload.conditions).atk


async def _rank_atk(
    authed_client: AsyncClient,
    db: AsyncSession,
    seed: dict,
    active_conditions: list[str],
    stack_counts: dict[str, int],
    disabled_buffs: list[str] | None = None,
    custom_buffs: list[dict] | None = None,
) -> int:
    # Calls resolve_rank_payload directly (service layer), avoiding the
    # process-pool disc scorer for a stat-only check.
    body = RankRequest(
        contexts=[
            RankContextSchema(
                combo_id=seed["combo_id"],
                enemy_profile_id=seed["enemy_id"],
                build_id=seed["build_id"],
                active_conditions=active_conditions,
                stack_counts=stack_counts,
                disabled_buffs=disabled_buffs or [],
                custom_buffs=custom_buffs or [],
            )
        ],
    )
    payload = await resolve_rank_payload(
        db,
        body,
        build_repo=BuildRepository(db),
        combo_repo=ComboRepository(db),
        attack_repo=AttackRepository(db),
        enemy_repo=EnemyProfileRepository(db),
    )
    ctx = payload.contexts[0]
    return resolve_build_stats(ctx.scoring_base, ctx.conditions).atk


_RESOLVERS = {
    "damage": _damage_atk,
    "simulate": _simulate_atk,
    "optimizer": _optimizer_atk,
    "rank": _rank_atk,
}


class TestActiveConditionsAndStacks:
    """Does each endpoint resolve active_conditions/stack_counts from the request?

    No disabled_buffs involved -- that's a separate concern (see
    TestDisabledBuffsFromRequest below) so each of these can go green as its
    own task (A2-A5) lands, without waiting on A6.
    """

    @pytest.mark.parametrize("endpoint", ["damage", "simulate", "optimizer", "rank"])
    async def test_endpoint_resolves_context_from_request(
        self,
        endpoint: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        seed = await _seed(authed_client, db_session)
        await db_session.commit()

        with patch(_MODULE_TARGET, return_value=_base_modifiers()):
            expected = await _expected_base_atk(db_session, seed["build_id"])
            actual = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                _CONTEXT_ACTIVE_CONDITIONS,
                _CONTEXT_STACK_COUNTS,
            )

        assert actual == expected, (
            f"{endpoint}: expected atk={expected} (HP_ABOVE_50 on, 2/4 stacks) "
            f"from the request context, got {actual}. See "
            f"docs/LOG_buff_context.md Task A1 for the root cause."
        )


class TestAlwaysConditionIsNeverUserToggleable:
    """Does omitting ``"always"`` from a non-empty context drop the baseline?

    The Builds conditions endpoint never lists ``always`` (``_SKIP_CONDITIONS``
    in ``api/v1/builds.py``) because it is not user-toggleable, so a build's
    saved ``active_conditions`` never contains it — buff-toggles.ts persists
    exactly the set of conditions the user checked. Since #93 the client sends
    those columns verbatim, so every real request from a build with one
    condition toggled on arrives as e.g. ``["hp_above_50"]``.

    ``_parse_conditions`` used to inject ``ALWAYS`` only for an *empty* list,
    so such a request gated off every unconditional modifier — the whole buff
    baseline. /damage and /simulate were unaffected (``team_calculator.
    _merge_conditions`` unions ``ALWAYS`` on their path); the optimizer and
    rank read the parsed conditions directly and lost ~21% ATK on the fixture
    below. Found reviewing #96 (#95's per-context rank seeding, which makes
    rank hit this deterministically rather than by navigation accident).
    """

    @pytest.mark.parametrize("endpoint", ["damage", "simulate", "optimizer", "rank"])
    async def test_omitting_always_does_not_drop_unconditional_buffs(
        self,
        endpoint: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        seed = await _seed(authed_client, db_session)
        await db_session.commit()

        with patch(_MODULE_TARGET, return_value=_base_modifiers()):
            with_always = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                _CONTEXT_ACTIVE_CONDITIONS,
                _CONTEXT_STACK_COUNTS,
            )
            # What the client actually sends: the saved column, which cannot
            # contain "always".
            without_always = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                [c for c in _CONTEXT_ACTIVE_CONDITIONS if c != "always"],
                _CONTEXT_STACK_COUNTS,
            )

        assert without_always == with_always, (
            f"{endpoint}: dropping 'always' from active_conditions changed atk "
            f"{with_always} -> {without_always}. ALWAYS marks a modifier as "
            f"unconditional and is not user-toggleable; it must be unioned in "
            f"regardless of what the request carries."
        )


class TestDisabledBuffsFromRequest:
    """Can a request-level disabled_buffs exclude a modifier from the calc?

    Resolved 2026-07-28 (Task A6, DESIGN §7 Q1): disabled_buffs stays in
    BuffContext, threaded to the three read sites in snapshot_builder.py /
    support_recompute.py. Each resolver now sends the disabled id through the
    request; before A6 landed, none of the four endpoints had a way to do
    this at all (only build.disabled_buffs was ever read).
    """

    @pytest.mark.parametrize("endpoint", ["damage", "simulate", "optimizer", "rank"])
    async def test_endpoint_can_disable_a_buff_via_request(
        self,
        endpoint: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        seed = await _seed(authed_client, db_session)
        await db_session.commit()
        disabled_id = buff_id(seed["hakushin_id"], "test:disable_me")

        with patch(_MODULE_TARGET, return_value=_all_modifiers()):
            expected = await _expected_base_atk(db_session, seed["build_id"])
            actual = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                _CONTEXT_ACTIVE_CONDITIONS,
                _CONTEXT_STACK_COUNTS,
                [disabled_id],
            )

        assert actual == expected, (
            f"{endpoint}: expected atk={expected} with 'test:disable_me' "
            f"excluded via a request-level disabled_buffs, got {actual} -- "
            f"the buff's contribution is still present. See Task A6."
        )


_STAGE_BUFF_FLAT_ATK = 500
_STAGE_BUFF = {
    "label": "DA Stage 3: squad ATK",
    "stat": "flat_atk",
    "value": _STAGE_BUFF_FLAT_ATK,
    "target": "team",
}


class TestCustomBuffsReachEveryEndpoint:
    """Does a stage buff (#64) resolve identically on all four entry points?

    Task B5a. ``custom_buffs`` shipped on ``BuffContext`` in B1/B4, which reaches
    ``/damage/build`` and ``/simulate`` — but the optimizer and rank requests never
    adopted ``BuffContext``, so until B5a a Deadly-Assault buff could not be expressed
    on the two surfaces where it matters most: you optimize *for* a stage, and the
    discs a stage buff favours are exactly what the run is meant to find.

    Parameterized over the same four resolvers as the Phase A suites, for the same
    reason — the failure mode is not "wrong number" but "silently no number at all on
    two of four endpoints", which only a per-endpoint parity assertion catches.
    """

    @pytest.mark.parametrize("endpoint", ["damage", "simulate", "optimizer", "rank"])
    async def test_endpoint_applies_a_custom_buff_from_the_request(
        self,
        endpoint: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        seed = await _seed(authed_client, db_session)
        await db_session.commit()

        with patch(_MODULE_TARGET, return_value=_base_modifiers()):
            plain = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                _CONTEXT_ACTIVE_CONDITIONS,
                _CONTEXT_STACK_COUNTS,
            )
            buffed = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                _CONTEXT_ACTIVE_CONDITIONS,
                _CONTEXT_STACK_COUNTS,
                None,
                [_STAGE_BUFF],
            )

        assert buffed == plain + _STAGE_BUFF_FLAT_ATK, (
            f"{endpoint}: a flat_atk stage buff of {_STAGE_BUFF_FLAT_ATK} moved atk "
            f"{plain} -> {buffed}. `custom_buffs` must reach the snapshot on every "
            f"entry point, not only the two that take a BuffContext (Task B5a)."
        )

    @pytest.mark.parametrize("endpoint", ["damage", "simulate", "optimizer", "rank"])
    async def test_endpoint_can_disable_a_custom_buff_by_its_slug(
        self,
        endpoint: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """`custom:<slug>` addresses a stage buff without an agent prefix.

        A stage buff belongs to the encounter, not to an agent, so its id must not be
        agent-qualified the way ``buff_id()`` values are — otherwise switching it off
        would apply to the DPS and leave it on for the supports.
        """
        seed = await _seed(authed_client, db_session)
        await db_session.commit()

        with patch(_MODULE_TARGET, return_value=_base_modifiers()):
            plain = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                _CONTEXT_ACTIVE_CONDITIONS,
                _CONTEXT_STACK_COUNTS,
            )
            switched_off = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                _CONTEXT_ACTIVE_CONDITIONS,
                _CONTEXT_STACK_COUNTS,
                ["custom:da_stage_3_squad_atk"],
                [_STAGE_BUFF],
            )

        assert switched_off == plain, (
            f"{endpoint}: 'custom:da_stage_3_squad_atk' in disabled_buffs left the "
            f"stage buff applied (atk {plain} -> {switched_off})."
        )


_TEAM_BUFF = Modifier(
    stat="atk_pct",
    value=3000,
    source=ModifierSource.EXTERNAL,
    source_label="test:team_disable_me",
    target=ModifierTarget.TEAM,
    conditions=(Condition.ALWAYS,),
    scopes=(AttackScope.ALL,),
    max_stacks=1,
)


async def _seed_with_support(authed_client: AsyncClient, db: AsyncSession) -> dict:
    """``_seed`` plus a second agent/build slotted as the team's support."""
    seed = await _seed(authed_client, db)

    support_agent = Agent(
        hakushin_id=_AGENT_HAKUSHIN_ID + 1,
        name="BuffContextParitySupport",
        element=Element.FIRE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
        base_atk=_BASE_ATK,
        base_hp=8000,
        base_def=600,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    db.add(support_agent)
    await db.flush()

    build_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "ParitySupportBuild", "agent_id": str(support_agent.id)},
    )
    assert build_resp.status_code == 201, build_resp.text
    support_build_id = build_resp.json()["id"]

    patch_resp = await authed_client.patch(
        f"/api/v1/teams/{seed['team_id']}",
        json={"build2_id": support_build_id},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    seed["support_hakushin_id"] = support_agent.hakushin_id
    seed["support_build_id"] = support_build_id
    return seed


class TestSupportDisabledBuffsFromRequest:
    """Can a support's TEAM-target buff be excluded via the DPS request's context?

    The single-build ``TestDisabledBuffsFromRequest`` cases above never
    involve a second build, so they cannot exercise
    ``snapshot_builder.py:916`` (``_support_modifiers``, folded into the DPS
    snapshot via ``build_snapshot_from_db``'s ``support_builds`` argument) or
    ``support_recompute.py:176`` (``build_support_recompute_kit``, used by
    rank's ``support_slot`` path). Both take the same request-scoped
    ``disabled_buffs`` list as the DPS's own read site -- entries are
    agent-qualified (``buff_id()``), so one flat list distinguishes the
    support's copy of a buff from the DPS's own copy of the same label.
    """

    async def test_optimizer_can_disable_a_supports_team_buff(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Covers snapshot_builder.py:916 via resolve_optimize_payload's support fold."""
        seed = await _seed_with_support(authed_client, db_session)
        await db_session.commit()
        support_disabled_id = buff_id(seed["support_hakushin_id"], "test:team_disable_me")

        base_kwargs = {
            "team_id": seed["team_id"],
            "combo_id": seed["combo_id"],
            "enemy_profile_id": seed["enemy_id"],
            "active_index": 0,
        }

        async def _resolve(disabled_buffs: list[str]) -> int:
            body = DiscOptimizeRequest(disabled_buffs=disabled_buffs, **base_kwargs)
            payload = await resolve_optimize_payload(
                db_session,
                body,
                ComboRepository(db_session),
                BuildRepository(db_session),
                AttackRepository(db_session),
                EnemyProfileRepository(db_session),
                team_repo=TeamRepository(db_session),
            )
            return resolve_build_stats(payload.scoring_snap, payload.conditions).atk

        with patch(_MODULE_TARGET, return_value=[_TEAM_BUFF]):
            enabled_atk = await _resolve([])
            disabled_atk = await _resolve([support_disabled_id])

        assert disabled_atk < enabled_atk, (
            "disabling the support's team buff via the DPS request's "
            f"disabled_buffs should lower the DPS's resolved atk; got "
            f"enabled={enabled_atk}, disabled={disabled_atk}. See Task A6 "
            "(snapshot_builder.py:916)."
        )

    async def test_rank_support_slot_can_disable_a_supports_buff(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Covers support_recompute.py:176 via resolve_rank_payload's support_slot path."""
        seed = await _seed_with_support(authed_client, db_session)
        await db_session.commit()
        support_disabled_id = buff_id(seed["support_hakushin_id"], "test:team_disable_me")

        async def _resolve(disabled_buffs: list[str]) -> list:
            body = RankRequest(
                contexts=[
                    RankContextSchema(
                        combo_id=seed["combo_id"],
                        enemy_profile_id=seed["enemy_id"],
                        team_id=seed["team_id"],
                        active_index=0,
                        support_slot=1,
                        disabled_buffs=disabled_buffs,
                    )
                ],
            )
            payload = await resolve_rank_payload(
                db_session,
                body,
                build_repo=BuildRepository(db_session),
                combo_repo=ComboRepository(db_session),
                attack_repo=AttackRepository(db_session),
                enemy_repo=EnemyProfileRepository(db_session),
                support_builds_by_build_id={
                    seed["build_id"]: [
                        (await BuildRepository(db_session).get_by_id(seed["support_build_id"]))
                    ],
                },
                team_repo=TeamRepository(db_session),
            )
            kit = payload.contexts[0].support_recompute_kit
            assert kit is not None
            return kit.agent_kit_mods_prefiltered

        # support_recompute.py imports load_agent_modifiers into its own module
        # namespace (separate from snapshot_builder's), so build_support_recompute_kit
        # needs its own patch target alongside _MODULE_TARGET.
        with (
            patch(_MODULE_TARGET, return_value=[_TEAM_BUFF]),
            patch(_SUPPORT_MODULE_TARGET, return_value=[_TEAM_BUFF]),
        ):
            enabled_mods = await _resolve([])
            disabled_mods = await _resolve([support_disabled_id])

        assert any(m.source_label == "test:team_disable_me" for m in enabled_mods), (
            "sanity check: the support's team buff should be present in the "
            "recompute kit when nothing is disabled."
        )
        assert not any(m.source_label == "test:team_disable_me" for m in disabled_mods), (
            "disabling the support's buff via the DPS request's "
            "disabled_buffs should exclude it from the support recompute "
            "kit. See Task A6 (support_recompute.py:176)."
        )


class TestBuildColumnsDoNotAffectCalculation:
    """DESIGN §2.1 guard: the server resolves buff state from the request and
    only from the request.

    Executable form of that rule (Task A7) -- mutates
    ``build.active_conditions`` / ``stack_counts`` / ``disabled_buffs``
    directly in the DB (via ``PATCH /api/v1/builds/{id}``, the same path the
    defaults editor uses per DESIGN §2.2), sends the *same* fixed
    ``BuffContext`` before and after, and asserts the result does not move.
    Each mutation is chosen to move the result if it leaked through: the
    conditional buff would turn on, the stackable buff would max out, and
    the disableable buff would drop out -- so a future change that quietly
    reintroduces any one of the three build reads makes this test fail.
    """

    @pytest.mark.parametrize("endpoint", ["damage", "simulate", "optimizer", "rank"])
    async def test_build_columns_do_not_affect_calculation(
        self,
        endpoint: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        seed = await _seed(authed_client, db_session)
        await db_session.commit()
        disabled_id = buff_id(seed["hakushin_id"], "test:disable_me")

        fixed_active_conditions = ["always"]
        fixed_stack_counts: dict[str, int] = {}
        fixed_disabled_buffs: list[str] = []

        with patch(_MODULE_TARGET, return_value=_all_modifiers()):
            before = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                fixed_active_conditions,
                fixed_stack_counts,
                fixed_disabled_buffs,
            )

            # Mutate the build's own columns to values that would move the
            # result if any of the three were ever read mid-calculation:
            # activates the conditional buff, maxes the stackable buff, and
            # disables the disableable buff -- opposite of what the fixed
            # request above says.
            patch_resp = await authed_client.patch(
                f"/api/v1/builds/{seed['build_id']}",
                json={
                    "active_conditions": ["always", "hp_above_50"],
                    "stack_counts": {"test:stack_atk": 4},
                    "disabled_buffs": [disabled_id],
                },
            )
            assert patch_resp.status_code == 200, patch_resp.text
            await db_session.commit()

            after = await _RESOLVERS[endpoint](
                authed_client,
                db_session,
                seed,
                fixed_active_conditions,
                fixed_stack_counts,
                fixed_disabled_buffs,
            )

        assert after == before, (
            f"{endpoint}: mutating build.active_conditions/stack_counts/"
            f"disabled_buffs changed the result ({before} -> {after}) even "
            "though the request's BuffContext was unchanged -- a build "
            "column leaked into the calc. See Task A7 / DESIGN §2.1."
        )
