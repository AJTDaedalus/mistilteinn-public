"""The wish planner's HTTP surface.

The math is proved in `tests/unit/test_wish_planner_math.py` and cross-validated against a
simulation in `tests/unit/test_wish_planner_crossval.py`. This file is about the contract:
that the routes require a caller, that a wallet becomes a budget, that the one unreachable
banner state is refused rather than answered, and that an unrefreshed income store says so
instead of inventing numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest

from app.models.wish_income import WishIncome

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_planning_requires_a_caller(client: AsyncClient) -> None:
    response = await client.post("/api/v1/wishes/plan", json={"banner": "character"})
    assert response.status_code == 401


async def test_income_requires_a_caller(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/wishes/income")).status_code == 401


async def test_a_fresh_character_ladder(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character"}, "primogems": 24_000, "intertwined_fate": 60},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["budget"] == 210, "24,000 primogems is 150 wishes, plus 60 fate"
    assert [m["label"] for m in body["milestones"]] == ["C0", "C1", "C2", "C3", "C4", "C5", "C6"]
    assert body["milestones"][0]["success_chance"] == pytest.approx(1.0, abs=1e-6)
    assert body["milestones"][0]["average_wishes"] == pytest.approx(93.45, abs=0.01)
    assert body["published_worst_case"] == 180


async def test_a_weapon_ladder_uses_refinements(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"targets": [{"banner": "weapon", "target_copies": 5}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert [m["label"] for m in body["milestones"]] == ["R1", "R2", "R3", "R4", "R5"]
    assert body["published_worst_case"] == 160


async def test_acquaint_fate_is_not_a_field(authed_client: AsyncClient) -> None:
    """Owner ruling, 2026-09-22. An unknown field must not silently inflate the budget."""
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"character": {"banner": "character"}, "acquaint_fate": 500}
    )
    assert response.status_code == 200
    assert response.json()["budget"] == 0


async def test_projected_income_adds_to_the_budget(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character"}, "primogems": 1_600, "extra_wishes": 90},
    )
    assert response.json()["budget"] == 100


async def test_banked_losses_change_the_answer(authed_client: AsyncClient) -> None:
    """If this ever stops mattering, Capturing Radiance has stopped being modelled."""
    chances = []
    for lost in (0, 3):
        response = await authed_client.post(
            "/api/v1/wishes/plan",
            json={
                "character": {"banner": "character", "lost_fifty_fifties": lost},
                "primogems": 28_800,
            },
        )
        assert response.status_code == 200
        chances.append(response.json()["milestones"][1]["success_chance"])
    assert chances[1] - chances[0] > 0.2


async def test_the_unreachable_state_is_refused(authed_client: AsyncClient) -> None:
    """Guaranteed with no 50/50s lost: arming the guarantee requires losing one."""
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character", "guaranteed": True, "lost_fifty_fifties": 0}},
    )
    assert response.status_code == 422
    assert "guarantee" in response.json()["detail"].lower()


async def test_radiance_on_the_weapon_banner_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"targets": [{"banner": "weapon", "target_copies": 1, "lost_fifty_fifties": 2}]},
    )
    assert response.status_code == 400


async def test_pity_beyond_hard_pity_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"character": {"banner": "character", "pity": 90}}
    )
    assert response.status_code == 400


async def test_owning_copies_shortens_the_ladder(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"character": {"banner": "character", "owned_copies": 5}}
    )
    assert [m["label"] for m in response.json()["milestones"]] == ["C5", "C6"]


async def test_a_negative_wallet_is_rejected_by_the_schema(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"character": {"banner": "character"}, "primogems": -1}
    )
    assert response.status_code == 422


# --- income ---------------------------------------------------------------------------


async def test_an_unrefreshed_store_is_empty_rather_than_invented(
    authed_client: AsyncClient,
) -> None:
    """The refresher has not run against the test database, and that is not an error.

    Filling it with plausible numbers would be the worse failure: nothing downstream could
    tell them from real ones.
    """
    response = await authed_client.get("/api/v1/wishes/income")
    assert response.status_code == 200
    body = response.json()
    assert body["versions"] == []
    assert body["fetched_at"] is None


async def test_income_reports_all_three_tiers_and_its_age(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    fetched = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    db_session.add_all(
        [
            WishIncome(
                version="7.1", major=7, minor=1, tier=tier, wishes=wishes,
                is_estimate=True, fetched_at=fetched,
            )
            for tier, wishes in (("f2p", 88.0), ("welkin", 114.3), ("welkin_bp", 122.5))
        ]
    )
    await db_session.commit()

    body = (await authed_client.get("/api/v1/wishes/income")).json()
    assert len(body["versions"]) == 1
    version = body["versions"][0]
    assert version["version"] == "7.1"
    assert version["is_estimate"] is True, "a forecast must not read as a settled total"
    assert version["f2p"] == pytest.approx(88.0)
    assert version["welkin"] == pytest.approx(114.3)
    assert version["welkin_bp"] == pytest.approx(122.5)
    assert body["fetched_at"] is not None, "a page must be able to say how old this is"


async def test_versions_are_ordered_by_number_not_by_string(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """"7.10" must follow "7.9". Sorting the label as text would put it second."""
    fetched = datetime(2026, 9, 22, tzinfo=UTC)
    db_session.add_all(
        [
            WishIncome(
                version=label, major=major, minor=minor, tier="f2p", wishes=100.0,
                is_estimate=False, fetched_at=fetched,
            )
            for label, major, minor in (("7.10", 7, 10), ("7.9", 7, 9), ("6.0", 6, 0))
        ]
    )
    await db_session.commit()

    body = (await authed_client.get("/api/v1/wishes/income")).json()
    assert [v["version"] for v in body["versions"]] == ["6.0", "7.9", "7.10"]


# --- limits ---------------------------------------------------------------------------


async def test_limits_let_the_page_build_its_controls(authed_client: AsyncClient) -> None:
    body = (await authed_client.get("/api/v1/wishes/limits")).json()
    assert body["primogems_per_wish"] == 160
    assert body["max_constellation"] == 6
    assert body["max_refinement"] == 5
    assert body["banners"]["character"]["hard_pity"] == 90
    assert body["banners"]["character"]["capturing_radiance"] is True
    assert body["banners"]["weapon"]["capturing_radiance"] is False
    assert body["max_lost_fifty_fifties"] == 3


# --- campaigns: one budget across several goals -------------------------------------------


async def test_a_character_and_their_weapon_share_one_budget(
    authed_client: AsyncClient,
) -> None:
    """The question two separate ladders cannot answer.

    At 160 wishes each banner alone reads near-certain; together, the weapon is not.
    """
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character", "label": "Furina"},
            "weapon": {"banner": "weapon", "label": "Splendor"},
            "strategy": "c0_first",
            "primogems": 25_600,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["budget"] == 160

    rungs = {m["label"]: m["success_chance"] for m in body["milestones"]}
    assert rungs["Furina C0"] > 0.98
    assert rungs["Splendor R1"] < 0.5, "both cannot be near-certain on one wallet"
    assert [m["label"] for m in body["milestones"]][:3] == [
        "Furina C0", "Splendor R1", "Furina C1",
    ]


async def test_the_strategy_reorders_the_ladder(authed_client: AsyncClient) -> None:
    async def first_rung(strategy: str) -> str:
        response = await authed_client.post(
            "/api/v1/wishes/plan",
            json={
                "character": {"banner": "character", "label": "Furina"},
                "weapon": {"banner": "weapon", "label": "Splendor"},
                "strategy": strategy,
            },
        )
        return response.json()["milestones"][0]["label"]

    assert await first_rung("c0_first") == "Furina C0"
    assert await first_rung("r1_first") == "Splendor R1"
    assert await first_rung("c2_first") == "Furina C0"


async def test_a_custom_plan_spans_several_characters(authed_client: AsyncClient) -> None:
    """The owner's shape: C2 R1 of one character and C0 R1 of another, one wallet."""
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "targets": [
                {"banner": "character", "label": "Furina", "target_copies": 3},
                {"banner": "weapon", "label": "Splendor", "target_copies": 1},
                {"banner": "character", "label": "Neuvillette", "target_copies": 1},
                {"banner": "weapon", "label": "Tome", "target_copies": 1},
            ],
            "primogems": 160_000,
        },
    )
    assert response.status_code == 200
    labels = [m["label"] for m in response.json()["milestones"]]
    assert labels == [
        "Furina C0", "Furina C1", "Furina C2",
        "Splendor R1",
        "Neuvillette C0",
        "Tome R1",
    ]


