"""O.1 — everything the browser kernel needs except the inventory.

`frontend/src/app/sim/search.ts` is a working optimizer that nothing imports, and the reason
was a `hit` nobody could supply without typing a multiplier. M.2 fixed that; this is what
carries the rest across.

**Published, not recomputed.** Every figure here is one the server already works out for
`/explain` — base contributions from `build_assembler`, set bonuses from the same, the hit
through `resolve_talent_hit`. A second assembly of "what a build starts from" is how two
definitions of it begin, which `build_assembler` records having already happened once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.artifact import Artifact, ArtifactSet, ArtifactSetAffix
from app.models.build import Build
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

pytestmark = pytest.mark.asyncio

BUILDS = "/api/v1/builds"

BURST = {"talent": "elemental_burst", "label": "Cutting DMG", "index": 0}


def _body(**overrides) -> dict:
    body = {
        "hit": {"channel": "cryo", "scope": "burst", "talent": BURST,
                "scaling_stat": "atk", "flat_damage": 0.0},
        "enemy": {"level": 90, "resistances": {}, "default_resistance": 0.1},
    }
    body.update(overrides)
    return body


@pytest.fixture
async def build(db_session: AsyncSession, authed_user: tuple[User, str]) -> str:
    """Ayaka at burst 9, holding a Blizzard Strayer flower."""
    user, _ = authed_user
    character = Character(
        nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO,
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
        nanoka_id=11509, name="Mistsplitter Reforged", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, base_atk_curve="GROW_CURVE_ATTACK_101",
        sub_stat_type=StatType.CRIT_DMG, sub_stat_base_value=0.096,
        sub_stat_curve="GROW_CURVE_CRITICAL_101",
        ascension_atk={str(p): {"fight_prop_base_attack": 31.1 * p} for p in range(1, 7)},
    )
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add_all([character, weapon, artifact_set])
    await db_session.flush()

    db_session.add(ArtifactSetAffix(
        artifact_set_id=str(artifact_set.id), position=0, pieces_required=2,
        name="", description="",
        add_props=[{"prop_type": "FIGHT_PROP_ICE_ADD_HURT", "value": 0.15}],
    ))
    db_session.add(Talent(
        character_id=str(character.id), nanoka_id=10024,
        talent_type=TalentType.ELEMENTAL_BURST, name="Soumetsu", description="",
    ))
    await db_session.flush()
    # Selected, not read off `character.talents`: `lazy` is `raise_on_sql`, so the
    # relationship refuses rather than emitting a query — which is the guard working, in a
    # fixture rather than in a request.
    talent = (await db_session.execute(
        select(Talent).where(Talent.character_id == str(character.id)),
    )).scalars().one()
    db_session.add(TalentScaling(
        talent_id=str(talent.id), level=9,
        labels=["Cutting DMG|{param1:P}", "Energy Cost|{param2:I}"], params=[1.9091, 80],
    ))

    row = Build(
        owner_id=str(user.id), character_id=str(character.id), weapon_id=str(weapon.id),
        character_level=90, ascension_phase=6, weapon_level=90,
        talent_levels={"elemental_burst": 9},
    )
    db_session.add(row)
    await db_session.flush()
    # All five: `/explain` refuses a partial build, because "a partial build scores as a
    # partial build, and next to a full one that difference reads as a choice the user made".
    for slot, main in (
        (ArtifactSlot.FLOWER, StatType.HP_FLAT),
        (ArtifactSlot.PLUME, StatType.ATK_FLAT),
        (ArtifactSlot.SANDS, StatType.ATK_PCT),
        (ArtifactSlot.GOBLET, StatType.CRYO_DMG_BONUS),
        (ArtifactSlot.CIRCLET, StatType.CRIT_DMG),
    ):
        db_session.add(Artifact(
            owner_id=str(user.id), artifact_set_id=str(artifact_set.id),
            build_id=str(row.id), slot=slot, rarity=Rarity.FIVE_STAR, level=20,
            main_stat_type=main, main_stat_value=0.466, substats=[],
        ))
    await db_session.flush()
    return str(row.id)


# ── the shape the kernel takes ───────────────────────────────────────────────


async def test_the_context_carries_what_the_kernel_needs(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """`SearchContext` in `search.ts` names exactly these. A missing key is a search that
    cannot start; a wrongly-named one is a search that starts and scores nothing."""
    db_session.expire_all()

    context = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()

    assert set(context) == {
        "base", "hit", "target", "character_level", "dmg_bonus_quantity", "set_bonuses",
    }
    assert context["character_level"] == 90
    assert context["dmg_bonus_quantity"] == "cryo_dmg_bonus"


async def test_the_base_is_keyed_by_kernel_quantity_not_fight_prop(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """The whole reason this endpoint exists. The kernel reads `base_atk`; the source spells
    it `FIGHT_PROP_BASE_ATTACK`, and the mapping between them is backend-private."""
    db_session.expire_all()

    base = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()["base"]

    assert "base_atk" in base
    assert not any(key.startswith("FIGHT_PROP") for key in base), sorted(base)
    assert base["base_atk"] > 0


async def test_the_base_sums_every_contribution_to_a_quantity(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """Found driving math-fallback P0. `base_atk` has two contributors — the character's
    curve and the weapon's — and `base_hp` has the curve and the ascension bonus. The base
    was a dict comprehension over the contributions, so each quantity kept only the **last**
    one: Neuvillette's `base_hp` reached the kernel as his ascension bonus alone (4,697.8 of
    14,695), and the single-hit search scored every build on a fraction of its base.

    Checked against `/explain`'s own account of the same quantities, which sums them."""
    db_session.expire_all()

    base = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()["base"]
    explained = (await authed_client.post(f"{BUILDS}/{build}/explain", json=_body())).json()
    accounts = {s["quantity"]: s for s in explained["stats"]}

    for quantity in ("base_atk", "base_hp", "base_def"):
        assert len(accounts[quantity]["parts"]) >= 1, quantity
        assert base[quantity] == pytest.approx(accounts[quantity]["sum_of_parts"]), quantity
    # The weapon's base ATK and the character's are both in it: the fixture's Mistsplitter is
    # most of the figure, so a base that kept one contributor fails here.
    assert len(accounts["base_atk"]["parts"]) >= 2


