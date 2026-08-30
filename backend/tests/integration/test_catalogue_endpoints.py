"""G.6 — the catalogue read endpoints.

Chunk D seeded 18 tables and nothing served any of it; the API answered seven paths. These
tests are about the ways a read surface over game data quietly lies:

* a `total` that ignores the filter the page used,
* a Traveler dropped because its key is not an integer,
* a curve or a `param_list` withheld as an "internal", leaving a client unable to evaluate
  the base stat or read a conditional set bonus at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.artifact import ArtifactSet, ArtifactSetAffix
from app.models.build import EnemyProfile
from app.models.character import (
    AscensionPassive,
    Character,
    Constellation,
    Talent,
    TalentScaling,
)
from app.models.enums import Element, Rarity, TalentType, WeaponType
from app.models.weapon import Weapon, WeaponRefinement

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _character(db: AsyncSession, **overrides) -> Character:
    fields = {
        "nanoka_id": "10000002",
        "name": "Ayaka",
        "element": Element.CRYO,
        "weapon_type": WeaponType.SWORD,
        "rarity": Rarity.FIVE_STAR,
        "base_hp": 1001.0,
        "base_atk": 26.6,
        "base_def": 61.0,
        "base_crit_rate": 0.05,
        "base_crit_dmg": 0.5,
        "prop_curves": {"FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S5"},
        "ascension_stats": [{"fight_prop_critical_hurt": 0.096}],
    }
    fields.update(overrides)
    character = Character(**fields)
    db.add(character)
    await db.flush()
    return character


@pytest.mark.asyncio
async def test_listing_characters_returns_the_summary_shape(
    client: AsyncClient, db_session: AsyncSession,
):
    await _character(db_session)

    response = await client.get("/api/v1/characters")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    entry = next(c for c in body["items"] if c["nanoka_id"] == "10000002")
    # The enum's wire value is the payload's own spelling, in the response *and* in the
    # query parameter below. A prettier second vocabulary for the API would be one more
    # mapping to keep in step with the game.
    assert entry["element"] == "Cryo"
    assert entry["weapon_type"] == "WEAPON_SWORD_ONE_HAND"
    # A summary is a summary: the kit rows are the detail route's job, not 150 characters'.
    assert "talents" not in entry


@pytest.mark.asyncio
async def test_the_total_counts_the_filter_not_the_table(
    client: AsyncClient, db_session: AsyncSession,
):
    """A bare table count beside a filtered page says "150 results" and hands back three.
    That reads as a broken page, and the client debugs the wrong thing."""
    await _character(db_session)
    await _character(
        db_session, nanoka_id="10000003", name="Jean", element=Element.ANEMO,
    )

    filtered = await client.get("/api/v1/characters", params={"element": "Cryo"})
    unfiltered = await client.get("/api/v1/characters")

    assert filtered.json()["total"] == len(filtered.json()["items"])
    assert filtered.json()["total"] < unfiltered.json()["total"]


@pytest.mark.asyncio
async def test_a_traveler_variant_is_reachable(
    client: AsyncClient, db_session: AsyncSession,
):
    """28 of the 150 characters are keyed `10000005-2`. A route typed `int` 422s on all of
    them, and they are the ones a Traveler main cares about."""
    await _character(db_session, nanoka_id="10000005-2", name="Traveler (Anemo)")

    response = await client.get("/api/v1/characters/10000005-2")

    assert response.status_code == 200
    assert response.json()["nanoka_id"] == "10000005-2"


@pytest.mark.asyncio
async def test_a_character_detail_carries_what_its_stats_cannot_be_read_without(
    client: AsyncClient, db_session: AsyncSession,
):
    """`base_hp` alone cannot be evaluated at any level. The curve that grows it is part of
    the answer, not an internal — F.3 found that out by having two of the three."""
    character = await _character(db_session)
    talent = Talent(
        character_id=str(character.id), nanoka_id=10002, talent_type=TalentType.ELEMENTAL_BURST,
        name="Soumetsu", description="",
    )
    db_session.add(talent)
    await db_session.flush()
    db_session.add_all([
        TalentScaling(
            talent_id=str(talent.id), level=1, labels=["DMG"], params=[1.5],
        ),
        Constellation(
            character_id=str(character.id), nanoka_id=1, position=1, name="C1",
            description="",
        ),
        AscensionPassive(
            character_id=str(character.id), nanoka_id=1, unlock_ascension=1, name="A1",
            description="",
        ),
    ])
    await db_session.flush()

    body = (await client.get("/api/v1/characters/10000002")).json()

    assert body["prop_curves"] == {"FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S5"}
    assert body["ascension_stats"] == [{"fight_prop_critical_hurt": 0.096}]
    # Down to the scaling table. The eager-load stopped at `talents` at first, so Pydantic
    # touched a lazy relationship on an async session and the route 500'd with
    # `MissingGreenlet` — a response shape correct in the schema and unreachable at runtime.
    assert [t["name"] for t in body["talents"]] == ["Soumetsu"]
    assert body["talents"][0]["scalings"] == [{"level": 1, "labels": ["DMG"], "params": [1.5]}]
    assert [c["position"] for c in body["constellations"]] == [1]
    # Nullable and left that way: a condition-gated passive has no phase, and a 0 would
    # claim it is ungated.
    assert body["ascension_passives"][0]["unlock_ascension"] == 1


@pytest.mark.asyncio
async def test_an_unknown_character_is_a_404(client: AsyncClient):
    response = await client.get("/api/v1/characters/nope")

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_weapon_with_no_base_atk_is_served_not_dropped(
    client: AsyncClient, db_session: AsyncSession,
):
    """The eight `ITEM_TPS_WEAPON` rows publish `atk: null` and `sub: null`. C.1 recorded
    them and D.4 imported them visibly; a response schema that required the field would
    undo that at the last step."""
    weapon = Weapon(
        nanoka_id=224001, name="Frag Crystal", weapon_type=WeaponType.CROSSBOW,
        rarity=Rarity.ONE_STAR, base_atk=None, sub_stat_type=None,
    )
    db_session.add(weapon)
    await db_session.flush()

    listed = (await client.get("/api/v1/weapons", params={"name": "Frag"})).json()

    assert listed["total"] == 1
    assert listed["items"][0]["base_atk"] is None
    assert (await client.get("/api/v1/weapons/224001")).status_code == 200


@pytest.mark.asyncio
async def test_a_weapon_detail_carries_its_curves_and_refinements(
    client: AsyncClient, db_session: AsyncSession,
):
    weapon = Weapon(
        nanoka_id=11509, name="Mistsplitter", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, base_atk_curve="GROW_CURVE_ATTACK_101",
        sub_stat_base_value=0.096, sub_stat_curve="GROW_CURVE_CRITICAL_101",
    )
    db_session.add(weapon)
    await db_session.flush()
    db_session.add(WeaponRefinement(
        weapon_id=str(weapon.id), level=1, name="Mistsplitter's Edge",
        description="", param_list=[0.12, 0.08],
    ))
    await db_session.flush()

    body = (await client.get("/api/v1/weapons/11509")).json()

    assert body["base_atk_curve"] == "GROW_CURVE_ATTACK_101"
    assert body["refinements"][0]["param_list"] == [0.12, 0.08]


@pytest.mark.asyncio
async def test_an_unknown_weapon_is_a_404(client: AsyncClient):
    assert (await client.get("/api/v1/weapons/999999")).status_code == 404


@pytest.mark.asyncio
async def test_a_one_piece_set_reports_its_real_thresholds(
    client: AsyncClient, db_session: AsyncSession,
):
    """Five of the 65 sets are `[1]` — the "Prayers" circlets. A client that assumed
    2pc/4pc would get those five wrong, so the field is on the response, not implied."""
    artifact_set = ArtifactSet(
        nanoka_id=15009, name="Prayers for Illumination", piece_thresholds=[1],
        available_ranks=[4, 5],
    )
    db_session.add(artifact_set)
    await db_session.flush()
    db_session.add(ArtifactSetAffix(
        artifact_set_id=str(artifact_set.id), position=0, pieces_required=1,
        name="", description="", add_props=[{"prop_type": "FIGHT_PROP_NONE", "value": 0}],
        param_list=[0.12],
    ))
    await db_session.flush()

    body = (await client.get("/api/v1/artifact-sets/15009")).json()

    assert body["piece_thresholds"] == [1]
    # A conditional bonus has no static prop; `param_list` is where its numbers are at all.
    # Withholding it would leave a client regexing `<color=#99FFFFFF>` markup.
    assert body["affixes"][0]["param_list"] == [0.12]


@pytest.mark.asyncio
async def test_listing_sets_includes_their_affixes(
    client: AsyncClient, db_session: AsyncSession,
):
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(artifact_set)
    await db_session.flush()
    db_session.add(ArtifactSetAffix(
        artifact_set_id=str(artifact_set.id), position=0, pieces_required=2,
        name="", description="",
        add_props=[{"prop_type": "FIGHT_PROP_ICE_ADD_HURT", "value": 0.15}],
    ))
    await db_session.flush()

    body = (await client.get("/api/v1/artifact-sets", params={"name": "Blizzard"})).json()

    assert body["total"] == 1
    assert body["items"][0]["affixes"][0]["pieces_required"] == 2


@pytest.mark.asyncio
async def test_an_unknown_set_is_a_404(client: AsyncClient):
    assert (await client.get("/api/v1/artifact-sets/999999")).status_code == 404


@pytest.mark.asyncio
async def test_an_enemy_profile_ships_the_curves_its_bases_are_meaningless_without(
    client: AsyncClient, db_session: AsyncSession,
):
    """A Hilichurl's `base_hp` is 13.584. Serving that without `stat_curves` invites a
    client to multiply it by a crit multiplier and call the result damage."""
    profile = EnemyProfile(
        nanoka_id=20010101, name="Hilichurl", level=90, base_hp=13.584, base_atk=1.0,
        base_def=1.0, cryo_res=0.1,
        stat_curves={"FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_2"},
        variant_nanoka_id=20010101, variant_count=3,
    )
    db_session.add(profile)
    await db_session.flush()

    body = (await client.get(f"/api/v1/enemies/{profile.id}")).json()

    assert body["base_hp"] == pytest.approx(13.584)
    assert body["stat_curves"] == {"FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_2"}
    assert body["cryo_res"] == pytest.approx(0.1)
    # "One row is one monster family, one of N configs" should be readable, not folklore.
    assert body["variant_count"] == 3


@pytest.mark.asyncio
async def test_a_hand_authored_enemy_profile_is_reachable(
    client: AsyncClient, db_session: AsyncSession,
):
    """`nanoka_id` is nullable — a test dummy or a crossval target is a legitimate row that
    no importer owns. Keying the detail route on it would make those unreachable."""
    profile = EnemyProfile(nanoka_id=None, name="Crossval dummy", level=90)
    db_session.add(profile)
    await db_session.flush()

    response = await client.get(f"/api/v1/enemies/{profile.id}")

    assert response.status_code == 200
    assert response.json()["nanoka_id"] is None


@pytest.mark.asyncio
async def test_an_unknown_enemy_profile_is_a_404(client: AsyncClient):
    assert (await client.get("/api/v1/enemies/00000000-0000-0000-0000-000000000000")
            ).status_code == 404


@pytest.mark.asyncio
async def test_the_catalogue_needs_no_bearer_token(client: AsyncClient):
    """The catalogue is the game's data, not a user's. There is nothing to scope."""
    for path in ("/api/v1/characters", "/api/v1/weapons", "/api/v1/artifact-sets",
                 "/api/v1/enemies"):
        assert (await client.get(path)).status_code == 200


@pytest.mark.asyncio
async def test_paging_is_bounded(client: AsyncClient):
    assert (await client.get("/api/v1/characters", params={"limit": 500})
            ).status_code == 422
    assert (await client.get("/api/v1/characters", params={"offset": -1})
            ).status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_filter_value_is_rejected_not_ignored(client: AsyncClient):
    """`Element.parse` returns None for an unrecognised value — correct for an importer
    reading a future patch, and wrong for a query parameter, where it would turn a typo
    into an unfiltered list. FastAPI's strict enum validation is what should answer here.
    """
    response = await client.get("/api/v1/characters", params={"element": "cryo"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_wildcard_in_a_name_search_is_taken_literally(
    client: AsyncClient, db_session: AsyncSession,
):
    """`ILIKE '%' || term || '%'` makes the user's `%` a wildcard, so a search for `%`
    returns the whole table and `a_c` matches `abc`. Not injection — the term is bound —
    but a filter quietly answering a different question, which is the shape of bug this
    chunk keeps producing.
    """
    await _character(db_session)
    await _character(db_session, nanoka_id="10000003", name="100% Real Character")

    wildcard = await client.get("/api/v1/characters", params={"name": "%"})
    underscore = await client.get("/api/v1/characters", params={"name": "Ay_ka"})
    literal = await client.get("/api/v1/characters", params={"name": "100%"})

    # Exactly one: the row whose name really contains a percent sign. Not both rows, which
    # is what a wildcard would return, and not zero — a literal search still finds literals.
    assert [c["name"] for c in wildcard.json()["items"]] == ["100% Real Character"]
    assert underscore.json()["total"] == 0, "_ must not stand in for a character"
    assert [c["name"] for c in literal.json()["items"]] == ["100% Real Character"]


async def test_artifact_sets_say_whether_gcsim_can_simulate_them(
    client: AsyncClient, db_session: AsyncSession,
):
    """`simulable` is answered by the same lookup a run would use.

    **The optimizer offered sets it could not run.** "All 4-piece" selected every set the
    inventory could field four of, gcsim has no key for some of them, and one such set fails
    the *whole* calibration with a 422 naming it — so the run returned nothing rather than the
    sets it could have done. A client cannot work this out, so the catalogue says it.
    """
    from app.models.artifact import ArtifactSet

    db_session.add_all([
        ArtifactSet(nanoka_id=15003, name="Blizzard Strayer"),
        # Real, and real about gcsim: released after the pin, so it has no key at 3647a07a.
        ArtifactSet(nanoka_id=999001, name="Scarlet Proof"),
    ])
    await db_session.flush()

    body = (await client.get("/api/v1/artifact-sets?limit=200")).json()
    by_name = {row["name"]: row["simulable"] for row in body["items"]}

    assert by_name["Blizzard Strayer"] is True
    assert by_name["Scarlet Proof"] is False


async def test_one_artifact_set_answers_simulable_the_same_way_the_list_does(
    client: AsyncClient, db_session: AsyncSession,
):
    """The detail route published `simulable: false` for every set, including runnable ones.

    The field is on the shared `ArtifactSetRead`, so the same documented field meant "answered
    by the gcsim lookup" on one route and "always false" on the other — and a client fetching
    one set would conclude it could not be simulated.
    """
    from app.models.artifact import ArtifactSet

    row = ArtifactSet(nanoka_id=15003, name="Blizzard Strayer")
    db_session.add(row)
    await db_session.flush()

    body = (await client.get("/api/v1/artifact-sets/15003")).json()

    assert body["simulable"] is True