async def test_a_custom_target_without_a_goal_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"targets": [{"banner": "character", "label": "Furina"}]},
    )
    assert response.status_code == 400
    assert "target_copies" in response.json()["detail"]


async def test_sending_both_shapes_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character"},
            "targets": [{"banner": "character", "target_copies": 1}],
        },
    )
    assert response.status_code == 400


async def test_sending_neither_shape_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post("/api/v1/wishes/plan", json={"primogems": 1600})
    assert response.status_code == 400


async def test_a_weapon_in_the_character_slot_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"character": {"banner": "weapon"}}
    )
    assert response.status_code == 400


async def test_only_the_first_target_may_set_the_counter(authed_client: AsyncClient) -> None:
    """One account, one Capturing Radiance counter — declared on the first character leg."""
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "targets": [
                {"banner": "character", "target_copies": 1},
                {"banner": "character", "target_copies": 2, "lost_fifty_fifties": 2},
            ]
        },
    )
    assert response.status_code == 400
    assert "first character-banner leg" in response.json()["detail"]


# --- starglitter refund --------------------------------------------------------------------


async def test_the_refund_grows_the_budget_and_is_reported_separately(
    authed_client: AsyncClient,
) -> None:
    """A player should see what their wallet holds and what the refund adds, not one total."""
    async def budget(tier: str) -> dict:
        response = await authed_client.post(
            "/api/v1/wishes/plan",
            json={
                "character": {"banner": "character"},
                "primogems": 32_000,
                "starglitter_refund": tier,
            },
        )
        assert response.status_code == 200
        return response.json()

    none = await budget("none")
    assert none["wallet_wishes"] == 200
    assert none["refunded_wishes"] == 0
    assert none["budget"] == 200

    for tier, expected in (("low", 7), ("average", 17), ("high", 24)):
        body = await budget(tier)
        assert body["wallet_wishes"] == 200
        assert body["refunded_wishes"] == expected
        assert body["budget"] == 200 + expected


