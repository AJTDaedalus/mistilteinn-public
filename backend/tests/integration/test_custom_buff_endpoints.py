"""Task B4 — a custom buff sent to an endpoint actually moves the number (#64).

The unit tests prove the synthesis is equivalent to a kit modifier and the schema proves
the input is well-formed. Neither proves the field is *wired*: between B1 and this change
`custom_buffs` was accepted by the API, documented in OpenAPI, and read by nothing. That
is the exact failure this feature exists to avoid, one level up from the stat allowlist —
so it needs a test that goes in through the endpoint.

Reuses the parity suite's seeding shape (a synthetic agent + build + attack + enemy) so
these tests need no seeded game data and run in ordinary CI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_BASE_ATK = 1000
_AGENT_HAKUSHIN_ID = 9801


async def _seed(db: AsyncSession) -> dict:
    agent = Agent(
        hakushin_id=_AGENT_HAKUSHIN_ID,
        name="CustomBuffAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=_BASE_ATK,
        base_hp=8000,
        base_def=600,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    enemy = EnemyProfile(name="CustomBuffDummy", level=60, defense=50, fire_res=0)
    db.add_all([agent, enemy])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=980101,
        skill_key="Basic",
        name="Basic Attack: Custom Buff Probe",
        hit_index=0,
        element="fire",
        damage_base=10000,
        damage_growth=0,
        stun_base=0,
        stun_growth=0,
        energy_gain=0,
        anomaly_buildup=0,
    )
    build = Build(agent_id=agent.id, agent_level=60, mindscape_level=0, core_skill_level=0)
    db.add_all([attack, build])
    await db.flush()
    return {
        "build_id": str(build.id),
        "attack_id": str(attack.id),
        "enemy_id": str(enemy.id),
    }


async def _damage(client: AsyncClient, seed: dict, custom_buffs: list[dict]) -> dict:
    resp = await client.post(
        "/api/v1/damage/build",
        json={
            "build_id": seed["build_id"],
            "attack_id": seed["attack_id"],
            "enemy_profile_id": seed["enemy_id"],
            "buff_context": {
                "active_conditions": ["always"],
                "stack_counts": {},
                "disabled_buffs": [],
                "custom_buffs": custom_buffs,
            },
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestCustomBuffsReachTheCalc:
    async def test_a_flat_atk_stage_buff_moves_total_atk(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        seed = await _seed(db_session)
        await db_session.commit()

        plain = await _damage(authed_client, seed, [])
        buffed = await _damage(
            authed_client,
            seed,
            [{"label": "DA Stage 3: ATK", "stat": "flat_atk", "value": 500, "target": "self"}],
        )
        assert buffed["total_atk"] == plain["total_atk"] + 500

    async def test_a_dmg_bonus_stage_buff_moves_damage_but_not_atk(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The buff lands in the boost zone, not the stat block — which is the property
        that tells a wired-up modifier apart from one that merely got added to ATK."""
        seed = await _seed(db_session)
        await db_session.commit()

        plain = await _damage(authed_client, seed, [])
        buffed = await _damage(
            authed_client,
            seed,
            [{"label": "DA Stage 3: Fire DMG", "stat": "fire_dmg", "value": 2500}],
        )
        assert buffed["total_atk"] == plain["total_atk"]
        assert buffed["total"] > plain["total"]

    async def test_a_debuff_lowers_damage(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Stage effects go both ways, and a negative value must survive the whole path
        rather than being clamped somewhere on the way in."""
        seed = await _seed(db_session)
        await db_session.commit()

        plain = await _damage(authed_client, seed, [])
        nerfed = await _damage(
            authed_client,
            seed,
            [{"label": "Stage: enemy resists fire", "stat": "fire_dmg", "value": -2000}],
        )
        assert nerfed["total"] < plain["total"]

    async def test_an_inactive_condition_gates_the_buff(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        seed = await _seed(db_session)
        await db_session.commit()

        plain = await _damage(authed_client, seed, [])
        gated = await _damage(
            authed_client,
            seed,
            [
                {
                    "label": "Stage: stunned-only",
                    "stat": "fire_dmg",
                    "value": 2500,
                    "conditions": ["enemy_stunned"],
                }
            ],
        )
        assert gated["total"] == plain["total"]

    async def test_disabled_buffs_switches_a_custom_buff_off_by_its_slug(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`custom:<slug>` is the id the client stores, so it has to address the buff
        without an agent prefix — a stage buff belongs to the encounter, not an agent."""
        seed = await _seed(db_session)
        await db_session.commit()

        plain = await _damage(authed_client, seed, [])
        buff = {"label": "DA Stage 3: ATK", "stat": "flat_atk", "value": 500, "target": "self"}
        resp = await authed_client.post(
            "/api/v1/damage/build",
            json={
                "build_id": seed["build_id"],
                "attack_id": seed["attack_id"],
                "enemy_profile_id": seed["enemy_id"],
                "buff_context": {
                    "active_conditions": ["always"],
                    "stack_counts": {},
                    "disabled_buffs": ["custom:da_stage_3_atk"],
                    "custom_buffs": [buff],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["total_atk"] == plain["total_atk"]

    async def test_an_unknown_stat_is_rejected_before_it_can_be_ignored(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        seed = await _seed(db_session)
        await db_session.commit()

        resp = await authed_client.post(
            "/api/v1/damage/build",
            json={
                "build_id": seed["build_id"],
                "attack_id": seed["attack_id"],
                "enemy_profile_id": seed["enemy_id"],
                "buff_context": {"custom_buffs": [{"label": "x", "stat": "atk", "value": 500}]},
            },
        )
        assert resp.status_code == 422, resp.text
        assert "flat_atk" in resp.text


# ---------------------------------------------------------------------------
# Task B10 — custom buffs in the buff roster and in attribution
# ---------------------------------------------------------------------------


async def _seed_team(authed_client: AsyncClient, db: AsyncSession) -> dict:
    """`_seed`'s agent/attack/enemy, plus an owned build, team and combo.

    The build has to come from the API rather than straight from the ORM: the team
    calculate endpoint loads members through the owner-scoped build repository, so a
    build with no owner is a 404 there.
    """
    agent = Agent(
        hakushin_id=_AGENT_HAKUSHIN_ID + 1,
        name="CustomBuffRosterAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=_BASE_ATK,
        base_hp=8000,
        base_def=600,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    enemy = EnemyProfile(name="CustomBuffRosterDummy", level=60, defense=50, fire_res=0)
    db.add_all([agent, enemy])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=980201,
        skill_key="Basic",
        name="Basic Attack: Roster Probe",
        hit_index=0,
        element="fire",
        damage_base=10000,
        damage_growth=0,
        stun_base=0,
        stun_growth=0,
        energy_gain=0,
        anomaly_buildup=0,
    )
    db.add(attack)
    await db.flush()

    build_resp = await authed_client.post(
        "/api/v1/builds", json={"agent_id": str(agent.id)}
    )
    assert build_resp.status_code == 201, build_resp.text
    build_id = build_resp.json()["id"]

    team_resp = await authed_client.post(
        "/api/v1/teams", json={"name": "RosterTeam", "build1_id": build_id}
    )
    assert team_resp.status_code == 201, team_resp.text
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "RosterCombo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(attack.id), "label": "hit"}],
        },
    )
    assert combo_resp.status_code == 201, combo_resp.text

    return {
        "build_id": build_id,
        "team_id": team_id,
        "combo_id": combo_resp.json()["id"],
        "enemy_id": str(enemy.id),
        "attack_name": attack.name,
    }


_ROSTER_BUFF = {
    "label": "DA Stage 3: Fire DMG",
    "stat": "fire_dmg",
    "value": 2500,
    "target": "team",
}
_ROSTER_BUFF_ID = "custom:da_stage_3_fire_dmg"


class TestCustomBuffsAppearInTheRosterAndAttribution:
    """Task B10 — a stage buff must be visible where every other buff is visible.

    DESIGN §2.3's claim is that synthesizing custom buffs into ordinary `Modifier` rows
    makes them work downstream with *zero additional code*. These tests are what makes
    that claim falsifiable: if the roster or attribution needed a special case to show a
    stage buff, the claim would be wrong and the fix would belong upstream in the
    synthesis, not in a downstream branch.
    """

    async def test_a_custom_buff_appears_in_the_simulate_buff_roster(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        seed = await _seed_team(authed_client, db_session)
        await db_session.commit()

        resp = await authed_client.post(
            "/api/v1/simulate",
            json={
                "team_builds": {"dps": seed["build_id"]},
                "steps": [{"agent_id": "dps", "move_name": seed["attack_name"]}],
                "enemy_profile_id": seed["enemy_id"],
                "buff_context": {"custom_buffs": [_ROSTER_BUFF]},
            },
        )
        assert resp.status_code == 200, resp.text

        entries = resp.json()["buff_roster"]["dps"]
        labels = [e["source_label"] for e in entries]
        match = [e for e in entries if e["source_label"] == _ROSTER_BUFF_ID]
        assert match, f"stage buff missing from the roster; got {labels}"
        entry = match[0]
        assert entry["stat"] == "fire_dmg"
        assert entry["value_bp"] == 2500
        assert entry["zone"] == "boost"
        assert entry["source_category"] == "external"
        assert entry["magnitude_display"] == "+25.00%"

    async def test_a_disabled_custom_buff_is_absent_from_the_roster(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Switching a stage buff off must remove it from the panel, not just from the
        arithmetic — a roster row for a buff that contributed nothing is a lie."""
        seed = await _seed_team(authed_client, db_session)
        await db_session.commit()

        resp = await authed_client.post(
            "/api/v1/simulate",
            json={
                "team_builds": {"dps": seed["build_id"]},
                "steps": [{"agent_id": "dps", "move_name": seed["attack_name"]}],
                "enemy_profile_id": seed["enemy_id"],
                "buff_context": {
                    "custom_buffs": [_ROSTER_BUFF],
                    "disabled_buffs": [_ROSTER_BUFF_ID],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        labels = [e["source_label"] for e in resp.json()["buff_roster"]["dps"]]
        assert _ROSTER_BUFF_ID not in labels

    async def test_a_custom_buff_appears_in_team_calculate_attribution(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        seed = await _seed_team(authed_client, db_session)
        await db_session.commit()

        resp = await authed_client.post(
            f"/api/v1/teams/{seed['team_id']}/calculate",
            json={
                "combo_id": seed["combo_id"],
                "enemy_profile_id": seed["enemy_id"],
                "with_attribution": True,
                "custom_buffs": [_ROSTER_BUFF],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        roster_labels = [e["source_label"] for e in body["buff_roster"]]
        assert _ROSTER_BUFF_ID in roster_labels

        # And in the per-step, per-zone attribution the roster is a pivot of. A
        # `fire_dmg` buff lands in the boost zone, so that is where its provenance
        # belongs — the roster and the zone breakdown have to name the same source.
        sources = [
            contribution["source"]
            for step in body["steps"]
            if step.get("attribution")
            for zone in step["attribution"].values()
            if isinstance(zone, dict)
            for contribution in zone.get("contributions", [])
        ]
        assert _ROSTER_BUFF_ID in sources, f"stage buff missing from attribution; got {sources}"


class TestCustomBuffStatOptionsEndpoint:
    """The stage-buff editor's stat picker is served, not hardcoded (Task B8).

    A picker built from a client-side copy of the allowlist drifts the moment the
    resolver's vocabulary changes, and the drift is silent in the worst direction: the
    editor keeps offering a stat the calc no longer reads.
    """

    async def test_it_lists_the_resolvers_vocabulary_and_excludes_the_dead_keys(
        self, authed_client: AsyncClient
    ) -> None:
        resp = await authed_client.get("/api/v1/damage/custom-buff-stats")
        assert resp.status_code == 200, resp.text
        stats = resp.json()

        assert stats == sorted(stats), "sorted so the picker's order is stable"
        for reaching in ("flat_atk", "atk_pct", "crit_rate", "fire_dmg", "vulnerability"):
            assert reaching in stats
        # The three StatType members no buff consumer reads (B2, measured end to end).
        for dead in ("atk", "def", "hp"):
            assert dead not in stats

    async def test_every_listed_stat_is_accepted_by_the_request_schema(
        self, authed_client: AsyncClient
    ) -> None:
        """What the picker offers must be what the calc endpoints accept — otherwise the
        editor can compose a buff that 422s on submit."""
        from app.schemas.damage import BuffContext

        resp = await authed_client.get("/api/v1/damage/custom-buff-stats")
        for stat in resp.json():
            BuffContext(custom_buffs=[{"label": f"probe {stat}", "stat": stat, "value": 100}])
