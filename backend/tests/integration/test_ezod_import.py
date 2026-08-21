"""Integration tests for import_ezod_payload (Task 5).

Covers: build counts, agent/engine assignment, disc slot attachment,
conflict resolution (skip / overwrite), and disc dedup idempotency.
"""

from __future__ import annotations

import copy
import json
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.data.importers.ezod_importer import import_ezod_payload
from app.models.agent import Agent
from app.models.build import Build, Combo
from app.models.disc import Disc, DiscSet
from app.models.enums import Element, Rarity, Specialty
from app.models.team import Team
from app.models.user import User
from app.models.w_engine import WEngine
from app.services.password import hash_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ezod_small.json"

# Hakushin IDs — arbitrary non-colliding values for this test module.
_HA = 9100  # Rina
_HB = 9101  # Anby
_HC = 9102  # Lucy
_HE = 9200  # BashfulDemon engine
_HD1 = 9300  # PufferElectro
_HD2 = 9301  # AstralVoice
_HD3 = 9302  # WoodpeckerElectro


async def _seed(db: AsyncSession) -> dict:
    """Seed agents, w-engine, and disc sets needed by ezod_small.json."""
    rina = Agent(
        hakushin_id=_HA, name="Rina",
        element=Element.ELECTRIC, specialty=Specialty.SUPPORT, rarity=Rarity.S,
    )
    anby = Agent(
        hakushin_id=_HB, name="Anby",
        element=Element.ELECTRIC, specialty=Specialty.STUN, rarity=Rarity.S,
    )
    lucy = Agent(
        hakushin_id=_HC, name="Lucy",
        element=Element.FIRE, specialty=Specialty.SUPPORT, rarity=Rarity.S,
    )
    engine = WEngine(
        hakushin_id=_HE, name="Bashful Demon",
        rarity=Rarity.S, specialty=Specialty.SUPPORT, base_atk=46,
    )
    pe = DiscSet(hakushin_id=_HD1, name="Puffer Electro")
    av = DiscSet(hakushin_id=_HD2, name="Astral Voice")
    we = DiscSet(hakushin_id=_HD3, name="Woodpecker Electro")
    db.add_all([rina, anby, lucy, engine, pe, av, we])
    await db.flush()
    return {
        "rina_id": rina.id,
        "anby_id": anby.id,
        "lucy_id": lucy.id,
        "engine_id": engine.id,
    }


@pytest.fixture
def ezod_payload() -> dict:
    return json.loads(_FIXTURE_PATH.read_text())


class TestEzodImportBasic:
    async def test_creates_three_builds(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        result = await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        assert result.builds_created == 3
        assert result.builds_skipped == 0
        assert result.builds_overwritten == 0

    async def test_imports_twelve_discs(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        result = await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        # 6 Rina + 4 Anby + 2 unequipped = 12 total
        assert result.imported == 12
        assert result.skipped_duplicate == 0

    async def test_rina_build_has_engine(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        rina_build = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["rina_id"]
                )
            )
        ).scalars().first()
        assert rina_build is not None
        assert rina_build.w_engine_id == ids["engine_id"]
        assert rina_build.w_engine_level == 60
        assert rina_build.w_engine_refinement == 1

    async def test_rina_build_has_six_discs_attached(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        rina_build = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["rina_id"]
                )
            )
        ).scalars().first()
        assert rina_build is not None

        attached = (
            await db_session.execute(
                select(Disc).where(Disc.build_id == rina_build.id)
            )
        ).scalars().all()
        assert len(attached) == 6
        slots = {d.build_slot for d in attached}
        assert slots == {1, 2, 3, 4, 5, 6}

    async def test_anby_build_no_engine_four_discs(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        anby_build = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["anby_id"]
                )
            )
        ).scalars().first()
        assert anby_build is not None
        assert anby_build.w_engine_id is None

        attached = (
            await db_session.execute(
                select(Disc).where(Disc.build_id == anby_build.id)
            )
        ).scalars().all()
        assert len(attached) == 4
        slots = {d.build_slot for d in attached}
        assert slots == {1, 2, 4, 5}

    async def test_lucy_build_bare(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        lucy_build = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["lucy_id"]
                )
            )
        ).scalars().first()
        assert lucy_build is not None
        assert lucy_build.w_engine_id is None

        attached = (
            await db_session.execute(
                select(Disc).where(Disc.build_id == lucy_build.id)
            )
        ).scalars().all()
        assert len(attached) == 0

    async def test_rina_skill_and_core_levels(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        rina_build = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["rina_id"]
                )
            )
        ).scalars().first()
        assert rina_build is not None
        # talent: basic=12, dodge=12, special=12, chain=12, core=6
        # skill_levels = "12,12,12,12,6" (core attack = max(1,6)=6)
        assert rina_build.skill_levels == "12,12,12,12,6"
        # core_skill_level = clamp(6-1, 0, 5) = 5
        assert rina_build.core_skill_level == 5
        assert rina_build.mindscape_level == 6

    async def test_lucy_core_zero(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        lucy_build = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["lucy_id"]
                )
            )
        ).scalars().first()
        assert lucy_build is not None
        # talent.core = 0 → core attack = max(1,0)=1; core_skill_level = clamp(-1,0,5)=0
        assert lucy_build.skill_levels.endswith(",1")
        assert lucy_build.core_skill_level == 0