async def test_an_unknown_refund_tier_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character"}, "starglitter_refund": "generous"},
    )
    assert response.status_code == 400
    assert "refund tier" in response.json()["detail"]


async def test_limits_publishes_the_strategies_and_refund_tiers(
    authed_client: AsyncClient,
) -> None:
    """The page builds both dropdowns from this rather than hardcoding them."""
    body = (await authed_client.get("/api/v1/wishes/limits")).json()
    assert body["strategies"][0] == "r1_first"
    assert "c6_first" in body["strategies"]
    tiers = body["starglitter_refund_tiers"]
    assert tiers["none"] == 0
    assert 0 < tiers["low"] < tiers["average"] < tiers["high"]


async def test_a_weapon_first_plan_accepts_banked_losses(authed_client: AsyncClient) -> None:
    """PR #331 review, finding 1. `R1 first` plus any banked losses used to answer 400.

    Reachable in two clicks: ticking "Guaranteed" sets the counter to 1 by itself.
    """
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character", "label": "F", "lost_fifty_fifties": 2},
            "weapon": {"banner": "weapon", "label": "S"},
            "strategy": "r1_first",
            "primogems": 32_000,
        },
    )
    assert response.status_code == 200
    assert response.json()["milestones"][0]["label"] == "S R1"


async def test_the_counter_is_bounded_by_the_model_not_by_constellations(
    authed_client: AsyncClient,
) -> None:
    """Four states, 0-3. Accepting 4-6 and silently clamping them answered a question about
    a counter both the model and the page say cannot exist."""
    body = (await authed_client.get("/api/v1/wishes/limits")).json()
    assert body["max_lost_fifty_fifties"] == 3

    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character", "lost_fifty_fifties": 4}},
    )
    assert response.status_code == 422


