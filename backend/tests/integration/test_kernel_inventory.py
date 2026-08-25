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
    """`search.ts`'s `Candidate` is exactly `{ id, slot, setId, stats }`."""
    db_session.expire_all()

    snapshot = (await authed_client.get(INVENTORY)).json()

    assert len(snapshot["artifacts"]) == 1
    candidate = snapshot["artifacts"][0]
    assert set(candidate) == {"id", "slot", "set_id", "stats"}
    assert candidate["slot"] == "equip_dress"
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
