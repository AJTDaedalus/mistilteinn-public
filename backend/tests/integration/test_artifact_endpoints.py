"""G.6b — the artifact inventory and the GOOD import.

The first write surface over Chunk G's work, and the tests are about the two ways an import
lies: by storing something the user does not have, and by storing something the *optimizer*
will misread. The second is the dangerous one, because the resulting build looks entirely
reasonable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.artifact import ArtifactSet
from app.services.good_import_service import set_lookup_key

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User


def _good(*artifacts, version: int = 3, source: str = "Inventory Kamera") -> dict:
    return {
        "format": "GOOD", "version": version, "source": source,
        "artifacts": list(artifacts),
    }


def _artifact(**overrides) -> dict:
    record = {
        "setKey": "BlizzardStrayer",
        "slotKey": "goblet",
        "rarity": 5,
        "level": 20,
        "mainStatKey": "cryo_dmg_",
        "substats": [
            {"key": "critDMG_", "value": 21.8},
            {"key": "", "value": 0},
        ],
        "location": "",
        "lock": False,
    }
    record.update(overrides)
    return record


async def _seed_sets(db: AsyncSession) -> dict[str, str]:
    sets = {}
    for nanoka_id, name in ((15025, "Blizzard Strayer"), (15006, "Gladiator's Finale")):
        row = ArtifactSet(
            nanoka_id=nanoka_id, name=name, piece_thresholds=[2, 4], available_ranks=[4, 5],
        )
        db.add(row)
        sets[name] = row
    await db.flush()
    return {name: str(row.id) for name, row in sets.items()}


def _auth(authed_user: tuple[User, str]) -> dict[str, str]:
    _, token = authed_user
    return {"Authorization": f"Bearer {token}"}


# ---- The set-key derivation ------------------------------------------------

def test_set_key_normalisation_is_injective_over_the_seeded_sets():
    """No two of the 65 sets may reduce to the same key.

    If two did, a GOOD `setKey` could bind the **wrong** set — and unlike a rejection, that
    failure is invisible: the import succeeds, the optimizer awards a real bonus from a set
    the user does not have, and the recommended build is wrong in a way nothing reports.

    Read from the committed nanoka fixture, so it is the game's 65 names and not a sample.
    """
    import json
    from collections import Counter
    from pathlib import Path

    index = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "artifact.json")
        .read_text(),
    )
    names = [next(iter(entry["set"].values()))["name"]["en"] for entry in index.values()]
    collisions = {k: c for k, c in Counter(map(set_lookup_key, names)).items() if c > 1}

    assert len(names) == 65
    assert collisions == {}


def test_punctuation_and_spacing_are_what_the_two_sides_differ_by():
    assert set_lookup_key("Gladiator's Finale") == set_lookup_key("GladiatorsFinale")
    assert set_lookup_key("Blizzard Strayer") == set_lookup_key("BlizzardStrayer")


# ---- Importing -------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_good_export_imports(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    ids = await _seed_sets(db_session)

    response = await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 1
    assert body["ok"] is True
    assert body["source"] == "Inventory Kamera"

    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()
    piece = listed["items"][0]
    assert piece["slot"] == "equip_ring"
    assert piece["artifact_set_id"] == ids["Blizzard Strayer"]
    # GOOD publishes percentages; this repo stores fractions.
    assert piece["substats"] == [{"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.218}]


@pytest.mark.asyncio
async def test_the_main_stat_value_comes_from_the_table_not_the_export(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """GOOD carries the number a scanner read off a screen. E.5 committed the table it came
    from, and the damage path reads that table — so storing the OCR result would let a
    misread digit become a stat the optimizer builds around, disagreeing with the number
    the build is finally scored on."""
    from app.data.snapshot import artifact_main_stat_value

    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )

    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()

    assert listed["items"][0]["main_stat_value"] == pytest.approx(
        artifact_main_stat_value(5, 20, "FIGHT_PROP_ICE_ADD_HURT"),
    )


@pytest.mark.asyncio
async def test_an_unknown_set_is_refused_rather_than_imported_without_one(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A null `artifact_set_id` would import cleanly and then make every set bonus that
    piece could contribute to invisible — for a whole set at a time, with nothing said."""
    await _seed_sets(db_session)

    body = (await client.post(
        "/api/v1/artifacts/import/good",
        # `append`, so this tests the rejection and not the replace guard below — with
        # `replace` the all-rejected file is a 409 before it ever reports the reason.
        json={"mode": "append", "payload": _good(_artifact(setKey="NotARealSet"))},
        headers=_auth(authed_user),
    )).json()

    assert body["inserted"] == 0
    assert body["ok"] is False
    assert "NotARealSet" in body["rejected"][0]["reason"]