async def test_limits_reads_its_constants_from_the_data_file(
    authed_client: AsyncClient,
) -> None:
    """Hardcoding them let the page and the server disagree with nothing failing."""
    from app.services.wishes.rates import primogems_per_wish, radiance_win_rates

    body = (await authed_client.get("/api/v1/wishes/limits")).json()
    assert body["primogems_per_wish"] == primogems_per_wish()
    assert body["max_lost_fifty_fifties"] == len(radiance_win_rates()) - 1


# --- banners --------------------------------------------------------------------------


async def _banner(db_session: AsyncSession, **over) -> str:
    from datetime import UTC, datetime

    from app.models.wish_banner import WishBanner

    fields = {
        "slug": "Test Banner/2026-09-23", "name": "Test Banner", "kind": "character",
        "starts_at": "2026-09-23 11:00:00", "ends_at": "2026-10-13 17:59:59",
        "featured_five": ["Vesna"], "featured_four": ["Diona", "Faruzan", "Chongyun"],
        "alongside": [], "fetched_at": datetime(2026, 9, 22, tzinfo=UTC),
    }
    fields.update(over)
    db_session.add(WishBanner(**fields))
    await db_session.commit()
    return str(fields["slug"])


async def test_banners_require_a_caller(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/wishes/banners")).status_code == 401


async def test_an_unseeded_banner_table_is_empty_rather_than_invented(
    authed_client: AsyncClient,
) -> None:
    body = (await authed_client.get("/api/v1/wishes/banners")).json()
    assert body["banners"] == []
    assert body["total"] == 0


async def test_banners_come_back_newest_first_with_their_featured_items(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    await _banner(db_session, slug="Old/2020-09-28", starts_at="2020-09-28 11:00:00")
    await _banner(db_session)

    body = (await authed_client.get("/api/v1/wishes/banners")).json()
    assert [b["slug"] for b in body["banners"]] == ["Test Banner/2026-09-23", "Old/2020-09-28"]
    assert [i["name"] for i in body["banners"][0]["featured_four"]] == [
        "Diona", "Faruzan", "Chongyun",
    ]
    # A name the catalogue does not have resolves to null art rather than a broken image.
    assert all("icon" in i for i in body["banners"][0]["featured_four"])
    assert body["total"] == 2
    assert body["fetched_at"] is not None


async def test_banners_page_rather_than_truncate(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """`total` is what lets the page offer "show more" instead of hiding the rest.

    CLAUDE.md records the materials tab being "fixed" by capping a 514-row list at 80, which
    made the page short by hiding the data.
    """
    for i in range(5):
        await _banner(db_session, slug=f"B{i}/2026-01-0{i + 1}", starts_at=f"2026-01-0{i + 1}")

    first = (await authed_client.get("/api/v1/wishes/banners?limit=2")).json()
    assert len(first["banners"]) == 2
    assert first["total"] == 5

    second = (await authed_client.get("/api/v1/wishes/banners?limit=2&offset=2")).json()
    assert second["banners"]
    assert [b["slug"] for b in second["banners"]] != [b["slug"] for b in first["banners"]]


async def test_banners_filter_by_kind(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    await _banner(db_session)
    await _banner(db_session, slug="Epitome/2026-09-23", kind="weapon",
                  featured_five=["A", "B"], featured_four=["c", "d", "e", "f", "g"])

    body = (await authed_client.get("/api/v1/wishes/banners?kind=weapon")).json()
    assert [b["kind"] for b in body["banners"]] == ["weapon"]
    assert body["total"] == 1


# --- the histogram ---------------------------------------------------------------------


async def test_the_plan_carries_the_exact_distribution(authed_client: AsyncClient) -> None:
    """The convolution already produces it; the page used to throw it away.

    It is the population, not a sample — so the bars sum to the success probability of the
    whole support, not to something with a standard error on it.
    """
    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character"}, "primogems": 32_000},
    )).json()

    first = body["milestones"][0]
    assert first["histogram"], "the first rung should be chartable"
    assert sum(b["probability"] for b in first["histogram"]) == pytest.approx(1.0, abs=0.01)
    assert all(b["end"] > b["start"] for b in first["histogram"])
    # Bins ascend and do not overlap.
    edges = [(b["start"], b["end"]) for b in first["histogram"]]
    assert all(a[1] <= b[0] for a, b in pairwise(edges))


async def test_only_the_first_rungs_carry_a_histogram(authed_client: AsyncClient) -> None:
    """Twelve charts nobody asked for is a payload, not a feature."""
    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character"}, "primogems": 32_000},
    )).json()
    charted = [m for m in body["milestones"] if m["histogram"]]
    assert 0 < len(charted) < len(body["milestones"])


