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

from app.models.artifact import Artifact, ArtifactSet, ArtifactSetAffix
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


@pytest.fixture
async def piece_with_bonuses(
    db_session: AsyncSession, authed_user: tuple[User, str],
) -> str:
    """A piece whose set actually carries its affix rows.

    The shared `piece` fixture creates a set with **no** affixes, which is right for the tests
    that use it and useless here: `set_bonuses` iterates `row.affixes`, so it would return an
    empty list and a passing assertion would mean nothing.

    The two affixes are the real shapes — a static 2-piece with a live `add_props`, and a
    conditional 4-piece whose props are all `FIGHT_PROP_NONE` with the numbers in
    `param_list`.
    """
    user, _ = authed_user
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(artifact_set)
    await db_session.flush()
    db_session.add_all([
        ArtifactSetAffix(
            artifact_set_id=str(artifact_set.id), position=0, pieces_required=2,
            name="Blizzard Strayer", description="Cryo DMG Bonus +15%.",
            add_props=[{"prop_type": "FIGHT_PROP_ICE_ADD_HURT", "value": 0.15}],
            param_list=[0, 0],
        ),
        ArtifactSetAffix(
            artifact_set_id=str(artifact_set.id), position=1, pieces_required=4,
            name="Blizzard Strayer",
            description="Attacks on Cryo-affected opponents increase CRIT Rate by 20%.",
            add_props=[{"prop_type": "FIGHT_PROP_NONE", "value": 0}],
            param_list=[0.2, 0.2],
        ),
    ])
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


