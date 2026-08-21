"""Integration tests for ``POST /api/v1/discs/import``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.data.importers.ezod_importer import MAX_CHAR_COUNT, MAX_DISC_COUNT, MAX_WEAPON_COUNT
from app.models.agent import Agent
from app.models.build import Build, Combo
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty
from app.models.team import Team
from app.models.w_engine import WEngine

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

_EZOD_FIXTURE = Path(__file__).parent / "fixtures" / "ezod_small.json"

# Hakushin IDs for this module — offset from test_ezod_import.py to avoid conflicts.
_HA = 8100  # Rina
_HB = 8101  # Anby
_HC = 8102  # Lucy
_HE = 8200  # BashfulDemon
_HD1 = 8300  # PufferElectro
_HD2 = 8301  # AstralVoice
_HD3 = 8302  # WoodpeckerElectro


async def _seed_ezod(db: AsyncSession) -> None:
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
    db.add_all([
        rina, anby, lucy, engine,
        DiscSet(hakushin_id=_HD1, name="Puffer Electro"),
        DiscSet(hakushin_id=_HD2, name="Astral Voice"),
        DiscSet(hakushin_id=_HD3, name="Woodpecker Electro"),
    ])
    await db.flush()


# Tests ship inline ZOD payloads to avoid coupling to the references file
# (which isn't bind-mounted into the backend container). The references
# file is exercised in a separate path test that runs only when present.


async def _seed_set(db: AsyncSession, name: str, set_id: int) -> str:
    s = DiscSet(hakushin_id=set_id, name=name)
    db.add(s)
    await db.flush()
    return s.id


def _zod(discs: list[dict]) -> dict:
    return {"format": "ZOD", "version": 1, "source": "test", "discs": discs}


class TestDiscImportEndpoint:
    async def test_imports_single_disc(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_set(db_session, "Moonlight Lullaby", 33400)
        payload = _zod(
            [
                {
                    "setKey": "MoonlightLullaby",
                    "slotKey": "1",
                    "level": 15,
                    "rarity": "S",
                    "mainStatKey": "hp",
                    "substats": [
                        {"key": "crit_", "upgrades": 2},
                        {"key": "atk_", "upgrades": 3},
                        {"key": "def_", "upgrades": 3},
                        {"key": "atk", "upgrades": 1},
                    ],
                }
            ]
        )
        resp = await authed_client.post("/api/v1/discs/import", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["imported"] == 1
        assert data["skipped_duplicate"] == 0

        # Disc landed unequipped in the inventory.
        listing = await authed_client.get("/api/v1/discs")
        assert listing.json()["total"] == 1

    async def test_dedups_on_reimport(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_set(db_session, "Moonlight Lullaby", 33400)
        payload = _zod(
            [
                {
                    "setKey": "MoonlightLullaby",
                    "slotKey": "1",
                    "level": 15,
                    "rarity": "S",
                    "mainStatKey": "hp",
                    "substats": [{"key": "crit_", "upgrades": 9}],
                }
            ]
        )
        first = await authed_client.post("/api/v1/discs/import", json=payload)
        second = await authed_client.post("/api/v1/discs/import", json=payload)
        assert first.json()["imported"] == 1
        assert second.json()["imported"] == 0
        assert second.json()["skipped_duplicate"] == 1
        # Inventory still has just the one.
        assert (await authed_client.get("/api/v1/discs")).json()["total"] == 1

    async def test_unknown_set_recorded_in_errors(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_set(db_session, "Moonlight Lullaby", 33400)
        payload = _zod(
            [
                {
                    "setKey": "TotallyMadeUp",
                    "slotKey": "1",
                    "level": 15,
                    "rarity": "S",
                    "mainStatKey": "hp",
                    "substats": [{"key": "crit_", "upgrades": 9}],
                }
            ]
        )
        resp = await authed_client.post("/api/v1/discs/import", json=payload)
        body = resp.json()
        assert body["imported"] == 0
        assert body["skipped_unknown_set"] == 1
        assert any("TotallyMadeUp" in e for e in body["errors"])

    async def test_partial_payload_imports_valid_skips_invalid(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_set(db_session, "Moonlight Lullaby", 33400)
        payload = _zod(
            [
                {  # valid
                    "setKey": "MoonlightLullaby",
                    "slotKey": "1",
                    "level": 15,
                    "rarity": "S",
                    "mainStatKey": "hp",
                    "substats": [{"key": "atk", "upgrades": 9}],
                },
                {  # invalid rarity
                    "setKey": "MoonlightLullaby",
                    "slotKey": "2",
                    "level": 15,
                    "rarity": "Z",
                    "mainStatKey": "atk",
                    "substats": [],
                },
                {  # unknown set
                    "setKey": "Mystery",
                    "slotKey": "1",
                    "level": 15,
                    "rarity": "S",
                    "mainStatKey": "hp",
                    "substats": [{"key": "atk", "upgrades": 9}],
                },
            ]
        )
        resp = await authed_client.post("/api/v1/discs/import", json=payload)
        body = resp.json()
        assert body["imported"] == 1
        assert body["skipped_invalid"] == 1
        assert body["skipped_unknown_set"] == 1

class TestDiscImportReferencesFile:
    """Smoke check against the actual ZOD export checked in to /references.

    Only runs when /references/*.ZOD.json is reachable from the container —
    skipped otherwise so the test stays passing in environments without
    the references bind mount.
    """

    async def test_full_references_payload_imports(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        # The references folder isn't bind-mounted into the backend
        # container; check both common locations.
        candidates = [
            Path("/references"),
            Path("/app/../references"),
            Path("/app/references"),
        ]
        zod = None
        for c in candidates:
            try:
                hits = list(c.glob("*.ZOD.json"))
            except OSError:
                continue
            if hits:
                zod = hits[0]
                break

        if zod is None:
            import pytest

            pytest.skip("references ZOD file not mounted into container")

        # Need disc sets in the test DB for the importer to resolve. Pull
        # the live names from the dev DB via the model's known seed data.
        # In a clean test DB we just seed the 22 sets the file references.
        for name, set_id in [
            ("Astral Voice", 32800),
            ("Branch & Blade Song", 32700),
            ("Chaos Jazz", 31800),
            ("Chaotic Metal", 32300),
            ("Dawn's Bloom", 33300),
            ("Fanged Metal", 32600),
            ("Freedom Blues", 31300),
            ("Hormone Punk", 31400),
            ("Inferno Metal", 32200),
            ("King of the Summit", 33200),
            ("Moonlight Lullaby", 33400),
            ("Phaethon's Melody", 33000),
            ("Polar Metal", 32500),
            ("Proto Punk", 31900),
            ("Puffer Electro", 31100),
            ("Shadow Harmony", 32900),
            ("Shockstar Disco", 31200),
            ("Soul Rock", 31500),
            ("Swing Jazz", 31600),
            ("Thunder Metal", 32400),
            ("Woodpecker Electro", 31000),
            ("Yunkui Tales", 33100),
        ]:
            await _seed_set(db_session, name, set_id)

        payload = json.loads(zod.read_text())
        resp = await authed_client.post("/api/v1/discs/import", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The references file has 1,609 discs; expect most to import cleanly.
        assert body["imported"] > 1000
        assert body["skipped_unknown_set"] == 0


class TestEzodImportEndpoint:
    """API-level tests for the eZOD branch of POST /discs/import."""

    async def test_ezod_import_returns_build_counts(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        resp = await authed_client.post("/api/v1/discs/import", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["builds_created"] == 3
        assert body["builds_overwritten"] == 0
        assert body["builds_skipped"] == 0
        assert body["imported"] == 12

    async def test_ezod_import_conflict_overwrite(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        first = await authed_client.post("/api/v1/discs/import", json=payload)
        assert first.json()["builds_created"] == 3
        second = await authed_client.post(
            "/api/v1/discs/import",
            json=payload,
            params={"build_conflict": "overwrite"},
        )
        assert second.status_code == 200, second.text
        body = second.json()
        assert body["builds_overwritten"] == 3
        # Issue #141: this asserted 3 and was pinning the defect — an overwrite
        # incremented `builds_overwritten` and then fell through to an unconditional
        # `builds_created += 1`, so 3 overwritten builds reported 6 build events.
        # Nothing is created here; all three already existed.
        assert body["builds_created"] == 0

    async def test_ezod_import_conflict_skip_explicit(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        await authed_client.post("/api/v1/discs/import", json=payload)
        second = await authed_client.post(
            "/api/v1/discs/import",
            json=payload,
            params={"build_conflict": "skip"},
        )
        body = second.json()
        assert body["builds_skipped"] == 3
        assert body["builds_created"] == 0

    async def test_ezod_import_conflict_overwrite_default(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Re-importing without specifying build_conflict overwrites existing builds."""
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        await authed_client.post("/api/v1/discs/import", json=payload)
        second = await authed_client.post("/api/v1/discs/import", json=payload)
        body = second.json()
        assert body["builds_overwritten"] == 3
        # Issue #141: this asserted 3 and was pinning the defect — an overwrite
        # incremented `builds_overwritten` and then fell through to an unconditional
        # `builds_created += 1`, so 3 overwritten builds reported 6 build events.
        # Nothing is created here; all three already existed.
        assert body["builds_created"] == 0
        assert body["builds_skipped"] == 0

    async def test_zod_response_includes_build_count_fields(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """ZOD path still works; new build-count fields default to 0."""
        await _seed_set(db_session, "Moonlight Lullaby", 33400)
        payload = _zod([{
            "setKey": "MoonlightLullaby", "slotKey": "1", "level": 15,
            "rarity": "S", "mainStatKey": "hp",
            "substats": [{"key": "crit_", "upgrades": 2}],
        }])
        resp = await authed_client.post("/api/v1/discs/import", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["imported"] == 1
        assert body["builds_created"] == 0
        assert body["builds_overwritten"] == 0
        assert body["builds_skipped"] == 0

    async def test_unsupported_format_rejected(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/discs/import",
            json={"format": "GOOD", "discs": []},
        )
        assert resp.status_code == 422
        assert "ZOD" in resp.json()["detail"]


class TestImportModeParams:
    """``disc_mode`` / ``build_mode`` query params and their response counters."""

    async def test_bad_disc_mode_returns_422(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/discs/import",
            json=_zod([]),
            params={"disc_mode": "nuke"},
        )
        assert resp.status_code == 422
        assert "disc_mode" in resp.json()["detail"]

    async def test_bad_build_mode_returns_422(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/discs/import",
            json=_zod([]),
            params={"build_mode": "nuke"},
        )
        assert resp.status_code == 422
        assert "build_mode" in resp.json()["detail"]

    async def test_mode_validation_precedes_format_check(self, authed_client: AsyncClient):
        """A bad mode is rejected even for an unsupported format."""
        resp = await authed_client.post(
            "/api/v1/discs/import",
            json={"format": "GOOD", "discs": []},
            params={"disc_mode": "nuke"},
        )
        assert resp.status_code == 422
        assert "disc_mode" in resp.json()["detail"]

    async def test_defaults_are_merge_and_report_zero_counters(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        await authed_client.post("/api/v1/discs/import", json=payload)
        second = await authed_client.post("/api/v1/discs/import", json=payload)
        body = second.json()
        assert body["discs_deleted"] == 0
        assert body["builds_deleted"] == 0
        assert body["teams_deleted"] == 0
        assert body["combos_deleted"] == 0
        assert body["team_slots_remapped"] == 0

    async def test_zod_disc_mode_clean_reports_discs_deleted(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_set(db_session, "Moonlight Lullaby", 33400)
        first = _zod([{
            "setKey": "MoonlightLullaby", "slotKey": "1", "level": 15,
            "rarity": "S", "mainStatKey": "hp",
            "substats": [{"key": "crit_", "upgrades": 2}],
        }])
        second = _zod([{
            "setKey": "MoonlightLullaby", "slotKey": "2", "level": 12,
            "rarity": "S", "mainStatKey": "atk",
            "substats": [{"key": "atk_", "upgrades": 3}],
        }])
        await authed_client.post("/api/v1/discs/import", json=first)
        resp = await authed_client.post(
            "/api/v1/discs/import", json=second, params={"disc_mode": "clean"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["discs_deleted"] == 1
        assert body["imported"] == 1
        # Inventory was replaced, not merged.
        assert (await authed_client.get("/api/v1/discs")).json()["total"] == 1

    async def test_zod_ignores_build_mode_clean(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple[User, str],
    ):
        """ZOD has no builds to wipe: ``build_mode=clean`` must not delete any."""
        user, _ = authed_user
        owner_id = user.id
        await _seed_ezod(db_session)
        await _seed_set(db_session, "Moonlight Lullaby", 33400)
        await authed_client.post(
            "/api/v1/discs/import", json=json.loads(_EZOD_FIXTURE.read_text())
        )
        db_session.expire_all()
        before = len(
            (await db_session.execute(select(Build).where(Build.owner_id == owner_id)))
            .scalars()
            .all()
        )
        assert before == 3

        resp = await authed_client.post(
            "/api/v1/discs/import",
            json=_zod([{
                "setKey": "MoonlightLullaby", "slotKey": "1", "level": 15,
                "rarity": "S", "mainStatKey": "hp",
                "substats": [{"key": "crit_", "upgrades": 2}],
            }]),
            params={"build_mode": "clean"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["builds_deleted"] == 0

        db_session.expire_all()
        after = (
            (await db_session.execute(select(Build).where(Build.owner_id == owner_id)))
            .scalars()
            .all()
        )
        assert len(after) == 3

    async def test_ezod_clean_modes_report_deleted_counts(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        first = await authed_client.post("/api/v1/discs/import", json=payload)
        assert first.json()["imported"] == 12

        resp = await authed_client.post(
            "/api/v1/discs/import",
            json=payload,
            params={"disc_mode": "clean", "build_mode": "clean"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["discs_deleted"] == 12
        assert body["builds_deleted"] == 3
        # Wiped baseline: everything re-imports as new, nothing conflicts.
        assert body["imported"] == 12
        assert body["builds_created"] == 3
        assert body["builds_overwritten"] == 0
        assert body["builds_skipped"] == 0

    async def test_ezod_build_mode_clean_surfaces_team_counters(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple[User, str],
    ):
        """Surviving teams are re-pointed; orphaned teams (+ combos) are deleted."""
        user, _ = authed_user
        owner_id = user.id
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        await authed_client.post("/api/v1/discs/import", json=payload)

        db_session.expire_all()
        rina = (
            await db_session.execute(select(Agent).where(Agent.hakushin_id == _HA))
        ).scalar_one()
        rina_build = (
            await db_session.execute(
                select(Build).where(Build.owner_id == owner_id, Build.agent_id == rina.id)
            )
        ).scalar_one()

        # Team A: slot-1 agent is in the file → slot gets re-pointed, team survives.
        survivor = Team(owner_id=owner_id, name="Survivor", build1_id=rina_build.id)
        # Team B: its only agent is absent from the file → team + combo deleted.
        ghost = Agent(
            hakushin_id=8999, name="Ghost",
            element=Element.ICE, specialty=Specialty.ATTACK, rarity=Rarity.S,
        )
        db_session.add(ghost)
        await db_session.flush()
        ghost_build = Build(owner_id=owner_id, agent_id=ghost.id, agent_level=60)
        db_session.add(ghost_build)
        await db_session.flush()
        doomed = Team(owner_id=owner_id, name="Doomed", build1_id=ghost_build.id)
        db_session.add_all([survivor, doomed])
        await db_session.flush()
        db_session.add_all([
            Combo(owner_id=owner_id, name="Keep", team_id=survivor.id, sequence=[]),
            Combo(owner_id=owner_id, name="Lose", team_id=doomed.id, sequence=[]),
        ])
        await db_session.flush()
        survivor_id, doomed_id, old_build_id = survivor.id, doomed.id, rina_build.id

        resp = await authed_client.post(
            "/api/v1/discs/import", json=payload, params={"build_mode": "clean"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["builds_deleted"] == 4  # 3 imported + the ghost
        assert body["team_slots_remapped"] == 1
        assert body["teams_deleted"] == 1
        assert body["combos_deleted"] == 1

        db_session.expire_all()
        kept = await db_session.get(Team, survivor_id)
        assert kept is not None
        assert kept.build1_id is not None
        assert kept.build1_id != old_build_id  # re-pointed at the fresh build
        assert await db_session.get(Team, doomed_id) is None

    async def test_ezod_disc_mode_clean_alone_keeps_builds(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple[User, str],
    ):
        """The hazard combo: wipe discs, merge builds. Builds survive, discs are replaced."""
        user, _ = authed_user
        owner_id = user.id
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        await authed_client.post("/api/v1/discs/import", json=payload)

        resp = await authed_client.post(
            "/api/v1/discs/import", json=payload, params={"disc_mode": "clean"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["discs_deleted"] == 12
        assert body["builds_deleted"] == 0
        assert body["builds_overwritten"] == 3

        db_session.expire_all()
        discs = (
            (await db_session.execute(select(Disc).where(Disc.owner_id == owner_id)))
            .scalars()
            .all()
        )
        assert len(discs) == 12


class TestDiscListPaginationCeiling:
    async def test_limit_above_3000_returns_422(self, authed_client: AsyncClient):
        resp = await authed_client.get("/api/v1/discs", params={"limit": 5000})
        assert resp.status_code == 422

    async def test_limit_3000_is_accepted(self, authed_client: AsyncClient):
        resp = await authed_client.get("/api/v1/discs", params={"limit": 3000})
        assert resp.status_code == 200

    async def test_limit_3001_returns_422(self, authed_client: AsyncClient):
        resp = await authed_client.get("/api/v1/discs", params={"limit": 3001})
        assert resp.status_code == 422


class TestEzodIdenticalDiscsOnDifferentCharacters:
    """Issue #139 — content-identical discs equipped to two characters.

    Two discs of the same set, slot, level, rarity, main stat and substat spread are
    indistinguishable by content hash, because there is nothing to distinguish. At
    endgame that is not rare. The importer hashes for idempotence (`test_dedups_on_reimport`)
    and previously used one `hash -> Disc` mapping, so the second occurrence was counted
    `skipped_duplicate` and both characters were then pointed at the *same* row —
    last write wins, and one character silently lost a slot.

    The counts reconciled perfectly while a build lost a piece, which is exactly why
    #81's "N imported, M skipped" headline cannot surface it.
    """

    @staticmethod
    def _payload_with_a_shared_disc() -> dict:
        """The fixture, with Anby given a byte-identical copy of Rina's slot-1 disc."""
        payload = json.loads(_EZOD_FIXTURE.read_text())
        rina_slot1 = next(
            d for d in payload["discs"] if d["location"] == "Rina" and d["slotKey"] == "1"
        )
        twin = json.loads(json.dumps(rina_slot1))
        twin["location"] = "Anby"
        # Drop Anby's own slot-1 disc so the twin is unambiguously her slot 1.
        payload["discs"] = [
            d
            for d in payload["discs"]
            if not (d["location"] == "Anby" and d["slotKey"] == "1")
        ]
        payload["discs"].append(twin)
        return payload

    async def test_both_characters_keep_their_slot_one_disc(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_ezod(db_session)

        resp = await authed_client.post(
            "/api/v1/discs/import", json=self._payload_with_a_shared_disc()
        )
        assert resp.status_code == 200, resp.text

        discs = (await db_session.execute(select(Disc))).scalars().all()
        equipped_slot1 = [d for d in discs if d.build_slot == DiscSlot.ONE and d.build_id]

        # Rina and Anby each equip a slot-1 disc in this payload (Lucy has none),
        # and after the twin swap those two discs are byte-identical.
        assert len(equipped_slot1) == 2, (
            f"expected two equipped slot-1 discs, got {len(equipped_slot1)} — a character "
            f"lost its slot-1 disc because both were pointed at one row (issue #139)"
        )
        owners = {str(d.build_id) for d in equipped_slot1}
        assert len(owners) == 2, (
            "both slot-1 discs are attached to the same build — last write wins, and the "
            "other character silently lost the slot (issue #139)"
        )

    async def test_the_twin_is_imported_not_dropped_as_a_duplicate(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Two identical discs in one payload are two discs the player owns."""
        await _seed_ezod(db_session)

        resp = await authed_client.post(
            "/api/v1/discs/import", json=self._payload_with_a_shared_disc()
        )
        body = resp.json()

        assert body["imported"] == 12, body
        assert body["skipped_duplicate"] == 0, (
            "the second copy is a disc the player owns, not a re-import of the first"
        )

    async def test_reimporting_the_same_payload_is_still_idempotent(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """The property the content hash exists for must survive the fix.

        Multiplicity, not mere presence: the second run must recognise it already holds
        *two* copies, not just that the hash is known.
        """
        await _seed_ezod(db_session)
        payload = self._payload_with_a_shared_disc()

        first = await authed_client.post("/api/v1/discs/import", json=payload)
        assert first.json()["imported"] == 12

        second = await authed_client.post("/api/v1/discs/import", json=payload)
        body = second.json()

        assert body["imported"] == 0, body
        assert body["skipped_duplicate"] == 12, body
        total = len((await db_session.execute(select(Disc))).scalars().all())
        assert total == 12, f"re-import created extra rows: {total}"

    async def test_a_character_listed_twice_keeps_its_discs(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A malformed payload naming one character twice must not strip its loadout.

        The second pass takes the overwrite branch, which detaches the build's discs
        before re-attaching whatever the file still lists. Those rows were claimed on
        the first pass, so unless detaching releases the claim the re-attach finds
        nothing available and the character is left with an empty build.
        """
        await _seed_ezod(db_session)
        payload = self._payload_with_a_shared_disc()
        rina = next(c for c in payload["characters"] if c["key"] == "Rina")
        payload["characters"].append(json.loads(json.dumps(rina)))

        resp = await authed_client.post("/api/v1/discs/import", json=payload)
        assert resp.status_code == 200, resp.text

        discs = (await db_session.execute(select(Disc))).scalars().all()
        per_build: dict[str, int] = {}
        for d in discs:
            if d.build_id:
                per_build[d.build_id] = per_build.get(d.build_id, 0) + 1

        # Rina equips six discs in the fixture, Anby four.
        assert sorted(per_build.values()) == [4, 6], (
            f"a build lost discs to a repeated character entry: {sorted(per_build.values())}"
        )


class TestZodIdenticalDiscs:
    """Issue #139, the ZOD half. Same root cause, no equip phase to make it visible.

    ZOD imports unequipped inventory, so there is no slot for a character to lose —
    the disc simply never arrives. That is the more common import path, and the
    presence-based dedup made a payload listing two identical discs import one.
    """

    @staticmethod
    def _payload(copies: int) -> dict:
        disc = {
            "setKey": "PufferElectro",
            "slotKey": "1",
            "level": 15,
            "rarity": "S",
            "mainStatKey": "hp",
            "substats": [{"key": "crit_", "upgrades": 9}],
        }
        return {
            "format": "ZOD",
            "version": 1,
            "source": "test",
            "discs": [json.loads(json.dumps(disc)) for _ in range(copies)],
        }

    async def test_identical_discs_in_one_payload_are_all_imported(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_set(db_session, "Puffer Electro", 31100)

        resp = await authed_client.post("/api/v1/discs/import", json=self._payload(3))

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["imported"] == 3, body
        assert body["skipped_duplicate"] == 0, body

    async def test_reimport_is_still_a_no_op(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Idempotence has to survive counting, not just presence."""
        await _seed_set(db_session, "Puffer Electro", 31100)
        payload = self._payload(3)

        await authed_client.post("/api/v1/discs/import", json=payload)
        second = await authed_client.post("/api/v1/discs/import", json=payload)

        body = second.json()
        assert body["imported"] == 0, body
        assert body["skipped_duplicate"] == 3, body
        assert len((await db_session.execute(select(Disc))).scalars().all()) == 3

    async def test_a_larger_second_payload_tops_up_rather_than_duplicating(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """The case presence and multiplicity actually disagree on.

        Holding 2, offered 3: exactly one is new. Presence-based dedup imports none;
        no dedup at all imports three.
        """
        await _seed_set(db_session, "Puffer Electro", 31100)

        await authed_client.post("/api/v1/discs/import", json=self._payload(2))
        resp = await authed_client.post("/api/v1/discs/import", json=self._payload(3))

        body = resp.json()
        assert body["imported"] == 1, body
        assert body["skipped_duplicate"] == 2, body
        assert len((await db_session.execute(select(Disc))).scalars().all()) == 3

    async def test_equipped_copies_count_towards_the_dedup_total(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A ZOD scan lists equipped discs too, so equipped rows are part of the count.

        The player owns two identical discs and has one of them equipped. The scanner
        file lists both. Counting only unequipped rows makes the denominator 1 against
        a payload of 2, so the equipped copy is imported a second time and the
        inventory grows a phantom disc that the player does not own.
        """
        set_id = await _seed_set(db_session, "Puffer Electro", 31100)
        await authed_client.post("/api/v1/discs/import", json=self._payload(1))
        original = (await db_session.execute(select(Disc))).scalars().all()[0]
        owner_id = original.owner_id

        agent = Agent(
            hakushin_id=8103, name="Equipper",
            element=Element.ICE, specialty=Specialty.ATTACK, rarity=Rarity.S,
        )
        db_session.add(agent)
        await db_session.flush()
        build = Build(agent_id=agent.id, agent_level=60, owner_id=owner_id)
        db_session.add(build)
        await db_session.flush()

        # A second, byte-identical disc, equipped to that build.
        db_session.add(
            Disc(
                disc_set_id=set_id,
                slot=original.slot,
                rarity=original.rarity,
                level=original.level,
                main_stat_type=original.main_stat_type,
                main_stat_value=original.main_stat_value,
                substats=original.substats,
                owner_id=owner_id,
                build_id=build.id,
                build_slot=DiscSlot.ONE,
            )
        )
        await db_session.flush()

        resp = await authed_client.post("/api/v1/discs/import", json=self._payload(2))

        body = resp.json()
        assert body["imported"] == 0, body
        assert body["skipped_duplicate"] == 2, body
        total = len((await db_session.execute(select(Disc))).scalars().all())
        assert total == 2, f"re-import inflated the inventory to {total} rows for 2 discs"


class TestEzodPayloadCapsAreEnforcedOnTheLivePath:
    """Issue #140 — the eZOD size caps existed, were tested, and never ran.

    `parse_ezod_payload` enforces MAX_DISC_COUNT / MAX_CHAR_COUNT / MAX_WEAPON_COUNT,
    and had no caller anywhere in `app/` — the endpoint went straight to
    `import_ezod_payload`. ZOD enforced its cap on the live path; eZOD did not.

    A limit asserted by tests while unreachable in production is worse than no limit,
    because it reads as covered. These drive the HTTP endpoint rather than the parser,
    so they cannot pass on a parser nothing calls.
    """

    @staticmethod
    def _payload(*, discs: int = 0, characters: int = 0, weapons: int = 0) -> dict:
        return {
            "format": "eZOD",
            "version": 1,
            "source": "test",
            "characters": [{"key": "Rina"} for _ in range(characters)],
            "weapons": [{"key": "BashfulDemon"} for _ in range(weapons)],
            "discs": [
                {
                    "setKey": "PufferElectro",
                    "slotKey": "1",
                    "level": 15,
                    "rarity": 4,
                    "mainStatKey": "hp",
                    "substats": [],
                }
                for _ in range(discs)
            ],
        }

    async def test_over_cap_disc_count_is_rejected(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/discs/import", json=self._payload(discs=MAX_DISC_COUNT + 1)
        )

        assert resp.status_code == 422, resp.status_code
        assert str(MAX_DISC_COUNT) in resp.text

    async def test_over_cap_character_count_is_rejected(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/discs/import", json=self._payload(characters=MAX_CHAR_COUNT + 1)
        )

        assert resp.status_code == 422, resp.status_code
        assert str(MAX_CHAR_COUNT) in resp.text

    async def test_over_cap_weapon_count_is_rejected(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/discs/import", json=self._payload(weapons=MAX_WEAPON_COUNT + 1)
        )

        assert resp.status_code == 422, resp.status_code
        assert str(MAX_WEAPON_COUNT) in resp.text

    async def test_a_payload_missing_a_required_section_is_rejected(
        self, authed_client: AsyncClient
    ):
        """Previously `data.get("discs", [])` defaulted to empty and imported nothing."""
        payload = self._payload()
        del payload["discs"]

        resp = await authed_client.post("/api/v1/discs/import", json=payload)

        assert resp.status_code == 422, resp.status_code
        assert "discs" in resp.text

    async def test_an_at_cap_payload_is_still_accepted(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        """The boundary must not be off by one — exactly at the cap is legal."""
        await _seed_set(db_session, "Puffer Electro", 31100)

        resp = await authed_client.post(
            "/api/v1/discs/import", json=self._payload(discs=MAX_DISC_COUNT)
        )

        assert resp.status_code == 200, resp.text
class TestBuildCountersPartitionTheCharacters:
    """Issue #141 — the three build counters must sum to the characters processed.

    Same class as #81: a number the UI renders faithfully that does not mean what it
    says. `builds_created` counted overwrites too, so a user re-importing their roster
    saw "Builds created: 3" for builds that already existed, one line below the
    "Builds overwritten: 3" that described the same three builds.
    """

    async def test_overwrite_reports_no_creations(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        await authed_client.post("/api/v1/discs/import", json=payload)

        second = await authed_client.post(
            "/api/v1/discs/import", json=payload, params={"build_conflict": "overwrite"}
        )

        body = second.json()
        assert body["builds_created"] == 0, body
        assert body["builds_overwritten"] == 3, body

    async def test_the_counters_partition_the_payload(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """created + overwritten + skipped == the characters the payload resolved.

        The property that makes the three numbers readable together. It held for a
        first import by luck (overwritten and skipped were both 0) and broke the
        moment anything already existed.
        """
        await _seed_ezod(db_session)
        payload = json.loads(_EZOD_FIXTURE.read_text())
        character_count = len(payload["characters"])

        first = (
            await authed_client.post("/api/v1/discs/import", json=payload)
        ).json()
        assert first["builds_created"] + first["builds_overwritten"] + first[
            "builds_skipped"
        ] == character_count, first

        second = (
            await authed_client.post(
                "/api/v1/discs/import", json=payload, params={"build_conflict": "overwrite"}
            )
        ).json()
        assert second["builds_created"] + second["builds_overwritten"] + second[
            "builds_skipped"
        ] == character_count, second

        third = (
            await authed_client.post(
                "/api/v1/discs/import", json=payload, params={"build_conflict": "skip"}
            )
        ).json()
        assert third["builds_created"] + third["builds_overwritten"] + third[
            "builds_skipped"
        ] == character_count, third