# --- the refund read from the account ---------------------------------------------------


async def test_the_refund_falls_back_to_the_tier_without_a_banner(
    authed_client: AsyncClient,
) -> None:
    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character"},
            "primogems": 32_000, "starglitter_refund": "average",
        },
    )).json()
    assert body["refund_source"] == "tier"
    assert body["refunded_wishes"] > 0


async def test_an_unknown_banner_falls_back_rather_than_failing(
    authed_client: AsyncClient,
) -> None:
    """None rather than a guess — and a fallback that says which it used."""
    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character", "banner_slug": "Nothing/1999-01-01"},
            "primogems": 32_000, "starglitter_refund": "low",
        },
    )).json()
    assert body["refund_source"] == "tier"


async def test_a_banner_with_no_roster_falls_back(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """An account that has said nothing cannot have its refund computed from nothing."""
    slug = await _banner(db_session)
    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character"}, "primogems": 32_000,
            "banner_slug": slug, "starglitter_refund": "low",
        },
    )).json()
    assert body["refund_source"] == "tier"


async def test_limits_publishes_the_banner_page_size(authed_client: AsyncClient) -> None:
    body = (await authed_client.get("/api/v1/wishes/limits")).json()
    assert body["banner_page"] == 8


# --- PR #332 review findings -------------------------------------------------------------


async def _owned_four_star(
    db_session: AsyncSession, owner_id: str, name: str, constellation: int | None,
    *, rarity: str = "FOUR_STAR", owned: bool = True, nanoka_id: str | None = None,
) -> None:
    from app.models.character import Character
    from app.models.enums import Element, Rarity, WeaponType
    from app.models.roster import CharacterRosterEntry

    character = Character(
        nanoka_id=nanoka_id or f"n-{name}", name=name, element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity[rarity],
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    db_session.add(character)
    await db_session.flush()
    db_session.add(CharacterRosterEntry(
        owner_id=owner_id, character_id=str(character.id),
        owned=owned, constellation=constellation, source="import",
    ))
    await db_session.commit()


async def test_the_refund_is_read_from_the_account(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    user, _ = authed_user
    slug = await _banner(db_session)
    for name in ("Diona", "Faruzan", "Chongyun"):
        await _owned_four_star(db_session, str(user.id), name, 6)
    await _owned_four_star(db_session, str(user.id), "Bennett", 6)

    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character", "banner_slug": slug},
            "primogems": 32_000, "starglitter_refund": "account",
        },
    )).json()
    assert body["refund_source"] == "roster"
    # `none` would have given zero; the account gave a real figure.
    assert body["refunded_wishes"] > 0


async def test_the_account_is_the_default_refund_choice(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """Omitting the field asks for the account, because that is the better answer.

    The owner's ruling: the dropdown has to *control* the refund, and the exact figure is
    what it should start on.
    """
    user, _ = authed_user
    slug = await _banner(db_session)
    for name in ("Diona", "Faruzan", "Chongyun", "Bennett"):
        await _owned_four_star(db_session, str(user.id), name, 6)

    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character", "banner_slug": slug}, "primogems": 32_000},
    )).json()
    assert body["refund_source"] == "roster"


async def test_a_chosen_tier_beats_the_account(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """A tier is a request, not a fallback.

    **This is the defect the owner found by reading the control.** The account used to win
    whenever it could answer, so the dropdown sat on "8.7% (Average)" while nothing it said
    was being used — a control that changed nothing.
    """
    user, _ = authed_user
    slug = await _banner(db_session)
    for name in ("Diona", "Faruzan", "Chongyun", "Bennett"):
        await _owned_four_star(db_session, str(user.id), name, 6)

    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character", "banner_slug": slug},
            "primogems": 32_000, "starglitter_refund": "average",
        },
    )).json()
    assert body["refund_source"] == "tier"