async def test_the_inventory_snapshot_identifies_the_set_by_catalogue_id(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """The snapshot stopped carrying `set_name` in O.2, and that is deliberate (OQ-O1).

    It exists for the client-side search, whose `Candidate` needs an **id to count set pieces
    by** — a display name is what `GET /artifacts` is for. This asserts the id is the
    catalogue's integer `nanoka_id`, because the kernel counts numbers and the row's UUID
    would make every piece its own set.
    """
    db_session.expire_all()

    snapshot = (await authed_client.get(f"{ARTIFACTS}/inventory")).json()

    assert snapshot["artifacts"][0]["set_id"] == 15025
    assert "set_name" not in snapshot["artifacts"][0]


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


async def test_artifacts_can_be_filtered_to_one_build(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user, piece: str,
):
    """A.4's filter. `equipped` says *whether*, this says *which* — and a build's five slots
    need the second. Answering it by fetching every equipped piece and filtering on the
    client scales with the whole inventory rather than with five.
    """
    user, _ = authed_user
    mine = Build(owner_id=str(user.id), character_id=None)
    other = Build(owner_id=str(user.id), character_id=None)
    db_session.add_all([mine, other])
    await db_session.flush()
    mine_id, other_id = str(mine.id), str(other.id)
    await authed_client.patch(f"{ARTIFACTS}/{piece}", json={"build_id": mine_id})

    on_mine = await authed_client.get(ARTIFACTS, params={"build_id": mine_id})
    on_other = await authed_client.get(ARTIFACTS, params={"build_id": other_id})

    assert [a["id"] for a in on_mine.json()["items"]] == [piece]
    assert on_mine.json()["total"] == 1, "the count is the filter's, not the table's"
    assert on_other.json()["items"] == []
    assert on_other.json()["total"] == 0


# ── upgrade potential — A.5/G.9 on the row ───────────────────────────────────


async def test_a_piece_reports_its_upgrade_potential(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """The fixture is a maxed 5-star circlet: no rolls left, and it says so with the parts
    that make that checkable rather than a bare figure."""
    db_session.expire_all()

    body = (await authed_client.get(f"{ARTIFACTS}/{piece}")).json()

    assert body["potential"] == {
        "rolls_remaining": 0,
        "rolls_total": 5,
        "level": 20,
        "max_level": 20,
        "levels_to_max": 0,
        # False, not null: the row carries its own lines, so the count is always available
        # here. A maxed piece gains nothing more — `gains_a_substat` is about the future.
        "gains_a_substat": False,
    }
    # The piece's substats are on the row itself, in full — not repeated inside the report.
    assert body["substats"][0]["stat"] == "FIGHT_PROP_CRITICAL"


async def test_a_fresh_piece_has_every_roll_ahead_of_it(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    user, _ = authed_user
    fresh = Artifact(
        owner_id=str(user.id), slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR,
        level=0, main_stat_type=StatType.HP_FLAT, main_stat_value=717.0, substats=[],
    )
    db_session.add(fresh)
    await db_session.flush()
    fresh_id = str(fresh.id)
    db_session.expire_all()

    body = (await authed_client.get(f"{ARTIFACTS}/{fresh_id}")).json()

    assert body["potential"]["rolls_remaining"] == 5
    assert body["potential"]["levels_to_max"] == 20


async def test_rarity_changes_the_potential_at_the_same_level(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """A 4-star caps at +16 with four rolls. A calculation that ignored rarity would agree
    with the 5-star case and nowhere else."""
    user, _ = authed_user
    four = Artifact(
        owner_id=str(user.id), slot=ArtifactSlot.PLUME, rarity=Rarity.FOUR_STAR,
        level=0, main_stat_type=StatType.ATK_FLAT, main_stat_value=27.0, substats=[],
    )
    db_session.add(four)
    await db_session.flush()
    four_id = str(four.id)
    db_session.expire_all()

    body = (await authed_client.get(f"{ARTIFACTS}/{four_id}")).json()

    assert body["potential"]["rolls_total"] == 4
    assert body["potential"]["max_level"] == 16


async def test_an_impossible_piece_reports_no_potential_rather_than_zero(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """A 3-star cannot be +20. Reporting zero rolls would be a plausible number for an
    impossible piece; **null** keeps the row visible and says the schedule could not answer.

    And the row still loads — one corrupt piece must not take down a list of eight hundred,
    which is the failure the inventory page met from the other side.
    """
    user, _ = authed_user
    impossible = Artifact(
        owner_id=str(user.id), slot=ArtifactSlot.SANDS, rarity=Rarity.THREE_STAR,
        level=20, main_stat_type=StatType.HP_PCT, main_stat_value=0.1, substats=[],
    )
    db_session.add(impossible)
    await db_session.flush()
    impossible_id = str(impossible.id)
    db_session.expire_all()

    single = await authed_client.get(f"{ARTIFACTS}/{impossible_id}")
    listed = await authed_client.get(ARTIFACTS)

    assert single.status_code == 200, single.text
    assert single.json()["potential"] is None
    assert listed.status_code == 200, "one impossible row must not fail the list"
    assert any(row["id"] == impossible_id for row in listed.json()["items"])


async def test_set_bonuses_are_published_in_kernel_terms_for_owned_sets(
    authed_client: AsyncClient, db_session: AsyncSession, piece_with_bonuses: str,
):
    """B.1 — the rotation objective's source for set bonuses.

    `/builds/{id}/search-context` already returns these, but it requires a **hit**, and the
    rotation objective has none: it scores a whole gcsim run rather than one Cutting DMG.
    This is that half on its own.

    The stats are keyed by **kernel quantity**, not `FIGHT_PROP_*`. A client could translate
    `/artifact-sets`'s `add_props` itself and would then own a second copy of a mapping that
    decides what every stat means — which `OptimizeService` refuses on purpose.
    """
    db_session.expire_all()

    response = await authed_client.get(f"{ARTIFACTS}/set-bonuses")

    assert response.status_code == 200, response.text
    bonuses = response.json()
    assert bonuses, "the caller owns a Blizzard Strayer piece; its tiers should be published"

    # Keyed by the same integer the inventory's `set_id` carries, so a caller can count set
    # pieces and look up their bonus without a second vocabulary.
    assert {b["set_id"] for b in bonuses} == {15025}
    assert {b["pieces_required"] for b in bonuses} == {2, 4}

    two_piece = next((b for b in bonuses if b["pieces_required"] == 2), None)
    assert two_piece is not None, bonuses
    assert two_piece["stats"], "Blizzard Strayer's 2-piece is a static Cryo DMG bonus"
    assert all(not key.startswith("FIGHT_PROP") for key in two_piece["stats"])


async def test_a_conditional_bonus_arrives_with_no_stats_rather_than_a_guess(
    authed_client: AsyncClient, db_session: AsyncSession, piece_with_bonuses: str,
):
    """Every 4-piece bonus in the game is conditional (`RESEARCH_conditional_sets.md`), and
    nine of the sixty 2-piece affixes are too.

    A conditional affix has `FIGHT_PROP_NONE` for every prop and its numbers in `param_list`.
    It arrives with **empty** `stats` — not omitted, and not filled with a guess. A caller
    that means to score it has to say so, which is what B.2/B.3 are for.
    """
    db_session.expire_all()

    bonuses = (await authed_client.get(f"{ARTIFACTS}/set-bonuses")).json()

    four_piece = next((b for b in bonuses if b["pieces_required"] == 4), None)
    assert four_piece is not None, bonuses
    assert four_piece["stats"] == {}
