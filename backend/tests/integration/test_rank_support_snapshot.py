"""Issue #121 — a support's team modifier is counted exactly once, on every path.

One snapshot used to feed two consumers with **opposite** requirements:

* the **scorer** (``evaluate_steps_total`` / ``score_disc_potential`` /
  ``_build_base_for_target``) re-scores each step against the snapshot it is
  handed, so ``build.modifiers`` is the only route by which a support's team
  buff reaches a score — it needs supports **present**;
* the **simulator** (``resolve_stateful_am_step_lists`` → ``anomaly_simulator``)
  merges every teammate's TEAM/ACTIVE modifier into the acting agent itself and
  ``resolve_modifiers`` sums duplicates with no dedupe — it needs supports
  **absent**.

There was one ``support_builds=`` switch, so each pipeline was wrong for one of
its consumers: the optimizer passed it (right for the scorer, double-counted in
the simulator) and rank/scorer omitted it (right for the simulator, supports
contributed nothing to any disc score). ``build_snapshot_split`` now returns one
snapshot per consumer; these tests pin the property on **both** pipelines.

Started life as the #97 harness for rank's support-slot path; that test is still
here (``TestSupportTeamModifierCountedOnce``) and still passes unchanged in
meaning — what changed is that the exactly-once guarantee now comes from a
deliberate split rather than from an omission that happened to be right.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.team import TeamRepository
from app.schemas.optimizer import DiscOptimizeRequest
from app.schemas.scorer import RankContextSchema, RankRequest
from app.services.build_damage_service import BuildSnapshot, resolve_build_stats
from app.services.damage_dag_service import evaluate_steps_total as _real_evaluate_steps_total
from app.services.disc_optimizer import DiscCandidate
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.optimizer_pipeline import (
    resolve_optimize_payload,
    resolve_stateful_am_step_lists,
)
from app.services.rank_pipeline import _score_pair, resolve_rank_payload
from app.services.scorer_support import _build_base_for_target as _real_build_base_for_target
from app.services.support_recompute import (
    SupportRecomputeKit,
    rebuild_primary_snapshot_with_support,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_DPS_HAKUSHIN_ID = 97970
_SUPPORT_HAKUSHIN_ID = 97971
_SUPPORT2_HAKUSHIN_ID = 97972
_TEAM_BUFF_LABEL = "test:support_team_atk"
_TEAM_BUFF2_LABEL = "test:support2_team_atk"
_SUPPORT_ATK_PCT = 3000  # +30%, the figure issue #121 measured rank losing

_SNAPSHOT_LOADER = "app.services.snapshot_builder.load_agent_modifiers"
# support_recompute imports load_agent_modifiers into its own namespace.
_RECOMPUTE_LOADER = "app.services.support_recompute.load_agent_modifiers"


def _team_buff(label: str, value: int = _SUPPORT_ATK_PCT) -> Modifier:
    return Modifier(
        stat="atk_pct",
        value=value,
        source=ModifierSource.EXTERNAL,
        source_label=label,
        target=ModifierTarget.TEAM,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


_SUPPORT_TEAM_BUFF = _team_buff(_TEAM_BUFF_LABEL)
_SUPPORT2_TEAM_BUFF = _team_buff(_TEAM_BUFF2_LABEL, value=1000)


def _count(snapshot: BuildSnapshot, label: str = _TEAM_BUFF_LABEL) -> int:
    return sum(1 for m in snapshot.modifiers if m.source_label == label)


_count_team_buff = _count  # name kept from the #97 harness


async def _seed(
    client: AsyncClient,
    db: AsyncSession,
    *,
    with_second_support: bool = False,
) -> dict:
    """DPS + support agent(s), one build each, a team, and a one-hit DPS combo."""
    dps_agent = Agent(
        hakushin_id=_DPS_HAKUSHIN_ID,
        name="RankSupportSnapshotDPS",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=1000,
        base_hp=8000,
        base_def=600,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    support_agent = Agent(
        hakushin_id=_SUPPORT_HAKUSHIN_ID,
        name="RankSupportSnapshotSupport",
        element=Element.ICE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
        base_atk=700,
        base_hp=9000,
        base_def=650,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    agents = [dps_agent, support_agent]
    if with_second_support:
        agents.append(
            Agent(
                hakushin_id=_SUPPORT2_HAKUSHIN_ID,
                name="RankSupportSnapshotSupport2",
                element=Element.ELECTRIC,
                specialty=Specialty.SUPPORT,
                rarity=Rarity.S,
                base_atk=690,
                base_hp=9100,
                base_def=640,
                base_crit_rate=500,
                base_crit_dmg=5000,
            )
        )
    enemy = EnemyProfile(name="RankSupportSnapshotDummy", level=60, defense=50, fire_res=0)
    db.add_all([*agents, enemy])
    await db.flush()

    attack = Attack(
        agent_id=dps_agent.id,
        hakushin_skill_id=979,
        skill_key="Basic",
        name="RankSupportSnapshotHit",
        hit_index=0,
        element=Element.FIRE,
        damage_base=10000,
        damage_growth=0,
    )
    db.add(attack)
    await db.flush()

    async def _make_build(name: str, agent: Agent) -> str:
        resp = await client.post(
            "/api/v1/builds",
            json={"name": name, "agent_id": str(agent.id)},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    dps_build_id = await _make_build("RankSupportSnapshotDPSBuild", dps_agent)
    support_build_id = await _make_build("RankSupportSnapshotSupportBuild", support_agent)

    team_body = {
        "name": "RankSupportSnapshotTeam",
        "build1_id": dps_build_id,
        "build2_id": support_build_id,
    }
    support2_build_id = None
    if with_second_support:
        support2_build_id = await _make_build("RankSupportSnapshotSupport2Build", agents[2])
        team_body["build3_id"] = support2_build_id

    team_resp = await client.post("/api/v1/teams", json=team_body)
    assert team_resp.status_code == 201, team_resp.text
    team_id = team_resp.json()["id"]

    combo_resp = await client.post(
        "/api/v1/combos",
        json={
            "name": "RankSupportSnapshotCombo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(attack.id), "label": "hit"}],
        },
    )
    assert combo_resp.status_code == 201, combo_resp.text

    return {
        "dps_build_id": dps_build_id,
        "support_build_id": support_build_id,
        "support2_build_id": support2_build_id,
        "team_id": team_id,
        "combo_id": combo_resp.json()["id"],
        "enemy_id": str(enemy.id),
    }


def _agent_modifier_loader(hakushin_id, *_args, **_kwargs) -> list[Modifier]:
    """Only the supports own their team buffs — so a count of 2 can only be a duplicate."""
    if str(hakushin_id) == str(_SUPPORT_HAKUSHIN_ID):
        return [_SUPPORT_TEAM_BUFF]
    if str(hakushin_id) == str(_SUPPORT2_HAKUSHIN_ID):
        return [_SUPPORT2_TEAM_BUFF]
    return []


@contextmanager
def _patched_loaders():
    """Both namespaces that load agent kit modifiers, patched to the probe kit."""
    with (
        patch(_SNAPSHOT_LOADER, side_effect=_agent_modifier_loader),
        patch(_RECOMPUTE_LOADER, side_effect=_agent_modifier_loader),
    ):
        yield


async def _rank_payload(db_session, seed, *, support_slot=None, supports_by_build=None, team=True):
    body = RankRequest(
        contexts=[
            RankContextSchema(
                combo_id=seed["combo_id"],
                enemy_profile_id=seed["enemy_id"],
                team_id=seed["team_id"] if team else None,
                build_id=None if team else seed["dps_build_id"],
                active_index=0,
                support_slot=support_slot,
            )
        ],
    )
    return await resolve_rank_payload(
        db_session,
        body,
        build_repo=BuildRepository(db_session),
        combo_repo=ComboRepository(db_session),
        attack_repo=AttackRepository(db_session),
        enemy_repo=EnemyProfileRepository(db_session),
        support_builds_by_build_id=supports_by_build,
        team_repo=TeamRepository(db_session),
    )


# ---------------------------------------------------------------------------
# Rank — ordinary (non-support-slot) disc scores.  Issue #121 defect 2.
# ---------------------------------------------------------------------------


async def test_rank_scoring_base_carries_the_support_team_mod_exactly_once(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The snapshot every ranked disc is scored against must carry the buff once.

    ``_build_base_for_target`` only re-fills disc stats and disc-set mods, so
    ``ctx.scoring_base`` is the sole route by which a support's team buff can
    reach a ranked disc score. Before #121 rank built it without
    ``support_builds=`` and the count here was 0.
    """
    seed = await _seed(authed_client, db_session)
    await db_session.commit()

    with _patched_loaders():
        payload = await _rank_payload(db_session, seed)

    ctx = payload.contexts[0]
    assert _count(ctx.scoring_base) == 1, (
        f"the support's team buff must appear exactly once in rank's scoring base; "
        f"got {_count(ctx.scoring_base)}. 0 means supports contribute nothing to "
        f"any ranked disc score (issue #121 defect 2); 2 is a double-count."
    )
    assert [name for _bid, name in ctx.scoring_base.folded_supports] == [
        "RankSupportSnapshotSupport"
    ]