async def test_the_hit_is_resolved_from_the_named_talent(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """M.2's resolution, reused rather than re-derived. 1.9091 is Ayaka's Cutting DMG at
    talent 9 — the figure M.4 checked against gcsim's `burstCut`."""
    db_session.expire_all()

    hit = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()["hit"]

    assert hit["multiplier"] == pytest.approx(1.9091)
    assert hit["channel"] == "cryo"
    assert hit["scaling_stat"] == "atk"
    assert hit["extra_terms"] == []


async def test_the_hit_carries_the_talents_own_stats_not_the_callers(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """Math-fallback P0. The page used to send `scaling_stat: 'atk'` for every talent, and the
    kernel scored whatever came back — so an HP scaler was searched off ATK. The talent's
    own stats come back now, with a mixed row's second term beside the first."""
    scaling = (await db_session.execute(select(TalentScaling))).scalars().one()
    scaling.labels = ["Field DMG|{param1:F1P} ATK+{param2:F2P} Max HP"]
    scaling.params = [1.1, 0.019]
    await db_session.flush()
    db_session.expire_all()

    body = _body()
    body["hit"] = {**body["hit"], "scaling_stat": None,
                   "talent": {"talent": "elemental_burst", "label": "Field DMG", "index": 0}}
    response = await authed_client.post(f"{BUILDS}/{build}/search-context", json=body)

    assert response.status_code == 200, response.text
    hit = response.json()["hit"]
    assert hit["scaling_stat"] == "atk"
    assert hit["multiplier"] == pytest.approx(1.1)
    assert hit["extra_terms"] == [{"stat": "hp", "multiplier": pytest.approx(0.019)}]


async def test_set_bonuses_come_back_in_kernel_terms(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """A 2-piece Blizzard Strayer is 15% cryo DMG, and the kernel reads that as
    `cryo_dmg_bonus`."""
    db_session.expire_all()

    bonuses = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()["set_bonuses"]

    two_piece = [b for b in bonuses if b["pieces_required"] == 2]
    assert two_piece, bonuses
    assert two_piece[0]["stats"] == {"cryo_dmg_bonus": pytest.approx(0.15)}


# ── the same server, asked twice, must agree with itself ─────────────────────


async def test_the_context_agrees_with_what_explain_computes(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """The acceptance criterion that matters.

    `/explain` and this endpoint both start from `build_assembler.base_contributions`. If they
    disagreed, the browser would search against one base and the explanation of its winner
    would be computed from another — and the two numbers on screen would differ for a reason
    no user could see.
    """
    db_session.expire_all()

    context = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()
    raw = await authed_client.post(
        f"{BUILDS}/{build}/explain", json=_body(artifact_ids=None, compare_to_equipped=False),
    )
    assert raw.status_code == 200, raw.text
    explained = raw.json()

    by_quantity = {stat["quantity"]: stat["sum_of_parts"] for stat in explained["stats"]}
    assert by_quantity, explained
    for quantity, value in context["base"].items():
        if quantity in by_quantity:
            # The explanation includes the equipped artifacts; the base does not. So the
            # explained total is the base *plus* what is worn, never less than it.
            assert by_quantity[quantity] >= value - 1e-9, quantity


# ── refusals ─────────────────────────────────────────────────────────────────


async def test_a_build_with_no_character_is_refused_with_its_reason(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user, build: str,
):
    """`base_contributions` refuses it: five artifacts on a base of zero would rank by their
    own stats alone, which is a plausible answer to a question nobody asked."""
    user, _ = authed_user
    empty = Build(owner_id=str(user.id), character_id=None)
    db_session.add(empty)
    await db_session.flush()
    empty_id = str(empty.id)
    db_session.expire_all()

    response = await authed_client.post(
        f"{BUILDS}/{empty_id}/search-context", json=_body(),
    )

    assert response.status_code == 422
    assert "character" in response.json()["detail"]


async def test_a_talent_with_no_level_is_refused(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """A missing level is not level 1 — M.2's refusal, reaching this endpoint intact."""
    row = (await db_session.execute(select(Build).where(Build.id == build))).scalars().one()
    row.talent_levels = {}
    await db_session.flush()
    db_session.expire_all()

    response = await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )

    assert response.status_code == 422
    assert "level" in response.json()["detail"]


async def test_someone_elses_build_is_a_404(authed_client: AsyncClient, build: str):
    response = await authed_client.post(
        f"{BUILDS}/00000000-0000-0000-0000-000000000001/search-context", json=_body(),
    )

    assert response.status_code == 404


async def test_the_target_carries_the_resistance_for_this_hit_s_channel(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """One number, because the kernel scores one channel — and it must be **that** channel's.

    Averaging the eight would be a resistance no enemy has, and taking the wrong one is a
    multiplier applied to every combination the search scores, so the whole ranking shifts
    while each individual figure still looks reasonable.
    """
    db_session.expire_all()

    context = (await authed_client.post(
        f"{BUILDS}/{build}/search-context",
        json=_body(enemy={"level": 90, "resistances": {"cryo": 0.6, "pyro": 0.1},
                          "default_resistance": 0.1}),
    )).json()

    assert context["target"]["resistance"] == pytest.approx(0.6)
    assert context["target"]["level"] == 90


async def test_a_set_the_build_does_not_wear_is_still_offered(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user, build: str,
):
    """The search may propose pieces from a set this build is not wearing, and a bonus the
    kernel was never told about is one it cannot score — so the ranking would silently prefer
    the sets that happened to be equipped already."""
    user, _ = authed_user
    other = ArtifactSet(
        nanoka_id=15026, name="Emblem of Severed Fate", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(other)
    await db_session.flush()
    db_session.add(ArtifactSetAffix(
        artifact_set_id=str(other.id), position=0, pieces_required=2,
        name="", description="",
        add_props=[{"prop_type": "FIGHT_PROP_CHARGE_EFFICIENCY", "value": 0.2}],
    ))
    # Owned but **unequipped** — exactly what a search is free to propose.
    db_session.add(Artifact(
        owner_id=str(user.id), artifact_set_id=str(other.id), build_id=None,
        slot=ArtifactSlot.SANDS, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.ENERGY_RECHARGE, main_stat_value=0.518, substats=[],
    ))
    await db_session.flush()
    db_session.expire_all()

    bonuses = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()["set_bonuses"]

    offered = {b["set_id"] for b in bonuses}
    assert 15026 in offered, f"an owned, unworn set was not offered: {sorted(offered)}"


async def test_owned_sets_are_asked_for_directly_not_read_out_of_the_inventory(
    db_session: AsyncSession, authed_user: tuple[User, str], build: str,
):
    """Derived from a set query, so a large account cannot lose one.

    `search`'s cap is 20,000 pieces. Collecting distinct sets from a capped read would
    silently omit a set from a larger inventory, and the ranking would then prefer whatever
    it did know about — **a ranking missing an option looks exactly like a ranking.**

    Checked at the repository, because that is where the cap would have applied.
    """
    from app.repositories.artifact import ArtifactRepository

    user, _ = authed_user
    # Captured before expiring: `expire_all()` expires this ORM object too, and reading
    # `user.id` afterwards is a synchronous refresh — a `MissingGreenlet` in the *test*,
    # which reads as a failure of the code under test.
    owner_id = str(user.id)
    unworn = ArtifactSet(
        nanoka_id=15027, name="Gladiator's Finale", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(unworn)
    await db_session.flush()
    db_session.add(ArtifactSetAffix(
        artifact_set_id=str(unworn.id), position=0, pieces_required=2,
        name="", description="",
        add_props=[{"prop_type": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.18}],
    ))
    db_session.add(Artifact(
        owner_id=owner_id, artifact_set_id=str(unworn.id), build_id=None,
        slot=ArtifactSlot.PLUME, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.ATK_FLAT, main_stat_value=311.0, substats=[],
    ))
    await db_session.flush()
    db_session.expire_all()

    sets = await ArtifactRepository(db_session, owner_id=owner_id).owned_sets()

    ids = {s.nanoka_id for s in sets}
    assert {15025, 15027} <= ids, sorted(ids)
    # Affixes eager-loaded: `set_bonuses` reads them, and `lazy` is `raise_on_sql`.
    assert all(s.affixes is not None for s in sets)


async def test_a_strangers_sets_are_not_offered(
    db_session: AsyncSession, authed_user: tuple[User, str], build: str,
):
    """Owner-scoped like every other read. An unscoped answer here would offer a bonus from
    a set the caller owns no piece of, and the search would rank builds it cannot assemble."""
    from app.models.user import User as UserModel
    from app.repositories.artifact import ArtifactRepository

    user, _ = authed_user
    owner_id = str(user.id)  # before `expire_all()`; see the note above
    stranger = UserModel(email="other@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    theirs = ArtifactSet(
        nanoka_id=15028, name="Theirs", piece_thresholds=[2], available_ranks=[5],
    )
    db_session.add(theirs)
    await db_session.flush()
    db_session.add(Artifact(
        owner_id=str(stranger.id), artifact_set_id=str(theirs.id), build_id=None,
        slot=ArtifactSlot.GOBLET, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.ATK_FLAT, main_stat_value=311.0, substats=[],
    ))
    await db_session.flush()
    db_session.expire_all()

    sets = await ArtifactRepository(db_session, owner_id=owner_id).owned_sets()

    assert 15028 not in {s.nanoka_id for s in sets}


# ── constellation talent boosts (math-fallback 9b) ───────────────────────────


async def _with_a_level_12_row(db_session: AsyncSession, build: str, constellation: int) -> None:
    """Ayaka with burst still **stored** at 9. Her C3 raises the burst (gcsim
    `internal/characters/ayaka/ayaka.go:21`, `c.BurstCon = 3`), so from C3 every hit reader
    must read the level-12 row: 2.386375, from the committed `character_10000002.json`."""
    talent = (await db_session.execute(select(Talent))).scalars().one()
    db_session.add(TalentScaling(
        talent_id=str(talent.id), level=12,
        labels=["Cutting DMG|{param1:P}", "Energy Cost|{param2:I}"], params=[2.386375, 80],
    ))
    row = await db_session.get(Build, build)
    row.constellation_level = constellation
    await db_session.flush()
    db_session.expire_all()


async def test_a_c3_build_reads_its_boosted_burst_everywhere_a_hit_is_read(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    """`/search-context` (the kernel), `/hits` (the picker) and `/explain` must agree: a
    picker offering one multiplier while the kernel scores another is two numbers on screen
    for a reason nobody can see."""
    await _with_a_level_12_row(db_session, build, 3)

    context = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()
    hits = (await authed_client.get(f"{BUILDS}/{build}/hits")).json()
    explained = await authed_client.post(f"{BUILDS}/{build}/explain", json=_body())

    assert context["hit"]["multiplier"] == pytest.approx(2.386375)
    assert [h["multiplier"] for h in hits if h["label"] == "Cutting DMG"] == [
        pytest.approx(2.386375),
    ]
    assert explained.status_code == 200, explained.text
    stored = (await db_session.get(Build, build)).talent_levels
    assert stored == {"elemental_burst": 9}, "the boost is applied on read, never stored"


async def test_a_c2_build_reads_its_stored_burst(
    authed_client: AsyncClient, db_session: AsyncSession, build: str,
):
    await _with_a_level_12_row(db_session, build, 2)

    context = (await authed_client.post(
        f"{BUILDS}/{build}/search-context", json=_body(),
    )).json()

    assert context["hit"]["multiplier"] == pytest.approx(1.9091)