class TestEzodImportConflict:
    async def test_skip_does_not_change_existing_builds(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)
        result2 = await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id, build_conflict="skip"
        )

        assert result2.builds_created == 0
        assert result2.builds_skipped == 3
        assert result2.builds_overwritten == 0

    async def test_overwrite_replaces_builds(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        result1 = await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)
        assert result1.builds_created == 3

        result2 = await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id, build_conflict="overwrite"
        )

        # Issue #141: asserted 3, pinning the defect. An overwrite incremented
        # `builds_overwritten` and then fell through to an unconditional
        # `builds_created += 1`. Nothing is created here — all three already exist.
        assert result2.builds_created == 0
        assert result2.builds_overwritten == 3
        assert result2.builds_skipped == 0

        # Still exactly one build per agent.
        builds = (
            await db_session.execute(
                select(Build).where(Build.owner_id == user.id)
            )
        ).scalars().all()
        assert len(builds) == 3

    async def test_overwrite_detaches_old_discs(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        # Capture old Rina build ID before overwrite.
        rina_build_before = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["rina_id"]
                )
            )
        ).scalars().first()
        old_build_id = rina_build_before.id

        await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id, build_conflict="overwrite"
        )

        # D-IM2: the build row is updated in place, not deleted+recreated —
        # its id survives so any Team/Combo referencing it stays intact.
        old_build = (
            await db_session.execute(select(Build).where(Build.id == old_build_id))
        ).scalars().first()
        assert old_build is not None

        # Discs from the (same) file are re-attached under the same build id.
        attached = (
            await db_session.execute(select(Disc).where(Disc.build_id == old_build_id))
        ).scalars().all()
        assert len(attached) == 6


