"""A squad-wide stage buff must apply exactly once, whatever the team size (#64).

Found while reviewing PR #198, and it was live on `dev`: `custom_buffs` was injected into
**every** team member's snapshot, but the engine's own merge is what distributes a
team-target modifier — `anomaly_simulator._resolve_onfield_modifiers` hands the acting
agent its own modifiers plus every teammate's TEAM/ACTIVE rows, and `resolve_modifiers`
sums duplicates rather than deduping. A 500 flat_atk stage buff therefore resolved as
+500 solo, **+1000 on a two-agent team and +1500 on a three-agent team** — the number
grew with the size of the squad the buff was supposed to apply to.

The rule now is one holder, engine distribution: the buff goes on the primary's snapshot
and reaches the rest through the same path a kit team buff does. This file pins it at the
size that exposes it — a single-member team cannot fail either way, which is exactly why
the original tests missed it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_STAGE_ATK = 500


async def _seed_team(db: AsyncSession, client: AsyncClient, size: int, *, run: int = 0) -> dict:
    """Seed `size` identical agents/builds. `run` offsets the synthetic hakushin ids so a
    single test can seed several teams without colliding on the unique index."""
    enemy = EnemyProfile(name=f"ExactlyOnceDummy{run}", level=60, defense=50, fire_res=0)
    db.add(enemy)
    await db.flush()

    team_builds: dict[str, str] = {}
    attack_name = ""
    for i in range(size):
        agent = Agent(
            hakushin_id=9700 + run * 10 + i,
            name=f"ExactlyOnceAgent{run}_{i}",
            element=Element.FIRE,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_atk=1000,
            base_hp=8000,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
        )
        db.add(agent)
        await db.flush()
        attack = Attack(
            agent_id=agent.id,
            hakushin_skill_id=970000 + i,
            skill_key="Basic",
            name=f"Basic Attack: ExactlyOnce{i}",
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

        resp = await client.post("/api/v1/builds", json={"agent_id": str(agent.id)})
        assert resp.status_code == 201, resp.text
        team_builds["dps" if i == 0 else f"support{i}"] = resp.json()["id"]
        if i == 0:
            attack_name = attack.name

    return {"team_builds": team_builds, "enemy_id": str(enemy.id), "attack_name": attack_name}


async def _effective_atk(client: AsyncClient, seed: dict, custom_buffs: list[dict]) -> int:
    resp = await client.post(
        "/api/v1/simulate",
        json={
            "team_builds": seed["team_builds"],
            "steps": [{"agent_id": "dps", "move_name": seed["attack_name"]}],
            "enemy_profile_id": seed["enemy_id"],
            "buff_context": {"custom_buffs": custom_buffs},
        },
    )
    assert resp.status_code == 200, resp.text
    hit = next(e for e in resp.json()["events"] if e["kind"] == "hit")
    return hit["detail"]["effective_atk"]


class TestAStageBuffDoesNotScaleWithTeamSize:
    @pytest.mark.parametrize("size", [1, 2, 3])
    async def test_a_squad_wide_buff_applies_once_on_a_team_of_any_size(
        self, authed_client: AsyncClient, db_session: AsyncSession, size: int
    ) -> None:
        seed = await _seed_team(db_session, authed_client, size)
        await db_session.commit()

        plain = await _effective_atk(authed_client, seed, [])
        buffed = await _effective_atk(
            authed_client,
            seed,
            [
                {
                    "label": "DA: squad ATK",
                    "stat": "flat_atk",
                    "value": _STAGE_ATK,
                    "target": "team",
                }
            ],
        )

        assert buffed - plain == _STAGE_ATK, (
            f"a {_STAGE_ATK} squad-wide stage buff moved ATK by {buffed - plain} on a "
            f"{size}-agent team. It must not scale with team size: the buff goes on one "
            f"holder and the simulator's TEAM merge distributes it."
        )

    @pytest.mark.parametrize("size", [2, 3])
    async def test_an_active_agent_only_buff_applies_once_too(
        self, authed_client: AsyncClient, db_session: AsyncSession, size: int
    ) -> None:
        seed = await _seed_team(db_session, authed_client, size)
        await db_session.commit()

        plain = await _effective_atk(authed_client, seed, [])
        buffed = await _effective_atk(
            authed_client,
            seed,
            [{"label": "DA: DPS ATK", "stat": "flat_atk", "value": _STAGE_ATK, "target": "self"}],
        )

        assert buffed - plain == _STAGE_ATK


async def _team_with_combo(
    db: AsyncSession, client: AsyncClient, size: int, *, run: int = 0
) -> dict:
    """`_seed_team`'s agents/builds, wired into a real team + team combo."""
    seed = await _seed_team(db, client, size, run=run)
    build_ids = list(seed["team_builds"].values())

    payload = {"name": "ExactlyOnceTeam", "build1_id": build_ids[0]}
    for i, bid in enumerate(build_ids[1:], start=2):
        payload[f"build{i}_id"] = bid
    team_resp = await client.post("/api/v1/teams", json=payload)
    assert team_resp.status_code == 201, team_resp.text
    team_id = team_resp.json()["id"]

    attack_resp = await client.post(
        "/api/v1/combos",
        json={
            "name": "ExactlyOnceCombo",
            "team_id": team_id,
            "sequence": [
                {"label": "hit", "move_name": seed["attack_name"], "agent_id": build_ids[0]}
            ],
        },
    )
    assert attack_resp.status_code == 201, attack_resp.text
    return {**seed, "team_id": team_id, "combo_id": attack_resp.json()["id"]}