@pytest.mark.asyncio
async def test_a_bad_artifact_does_not_cost_the_good_ones(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Someone with 800 artifacts and two odd ones wants the 798."""
    await _seed_sets(db_session)

    body = (await client.post(
        "/api/v1/artifacts/import/good",
        json={
            "mode": "replace",
            # A flower cannot roll CRIT DMG; the game does not produce it.
            "payload": _good(
                _artifact(),
                _artifact(slotKey="flower", mainStatKey="critDMG_"),
                _artifact(setKey="Gladiator's Finale", slotKey="plume", mainStatKey="atk"),
            ),
        },
        headers=_auth(authed_user),
    )).json()

    assert body["inserted"] == 2
    assert [r["index"] for r in body["rejected"]] == [1]
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_good_export_is_a_400(
    client: AsyncClient, authed_user: tuple[User, str],
):
    """Nothing about it can be salvaged, unlike one bad artifact inside a good file."""
    response = await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": {"format": "NOTGOOD", "version": 3}},
        headers=_auth(authed_user),
    )

    assert response.status_code == 400
    assert "GOOD" in response.json()["detail"]


@pytest.mark.asyncio
async def test_the_import_mode_has_no_default(
    client: AsyncClient, authed_user: tuple[User, str],
):
    """GOOD carries no stable per-artifact id, so `append` twice duplicates an inventory and
    `replace` deletes one. Neither may be reached by omitting a field."""
    response = await client.post(
        "/api/v1/artifacts/import/good",
        json={"payload": _good()},
        headers=_auth(authed_user),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_replace_clears_the_previous_inventory_and_append_does_not(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    await _seed_sets(db_session)
    payload = {"mode": "replace", "payload": _good(_artifact())}

    first = (await client.post(
        "/api/v1/artifacts/import/good", json=payload, headers=_auth(authed_user),
    )).json()
    appended = (await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "append", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )).json()
    replaced = (await client.post(
        "/api/v1/artifacts/import/good", json=payload, headers=_auth(authed_user),
    )).json()

    assert first["deleted"] == 0
    assert appended["deleted"] == 0
    assert replaced["deleted"] == 2, "both the original and the appended copy"

    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()
    assert listed["total"] == 1


@pytest.mark.asyncio
async def test_a_replace_that_resolved_nothing_refuses_instead_of_wiping(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The seeder's `PRUNE REFUSED` rule, one layer up (D.7).

    Resolving sets before deleting is **not enough on its own** — the first version of this
    did exactly that and still ran the delete. A file that parses as valid GOOD but whose
    sets this build cannot resolve (a patch adding sets the snapshot predates is the
    obvious way) would have deleted the whole inventory, inserted nothing, and reported a
    successful import of zero artifacts.
    """
    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )

    refused = await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(
            _artifact(setKey="SetFromAFuturePatch"),
            _artifact(setKey="AnotherFutureSet"),
        )},
        headers=_auth(authed_user),
    )

    # 409, not 400: the request is well-formed and the refusal is about the state it would
    # have left behind.
    assert refused.status_code == 409
    assert "Nothing was deleted" in refused.json()["detail"]
    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()
    assert listed["total"] == 1


@pytest.mark.asyncio
async def test_an_empty_replace_really_does_clear_the_inventory(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The guard is about a file that *had* artifacts and resolved none. A genuinely empty
    export is a user saying they have nothing, and must still be able to say it."""
    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )

    cleared = await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good()},
        headers=_auth(authed_user),
    )

    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 1
    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()
    assert listed["total"] == 0


@pytest.mark.asyncio
async def test_an_unreadable_replace_does_not_empty_the_inventory(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Set resolution runs before anything is deleted. Otherwise a re-scan whose set names
    this build does not know leaves the user with nothing and an error message."""
    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )

    broken = (await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": {"format": "GOOD", "version": 99}},
        headers=_auth(authed_user),
    ))

    assert broken.status_code == 400
    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()
    assert listed["total"] == 1