async def test_an_account_that_cannot_answer_falls_back_to_nothing(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Not to a tier — a constant the caller did not pick is a number they cannot trust."""
    slug = await _banner(db_session)
    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character", "banner_slug": slug},
            "primogems": 32_000, "starglitter_refund": "account",
        },
    )).json()
    assert body["refund_source"] == "none"
    assert body["refunded_wishes"] == 0
    # The wallet is untouched: `none` is exactly "no refund", not "a small one".
    assert body["budget"] == body["wallet_wishes"]


async def test_a_five_star_does_not_dilute_the_four_star_pool(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """Finding 1. Without a rarity filter every 5-star owned joined the pool a non-featured
    *4-star* draw spreads over, diluting it and understating the refund."""
    user, _ = authed_user
    slug = await _banner(db_session)
    for name in ("Diona", "Faruzan", "Chongyun"):
        await _owned_four_star(db_session, str(user.id), name, 6)
    await _owned_four_star(db_session, str(user.id), "Bennett", 6)

    async def refund() -> int:
        return (await authed_client.post(
            "/api/v1/wishes/plan",
            json={"character": {"banner": "character", "banner_slug": slug},
                  "primogems": 32_000, "starglitter_refund": "none"},
        )).json()["refunded_wishes"]

    before = await refund()
    for i in range(12):
        await _owned_four_star(db_session, str(user.id), f"Five{i}", 6, rarity="FIVE_STAR")
    assert await refund() == before, "5-stars are not in the 4-star pool"


async def test_a_character_marked_not_owned_does_not_contribute(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """Finding 1. Un-owning a character keeps its stored constellation, so without the
    ownership filter it kept paying into the refund."""
    user, _ = authed_user
    slug = await _banner(db_session)
    for name in ("Diona", "Faruzan", "Chongyun"):
        await _owned_four_star(db_session, str(user.id), name, 6)
    await _owned_four_star(db_session, str(user.id), "Kept", 6)

    async def refund() -> int:
        return (await authed_client.post(
            "/api/v1/wishes/plan",
            json={"character": {"banner": "character", "banner_slug": slug},
                  "primogems": 32_000, "starglitter_refund": "none"},
        )).json()["refunded_wishes"]

    before = await refund()
    await _owned_four_star(db_session, str(user.id), "Disowned", 6, owned=False)
    assert await refund() == before


async def test_the_banner_decides_the_kind_not_the_first_leg(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """Finding 2. Reading the kind off `legs[0]` priced a weapon banner's five weapon names
    as unowned *characters*, and the mirror case threw away three real constellations."""
    user, _ = authed_user
    for name in ("Diona", "Faruzan", "Chongyun"):
        await _owned_four_star(db_session, str(user.id), name, 6)
    character_slug = await _banner(db_session)

    # The character banner with a strategy whose FIRST leg is the weapon banner.
    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "character": {"banner": "character", "banner_slug": character_slug},
            "weapon": {"banner": "weapon"},
            "strategy": "r1_first", "primogems": 32_000, "starglitter_refund": "account",
        },
    )).json()
    assert body["refund_source"] == "roster"
    assert body["refunded_wishes"] > 0, (
        "the three featured constellations must still be priced as characters"
    )


async def test_an_unknown_constellation_is_left_out_rather_than_read_as_unowned(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """Finding 5. `None` means "not owned" to `payout`, which gives the first copy away
    free — so forwarding a NULL understated exactly the accounts the column was added for."""
    user, _ = authed_user
    slug = await _banner(db_session)
    for name in ("Diona", "Faruzan", "Chongyun"):
        await _owned_four_star(db_session, str(user.id), name, 6)
    await _owned_four_star(db_session, str(user.id), "Known", 6)

    async def refund() -> int:
        return (await authed_client.post(
            "/api/v1/wishes/plan",
            json={"character": {"banner": "character", "banner_slug": slug},
                  "primogems": 32_000, "starglitter_refund": "none"},
        )).json()["refunded_wishes"]

    before = await refund()
    for i in range(10):
        await _owned_four_star(db_session, str(user.id), f"Unknown{i}", None)
    assert await refund() == before, "a NULL constellation must not enter the pool at all"


async def test_a_bad_tier_is_still_refused_when_a_banner_is_picked(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Finding 11. The handler moved into the `else` branch and stopped firing."""
    slug = await _banner(db_session)
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"character": {"banner": "character", "banner_slug": slug},
              "starglitter_refund": "bogus"},
    )
    assert response.status_code == 400


