"""G.6c — builds, and the optimizer and ranker over them.

This is where Chunks F and G become reachable: until now the damage chain and the artifact
search existed and nothing could call them. The tests that matter are the ones where a wrong
answer would look right — a set bonus counted more than once, a build scored on a base of
zero, a burst scored under normal-attack buffs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.artifact import Artifact, ArtifactSet, ArtifactSetAffix
from app.models.build import Build, EnemyProfile
from app.models.character import Character, Talent, TalentScaling
from app.models.enums import (
    ArtifactSlot,
    Element,
    Rarity,
    StatType,
    TalentType,
    WeaponType,
)
from app.models.weapon import Weapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

_MAINS = {
    ArtifactSlot.FLOWER: StatType.HP_FLAT,
    ArtifactSlot.PLUME: StatType.ATK_FLAT,
    ArtifactSlot.SANDS: StatType.ATK_PCT,
    ArtifactSlot.GOBLET: StatType.CRYO_DMG_BONUS,
    ArtifactSlot.CIRCLET: StatType.CRIT_DMG,
}

CRYO_BURST = {"multiplier": 2.0, "channel": "cryo", "scope": "burst"}


def _auth(authed_user: tuple[User, str]) -> dict[str, str]:
    _, token = authed_user
    return {"Authorization": f"Bearer {token}"}


async def _catalogue(db: AsyncSession) -> tuple[Character, Weapon, ArtifactSet]:
    character = Character(
        nanoka_id="10000002", name="Ayaka", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1001.0, base_atk=26.6, base_def=61.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
        prop_curves={
            "FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S5",
            "FIGHT_PROP_BASE_ATTACK": "GROW_CURVE_ATTACK_S5",
            "FIGHT_PROP_BASE_DEFENSE": "GROW_CURVE_HP_S5",
        },
        ascension_stats=[{"fight_prop_critical_hurt": 0.096}] * 6,
    )
    weapon = Weapon(
        nanoka_id=11509, name="Mistsplitter", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, base_atk_curve="GROW_CURVE_ATTACK_101",
        sub_stat_type=StatType.CRIT_DMG, sub_stat_base_value=0.096,
        sub_stat_curve="GROW_CURVE_CRITICAL_101",
        # A real table: `add_weapon` refuses phase 6 against an empty one, which is right —
        # "a weapon with no ascension table cannot be ascended" — and would otherwise make
        # every test here fail for a reason that has nothing to do with what it tests.
        ascension_atk={
            str(phase): {"fight_prop_base_attack": 31.1 * phase} for phase in range(1, 7)
        },
    )
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db.add_all([character, weapon, artifact_set])
    await db.flush()
    db.add(ArtifactSetAffix(
        artifact_set_id=str(artifact_set.id), position=0, pieces_required=2,
        name="", description="",
        add_props=[{"prop_type": "FIGHT_PROP_ICE_ADD_HURT", "value": 0.15}],
    ))
    await db.flush()
    return character, weapon, artifact_set


async def _build_with_five(
    db: AsyncSession, user: User, character: Character, weapon: Weapon, sets: ArtifactSet,
    *, spares: int = 0,
) -> Build:
    build = Build(
        owner_id=str(user.id), character_id=str(character.id), weapon_id=str(weapon.id),
        character_level=90, ascension_phase=6, weapon_level=90,
    )
    db.add(build)
    await db.flush()
    for slot, main in _MAINS.items():
        db.add(Artifact(
            owner_id=str(user.id), artifact_set_id=str(sets.id), build_id=str(build.id),
            slot=slot, rarity=Rarity.FIVE_STAR, level=20, main_stat_type=main,
            main_stat_value=0.0, substats=[],
        ))
    for index in range(spares):
        db.add(Artifact(
            owner_id=str(user.id), artifact_set_id=str(sets.id), slot=ArtifactSlot.GOBLET,
            rarity=Rarity.FIVE_STAR, level=20,
            main_stat_type=StatType.CRYO_DMG_BONUS, main_stat_value=0.0,
            substats=[{"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.1 * (index + 1)}],
        ))
    await db.flush()
    return build


# ---- Builds CRUD -----------------------------------------------------------

@pytest.mark.asyncio
async def test_saving_reading_and_deleting_a_build(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    character, weapon, _ = await _catalogue(db_session)

    created = await client.post(
        "/api/v1/builds",
        json={"character_id": str(character.id), "weapon_id": str(weapon.id),
              "talent_levels": {"elemental_burst": 10}},
        headers=_auth(authed_user),
    )
    assert created.status_code == 201
    build_id = created.json()["id"]

    assert (await client.get(f"/api/v1/builds/{build_id}", headers=_auth(authed_user))
            ).json()["talent_levels"] == {"elemental_burst": 10}

    patched = await client.patch(
        f"/api/v1/builds/{build_id}", json={"constellation_level": 6},
        headers=_auth(authed_user),
    )
    assert patched.json()["constellation_level"] == 6
    assert patched.json()["character_level"] == 90, "an omitted field is not reset"

    assert (await client.delete(f"/api/v1/builds/{build_id}", headers=_auth(authed_user))
            ).status_code == 204
    assert (await client.get(f"/api/v1/builds/{build_id}", headers=_auth(authed_user))
            ).status_code == 404


@pytest.mark.asyncio
async def test_builds_need_a_bearer_token(client: AsyncClient):
    assert (await client.get("/api/v1/builds")).status_code == 401


@pytest.mark.asyncio
async def test_deleting_a_build_unequips_its_artifacts_rather_than_deleting_them(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """`Artifact.build_id` is `SET NULL`. Losing an inventory to a deleted build would be a
    bad afternoon for a user who spent a year farming it."""
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)

    await client.delete(f"/api/v1/builds/{build.id}", headers=_auth(authed_user))

    remaining = (await db_session.execute(
        select(Artifact).where(Artifact.owner_id == str(user.id)),
    )).scalars().all()
    assert len(remaining) == 5
    assert all(a.build_id is None for a in remaining)


# ---- Scoring a build -------------------------------------------------------
#
# C.6 deleted `/optimize` and `/rank-artifacts`; searching moved to the browser. The cases
# below are the ones whose *property* outlived the endpoint they were written against, ported
# onto `/explain` — it reaches the same `build_combination_log` and `BuildEvaluator`, so they
# still guard what they were written to guard. The ones that went with the surface were about
# the search itself: ranking, transparency counters, inventory coverage.


@pytest.mark.asyncio
async def test_a_set_bonus_is_counted_once_however_many_pieces_carry_it(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """`set_bonuses` expands every affix of every set row it is handed.

    An early version passed the build's equipped sets *and* the whole inventory's, so a build
    wearing five of one set handed the same `ArtifactSet` in six times — and its 2-piece Cryo
    bonus registered six times over. The damage would have been several times what it really
    is, in a response that otherwise looks entirely normal.
    """
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)

    body = (await client.post(
        f"/api/v1/builds/{build.id}/explain",
        json={"hit": CRYO_BURST, "enemy": {"level": 90, "default_resistance": 0.1}},
        headers=_auth(authed_user),
    )).json()

    parts = [
        part
        for account in body["stats"]
        if account["quantity"] == "cryo_dmg_bonus"
        for part in account["parts"]
        if part["source"] == "artifact_set"
    ]
    assert len(parts) == 1, "one 2-piece bonus, registered once"
    assert parts[0]["value"] == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_a_build_with_no_character_is_refused_rather_than_scored(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Scoring one would rank five artifacts on a base of zero — by their own stats alone —
    and present that as a build."""
    user, _ = authed_user
    build = Build(owner_id=str(user.id), character_id=None)
    db_session.add(build)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/builds/{build.id}/explain",
        json={"hit": CRYO_BURST, "enemy": {"level": 90, "default_resistance": 0.1}},
        headers=_auth(authed_user),
    )

    assert response.status_code == 422
    assert "no character" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_hit_must_name_a_real_channel_and_a_real_scope(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Validated against `tags.DAMAGE_CHANNELS` and `tags.SCOPES` themselves, not a restated
    copy — a second list would drift from the one the damage chain enforces, and the drift
    would surface as a 500 from inside it."""
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)

    for bad in ({"multiplier": 1.0, "channel": "ice", "scope": "burst"},
                {"multiplier": 1.0, "channel": "cryo", "scope": "ultimate"},
                {"multiplier": 0.0, "channel": "cryo", "scope": "burst"}):
        response = await client.post(
            f"/api/v1/builds/{build.id}/explain",
            json={"hit": bad, "enemy": {"level": 90, "default_resistance": 0.1}},
            headers=_auth(authed_user),
        )
        assert response.status_code == 422, bad


@pytest.mark.asyncio
async def test_the_scope_has_no_default(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """There is no "any scope". Defaulting to `normal` would score a burst under
    normal-attack buffs — a wrong number that looks like a right one."""
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)

    response = await client.post(
        f"/api/v1/builds/{build.id}/explain",
        json={"hit": {"multiplier": 1.0, "channel": "cryo"},
              "enemy": {"level": 90, "default_resistance": 0.1}},
        headers=_auth(authed_user),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_enemy_profile_supplies_the_target(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A profile's eight resistance columns are the whole of what an outgoing hit needs
    from it. Its HP/ATK/DEF are curve bases and nothing here reads them."""
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)
    profile = EnemyProfile(
        nanoka_id=20010101, name="Cryo Regisvine", level=90, cryo_res=0.5,
    )
    db_session.add(profile)
    await db_session.flush()

    resistant = (await client.post(
        f"/api/v1/builds/{build.id}/explain",
        json={"hit": CRYO_BURST, "enemy": {"enemy_profile_id": str(profile.id)}},
        headers=_auth(authed_user),
    )).json()
    plain = (await client.post(
        f"/api/v1/builds/{build.id}/explain",
        json={"hit": CRYO_BURST, "enemy": {"level": 90, "resistances": {"cryo": 0.1}}},
        headers=_auth(authed_user),
    )).json()

    assert resistant["damage"] < plain["damage"]


