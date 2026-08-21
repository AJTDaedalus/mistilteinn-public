"""Integration tests for the stateful anomaly simulation API endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.enums import Element, Rarity, Specialty
from app.services.modifiers import AttackScope, Condition, Modifier, ModifierSource, ModifierTarget

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


class TestSimulateAPI:
    async def test_simulate_success(self, authed_client: AsyncClient, db_session: AsyncSession):
        # 1. Seed Burnice Agent
        burnice = Agent(
            hakushin_id=10001,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1000,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=115,
        )
        db_session.add(burnice)
        await db_session.flush()

        # 2. Seed Fire Attack Move
        attack = Attack(
            agent_id=burnice.id,
            hakushin_skill_id=100,
            skill_key="Basic",
            name="Basic Attack: Mixed Flame Blend",
            hit_index=0,
            element=Element.FIRE,
            damage_base=10000,
            damage_growth=500,
        )
        db_session.add(attack)
        await db_session.flush()

        # 3. Seed Enemy Target Profile with 100 Capacity for Fire
        enemy = EnemyProfile(
            name="Anomaly Dummy Target",
            level=60,
            defense=50,
            fire_res=0,
            anomaly_capacity_fire=100,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )
        db_session.add(enemy)
        await db_session.flush()

        # 4. Create Build via API
        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "Test Burnice Build",
                "agent_id": str(burnice.id),
                "mindscape_level": 0,
            },
        )
        assert build_resp.status_code == 201
        build_id = build_resp.json()["id"]

        # 5. Run simulation via endpoint
        payload = {
            "team_builds": {"burnice_key": build_id},
            "steps": [
                {
                    "agent_id": "burnice_key",
                    "move_name": "Basic Attack: Mixed Flame Blend",
                    "conditions": [],
                }
            ],
            "enemy_profile_id": str(enemy.id),
        }

        resp = await authed_client.post("/api/v1/simulate", json=payload)
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert "events" in data
        assert "totals" in data
        assert "per_agent_attribution" in data
        assert "warnings" in data
        assert "buff_roster" in data

        # Check total damage was resolved and is > 0
        assert data["totals"]["total"] > 0
        assert data["per_agent_attribution"]["burnice_key"] > 0

        # Verify that hit events are recorded
        events = data["events"]
        assert len(events) > 0
        hit_events = [e for e in events if e["kind"] == "hit"]
        assert len(hit_events) > 0
        assert hit_events[0]["agent_id"] == "burnice_key"
        assert hit_events[0]["damage"] > 0

        # DESIGN §2.2/2.3: zone_formulas ride along with per-step attribution,
        # and buff_roster is a build-level "every resolved buff, once" panel
        # keyed by the same team_builds keys -- both must be present even
        # though this build has no discs/modifiers curated (empty list is
        # fine, missing key is not).
        assert "zone_formulas" in hit_events[0]["detail"]
        assert isinstance(data["buff_roster"]["burnice_key"], list)

    async def test_stack_count_override_changes_result(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        """A partial stack_counts override in buff_context must move the result.

        Regression for DESIGN §1.1 defect 1 (Task A2): simulate previously
        never read stack_counts at all -- an unset override silently resolved
        to full stacks regardless of what the caller intended.
        """
        agent = Agent(
            hakushin_id=10050,
            name="StackOverrideAgent",
            element=Element.FIRE,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1000,
            base_def=600,
        )
        db_session.add(agent)
        await db_session.flush()

        attack = Attack(
            agent_id=agent.id,
            hakushin_skill_id=101,
            skill_key="Basic",
            name="StackOverrideHit",
            hit_index=0,
            element=Element.FIRE,
            damage_base=10000,
            damage_growth=0,
        )
        db_session.add(attack)

        enemy = EnemyProfile(name="StackOverrideDummy", level=60, defense=50, fire_res=0)
        db_session.add(enemy)
        await db_session.flush()

        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "StackOverrideBuild", "agent_id": str(agent.id)},
        )
        assert build_resp.status_code == 201, build_resp.text
        build_id = build_resp.json()["id"]

        stackable = Modifier(
            stat="atk_pct",
            value=1000,
            source=ModifierSource.EXTERNAL,
            source_label="test:stack_override",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=4,
        )

        def _payload(stack_counts: dict[str, int]) -> dict:
            return {
                "team_builds": {"dps": build_id},
                "steps": [{"agent_id": "dps", "move_name": attack.name}],
                "enemy_profile_id": str(enemy.id),
                "buff_context": {"stack_counts": stack_counts},
            }

        with patch(
            "app.services.snapshot_builder.load_agent_modifiers",
            return_value=[stackable],
        ):
            full_resp = await authed_client.post("/api/v1/simulate", json=_payload({}))
            partial_resp = await authed_client.post(
                "/api/v1/simulate", json=_payload({"test:stack_override": 2})
            )

        assert full_resp.status_code == 200, full_resp.text
        assert partial_resp.status_code == 200, partial_resp.text

        full_atk = next(e for e in full_resp.json()["events"] if e["kind"] == "hit")["detail"][
            "effective_atk"
        ]
        partial_atk = next(
            e for e in partial_resp.json()["events"] if e["kind"] == "hit"
        )["detail"]["effective_atk"]

        assert partial_atk < full_atk, (
            "2/4 stacks should resolve to a lower atk than the default (unset "
            f"-> full 4 stacks), got partial={partial_atk} full={full_atk}"
        )

    async def test_simulate_aftershock_total(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        """Off-field Trigger aftershock procs surface in totals["aftershock"] via /simulate.

        3 Burnice EX Special steps → 2 Trigger procs (gated by 3s CD + 2/20s window):
          t=0: EX hit → proc 1 (CD until t=3)
          t=2: EX hit → blocked (CD not ready)
          t=4: EX hit → proc 2 (CD ready, window=[0,4], cap=2)
        """
        burnice = Agent(
            hakushin_id=30001,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_atk=1000,
        )
        db_session.add(burnice)
        await db_session.flush()

        ex_attack = Attack(
            agent_id=burnice.id,
            hakushin_skill_id=300,
            skill_key="EXSpecial",
            name="EX Special Attack: Intense Heat Stirring Method",
            hit_index=0,
            element=Element.FIRE,
            damage_base=10000,
            damage_growth=0,
        )
        db_session.add(ex_attack)

        trigger = Agent(
            hakushin_id=30002,
            name="Trigger",
            element=Element.ELECTRIC,
            specialty=Specialty.STUN,
            rarity=Rarity.S,
            base_atk=800,
        )
        db_session.add(trigger)
        await db_session.flush()

        enemy = EnemyProfile(
            name="Aftershock Crossval Dummy",
            level=60,
            defense=50,
            electric_res=0,
            fire_res=0,
            anomaly_capacity_fire=10000,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )
        db_session.add(enemy)
        await db_session.flush()

        burnice_build_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "Burnice Build", "agent_id": str(burnice.id), "mindscape_level": 0},
        )
        assert burnice_build_resp.status_code == 201
        burnice_build_id = burnice_build_resp.json()["id"]

        trigger_build_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "Trigger Build", "agent_id": str(trigger.id), "mindscape_level": 0},
        )
        assert trigger_build_resp.status_code == 201
        trigger_build_id = trigger_build_resp.json()["id"]

        payload = {
            "team_builds": {
                "burnice_key": burnice_build_id,
                "trigger_key": trigger_build_id,
            },
            "steps": [
                {
                    "agent_id": "burnice_key",
                    "move_name": "EX Special Attack: Intense Heat Stirring Method",
                    "conditions": [],
                }
            ]
            * 3,
            "enemy_profile_id": str(enemy.id),
        }

        resp = await authed_client.post("/api/v1/simulate", json=payload)
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert "aftershock" in data["totals"]
        assert data["totals"]["aftershock"] > 0

        aftershock_events = [e for e in data["events"] if e["kind"] == "aftershock"]
        assert len(aftershock_events) == 2, (
            f"Expected 2 Trigger procs (3s CD + 2/20s window), got {len(aftershock_events)}"
        )

    async def test_simulate_enemy_not_found(self, authed_client: AsyncClient):
        payload = {
            "team_builds": {},
            "steps": [],
            "enemy_profile_id": "00000000-0000-0000-0000-000000000000",
        }
        resp = await authed_client.post("/api/v1/simulate", json=payload)
        assert resp.status_code == 404
        assert "Enemy profile not found" in resp.json()["detail"]

    async def test_simulate_build_not_found(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        # Seed Enemy Target Profile
        enemy = EnemyProfile(
            name="Enemy Target",
            level=60,
            defense=50,
        )
        db_session.add(enemy)
        await db_session.flush()

        payload = {
            "team_builds": {"agent_key": "00000000-0000-0000-0000-000000000000"},
            "steps": [],
            "enemy_profile_id": str(enemy.id),
        }
        resp = await authed_client.post("/api/v1/simulate", json=payload)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    async def test_simulate_unmatched_agent_in_steps(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        # Seed Burnice Agent
        burnice = Agent(
            hakushin_id=10002,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
        )
        db_session.add(burnice)
        await db_session.flush()

        # Seed Enemy Profile
        enemy = EnemyProfile(
            name="Enemy Target",
            level=60,
            defense=50,
        )
        db_session.add(enemy)
        await db_session.flush()

        # Create Build via API
        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "Test Burnice Build",
                "agent_id": str(burnice.id),
            },
        )
        assert build_resp.status_code == 201
        build_id = build_resp.json()["id"]

        payload = {
            "team_builds": {"burnice_key": build_id},
            "steps": [
                {
                    "agent_id": "unmatched_key",  # Not in team_builds
                    "move_name": "Basic Attack: Mixed Flame Blend",
                    "conditions": [],
                }
            ],
            "enemy_profile_id": str(enemy.id),
        }
        resp = await authed_client.post("/api/v1/simulate", json=payload)
        assert resp.status_code == 422
        assert "unmatched_key" in resp.json()["detail"]

    async def test_simulate_field_timeline_and_switch_events(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        """Multi-agent sim: field_timeline and switch events are surfaced in the response."""
        burnice = Agent(
            hakushin_id=10010,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_atk=1000,
        )
        yanagi = Agent(
            hakushin_id=10011,
            name="Yanagi",
            element=Element.ELECTRIC,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_atk=900,
        )
        db_session.add_all([burnice, yanagi])
        await db_session.flush()

        fire_attack = Attack(
            agent_id=burnice.id,
            hakushin_skill_id=200,
            skill_key="Basic",
            name="Basic Attack: Fire Blend",
            hit_index=0,
            element=Element.FIRE,
            damage_base=5000,
            damage_growth=0,
        )
        elec_attack = Attack(
            agent_id=yanagi.id,
            hakushin_skill_id=201,
            skill_key="Basic",
            name="Basic Attack: Electric Strike",
            hit_index=0,
            element=Element.ELECTRIC,
            damage_base=5000,
            damage_growth=0,
        )
        db_session.add_all([fire_attack, elec_attack])
        await db_session.flush()

        enemy = EnemyProfile(
            name="Switch Test Dummy",
            level=60,
            defense=50,
            anomaly_capacity_fire=100,
            anomaly_capacity_electric=100,
        )
        db_session.add(enemy)
        await db_session.flush()

        b_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "Burnice Build", "agent_id": str(burnice.id), "mindscape_level": 0},
        )
        assert b_resp.status_code == 201
        y_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "Yanagi Build", "agent_id": str(yanagi.id), "mindscape_level": 0},
        )
        assert y_resp.status_code == 201

        payload = {
            "team_builds": {
                "burnice": b_resp.json()["id"],
                "yanagi": y_resp.json()["id"],
            },
            "steps": [
                {
                    "agent_id": "burnice",
                    "move_name": "Basic Attack: Fire Blend",
                    "conditions": [],
                },
                # Explicit switch to yanagi
                {"agent_id": "yanagi", "move_name": "switch", "conditions": []},
                {
                    "agent_id": "yanagi",
                    "move_name": "Basic Attack: Electric Strike",
                    "conditions": [],
                },
            ],
            "enemy_profile_id": str(enemy.id),
        }

        resp = await authed_client.post("/api/v1/simulate", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # field_timeline must be present; only charged swaps recorded (not None→first)
        assert "field_timeline" in data
        ft = data["field_timeline"]
        assert isinstance(ft, list)
        # One entry: burnice→yanagi (the explicit switch charges 1s)
        # None→burnice at t=0 is intentionally omitted (no swap cost)
        assert len(ft) == 1
        assert ft[0][1] == "yanagi"

        # switch events must be in the events list
        switch_events = [e for e in data["events"] if e["kind"] == "switch"]
        assert len(switch_events) == 2  # implicit None→burnice + explicit burnice→yanagi
        yanagi_switch = next(e for e in switch_events if e["agent_id"] == "yanagi")
        assert yanagi_switch["detail"]["from"] == "burnice"

    async def test_switch_unknown_agent_422(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        """A switch step whose agent_id is absent from team_builds must return 422."""
        burnice = Agent(
            hakushin_id=10020,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
        )
        db_session.add(burnice)
        await db_session.flush()

        enemy = EnemyProfile(name="Dummy", level=60, defense=50)
        db_session.add(enemy)
        await db_session.flush()

        b_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "Burnice Build", "agent_id": str(burnice.id)},
        )
        assert b_resp.status_code == 201

        payload = {
            "team_builds": {"burnice": b_resp.json()["id"]},
            "steps": [
                # Switch step referencing an agent not registered in team_builds
                {"agent_id": "ghost_agent", "move_name": "switch", "conditions": []},
            ],
            "enemy_profile_id": str(enemy.id),
        }

        resp = await authed_client.post("/api/v1/simulate", json=payload)
        assert resp.status_code == 422
        assert "ghost_agent" in resp.json()["detail"]

    async def test_simulate_build_readable_after_run(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        """Simulate endpoint runs successfully and build is readable afterwards."""
        burnice = Agent(
            hakushin_id=10003,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
        )
        db_session.add(burnice)
        await db_session.flush()

        enemy = EnemyProfile(name="Enemy Target", level=60, defense=50)
        db_session.add(enemy)
        await db_session.flush()

        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "Burnice Build", "agent_id": str(burnice.id)},
        )
        assert build_resp.status_code == 201
        build_id = build_resp.json()["id"]

        resp = await authed_client.post(
            "/api/v1/simulate",
            json={
                "team_builds": {"dps": build_id},
                "steps": [],
                "enemy_profile_id": str(enemy.id),
            },
        )
        assert resp.status_code == 200

        get_resp = await authed_client.get(f"/api/v1/builds/{build_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == build_id