# ---- The inventory ---------------------------------------------------------

@pytest.mark.asyncio
async def test_artifacts_list_in_game_slot_order(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """`ORDER BY slot` sorts the payload keys alphabetically — flower, circlet, plume,
    goblet, sands. Correct-looking, and wrong for anything that iterates the result."""
    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(
            _artifact(slotKey="circlet", mainStatKey="critDMG_"),
            _artifact(slotKey="flower", mainStatKey="hp"),
            _artifact(slotKey="sands", mainStatKey="atk_"),
            _artifact(slotKey="plume", mainStatKey="atk"),
            _artifact(slotKey="goblet", mainStatKey="cryo_dmg_"),
        )},
        headers=_auth(authed_user),
    )

    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()

    assert [a["slot"] for a in listed["items"]] == [
        "equip_bracer", "equip_necklace", "equip_shoes", "equip_ring", "equip_dress",
    ]


@pytest.mark.asyncio
async def test_the_inventory_is_scoped_to_its_owner(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """An unauthenticated request sees nothing, rather than everyone's pieces."""
    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )

    assert (await client.get("/api/v1/artifacts")).status_code == 401
    assert (await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good()},
    )).status_code == 401


@pytest.mark.asyncio
async def test_filtering_by_slot_narrows_the_total_too(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(
            _artifact(slotKey="flower", mainStatKey="hp"),
            _artifact(slotKey="plume", mainStatKey="atk"),
        )},
        headers=_auth(authed_user),
    )

    filtered = (await client.get(
        "/api/v1/artifacts", params={"slot": "equip_bracer"}, headers=_auth(authed_user),
    )).json()

    assert filtered["total"] == 1
    assert filtered["items"][0]["slot"] == "equip_bracer"


@pytest.mark.asyncio
async def test_fetching_and_deleting_one_artifact(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    await _seed_sets(db_session)
    await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "replace", "payload": _good(_artifact())},
        headers=_auth(authed_user),
    )
    listed = (await client.get("/api/v1/artifacts", headers=_auth(authed_user))).json()
    artifact_id = listed["items"][0]["id"]

    assert (await client.get(
        f"/api/v1/artifacts/{artifact_id}", headers=_auth(authed_user),
    )).status_code == 200
    assert (await client.delete(
        f"/api/v1/artifacts/{artifact_id}", headers=_auth(authed_user),
    )).status_code == 204
    assert (await client.get(
        f"/api/v1/artifacts/{artifact_id}", headers=_auth(authed_user),
    )).status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_artifact_is_a_404_not_a_403(
    client: AsyncClient, authed_user: tuple[User, str],
):
    """The repository is scoped, so a foreign id is indistinguishable from a missing one —
    and saying which would confirm that someone else owns that id."""
    response = await client.delete(
        "/api/v1/artifacts/00000000-0000-0000-0000-000000000000",
        headers=_auth(authed_user),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_rejection_names_the_record_in_the_file_not_in_the_survivors(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """`RejectedArtifact.index` exists so a user can find the record in their export.

    The parser numbers records by their position in the file; the importer's own rejections
    (a set this database does not know) were numbered by position among the artifacts that
    *survived* parsing. Those differ by however many the parser refused first, so with one
    bad record before an unknown set the report named index 1 **twice** and never mentioned
    index 2 — pointing the user at a record that was already accounted for.
    """
    await _seed_sets(db_session)

    body = (await client.post(
        "/api/v1/artifacts/import/good",
        json={"mode": "append", "payload": _good(
            _artifact(),                                              # 0: fine
            _artifact(slotKey="flower", mainStatKey="critDMG_"),      # 1: parser refuses
            _artifact(setKey="SetFromAFuturePatch"),                  # 2: unknown set
        )},
        headers=_auth(authed_user),
    )).json()

    assert body["inserted"] == 1
    assert sorted(r["index"] for r in body["rejected"]) == [1, 2]
    by_index = {r["index"]: r["reason"] for r in body["rejected"]}
    assert "flower" in by_index[1]
    assert "SetFromAFuturePatch" in by_index[2]
