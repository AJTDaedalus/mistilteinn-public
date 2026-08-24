"""A.3 — what an inventory needs to draw a row.

`ArtifactRead` carried `slot`, `main_stat_type` and `artifact_set_id` as the source's internal
spellings and a UUID. A page cannot render "Blizzard Strayer · Flower · CRIT DMG 62.2%" from
those without either a request per row or a client-side copy of three mappings.

The split here is deliberate: the **vocabulary** (26 stats, 5 slots) is published once at
`/artifacts/options`, because repeating it across 800 pieces is the same table 800 times; the
**set name** is on the row, because it differs per piece.

**Every test expires the session before the request.** `set_name` reads an eager relationship
and `lazy` is `raise_on_sql`, so without expiring, the identity map serves the handler and a
missing loader emits no SQL — the T.1a trap, met again in this very task when the property was
added before the routes were fixed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.artifact import Artifact, ArtifactSet
from app.models.build import Build
from app.models.enums import ArtifactSlot, Rarity, StatType

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

ARTIFACTS = "/api/v1/artifacts"


@pytest.fixture
async def piece(db_session: AsyncSession, authed_user: tuple[User, str]) -> str:
    user, _ = authed_user
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(artifact_set)
    await db_session.flush()
    artifact = Artifact(
        owner_id=str(user.id), artifact_set_id=str(artifact_set.id),
        slot=ArtifactSlot.CIRCLET, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.CRIT_DMG, main_stat_value=0.622,
        substats=[{"stat": "FIGHT_PROP_CRITICAL", "value": 0.109, "rolls": 3}],
    )
    db_session.add(artifact)
    await db_session.flush()
    return str(artifact.id)


# ── the row names its set ────────────────────────────────────────────────────


async def test_a_listed_piece_names_its_set(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    db_session.expire_all()

    listed = (await authed_client.get(ARTIFACTS)).json()

    assert listed["items"][0]["set_name"] == "Blizzard Strayer"
    assert listed["items"][0]["artifact_set_id"], "beside the id, not instead of it"


async def test_a_single_read_names_it_too(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    db_session.expire_all()

    body = (await authed_client.get(f"{ARTIFACTS}/{piece}")).json()

    assert body["set_name"] == "Blizzard Strayer"


async def test_equipping_returns_a_row_that_still_names_its_set(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user, piece: str,
):
    """The write path is the one that broke: it fetched with `get_by_id`, which loads no
    relationships, so `set_name` raised `MissingGreenlet` the moment the property existed."""
    user, _ = authed_user
    build = Build(owner_id=str(user.id), character_id=None)
    db_session.add(build)
    await db_session.flush()
    # Captured **before** expiring. Reading `build.id` afterwards is itself a refresh, and
    # the test would fail on its own setup rather than on what it is checking.
    build_id = str(build.id)
    db_session.expire_all()

    equipped = await authed_client.patch(
        f"{ARTIFACTS}/{piece}", json={"build_id": build_id},
    )

    assert equipped.status_code == 200, equipped.text
    assert equipped.json()["set_name"] == "Blizzard Strayer"


async def test_the_inventory_snapshot_names_sets_as_well(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    db_session.expire_all()

    snapshot = (await authed_client.get(f"{ARTIFACTS}/inventory")).json()

    assert snapshot["artifacts"][0]["set_name"] == "Blizzard Strayer"


async def test_a_setless_piece_says_so_rather_than_failing(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """32 starter relics carry no set at all (`excluded_unupgradable` in the roll schedule).
    `set_name` is null for them, not an error and not an empty string that would sort among
    real names."""
    user, _ = authed_user
    setless = Artifact(
        owner_id=str(user.id), artifact_set_id=None, slot=ArtifactSlot.FLOWER,
        rarity=Rarity.ONE_STAR, level=0, main_stat_type=StatType.HP_FLAT,
        main_stat_value=129.0, substats=[],
    )
    db_session.add(setless)
    await db_session.flush()
    setless_id = str(setless.id)
    db_session.expire_all()

    body = (await authed_client.get(f"{ARTIFACTS}/{setless_id}")).json()

    assert body["set_name"] is None


# ── the vocabulary ───────────────────────────────────────────────────────────


async def test_options_publish_every_stat_a_piece_can_carry(authed_client: AsyncClient):
    """Every member, so a page can look up any key it is handed rather than guessing at a
    missing entry."""
    options = (await authed_client.get(f"{ARTIFACTS}/options")).json()

    keys = {entry["key"] for entry in options["stats"]}
    assert keys == {stat.value for stat in StatType}


async def test_options_say_which_values_are_fractions(authed_client: AsyncClient):
    """`0.466` is 46.6% HP and `4780` is 4780 HP. Without this a page prints one as the
    other, and neither looks obviously wrong at a glance."""
    options = (await authed_client.get(f"{ARTIFACTS}/options")).json()
    by_key = {entry["key"]: entry for entry in options["stats"]}

    assert by_key["FIGHT_PROP_HP_PERCENT"]["percentage"] is True
    assert by_key["FIGHT_PROP_HP_PERCENT"]["display"] == "HP%"
    assert by_key["FIGHT_PROP_HP"]["percentage"] is False
    assert by_key["FIGHT_PROP_HP"]["display"] == "HP"


async def test_options_list_the_slots_in_the_order_they_are_worn(
    authed_client: AsyncClient,
):
    """Flower, plume, sands, goblet, circlet — the conventional order, which `sort_index`
    already defines. A page iterating this should not have to re-sort."""
    options = (await authed_client.get(f"{ARTIFACTS}/options")).json()

    assert [entry["display"] for entry in options["slots"]] == [
        "Flower", "Plume", "Sands", "Goblet", "Circlet",
    ]


async def test_the_options_path_is_not_read_as_an_artifact_id(authed_client: AsyncClient):
    """Declared above `/{artifact_id}`. Below it this 404s and looks like an empty inventory
    rather than a routing mistake."""
    response = await authed_client.get(f"{ARTIFACTS}/options")

    assert response.status_code == 200
    assert "stats" in response.json()


async def test_options_say_how_many_stars_a_rarity_is(authed_client: AsyncClient):
    """`Rarity.stars` already knows. Parsing `five_star` on the client would be a second
    implementation of it, and the kind that reads as harmless until a rarity is renamed."""
    options = (await authed_client.get(f"{ARTIFACTS}/options")).json()
    by_key = {entry["key"]: entry["stars"] for entry in options["rarities"]}

    assert by_key["five_star"] == 5
    assert by_key["one_star"] == 1
    assert set(by_key) == {rarity.value for rarity in Rarity}