class TestEzodOverwritePreservesTeamAndCombo:
    """D-IM2 regression: the live prod bug. build_conflict=overwrite (the
    default) must update the Build row in place, not delete+recreate it —
    otherwise Team.build1_id → SET NULL (D-IM1) silently empties any team
    whose slot-1 agent is re-imported, even though the team itself survives.
    """

    async def test_overwrite_preserves_build_id_team_and_combo(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        rina_build = (
            await db_session.execute(
                select(Build).where(
                    Build.owner_id == user.id, Build.agent_id == ids["rina_id"]
                )
            )
        ).scalars().first()
        assert rina_build is not None
        original_build_id = rina_build.id

        team = Team(name="Rina Team", build1_id=original_build_id)
        db_session.add(team)
        await db_session.flush()
        combo = Combo(name="Rotation", team_id=team.id, sequence=[])
        db_session.add(combo)
        await db_session.flush()
        team_id, combo_id = team.id, combo.id

        # Re-import with a changed level/refinement so the update is
        # observable, not an accidental match against the first import.
        changed_payload = copy.deepcopy(ezod_payload)
        for char in changed_payload["characters"]:
            if char["key"] == "Rina":
                char["level"] = 55
        for weapon in changed_payload["weapons"]:
            if weapon.get("location") == "Rina":
                weapon["refinement"] = 3

        result = await import_ezod_payload(
            changed_payload, db_session, owner_id=user.id, build_conflict="overwrite"
        )
        assert result.builds_overwritten == 3

        db_session.expire_all()

        # Row identity survives.
        updated_build = await db_session.get(Build, original_build_id)
        assert updated_build is not None
        assert updated_build.agent_level == 55
        assert updated_build.w_engine_refinement == 3

        # Team and Combo survive, and the team's slot still points at the
        # (unchanged-id) build — no SET NULL, no cascade.
        refreshed_team = await db_session.get(Team, team_id)
        assert refreshed_team is not None
        assert refreshed_team.build1_id == original_build_id

        refreshed_combo = await db_session.get(Combo, combo_id)
        assert refreshed_combo is not None


class TestEzodImportCleanModes:
    """Task 4: ``disc_mode`` / ``build_mode`` = ``clean`` wipe the owner's
    existing rows before the import, inside the same transaction.
    """

    async def test_clean_disc_mode_replaces_inventory(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        # A clean re-import wipes the 12 existing discs, then re-imports all 12
        # as new rows (nothing to dedup against).
        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id, disc_mode="clean"
        )
        assert result.discs_deleted == 12
        assert result.imported == 12
        assert result.skipped_duplicate == 0

        discs = (
            await db_session.execute(select(Disc).where(Disc.owner_id == user.id))
        ).scalars().all()
        assert len(discs) == 12

    async def test_clean_build_mode_wipes_builds_absent_from_file(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        # An extra build for an agent the file does not mention.
        ghost_agent = Agent(
            hakushin_id=9109, name="Ghost",
            element=Element.ICE, specialty=Specialty.ATTACK, rarity=Rarity.S,
        )
        db_session.add(ghost_agent)
        await db_session.flush()
        db_session.add(Build(owner_id=user.id, agent_id=ghost_agent.id, agent_level=60))
        await db_session.flush()

        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id, build_mode="clean"
        )
        assert result.builds_deleted == 4
        assert result.builds_created == 3
        assert result.builds_overwritten == 0

        builds = (
            await db_session.execute(select(Build).where(Build.owner_id == user.id))
        ).scalars().all()
        assert len(builds) == 3
        assert ghost_agent.id not in {b.agent_id for b in builds}

    async def test_clean_build_mode_detaches_discs_of_wiped_builds(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        owner_id = user.id
        await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=owner_id)

        # Lucy has no equipped discs in the fixture, but Rina/Anby do (6 + 4).
        # Wiping builds detaches every disc; the re-import re-attaches the same
        # ten, and the 2 unequipped discs stay detached.
        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
        )
        assert result.builds_deleted == 3

        db_session.expire_all()
        detached = (
            await db_session.execute(
                select(Disc).where(Disc.owner_id == owner_id, Disc.build_id.is_(None))
            )
        ).scalars().all()
        assert len(detached) == 2

    async def test_build_conflict_ignored_under_clean_build_mode(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        # `skip` would normally leave all three builds untouched; under
        # build_mode=clean there is nothing left to skip.
        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id,
            build_conflict="skip", build_mode="clean",
        )
        assert result.builds_skipped == 0
        assert result.builds_created == 3

    async def test_merge_modes_are_the_default_and_delete_nothing(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)
        result = await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)

        assert result.discs_deleted == 0
        assert result.builds_deleted == 0
        assert result.skipped_duplicate == 12
        assert result.builds_overwritten == 3

    async def test_clean_is_owner_scoped(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        ids = await _seed(db_session)

        other = User(
            email=f"other_{secrets.token_hex(4)}@test.example",
            label="Other",
            password_hash=hash_password("alpha-test-password-1234"),
        )
        db_session.add(other)
        await db_session.flush()
        other_build = Build(owner_id=other.id, agent_id=ids["rina_id"], agent_level=60)
        db_session.add(other_build)
        await db_session.flush()
        other_build_id = other_build.id

        await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id,
            disc_mode="clean", build_mode="clean",
        )

        assert await db_session.get(Build, other_build_id) is not None

    async def test_clean_without_owner_id_raises(
        self, db_session: AsyncSession, ezod_payload: dict
    ):
        await _seed(db_session)

        with pytest.raises(ValueError, match="owner_id"):
            await import_ezod_payload(ezod_payload, db_session, disc_mode="clean")