async def _team_total(client: AsyncClient, seed: dict, body_extra: dict) -> int:
    resp = await client.post(
        f"/api/v1/teams/{seed['team_id']}/calculate",
        json={
            "combo_id": seed["combo_id"],
            "enemy_profile_id": seed["enemy_id"],
            **body_extra,
        },
    )
    assert resp.status_code == 200, resp.text
    return sum(s.get("total", 0) for s in resp.json()["steps"])


class TestTheTeamCalculatePathAgrees:
    """`/teams/{id}/calculate` distributes stage buffs through the same one-holder rule.

    It reaches the simulator by a different route than `/simulate` (member snapshots plus
    a `TeamMember` list that `_augment_for_member` merges), so it can — and did — get the
    multiplication wrong independently. Reviewed and fixed together; pinned separately,
    because the two paths have no code in common at the point where it goes wrong.
    """

    async def test_a_squad_wide_buff_gains_the_same_on_a_1_2_and_3_agent_team(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The gain must be identical at every team size.

        Asserted as an equality *across sizes* rather than against a fixed number: only
        the DPS acts in this rotation, so its damage is the whole total, and the stage
        buff is the only thing that differs between the two calls at a given size. Under
        the defect the gain grew with the squad — 1x, 2x, 3x — which no
        internally-consistent single-size assertion can see.
        """
        buff = {
            "label": "DA: squad ATK",
            "stat": "flat_atk",
            "value": _STAGE_ATK,
            "target": "team",
        }

        gains = []
        for size in (1, 2, 3):
            seed = await _team_with_combo(db_session, authed_client, size, run=size)
            await db_session.commit()
            plain = await _team_total(authed_client, seed, {})
            buffed = await _team_total(authed_client, seed, {"custom_buffs": [buff]})
            assert buffed > plain, f"the stage buff did nothing on a {size}-agent team"
            gains.append(buffed - plain)

        assert gains[0] == gains[1] == gains[2], (
            f"a squad-wide stage buff gained {gains} on 1-, 2- and 3-agent teams. It must "
            f"not scale with team size: one holder, and the engine's TEAM merge "
            f"distributes it."
        )

    async def test_a_stage_buff_can_be_switched_off_from_the_request(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The keystone endpoints had no `disabled_buffs` field at all, so a stage buff
        the optimizer/rank run had switched off was still applied when the user clicked
        the candidate to explain it — a number the run could not reproduce."""
        seed = await _team_with_combo(db_session, authed_client, 2)
        await db_session.commit()

        buff = {
            "label": "DA: squad ATK",
            "stat": "flat_atk",
            "value": _STAGE_ATK,
            "target": "team",
        }
        plain = await _team_total(authed_client, seed, {})
        applied = await _team_total(authed_client, seed, {"custom_buffs": [buff]})
        switched_off = await _team_total(
            authed_client,
            seed,
            {"custom_buffs": [buff], "disabled_buffs": ["custom:da_squad_atk"]},
        )

        assert applied > plain
        assert switched_off == plain


class TestTheTeamEndpointsReadBuffStateFromTheRequestOnly:
    """DESIGN §2.1, finally applied to the two keystone endpoints (#64).

    Phase A left `/teams/{id}/calculate` and `/evaluate-discs` reading each member's
    `build.disabled_buffs` column, because those requests had no such field. They do now,
    and — like the other four entry points — supplying it *replaces* the column rather
    than merging with it. That is a real behaviour change for a caller that omits the
    field and relied on the column, so it is asserted from both sides rather than left
    implied.
    """

    async def test_a_disabled_column_no_longer_reaches_the_calc(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from sqlalchemy import select

        from app.models.build import Build

        seed = await _team_with_combo(db_session, authed_client, 2, run=7)
        primary_id = seed["team_builds"]["dps"]

        buff = {
            "label": "DA: squad ATK",
            "stat": "flat_atk",
            "value": _STAGE_ATK,
            "target": "team",
        }
        with_buff = await _team_total(authed_client, seed, {"custom_buffs": [buff]})

        # Write an id into the build column that would switch the stage buff off if the
        # server still read it. The request says nothing about it.
        build = (
            await db_session.execute(select(Build).where(Build.id == primary_id))
        ).scalar_one()
        build.disabled_buffs = ["custom:da_squad_atk"]
        await db_session.flush()

        unchanged = await _team_total(authed_client, seed, {"custom_buffs": [buff]})
        assert unchanged == with_buff, (
            "the build's disabled_buffs column changed a team calc result — the server "
            "must resolve buff state from the request and only from the request "
            "(DESIGN_buff_context.md §2.1)."
        )

    async def test_the_request_field_is_what_switches_it_off(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        seed = await _team_with_combo(db_session, authed_client, 2, run=8)
        await db_session.commit()

        buff = {
            "label": "DA: squad ATK",
            "stat": "flat_atk",
            "value": _STAGE_ATK,
            "target": "team",
        }
        plain = await _team_total(authed_client, seed, {})
        off = await _team_total(
            authed_client,
            seed,
            {"custom_buffs": [buff], "disabled_buffs": ["custom:da_squad_atk"]},
        )
        assert off == plain
