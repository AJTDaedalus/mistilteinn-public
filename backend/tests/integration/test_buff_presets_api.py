"""Tasks B6 + B7 — `buff_presets` storage and `/api/v1/buff-presets` CRUD (#64).

Stage buffs rotate with the patch cycle and get re-applied across many builds, so they
have to be savable independently of any build (DESIGN_buff_context.md §2.4). These tests
cover the three properties that make that storage trustworthy:

1. round-trip — what you save is what you get back, buff for buff;
2. owner scoping — one user can neither read nor mutate another's presets;
3. cascade — deleting a user takes their presets with them, rather than leaving rows
   nobody can ever list, apply or delete (every read path is owner-scoped).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.buff_preset import BuffPreset
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.buff_preset import BuffPresetRepository

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_STAGE_BUFFS = [
    {
        "label": "DA Stage 3: Ice DMG",
        "stat": "ice_dmg",
        "value": 2500,
        "target": "team",
        "conditions": ["always"],
        "scopes": ["all"],
        "max_stacks": 1,
    },
    {
        "label": "DA Stage 3: CRIT DMG while stunned",
        "stat": "crit_dmg",
        "value": 4000,
        "target": "team",
        "conditions": ["enemy_stunned"],
        "scopes": ["all"],
        "max_stacks": 1,
    },
]


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        label="Preset Test User",
        password_hash=hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest(),
        status=UserStatus.APPROVED,
    )
    db.add(user)
    await db.flush()
    return user


class TestBuffPresetCrud:
    async def test_create_then_read_round_trips_every_buff_field(
        self, authed_client: AsyncClient
    ) -> None:
        resp = await authed_client.post(
            "/api/v1/buff-presets",
            json={"name": "DA 2.1 Stage 3", "buffs": _STAGE_BUFFS},
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["name"] == "DA 2.1 Stage 3"
        assert created["buffs"] == _STAGE_BUFFS

        fetched = await authed_client.get(f"/api/v1/buff-presets/{created['id']}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["buffs"] == _STAGE_BUFFS

    async def test_saved_buffs_are_accepted_verbatim_as_a_requests_custom_buffs(
        self, authed_client: AsyncClient
    ) -> None:
        """Applying a preset is a copy into ``custom_buffs`` (DESIGN §2.4).

        That only works if the stored shape *is* the request shape — so the same
        validator has to accept both. This is the assertion that keeps the two from
        drifting into "saveable but not sendable".
        """
        from app.schemas.damage import BuffContext

        resp = await authed_client.post(
            "/api/v1/buff-presets",
            json={"name": "Shiyu 2.1 Node 2", "buffs": _STAGE_BUFFS},
        )
        assert resp.status_code == 201, resp.text

        ctx = BuffContext(custom_buffs=resp.json()["buffs"])
        assert [b.label for b in ctx.custom_buffs] == [b["label"] for b in _STAGE_BUFFS]

    async def test_list_returns_the_callers_presets(self, authed_client: AsyncClient) -> None:
        for name in ("DA Stage 1", "DA Stage 2"):
            resp = await authed_client.post(
                "/api/v1/buff-presets", json={"name": name, "buffs": []}
            )
            assert resp.status_code == 201, resp.text

        listing = await authed_client.get("/api/v1/buff-presets")
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 2
        assert [p["name"] for p in body["items"]] == ["DA Stage 1", "DA Stage 2"]

    async def test_patch_replaces_the_buff_list_wholesale(
        self, authed_client: AsyncClient
    ) -> None:
        created = await authed_client.post(
            "/api/v1/buff-presets",
            json={"name": "DA 2.0 Stage 3", "buffs": _STAGE_BUFFS},
        )
        preset_id = created.json()["id"]

        replacement = [{"label": "DA 2.2: Fire DMG", "stat": "fire_dmg", "value": 3000}]
        patched = await authed_client.patch(
            f"/api/v1/buff-presets/{preset_id}",
            json={"name": "DA 2.2 Stage 3", "buffs": replacement},
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["name"] == "DA 2.2 Stage 3"
        assert [b["label"] for b in body["buffs"]] == ["DA 2.2: Fire DMG"]

    async def test_patching_only_the_name_leaves_the_buffs_alone(
        self, authed_client: AsyncClient
    ) -> None:
        created = await authed_client.post(
            "/api/v1/buff-presets",
            json={"name": "Untitled", "buffs": _STAGE_BUFFS},
        )
        preset_id = created.json()["id"]

        patched = await authed_client.patch(
            f"/api/v1/buff-presets/{preset_id}", json={"name": "DA 2.1 Stage 3"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["buffs"] == _STAGE_BUFFS

    async def test_delete_then_get_is_404(self, authed_client: AsyncClient) -> None:
        created = await authed_client.post(
            "/api/v1/buff-presets", json={"name": "Temp", "buffs": []}
        )
        preset_id = created.json()["id"]

        deleted = await authed_client.delete(f"/api/v1/buff-presets/{preset_id}")
        assert deleted.status_code == 204, deleted.text

        gone = await authed_client.get(f"/api/v1/buff-presets/{preset_id}")
        assert gone.status_code == 404


class TestBuffPresetValidation:
    async def test_an_unknown_stat_is_rejected_at_save_time(
        self, authed_client: AsyncClient
    ) -> None:
        """The same allowlist the request enforces (B2), applied where it is authored.

        A preset accepted with a no-op stat would fail — silently, as an unmoved number
        — every time it is applied, long after the user could connect the two.
        """
        resp = await authed_client.post(
            "/api/v1/buff-presets",
            json={
                "name": "Bad stat",
                "buffs": [{"label": "nope", "stat": "not_a_stat", "value": 100}],
            },
        )
        assert resp.status_code == 422, resp.text

    async def test_two_buffs_slugifying_alike_are_rejected(
        self, authed_client: AsyncClient
    ) -> None:
        """`custom:<slug>` is how `disabled_buffs` addresses a stage buff, so within one
        preset the slugs must be distinct or the toggle is ambiguous once applied."""
        resp = await authed_client.post(
            "/api/v1/buff-presets",
            json={
                "name": "Ambiguous",
                "buffs": [
                    {"label": "Stage 3 ATK", "stat": "atk_pct", "value": 1000},
                    {"label": "stage-3-atk", "stat": "atk_pct", "value": 1000},
                ],
            },
        )
        assert resp.status_code == 422, resp.text

    async def test_an_explicit_null_in_a_patch_is_a_422_not_a_500(
        self, authed_client: AsyncClient
    ) -> None:
        """`None` means "field absent", never "null this column" — both are NOT NULL.

        `exclude_unset=True` drops an omitted field, but an explicit `{"name": null}`
        survives it and reached the DB as an IntegrityError: a 500 for what is plainly a
        bad request.
        """
        created = await authed_client.post(
            "/api/v1/buff-presets", json={"name": "Nullable?", "buffs": []}
        )
        preset_id = created.json()["id"]

        for body in ({"name": None}, {"buffs": None}):
            resp = await authed_client.patch(f"/api/v1/buff-presets/{preset_id}", json=body)
            assert resp.status_code == 422, f"{body} -> {resp.status_code}: {resp.text}"

        # And the preset is untouched.
        after = await authed_client.get(f"/api/v1/buff-presets/{preset_id}")
        assert after.json()["name"] == "Nullable?"

    async def test_a_label_that_slugifies_to_nothing_is_rejected(
        self, authed_client: AsyncClient
    ) -> None:
        resp = await authed_client.post(
            "/api/v1/buff-presets",
            json={
                "name": "Punctuation",
                "buffs": [{"label": "!!!", "stat": "atk_pct", "value": 1}],
            },
        )
        assert resp.status_code == 422, resp.text


class TestBuffPresetOwnerScoping:
    async def test_another_users_preset_is_invisible_and_immutable(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        stranger = await _make_user(db_session, f"stranger_{uuid.uuid4().hex[:8]}@test.example")
        foreign = BuffPreset(
            owner_id=str(stranger.id), name="Someone else's stage buffs", buffs=_STAGE_BUFFS
        )
        db_session.add(foreign)
        await db_session.flush()

        assert (await authed_client.get(f"/api/v1/buff-presets/{foreign.id}")).status_code == 404
        patched = await authed_client.patch(
            f"/api/v1/buff-presets/{foreign.id}", json={"name": "hijacked"}
        )
        assert patched.status_code == 404
        assert (
            await authed_client.delete(f"/api/v1/buff-presets/{foreign.id}")
        ).status_code == 404

        listing = await authed_client.get("/api/v1/buff-presets")
        assert listing.json()["total"] == 0
        assert listing.json()["items"] == []

        # The row is still there — the caller was denied, not the data destroyed.
        await db_session.refresh(foreign)
        assert foreign.name == "Someone else's stage buffs"

    async def test_count_is_owner_scoped_so_pagination_does_not_leak_totals(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple[User, str],
    ) -> None:
        me, _ = authed_user
        stranger = await _make_user(db_session, f"stranger_{uuid.uuid4().hex[:8]}@test.example")
        db_session.add_all(
            [
                BuffPreset(owner_id=str(me.id), name="Mine", buffs=[]),
                BuffPreset(owner_id=str(stranger.id), name="Theirs A", buffs=[]),
                BuffPreset(owner_id=str(stranger.id), name="Theirs B", buffs=[]),
            ]
        )
        await db_session.flush()

        listing = await authed_client.get("/api/v1/buff-presets")
        assert listing.json()["total"] == 1


class TestBuffPresetCascade:
    async def test_deleting_a_user_deletes_their_presets(self, db_session: AsyncSession) -> None:
        """ON DELETE CASCADE, not SET NULL.

        Every read path for a preset is owner-scoped, so an ownerless preset is a row
        nobody could ever list, apply or delete — orphaned storage, not preserved data.
        """
        owner = await _make_user(db_session, f"cascade_{uuid.uuid4().hex[:8]}@test.example")
        preset = BuffPreset(owner_id=str(owner.id), name="Doomed", buffs=_STAGE_BUFFS)
        db_session.add(preset)
        await db_session.flush()
        preset_id = preset.id

        await db_session.delete(owner)
        await db_session.flush()

        remaining = await db_session.execute(select(BuffPreset).where(BuffPreset.id == preset_id))
        assert remaining.scalar_one_or_none() is None

    async def test_repository_scoping_matches_the_api(
        self, db_session: AsyncSession
    ) -> None:
        """The repo is the enforcement point the routes rely on — assert it directly too."""
        a = await _make_user(db_session, f"repo_a_{uuid.uuid4().hex[:8]}@test.example")
        b = await _make_user(db_session, f"repo_b_{uuid.uuid4().hex[:8]}@test.example")
        mine = BuffPreset(owner_id=str(a.id), name="A's", buffs=[])
        theirs = BuffPreset(owner_id=str(b.id), name="B's", buffs=[])
        db_session.add_all([mine, theirs])
        await db_session.flush()

        repo = BuffPresetRepository(db_session, owner_id=str(a.id))
        assert await repo.get_by_id(str(theirs.id)) is None
        assert await repo.delete(str(theirs.id)) is False
        assert [p.name for p in await repo.get_all()] == ["A's"]


class TestStalePresetsStayReadable:
    """A preset saved against a stat key that later leaves the allowlist.

    The vocabulary a stage buff draws on is the engine's, and the engine's changes. If the
    read path validated against it, one stale row would 500 `GET /buff-presets` — taking
    down the whole panel for that user, including their ability to see and delete the row
    that did it. Strict on write, permissive on read, loud on use.
    """

    async def test_listing_survives_a_buff_whose_stat_is_no_longer_known(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple[User, str],
    ) -> None:
        me, _ = authed_user
        db_session.add(
            BuffPreset(
                owner_id=str(me.id),
                name="Saved before a rename",
                # Written straight to the row: the API would (correctly) reject this today.
                buffs=[{"label": "Old stat", "stat": "stat_that_no_longer_exists", "value": 2500}],
            )
        )
        await db_session.flush()

        listing = await authed_client.get("/api/v1/buff-presets")
        assert listing.status_code == 200, listing.text
        (preset,) = listing.json()["items"]
        assert preset["buffs"][0]["stat"] == "stat_that_no_longer_exists"

    async def test_the_stale_preset_can_still_be_deleted(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple[User, str],
    ) -> None:
        me, _ = authed_user
        preset = BuffPreset(
            owner_id=str(me.id),
            name="Doomed and stale",
            buffs=[{"label": "Old stat", "stat": "stat_that_no_longer_exists", "value": 1}],
        )
        db_session.add(preset)
        await db_session.flush()

        assert (await authed_client.delete(f"/api/v1/buff-presets/{preset.id}")).status_code == 204

    async def test_applying_a_stale_buff_still_fails_loudly_at_the_calc(
        self, authed_client: AsyncClient
    ) -> None:
        """Permissive on read is not permissive on use — the run must not quietly drop it."""
        from app.schemas.damage import BuffContext

        with pytest.raises(ValueError, match="unknown buff stat"):
            BuffContext(
                custom_buffs=[
                    {"label": "Old stat", "stat": "stat_that_no_longer_exists", "value": 1}
                ]
            )