class TestEzodCleanRemapsTeams:
    """Task 4.5 / D-IM3: `build_mode="clean"` destroys every owner build, so
    team slots cannot survive by row identity the way D-IM2's overwrite lets
    them. Teams are hand-authored composition — carry them across the wipe by
    re-mapping each slot to the new build for the same agent, and delete only
    the teams that end up with nothing at all.
    """

    async def _import_and_get_builds(
        self, db_session: AsyncSession, payload: dict, owner_id: str
    ) -> dict[str, str]:
        """Import, then map ``agent_id → build_id`` for the owner."""
        await import_ezod_payload(payload, db_session, owner_id=owner_id)
        builds = (
            await db_session.execute(select(Build).where(Build.owner_id == owner_id))
        ).scalars().all()
        return {b.agent_id: b.id for b in builds}

    async def test_team_with_all_agents_in_file_keeps_every_slot(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        owner_id = user.id
        ids = await _seed(db_session)

        by_agent = await self._import_and_get_builds(db_session, ezod_payload, owner_id)
        team = Team(
            owner_id=owner_id,
            name="Full",
            build1_id=by_agent[ids["rina_id"]],
            build2_id=by_agent[ids["anby_id"]],
            build3_id=by_agent[ids["lucy_id"]],
        )
        db_session.add(team)
        await db_session.flush()
        combo = Combo(owner_id=owner_id, name="Rotation", team_id=team.id, sequence=[])
        db_session.add(combo)
        await db_session.flush()
        team_id, combo_id = team.id, combo.id

        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
        )
        assert result.builds_deleted == 3
        assert result.team_slots_remapped == 3
        assert result.teams_deleted == 0
        assert result.combos_deleted == 0

        db_session.expire_all()
        refreshed = await db_session.get(Team, team_id)
        assert refreshed is not None
        assert await db_session.get(Combo, combo_id) is not None

        # Slots point at the *new* build rows, one per original agent.
        new_by_agent = {
            b.agent_id: b.id
            for b in (
                await db_session.execute(select(Build).where(Build.owner_id == owner_id))
            ).scalars().all()
        }
        assert refreshed.build1_id == new_by_agent[ids["rina_id"]]
        assert refreshed.build2_id == new_by_agent[ids["anby_id"]]
        assert refreshed.build3_id == new_by_agent[ids["lucy_id"]]
        # ...and those are genuinely new rows, not the pre-wipe ones.
        assert refreshed.build1_id != by_agent[ids["rina_id"]]

    async def test_team_with_some_agents_in_file_survives_with_partial_slots(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        owner_id = user.id
        ids = await _seed(db_session)

        ghost = Agent(
            hakushin_id=9110, name="Ghost",
            element=Element.ICE, specialty=Specialty.ATTACK, rarity=Rarity.S,
        )
        db_session.add(ghost)
        await db_session.flush()
        ghost_id = ghost.id

        by_agent = await self._import_and_get_builds(db_session, ezod_payload, owner_id)
        ghost_build = Build(owner_id=owner_id, agent_id=ghost_id, agent_level=60)
        db_session.add(ghost_build)
        await db_session.flush()

        team = Team(
            owner_id=owner_id,
            name="Partial",
            build1_id=by_agent[ids["rina_id"]],
            build2_id=ghost_build.id,
        )
        db_session.add(team)
        await db_session.flush()
        combo = Combo(owner_id=owner_id, name="Rotation", team_id=team.id, sequence=[])
        db_session.add(combo)
        await db_session.flush()
        team_id, combo_id = team.id, combo.id

        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
        )
        assert result.team_slots_remapped == 1
        assert result.teams_deleted == 0

        db_session.expire_all()
        refreshed = await db_session.get(Team, team_id)
        assert refreshed is not None
        assert refreshed.build1_id is not None  # Rina came back
        assert refreshed.build2_id is None  # Ghost did not
        assert await db_session.get(Combo, combo_id) is not None

    async def test_team_with_no_agents_in_file_is_deleted_and_counted(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        owner_id = user.id
        await _seed(db_session)

        ghost = Agent(
            hakushin_id=9111, name="Ghost",
            element=Element.ICE, specialty=Specialty.ATTACK, rarity=Rarity.S,
        )
        db_session.add(ghost)
        await db_session.flush()

        ghost_build = Build(owner_id=owner_id, agent_id=ghost.id, agent_level=60)
        db_session.add(ghost_build)
        await db_session.flush()
        team = Team(owner_id=owner_id, name="Doomed", build1_id=ghost_build.id)
        db_session.add(team)
        await db_session.flush()
        db_session.add_all(
            [
                Combo(owner_id=owner_id, name="C1", team_id=team.id, sequence=[]),
                Combo(owner_id=owner_id, name="C2", team_id=team.id, sequence=[]),
            ]
        )
        await db_session.flush()
        team_id = team.id

        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
        )
        assert result.team_slots_remapped == 0
        assert result.teams_deleted == 1
        assert result.combos_deleted == 2

        db_session.expire_all()
        assert await db_session.get(Team, team_id) is None
        assert (
            await db_session.execute(select(Combo).where(Combo.team_id == team_id))
        ).scalars().all() == []

    async def test_preexisting_empty_team_is_left_alone(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        # A team that was already all-NULL before the import is outside the
        # import's blast radius — the sweep must not adopt it.
        user, _ = authed_user
        owner_id = user.id
        await _seed(db_session)

        team = Team(owner_id=owner_id, name="Already Empty")
        db_session.add(team)
        await db_session.flush()
        team_id = team.id

        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
        )
        assert result.teams_deleted == 0

        db_session.expire_all()
        assert await db_session.get(Team, team_id) is not None

    async def test_other_owners_teams_are_untouched(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        owner_id = user.id
        ids = await _seed(db_session)

        other = User(
            email=f"other_{secrets.token_hex(4)}@test.example",
            label="Other",
            password_hash=hash_password("alpha-test-password-1234"),
        )
        db_session.add(other)
        await db_session.flush()
        other_build = Build(owner_id=other.id, agent_id=ids["rina_id"], agent_level=60)
        db_session.add(other_build)
        await db_session.flush()
        other_team = Team(owner_id=other.id, name="Theirs", build1_id=other_build.id)
        db_session.add(other_team)
        await db_session.flush()
        other_team_id, other_build_id = other_team.id, other_build.id

        await self._import_and_get_builds(db_session, ezod_payload, owner_id)
        result = await import_ezod_payload(
            ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
        )
        assert result.teams_deleted == 0

        db_session.expire_all()
        refreshed = await db_session.get(Team, other_team_id)
        assert refreshed is not None
        assert refreshed.build1_id == other_build_id

    async def test_merge_mode_reports_zero_team_counters(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        result = await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)
        assert result.team_slots_remapped == 0
        assert result.teams_deleted == 0
        assert result.combos_deleted == 0


class TestEzodImportDedup:
    async def test_disc_dedup_on_reimport(
        self, db_session: AsyncSession, authed_user: tuple, ezod_payload: dict
    ):
        user, _ = authed_user
        await _seed(db_session)

        result1 = await import_ezod_payload(ezod_payload, db_session, owner_id=user.id)
        assert result1.imported == 12

        # Re-import: all discs already exist, none should be duplicated.
        result2 = await import_ezod_payload(
            ezod_payload, db_session, owner_id=user.id, build_conflict="skip"
        )
        assert result2.imported == 0
        assert result2.skipped_duplicate == 12

    async def test_unknown_agent_key_recorded_in_errors(
        self, db_session: AsyncSession, authed_user: tuple
    ):
        user, _ = authed_user
        await _seed(db_session)

        payload = {
            "format": "eZOD",
            "version": 1,
            "source": "Youkai",
            "characters": [{"key": "UnknownAgent", "level": 60, "constellation": 0}],
            "weapons": [],
            "discs": [],
        }
        result = await import_ezod_payload(payload, db_session, owner_id=user.id)

        assert result.builds_created == 0
        assert any("UnknownAgent" in e for e in result.errors)