async def test_a_banner_with_no_start_date_does_not_take_the_first_slot(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Finding 8. Postgres sorts NULLs first under DESC."""
    await _banner(db_session, slug="Undated/2019-01-01", starts_at=None)
    await _banner(db_session)

    body = (await authed_client.get("/api/v1/wishes/banners")).json()
    assert body["banners"][0]["slug"] == "Test Banner/2026-09-23"


async def test_fetched_at_is_the_table_not_the_page(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Finding 7. Taken from the page it changed as the user clicked "show more"."""
    for i in range(4):
        await _banner(db_session, slug=f"B{i}/2026-01-0{i + 1}", starts_at=f"2026-01-0{i + 1}")

    first = (await authed_client.get("/api/v1/wishes/banners?limit=1")).json()
    later = (await authed_client.get("/api/v1/wishes/banners?limit=1&offset=3")).json()
    assert first["fetched_at"] == later["fetched_at"]

    past_the_end = (await authed_client.get("/api/v1/wishes/banners?limit=1&offset=99")).json()
    assert past_the_end["banners"] == []
    assert past_the_end["fetched_at"] is not None, "the table is populated; say so"


async def test_a_custom_plan_prices_each_banner_separately(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """The picker used to set one banner for the whole plan.

    That was wrong the moment a second row existed: each row is on its own banner with its
    own featured 4-stars, and the refund is priced per leg in proportion to what each leg is
    expected to cost.
    """
    user, _ = authed_user
    character_slug = await _banner(db_session)
    weapon_slug = await _banner(
        db_session, slug="Epitome/2026-09-23", kind="weapon",
        featured_five=["Splendor", "Other"],
        featured_four=["w1", "w2", "w3", "w4", "w5"],
    )
    for name in ("Diona", "Faruzan", "Chongyun"):
        await _owned_four_star(db_session, str(user.id), name, 6)
    for i in range(20):
        await _owned_four_star(db_session, str(user.id), f"Owned{i}", 6)

    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "targets": [
                {"banner": "character", "label": "Vesna", "target_copies": 1,
                 "banner_slug": character_slug},
                {"banner": "weapon", "label": "Splendor", "target_copies": 1,
                 "banner_slug": weapon_slug},
            ],
            "primogems": 48_000, "starglitter_refund": "account",
        },
    )).json()
    assert body["refund_source"] == "roster"
    assert body["refunded_wishes"] > 0
    assert [m["label"] for m in body["milestones"]] == ["Vesna C0", "Splendor R1"]


async def test_a_row_without_a_banner_does_not_sink_the_whole_plan(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple,
) -> None:
    """Some legs priced and some not under-states rather than inventing — and must not fall
    all the way back to the tier when one leg could be priced."""
    user, _ = authed_user
    slug = await _banner(db_session)
    for name in ("Diona", "Faruzan", "Chongyun"):
        await _owned_four_star(db_session, str(user.id), name, 6)
    for i in range(20):
        await _owned_four_star(db_session, str(user.id), f"Owned{i}", 6)

    body = (await authed_client.post(
        "/api/v1/wishes/plan",
        json={
            "targets": [
                {"banner": "character", "target_copies": 1, "banner_slug": slug},
                {"banner": "character", "target_copies": 1},
            ],
            "primogems": 48_000, "starglitter_refund": "account",
        },
    )).json()
    assert body["refund_source"] == "roster"
    assert body["refunded_wishes"] > 0