async def test_rank_ordinary_disc_scores_include_the_support_atk_buff(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The measurement issue #121 quotes: ATK 2790 where the team value is 3627.

    Same build, same combo — resolved once with the team and once without. The
    delta must be exactly the support's +30% of base ATK. Before the split, the
    two were identical because rank's scoring base never saw the support.
    """
    seed = await _seed(authed_client, db_session)
    await db_session.commit()

    with _patched_loaders():
        with_team = await _rank_payload(db_session, seed)
        solo = await _rank_payload(db_session, seed, team=False)

    ctx_team = with_team.contexts[0]
    ctx_solo = solo.contexts[0]
    atk_team = resolve_build_stats(ctx_team.scoring_base, ctx_team.conditions).atk
    atk_solo = resolve_build_stats(ctx_solo.scoring_base, ctx_solo.conditions).atk

    assert ctx_solo.scoring_base.folded_supports == (), "control must be support-free"
    expected_delta = ctx_team.scoring_base.agent_base_atk * _SUPPORT_ATK_PCT // 10000
    assert atk_team - atk_solo == expected_delta, (
        f"the support's +{_SUPPORT_ATK_PCT / 100:.0f}% team ATK must reach the "
        f"snapshot every ranked disc is scored against: with-team ATK {atk_team}, "
        f"solo ATK {atk_solo}, expected delta {expected_delta}. A delta of 0 is the "
        f"defect issue #121 measured."
    )


async def test_rank_hands_the_simulator_a_support_free_base(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The other half of the split: the simulator must NOT get the folded snapshot.

    ``anomaly_simulator`` merges every teammate's TEAM/ACTIVE modifiers into the
    acting agent itself, so a folded ``base_build`` resolves them twice.
    """
    seed = await _seed(authed_client, db_session)
    await db_session.commit()

    captured: list[BuildSnapshot] = []

    async def _spy(**kwargs):
        captured.append(kwargs["base_build"])
        return await resolve_stateful_am_step_lists(**kwargs)

    with (
        _patched_loaders(),
        patch(
            "app.services.optimizer_pipeline.resolve_stateful_am_step_lists",
            side_effect=_spy,
        ),
    ):
        await _rank_payload(db_session, seed)

    assert captured, "rank never called the simulator"
    for snap in captured:
        assert snap.folded_supports == (), (
            f"rank handed the simulator a support-folded base_build "
            f"({snap.folded_supports}); the simulator merges teammate TEAM mods "
            f"itself, so this double-counts them (issue #121)."
        )
        assert _count(snap) == 0


# ---------------------------------------------------------------------------
# Optimizer — issue #121 defect 1, the double-count.
# ---------------------------------------------------------------------------


async def _optimize_payload(db_session, seed):
    return await resolve_optimize_payload(
        db_session,
        DiscOptimizeRequest(
            team_id=seed["team_id"],
            active_index=0,
            combo_id=seed["combo_id"],
            enemy_profile_id=seed["enemy_id"],
        ),
        ComboRepository(db_session),
        BuildRepository(db_session),
        AttackRepository(db_session),
        EnemyProfileRepository(db_session),
        team_repo=TeamRepository(db_session),
    )


async def test_optimizer_scoring_snapshots_carry_the_support_team_mod_exactly_once(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Both scorer-facing optimizer snapshots: exactly one copy, never two."""
    seed = await _seed(authed_client, db_session)
    await db_session.commit()

    with _patched_loaders():
        payload = await _optimize_payload(db_session, seed)

    counts = {
        "scoring_snap": _count(payload.scoring_snap),
        "scoring_base": _count(payload.scoring_base),
    }
    assert counts == {"scoring_snap": 1, "scoring_base": 1}, (
        f"the optimizer's scorer inputs must carry the support's team buff exactly "
        f"once; got {counts}."
    )


async def test_optimizer_simulator_merges_the_support_team_mod_exactly_once(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The defect issue #121 measured: ``in_base=1, in_merged=2``.

    ``anomaly_simulator`` merges every teammate's TEAM/ACTIVE modifier into the
    acting agent's own modifier list, and ``resolve_modifiers`` sums duplicates
    with no dedupe. When the optimizer's ``base_build`` also carried them, a
    support's buff resolved at double strength — and that reaches the *scored*
    step list, because anomaly proc counts, stun windows and Luminize
    ``frozen_damage`` are all simulator-derived.

    Spied at ``resolve_build_stats``, the first thing the simulator does with
    the merged snapshot.
    """
    seed = await _seed(authed_client, db_session)
    await db_session.commit()

    from app.services import anomaly_simulator as _sim

    real_resolve = _sim.resolve_build_stats
    merged_counts: list[int] = []

    def _spy(snapshot, *args, **kwargs):
        merged_counts.append(_count(snapshot))
        return real_resolve(snapshot, *args, **kwargs)

    with (
        _patched_loaders(),
        patch.object(_sim, "resolve_build_stats", side_effect=_spy),
    ):
        await _optimize_payload(db_session, seed)

    assert merged_counts, "the simulator resolved no acting snapshot at all"
    assert set(merged_counts) == {1}, (
        f"the support's team modifier must be merged exactly once into every "
        f"acting-agent snapshot the simulator resolves; got {merged_counts}. "
        f"2 is issue #121 defect 1 — the optimizer folded the supports into "
        f"base_build and the simulator merged them again."
    )


# A cross-pipeline "optimizer and rank now simulate the same step list" test was
# written here and then deleted: it passes with the fix inverted (this probe's
# buff is atk_pct, which changes damage but not step *structure*), so it pinned
# nothing. The exactly-once tests above are the discriminating form of the same
# claim.


# ---------------------------------------------------------------------------
# api/v1/scorer.py — the third pipeline #121 fixed. Same split, own wiring.
# ---------------------------------------------------------------------------


async def test_scorer_disc_endpoint_counts_the_support_team_mod_exactly_once(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """``/scorer/disc`` had rank's omission; it gets rank's fix, so pin it too.

    Both halves in one request: the scorer's snapshots must carry the support's
    team buff exactly once (before #121: zero — team buffs were absent from
    every scored number), and the snapshot handed to the simulator must still
    carry none (the simulator merges teammates itself).
    """
    user, _ = authed_user
    seed = await _seed(authed_client, db_session)
    disc_set = DiscSet(
        hakushin_id=99970,
        name="RankSupportSnapshotSet",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +25%",
    )
    db_session.add(disc_set)
    await db_session.flush()
    candidate = Disc(
        owner_id=str(user.id),
        disc_set_id=str(disc_set.id),
        slot=DiscSlot(4),
        rarity=Rarity.S,
        level=0,
        main_stat_type="atk_pct",
        main_stat_value=0,
        substats=[
            {"stat": "crit_dmg", "value": 480, "rolls": 1},
            {"stat": "hp_pct", "value": 300, "rolls": 1},
            {"stat": "crit_rate", "value": 240, "rolls": 1},
            {"stat": "def_pct", "value": 480, "rolls": 1},
        ],
    )
    db_session.add(candidate)
    await db_session.flush()
    await db_session.commit()

    sim_bases: list[BuildSnapshot] = []
    scoring_snaps: list[BuildSnapshot] = []
    scoring_bases: list[BuildSnapshot] = []

    async def _spy_sim(**kwargs):
        sim_bases.append(kwargs["base_build"])
        return await resolve_stateful_am_step_lists(**kwargs)

    def _spy_eval(*, build, **kwargs):
        scoring_snaps.append(build)
        return _real_evaluate_steps_total(build=build, **kwargs)

    def _spy_base(*, stripped, **kwargs):
        scoring_bases.append(stripped)
        return _real_build_base_for_target(stripped=stripped, **kwargs)

    with (
        _patched_loaders(),
        patch("app.api.v1.scorer.resolve_stateful_am_step_lists", side_effect=_spy_sim),
        patch("app.api.v1.scorer.evaluate_steps_total", side_effect=_spy_eval),
        patch("app.api.v1.scorer._build_base_for_target", side_effect=_spy_base),
    ):
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": seed["combo_id"],
                "disc_id": str(candidate.id),
                "enemy_profile_id": seed["enemy_id"],
            },
        )
    assert resp.status_code == 200, resp.text

    assert sim_bases, "the endpoint never called the simulator"
    for snap in sim_bases:
        assert snap.folded_supports == (), (
            f"/scorer/disc handed the simulator a support-folded base_build "
            f"({snap.folded_supports}); it merges teammate TEAM mods itself "
            f"(issue #121)."
        )
        assert _count(snap) == 0
    assert scoring_snaps, "the endpoint computed no baseline"
    assert scoring_bases, "the endpoint scored no disc"
    for snap in (*scoring_snaps, *scoring_bases):
        assert _count(snap) == 1, (
            f"the support's team buff must reach /scorer/disc's scored snapshots "
            f"exactly once; got {_count(snap)}. 0 is the pre-#121 defect."
        )


# ---------------------------------------------------------------------------
# The guards — no third caller can pick the wrong snapshot silently.
# ---------------------------------------------------------------------------


async def test_simulator_refuses_a_support_folded_base_build() -> None:
    """``resolve_stateful_am_step_lists`` rejects the scorer's snapshot outright."""
    folded = BuildSnapshot(folded_supports=(("build-1", "SomeSupport"),))
    with pytest.raises(ValueError, match="support-free base_build"):
        await resolve_stateful_am_step_lists(
            combo=None,  # type: ignore[arg-type]
            build=None,  # type: ignore[arg-type]
            base_build=folded,
            enemy=None,  # type: ignore[arg-type]
            attack_repo=None,  # type: ignore[arg-type]
            inventory=[],
            am_2pc_sets={},
            conditions=None,  # type: ignore[arg-type]
        )


def test_support_rebake_refuses_a_snapshot_that_already_has_that_support() -> None:
    """``rebuild_primary_snapshot_with_support`` appends — so it checks first."""
    kit = SupportRecomputeKit(
        agent_base_hp=0,
        core_hp_pct=0,
        we_initial_hp_pct=0,
        we_combat_hp_pct=0,
        we_secondary_hp_pct=0,
        disc_set_modifiers={},
        build_discs=[],
        agent_name="SomeSupport",
        build_id="build-1",
    )
    already = BuildSnapshot(folded_supports=(("build-1", "SomeSupport"),))
    with pytest.raises(ValueError, match="already has them folded in"):
        rebuild_primary_snapshot_with_support(already, kit, [])

    # A *different* support being folded in is fine — that is the three-agent
    # team case, where the other support must keep buffing the primary.
    other = BuildSnapshot(folded_supports=(("build-2", "OtherSupport"),))
    assert rebuild_primary_snapshot_with_support(other, kit, []) is not None


async def test_support_rebake_records_itself_in_folded_supports() -> None:
    """The re-baked snapshot must not advertise itself as support-free.

    ``rebuild_primary_snapshot_with_support`` appends a support's team mods, so
    its output *is* support-folded. If ``folded_supports`` did not record that,
    the object would sail past ``resolve_stateful_am_step_lists``'s guard — the
    silent double-count #121 exists to stop — and a second re-bake with the same
    kit would stack instead of raising.
    """
    kit = SupportRecomputeKit(
        agent_base_hp=0,
        core_hp_pct=0,
        we_initial_hp_pct=0,
        we_combat_hp_pct=0,
        we_secondary_hp_pct=0,
        disc_set_modifiers={},
        build_discs=[],
        agent_name="SomeSupport",
        build_id="build-1",
    )
    other = BuildSnapshot(folded_supports=(("build-2", "OtherSupport"),))
    rebaked = rebuild_primary_snapshot_with_support(other, kit, [])

    assert rebaked.folded_supports == (
        ("build-2", "OtherSupport"),
        ("build-1", "SomeSupport"),
    )
    # The simulator's guard now refuses it, as it refuses any support-folded
    # snapshot — before this it accepted the re-baked one silently.
    with pytest.raises(ValueError, match="support-free base_build"):
        await resolve_stateful_am_step_lists(
            combo=None,  # type: ignore[arg-type]
            build=None,  # type: ignore[arg-type]
            base_build=rebaked,
            enemy=None,  # type: ignore[arg-type]
            attack_repo=None,  # type: ignore[arg-type]
            inventory=[],
            am_2pc_sets={},
            conditions=None,  # type: ignore[arg-type]
        )

    # And the re-bake guard itself now refuses a second append of the same kit.
    with pytest.raises(ValueError, match="already has them folded in"):
        rebuild_primary_snapshot_with_support(rebaked, kit, [])


# ---------------------------------------------------------------------------
# Rank — support-slot path.  The #97 harness, plus the three-agent case.
# ---------------------------------------------------------------------------


class TestSupportTeamModifierCountedOnce:
    async def test_support_team_mod_appears_exactly_once_in_scored_snapshot(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        seed = await _seed(authed_client, db_session)
        await db_session.commit()

        build_repo = BuildRepository(db_session)
        support_build = await build_repo.get_by_id(seed["support_build_id"])

        with _patched_loaders():
            payload = await _rank_payload(
                db_session,
                seed,
                support_slot=1,
                supports_by_build={seed["dps_build_id"]: [support_build]},
            )
            ctx = payload.contexts[0]
            assert ctx.support_recompute_kit is not None
            assert any(
                m.source_label == _TEAM_BUFF_LABEL
                for m in ctx.support_recompute_kit.agent_kit_mods_prefiltered
            ), "sanity: the recompute kit must actually carry the support's team buff"

            # Capture every snapshot score_support_disc_potential actually evaluates.
            evaluated: list = []

            def _spy(*, build, **kwargs) -> float:
                evaluated.append(build)
                return 1.0

            candidate = DiscCandidate(
                disc_id="candidate-disc",
                slot=4,
                set_id=99970,
                main_stat_type="atk_pct",
                main_stat_value=3000,
                substats=[],
            )
            with patch("app.services.support_scorer.evaluate_steps_total", side_effect=_spy):
                assert (
                    _score_pair(
                        (
                            candidate,
                            ctx.build_id,
                            ctx.scoring_base,
                            ctx.build_discs,
                            ctx.enemy_snap,
                            ctx.combo_steps,
                            ctx.conditions,
                            ctx.crit_mode,
                            ctx.is_stunned,
                            ctx.stun_dmg_mult,
                            ctx.disc_set_modifiers,
                            ctx.baseline_damage,
                            "S",
                            ctx.support_recompute_kit,
                            ctx.primary_snap_without_support,
                        )
                    )
                    is not None
                )

        assert evaluated, "score_support_disc_potential evaluated no snapshot at all"
        counts = [_count_team_buff(snap) for snap in evaluated]
        assert counts == [1] * len(counts), (
            f"the support's team modifier {_TEAM_BUFF_LABEL!r} must appear exactly "
            f"once in every snapshot score_support_disc_potential evaluates; got "
            f"{counts}. 0 means the support's buffs never reach the primary's "
            f"damage; 2 means the primary snapshot baked them in and the scorer "
            f"appended them again (issue #97 / #121)."
        )

        # The other half of the same coin, stated as the documented precondition
        # of rebuild_primary_snapshot_with_support (which appends, never merges).
        assert _count_team_buff(ctx.primary_snap_without_support) == 0, (
            "the snapshot handed to score_support_disc_potential must carry none "
            "of the SCORED support's team mods before the scorer re-bakes them."
        )


async def test_support_slot_keeps_the_other_support_and_drops_only_the_scored_one(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Three-agent team, ranking discs for support slot 1.

    Slot 1's own mods come solely from the scorer's per-candidate re-bake, so the
    primary snapshot must not carry them. Slot 2's are static for this run and
    must be present — before #121 the snapshot had no supports folded in at all,
    so the *other* support silently stopped buffing the primary.
    """
    seed = await _seed(authed_client, db_session, with_second_support=True)
    await db_session.commit()

    build_repo = BuildRepository(db_session)
    support_build = await build_repo.get_by_id(seed["support_build_id"])
    support2_build = await build_repo.get_by_id(seed["support2_build_id"])

    with _patched_loaders():
        payload = await _rank_payload(
            db_session,
            seed,
            support_slot=1,
            supports_by_build={seed["dps_build_id"]: [support_build, support2_build]},
        )
        ctx = payload.contexts[0]
        assert ctx.support_recompute_kit is not None
        assert ctx.support_recompute_kit.agent_name == "RankSupportSnapshotSupport"

        primary = ctx.primary_snap_without_support
        assert _count(primary, _TEAM_BUFF_LABEL) == 0, (
            "the scored support's own mods must come only from the scorer's re-bake"
        )
        assert _count(primary, _TEAM_BUFF2_LABEL) == 1, (
            "the OTHER support must still buff the primary while slot 1 is ranked; "
            "0 is the pre-#121 behaviour (no supports folded in at all)"
        )

        evaluated: list = []

        def _spy(*, build, **kwargs) -> float:
            evaluated.append(build)
            return 1.0

        candidate = DiscCandidate(
            disc_id="candidate-disc",
            slot=4,
            set_id=99970,
            main_stat_type="atk_pct",
            main_stat_value=3000,
            substats=[],
        )
        with patch("app.services.support_scorer.evaluate_steps_total", side_effect=_spy):
            _score_pair(
                (
                    candidate,
                    ctx.build_id,
                    ctx.scoring_base,
                    ctx.build_discs,
                    ctx.enemy_snap,
                    ctx.combo_steps,
                    ctx.conditions,
                    ctx.crit_mode,
                    ctx.is_stunned,
                    ctx.stun_dmg_mult,
                    ctx.disc_set_modifiers,
                    ctx.baseline_damage,
                    "S",
                    ctx.support_recompute_kit,
                    ctx.primary_snap_without_support,
                )
            )

    assert evaluated
    scored = [_count(s, _TEAM_BUFF_LABEL) for s in evaluated]
    others = [_count(s, _TEAM_BUFF2_LABEL) for s in evaluated]
    assert scored == [1] * len(scored), f"scored support counted {scored}, want all 1"
    assert others == [1] * len(others), f"other support counted {others}, want all 1"


_DPS_SELF_LABEL = "test:dps_self_atk"
_DPS_SELF_BUFF = Modifier(
    stat="atk_pct",
    value=2500,
    source=ModifierSource.EXTERNAL,
    source_label=_DPS_SELF_LABEL,
    target=ModifierTarget.SELF,
    conditions=(Condition.ALWAYS,),
    scopes=(AttackScope.ALL,),
    max_stacks=1,
)


def _dup_slot_modifier_loader(hakushin_id, *_args, **_kwargs) -> list[Modifier]:
    """The DPS owns a self buff of its own, so there is something for a strip to destroy."""
    if str(hakushin_id) == str(_SUPPORT_HAKUSHIN_ID):
        return [_SUPPORT_TEAM_BUFF]
    if str(hakushin_id) == str(_DPS_HAKUSHIN_ID):
        return [_DPS_SELF_BUFF]
    return []


async def test_primary_keeps_own_modifiers_when_it_also_fills_the_support_slot(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Resolving a support slot must never delete the primary's own kit.

    ``owner_name`` is stamped on the *primary's own* kit / core / W-Engine / disc
    modifiers too (``snapshot_builder.py`` -- ``owner_name=dps_name``). The strip
    #120 deleted therefore removed the primary's entire modifier list whenever
    ``support_kit.agent_name`` happened to equal the primary's own agent name.

    #121 keeps that property by filtering the support list by **build id** rather
    than by agent name, and by checking the re-bake precondition against
    ``folded_supports`` (build ids) instead of scanning ``owner_name``.
    """
    seed = await _seed(authed_client, db_session)
    await db_session.commit()

    build_repo = BuildRepository(db_session)
    primary_build = await build_repo.get_by_id(seed["dps_build_id"])

    with (
        patch(_SNAPSHOT_LOADER, side_effect=_dup_slot_modifier_loader),
        patch(_RECOMPUTE_LOADER, side_effect=_dup_slot_modifier_loader),
    ):
        payload = await _rank_payload(
            db_session,
            seed,
            support_slot=1,
            # The primary build IS the support build -- the degenerate shape the
            # old strip mishandled.
            supports_by_build={seed["dps_build_id"]: [primary_build]},
        )

    ctx = payload.contexts[0]
    assert ctx.support_recompute_kit is not None
    assert ctx.support_recompute_kit.agent_name == primary_build.agent.name, (
        "sanity: this fixture only bites when the support kit's agent name matches the primary's"
    )

    own = sum(
        1 for m in ctx.primary_snap_without_support.modifiers if m.source_label == _DPS_SELF_LABEL
    )
    assert own == 1, (
        f"the primary's own {_DPS_SELF_LABEL!r} modifier was dropped from the "
        f"snapshot handed to score_support_disc_potential (found {own} copies) "
        "because the support slot resolved to the primary's own agent name."
    )