@pytest.mark.asyncio
async def test_an_unknown_enemy_profile_is_a_404(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)

    response = await client.post(
        f"/api/v1/builds/{build.id}/explain",
        json={"hit": CRYO_BURST,
              "enemy": {"enemy_profile_id": "00000000-0000-0000-0000-000000000000"}},
        headers=_auth(authed_user),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_scoring_someone_elses_build_is_a_404(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    character, _weapon, _sets = await _catalogue(db_session)
    stranger = Build(owner_id=None, character_id=str(character.id))
    db_session.add(stranger)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/builds/{stranger.id}/explain",
        json={"hit": CRYO_BURST, "enemy": {"level": 90, "default_resistance": 0.1}},
        headers=_auth(authed_user),
    )

    assert response.status_code == 404


# ── naming a talent instead of typing a multiplier — M.2 ─────────────────────


@pytest.mark.asyncio
async def test_explain_resolves_a_named_talent_against_the_build(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """The `TODO(chunk-H)` this closes: `HitSpec` required a bare multiplier, so asking why a
    build scores what it scores meant knowing that Ayaka's burst is 1.123 per cut.

    The multiplier now comes from the character's own published table, at **this build's**
    talent level. Both forms are scored so the comparison is against a known number rather
    than against an assertion that it looks plausible.
    """
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    db_session.add(Talent(
        character_id=str(character.id), nanoka_id=10024,
        talent_type=TalentType.ELEMENTAL_BURST, name="Kamisato Art: Soumetsu",
        description="",
    ))
    await db_session.flush()
    talent = (await db_session.execute(
        select(Talent).where(Talent.character_id == str(character.id)),
    )).scalars().one()
    for level, cutting in ((1, 1.123), (9, 1.9091)):
        db_session.add(TalentScaling(
            talent_id=str(talent.id), level=level,
            labels=["Cutting DMG|{param1:P}", "Energy Cost|{param2:I}"],
            params=[cutting, 80],
        ))
    build = await _build_with_five(db_session, user, character, weapon, sets)
    build.talent_levels = {"elemental_burst": 9}
    await db_session.flush()

    def body(hit: dict) -> dict:
        return {"hit": {"channel": "cryo", "scope": "burst", **hit},
                "enemy": {"level": 90}}

    named = await client.post(
        f"/api/v1/builds/{build.id}/explain", headers=_auth(authed_user),
        json=body({"talent": {"talent": "elemental_burst", "label": "Cutting DMG"}}),
    )
    typed = await client.post(
        f"/api/v1/builds/{build.id}/explain", headers=_auth(authed_user),
        json=body({"multiplier": 1.9091}),
    )

    assert named.status_code == 200, named.text
    assert typed.status_code == 200, typed.text
    assert named.json()["damage"] == pytest.approx(typed.json()["damage"])


@pytest.mark.asyncio
async def test_a_hit_needs_exactly_one_of_multiplier_or_talent(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """Both would let one request state two different numbers for one hit, and whichever the
    server picked would silently contradict the other half of the same body."""
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)

    for hit in (
        {},
        {"multiplier": 1.5, "talent": {"talent": "elemental_burst", "label": "Cutting DMG"}},
    ):
        response = await client.post(
            f"/api/v1/builds/{build.id}/explain", headers=_auth(authed_user),
            json={"hit": {"channel": "cryo", "scope": "burst", **hit},
                  "enemy": {"level": 90}},
        )
        assert response.status_code == 422, hit


@pytest.mark.asyncio
async def test_a_talent_the_character_does_not_have_is_refused_with_its_reason(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets)
    build.talent_levels = {"elemental_burst": 9}
    await db_session.flush()

    response = await client.post(
        f"/api/v1/builds/{build.id}/explain", headers=_auth(authed_user),
        json={"hit": {"channel": "cryo", "scope": "burst",
                      "talent": {"talent": "elemental_burst", "label": "Cutting DMG"}},
              "enemy": {"level": 90}},
    )

    assert response.status_code == 422
    assert "elemental_burst" in response.json()["detail"]
