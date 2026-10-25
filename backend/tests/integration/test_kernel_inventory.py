"""O.2 — the inventory in the terms the browser kernel reads.

`GET /artifacts/inventory` exists **for the client-side search** — its docstring answers OQ-S3
with "the browser holds the inventory and revalidates it", and it is ETag'd so an unchanged
account revalidates for free. Nothing else consumes it: `GET /artifacts` is the UI list.

So it carries kernel-ready candidates rather than `ArtifactRead` (OQ-O1). That is *smaller*
than what it returned before, and it is what its only intended consumer needs.

**The translation is the point.** `search.ts` reads `atk_pct`; the source spells it
`FIGHT_PROP_ATTACK_PERCENT`; the mapping is `stat_calculator._quantity_for_prop`, which
decides what every stat means and refuses rather than guessing. A TypeScript copy would have a
silent failure mode — a mis-mapped substat optimising for a stat the character does not have.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.artifact import Artifact, ArtifactSet
from app.models.enums import ArtifactSlot, Rarity, StatType

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

INVENTORY = "/api/v1/artifacts/inventory"

#: Quantities the snapshot emits that `search.ts` does not read, and why each is fine.
#:
#: The snapshot describes **the artifact**, not today's kernel: trimming it to exactly what
#: the current search sums would make the payload kernel-version-specific, and the browser
#: holds it across searches. So extras are expected — but each one is named here, because an
#: unexplained extra is indistinguishable from a quantity the kernel *should* read and does
#: not, which is a stat silently contributing nothing to every ranking.
UNREAD_BY_THE_KERNEL = {
    "energy_recharge": (
        "the search scores one hit and ER changes whether a rotation happens, not how hard "
        "it lands. `sim_context` buckets it separately for exactly that reason."
    ),
    "healing_bonus": "the kernel scores damage; healing is not part of a hit.",
    "incoming_healing_bonus": "as healing_bonus — a stat about being healed, not about a hit.",
    "shield_strength": "shields absorb damage rather than dealing it.",
}


@pytest.fixture
async def piece(db_session: AsyncSession, authed_user: tuple[User, str]) -> str:
    """A circlet: CRIT DMG main, CRIT Rate and flat ATK substats."""
    user, _ = authed_user
    owner_id = str(user.id)
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(artifact_set)
    await db_session.flush()
    artifact = Artifact(
        owner_id=owner_id, artifact_set_id=str(artifact_set.id),
        slot=ArtifactSlot.CIRCLET, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.CRIT_DMG, main_stat_value=0.622,
        substats=[
            {"stat": "FIGHT_PROP_CRITICAL", "value": 0.109, "rolls": 3},
            {"stat": "FIGHT_PROP_ATTACK", "value": 47.0, "rolls": 1},
        ],
    )
    db_session.add(artifact)
    await db_session.flush()
    return str(artifact.id)


# ── the shape the kernel takes ───────────────────────────────────────────────


async def test_a_candidate_is_what_the_kernel_reads(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """`search.ts`'s `Candidate`, plus the one field the *user* needs.

    Deliberately an exact set rather than a subset check: this payload is fetched per search
    over a whole inventory, so a field added without thinking about it is paid for 2,370
    times. Growing it is a decision, and this test is where the decision gets made.
    """
    db_session.expire_all()

    snapshot = (await authed_client.get(INVENTORY)).json()

    assert len(snapshot["artifacts"]) == 1
    candidate = snapshot["artifacts"][0]
    assert set(candidate) == {
        "id", "slot", "set_id", "stats", "main_stat",
        # A.4 added three, and this is the decision that test's docstring asks for. They are
        # paid 2,370 times and earn it: `rarity` and `level` were already hashed into the
        # inventory version and deliberately not emitted — see `_inventory_version`, which
        # called itself "a superset of what the payload carries" — so emitting them narrows an
        # over-hash rather than widening a risk. `potential` is the artifact ranker's input and
        # is four small numbers, not a second copy of the piece.
        "rarity", "level", "potential",
    }
    assert candidate["slot"] == "equip_dress"
    # **Carried even though it is already summed into `stats`.** The kernel wants one number
    # per quantity and does not care which was the main stat; a user cares enormously, and it
    # cannot be recovered from the pool — a CRIT DMG circlet with a CRIT DMG substat looks
    # identical either way.
    assert candidate["main_stat"] == candidate["main_stat"].upper()
    assert candidate["main_stat"].startswith("FIGHT_PROP_")
    # The catalogue's integer id, not the row's UUID: the kernel counts set pieces by id and
    # it counts numbers, so a UUID would make every piece its own set and no bonus would
    # ever reach two pieces.
    assert candidate["set_id"] == 15025


async def test_the_stats_are_kernel_quantities_not_fight_props(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """The main stat and every substat, translated and summed into one map.

    `FIGHT_PROP_CRITICAL_HURT` is `crit_dmg`, `FIGHT_PROP_CRITICAL` is `crit_rate`, and
    `FIGHT_PROP_ATTACK` is `flat_atk` — a different quantity from `atk_pct`, and confusing
    the two is the silent failure this endpoint exists to prevent.

    The names are `search.ts`'s own: `search.ts:79` resolves ATK from
    `['base_atk', 'atk_pct', 'flat_atk']`. Asserted against those rather than against what
    they might reasonably have been called — this test first said `atk`, which is the
    *scaling stat* name and not a quantity the kernel sums.
    """
    db_session.expire_all()

    stats = (await authed_client.get(INVENTORY)).json()["artifacts"][0]["stats"]

    assert not any(key.startswith("FIGHT_PROP") for key in stats), sorted(stats)
    assert stats["crit_dmg"] == pytest.approx(0.622)
    assert stats["crit_rate"] == pytest.approx(0.109)
    assert stats["flat_atk"] == pytest.approx(47.0)


async def test_a_main_stat_and_a_substat_of_the_same_quantity_are_summed(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """A CRIT DMG circlet with a CRIT DMG substat has both, and the kernel takes one number
    per quantity. Overwriting instead of summing would drop whichever came second."""
    user, _ = authed_user
    owner_id = str(user.id)
    db_session.add(Artifact(
        owner_id=owner_id, artifact_set_id=None, slot=ArtifactSlot.CIRCLET,
        rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.CRIT_DMG, main_stat_value=0.622,
        substats=[{"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.1, "rolls": 2}],
    ))
    await db_session.flush()
    db_session.expire_all()

    stats = (await authed_client.get(INVENTORY)).json()["artifacts"][0]["stats"]

    assert stats["crit_dmg"] == pytest.approx(0.722)


async def test_a_setless_piece_reports_no_set_rather_than_a_fabricated_one(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """32 starter relics carry no set. `set_id` is null for them — a `0` would be a real
    catalogue id to the kernel, which counts set pieces by id."""
    user, _ = authed_user
    db_session.add(Artifact(
        owner_id=str(user.id), artifact_set_id=None, slot=ArtifactSlot.FLOWER,
        rarity=Rarity.ONE_STAR, level=0, main_stat_type=StatType.HP_FLAT,
        main_stat_value=129.0, substats=[],
    ))
    await db_session.flush()
    db_session.expire_all()

    candidate = (await authed_client.get(INVENTORY)).json()["artifacts"][0]

    assert candidate["set_id"] is None


# ── what it refuses to do quietly ────────────────────────────────────────────


async def test_a_prop_the_mapping_refuses_is_reported_not_dropped(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """OQ-O2.

    A silently omitted piece is an inventory the user cannot see is incomplete, and a search
    over it recommends the best of what it was **shown** while looking like the best of what
    they own. The snapshot already carries `truncated` for the analogous case.
    """
    user, _ = authed_user
    db_session.add(Artifact(
        owner_id=str(user.id), artifact_set_id=None, slot=ArtifactSlot.SANDS,
        rarity=Rarity.FIVE_STAR, level=20, main_stat_type=StatType.ATK_PCT,
        main_stat_value=0.466,
        substats=[{"stat": "FIGHT_PROP_NOT_A_REAL_STAT", "value": 1.0, "rolls": 1}],
    ))
    await db_session.flush()
    db_session.expire_all()

    snapshot = (await authed_client.get(INVENTORY)).json()

    assert snapshot["unreadable"], "the piece was dropped without a word"
    entry = snapshot["unreadable"][0]
    assert "FIGHT_PROP_NOT_A_REAL_STAT" in entry["reason"]
    assert entry["artifact_id"]


async def test_an_unreadable_piece_is_left_out_of_the_candidates(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """Reported *and* excluded: the kernel cannot score a piece whose stats did not resolve,
    and a candidate with a partial stat map would be ranked as though it were weaker than it
    is — a wrong ordering, silently."""
    user, _ = authed_user
    db_session.add(Artifact(
        owner_id=str(user.id), artifact_set_id=None, slot=ArtifactSlot.SANDS,
        rarity=Rarity.FIVE_STAR, level=20, main_stat_type=StatType.ATK_PCT,
        main_stat_value=0.466,
        substats=[{"stat": "FIGHT_PROP_NOT_A_REAL_STAT", "value": 1.0, "rolls": 1}],
    ))
    await db_session.flush()
    db_session.expire_all()

    snapshot = (await authed_client.get(INVENTORY)).json()

    assert snapshot["artifacts"] == []
    assert snapshot["total"] == 0, "the count must describe what was returned"


async def test_an_absent_substat_marker_is_not_an_error(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user,
):
    """`FIGHT_PROP_NONE` is one of the three ways the data spells "no stat here", and a piece
    with fewer than four substats is ordinary rather than broken."""
    user, _ = authed_user
    db_session.add(Artifact(
        owner_id=str(user.id), artifact_set_id=None, slot=ArtifactSlot.PLUME,
        rarity=Rarity.FIVE_STAR, level=0, main_stat_type=StatType.ATK_FLAT,
        main_stat_value=311.0,
        substats=[{"stat": "FIGHT_PROP_NONE", "value": 0.0, "rolls": 0}],
    ))
    await db_session.flush()
    db_session.expire_all()

    snapshot = (await authed_client.get(INVENTORY)).json()

    assert snapshot["unreadable"] == []
    assert snapshot["artifacts"][0]["stats"] == {"flat_atk": pytest.approx(311.0)}


# ── the ETag still means what it meant ───────────────────────────────────────


async def test_an_unchanged_inventory_still_revalidates_for_free(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    db_session.expire_all()

    first = await authed_client.get(INVENTORY)
    again = await authed_client.get(
        INVENTORY, headers={"If-None-Match": first.headers["ETag"]},
    )

    assert first.status_code == 200
    assert again.status_code == 304


async def test_levelling_a_piece_changes_the_version(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """The version tracks what a search would read. A piece whose stats moved is a different
    inventory, and a browser holding the old one would search over stats nobody has."""
    db_session.expire_all()
    before = (await authed_client.get(INVENTORY)).json()["version"]

    row = await db_session.get(Artifact, piece)
    row.level = 16
    await db_session.flush()
    db_session.expire_all()

    assert (await authed_client.get(INVENTORY)).json()["version"] != before


async def test_every_quantity_the_endpoint_emits_is_one_the_kernel_reads() -> None:
    """The two vocabularies must be the same vocabulary.

    This endpoint exists so the client does not reimplement `_quantity_for_prop` — but that
    only helps if what it emits is what `search.ts` sums. Nothing pinned the two together, and
    writing this file's first draft I asserted `atk` where the kernel reads `flat_atk`: the
    *scaling stat* name, not a quantity. The tests were wrong and the code was right, which is
    the pleasant version; the unpleasant version is the same mistake in the endpoint, where a
    stat would silently contribute nothing.

    Read out of `search.ts` rather than restated, so the kernel renaming a quantity fails here
    rather than being silently dropped from every search.
    """
    import re
    from pathlib import Path

    from app.models.enums import StatType
    from app.services.stat_calculator import StatInputError, _quantity_for_prop

    source = (
        Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "sim" / "search.ts"
    ).read_text()
    known = set(re.findall(r"'([a-z_]+)'", source))
    assert "flat_atk" in known, "search.ts did not parse as expected; this check is inert"

    emitted = set()
    for stat in StatType:
        try:
            quantity = _quantity_for_prop(stat.value, allow_absent=True)
        except StatInputError:
            continue
        if quantity is not None:
            emitted.add(quantity)

    # Damage-bonus and RES quantities are named by channel in `tags`, and the kernel builds
    # them from `dmgBonusQuantity` rather than listing them — exempt by shape, not by
    # exception.
    unpinned = {
        q for q in emitted - known
        if not q.endswith(("_dmg_bonus", "_res", "_res_shred"))
    }

    unexplained = unpinned - set(UNREAD_BY_THE_KERNEL)
    assert not unexplained, (
        f"these quantities are emitted to the kernel and never read by it: "
        f"{sorted(unexplained)}. Either the kernel should read them, or add them to "
        f"UNREAD_BY_THE_KERNEL with the reason."
    )


def test_every_exemption_has_a_reason_and_is_still_needed() -> None:
    """Guards the guard above.

    An exemption list that nobody prunes becomes a list of quantities the kernel quietly
    stopped reading — the same failure `ci_local`'s adaptations carry a precondition for.
    """
    from app.models.enums import StatType
    from app.services.stat_calculator import StatInputError, _quantity_for_prop

    emitted = set()
    for stat in StatType:
        try:
            quantity = _quantity_for_prop(stat.value, allow_absent=True)
        except StatInputError:
            continue
        if quantity is not None:
            emitted.add(quantity)

    for quantity, reason in UNREAD_BY_THE_KERNEL.items():
        assert len(reason) > 20, f"{quantity} is exempt without a reason"
        assert quantity in emitted, (
            f"{quantity} is exempt but no longer emitted — drop the exemption"
        )


async def test_equipping_a_piece_invalidates_the_snapshot(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user, piece: str,
):
    """A spurious miss, and the safe direction — recorded so it is a decision, not a bug.

    `build_id` is hashed into the version and no longer appears in the payload, so equipping
    invalidates a snapshot whose bytes did not change. A digest **narrower** than the payload
    would risk serving a stale inventory instead, and a search over one recommends artifacts
    the user no longer owns.
    """
    from app.models.build import Build

    user, _ = authed_user
    owner_id = str(user.id)
    build = Build(owner_id=owner_id, character_id=None)
    db_session.add(build)
    await db_session.flush()
    build_id = str(build.id)
    db_session.expire_all()

    before = (await authed_client.get(INVENTORY)).json()
    await authed_client.patch(f"/api/v1/artifacts/{piece}", json={"build_id": build_id})
    db_session.expire_all()
    after = (await authed_client.get(INVENTORY)).json()

    assert after["version"] != before["version"]
    assert after["artifacts"] == before["artifacts"], "the payload itself did not change"


# ── A.4: what the artifact ranker projects from ──────────────────────────────


async def test_a_candidate_carries_what_a_projection_needs(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """`TASKS_artifact_ranking.md` A.4. The fixture is a 5-star at +20: nothing left."""
    db_session.expire_all()

    candidate = (await authed_client.get(INVENTORY)).json()["artifacts"][0]

    assert candidate["rarity"] == 5
    assert candidate["level"] == 20
    potential = candidate["potential"]
    assert potential["rolls_remaining"] == 0, "a +20 five-star has no upgrades left"
    assert potential["rolls_total"] == 5
    assert potential["gains_a_substat"] is False


async def test_the_lines_are_named_because_the_summed_pool_cannot_name_them(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user, piece: str,
):
    """The reason `substat_quantities` exists at all.

    A CRIT DMG circlet with a CRIT DMG **substat** has one entry in `stats` for both, so the
    summed pool cannot say whether the piece has a CRIT DMG line — and that is exactly what
    decides whether a future roll deepens a line or creates one.
    """
    user, _ = authed_user
    artifact = Artifact(
        owner_id=str(user.id), slot=ArtifactSlot.CIRCLET, rarity=Rarity.FIVE_STAR, level=0,
        main_stat_type=StatType.CRIT_DMG, main_stat_value=0.078,
        substats=[
            {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.078},
            {"stat": "FIGHT_PROP_CRITICAL", "value": 0.039},
            {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.047},
        ],
    )
    db_session.add(artifact)
    await db_session.flush()
    db_session.expire_all()

    body = (await authed_client.get(INVENTORY)).json()
    card = next(c for c in body["artifacts"] if c["id"] == str(artifact.id))

    # One entry in the pool for two sources — which is the whole problem.
    assert "crit_dmg" in card["stats"]
    assert card["potential"]["substat_quantities"] == ["crit_dmg", "crit_rate", "atk_pct"]
    # Three lines at +0: five upgrades ahead, one of which creates the fourth.
    assert card["potential"]["rolls_remaining"] == 5
    assert card["potential"]["gains_a_substat"] is True


def ladders_of(model: dict) -> dict[str, list[float]]:
    """The five-star roll ladders, keyed by quantity."""
    return {row["quantity"]: row["values"] for row in model["roll_tiers"]["5"]}


async def test_the_draw_model_ships_once_and_carries_its_caveat(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """The shared half of the projection input, and the citation that has to travel with it."""
    db_session.expire_all()

    model = (await authed_client.get(INVENTORY)).json()["draw_model"]

    # Kernel quantities, not GO's own spelling: these have to join `roll_tiers` below without
    # the client holding two vocabularies and a mapping between them.
    assert set(model["substat_weights"]) == set(ladders_of(model))
    assert model["substat_weights"]["flat_hp"] > model["substat_weights"]["crit_rate"]
    # Only the rarities actually held. The fixture inventory is five-star.
    assert set(model["roll_tiers"]) == {"5"}
    ladders = ladders_of(model)
    assert len(ladders["crit_dmg"]) == 4, "four roll tiers at five-star"
    assert ladders["crit_dmg"] == sorted(ladders["crit_dmg"])
    # The weights are cited rather than derived, and a number computed from them has to be
    # able to say so on screen — not in a comment nobody reading it will see.
    assert "cannot" in model["weights_caveat"] or "could not" in model["weights_caveat"]
    # The upgrade estimator's half rides on the same payload (TASKS_upgrade_estimator.md 2).
    fresh = model["fresh_drop"]
    assert fresh["five_star_per_run"] == 1.065
    assert fresh["resin_per_run"] == 20
    assert fresh["main_stat_probabilities"]["equip_bracer"] == {"flat_hp": 1.0}
    assert 15001 in fresh["sets_without_domain_drop"]


async def test_the_five_star_ladders_ship_to_an_account_with_no_five_stars(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The estimator models a fresh 5-star drop, so a 4-star-only account still needs them.

    It used to ship ladders only for the rarities held, and the estimate then refused with
    "no 5-star roll ladders arrived" for exactly the newer account it is most useful to.
    """
    user, _ = authed_user
    artifact_set = ArtifactSet(
        nanoka_id=15040, name="Finale of the Deep Galleries", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(artifact_set)
    await db_session.flush()
    db_session.add(Artifact(
        owner_id=str(user.id), artifact_set_id=str(artifact_set.id),
        slot=ArtifactSlot.FLOWER, rarity=Rarity.FOUR_STAR, level=16,
        main_stat_type=StatType.HP_FLAT, main_stat_value=3571.0, substats=[],
    ))
    await db_session.flush()
    db_session.expire_all()

    model = (await authed_client.get(INVENTORY)).json()["draw_model"]

    assert "5" in model["roll_tiers"]
    assert len(ladders_of(model)["crit_dmg"]) == 4


async def test_a_ladder_is_never_the_unupgradable_fixed_value(
    authed_client: AsyncClient, db_session: AsyncSession, piece: str,
):
    """`_tiers_for` filters depots that publish one fixed value; `roll_tiers` inherits that.

    It went wrong once — a single `0.1943` merged beside 5-star CRIT DMG's real
    `0.0544-0.0777` ladder divided `roll_value` by the wrong maximum, scoring a 24.9% CRIT DMG
    substat 1.28 instead of 3.20. A projection reading that ladder would overstate every
    remaining roll by the same factor.
    """
    db_session.expire_all()

    ladders = ladders_of((await authed_client.get(INVENTORY)).json()["draw_model"])

    assert max(ladders["crit_dmg"]) < 0.1, ladders["crit_dmg"]
    for quantity, values in ladders.items():
        assert len(set(values)) == len(values) > 1, f"{quantity} is not a ladder: {values}"
