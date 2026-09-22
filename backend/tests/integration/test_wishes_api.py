"""The wish planner's HTTP surface.

The math is proved in `tests/unit/test_wish_planner_math.py` and cross-validated against a
simulation in `tests/unit/test_wish_planner_crossval.py`. This file is about the contract:
that the routes require a caller, that a wallet becomes a budget, that the one unreachable
banner state is refused rather than answered, and that an unrefreshed income store says so
instead of inventing numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
        json={"banner": "character", "primogems": 24_000, "intertwined_fate": 60},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["budget"] == 210, "24,000 primogems is 150 wishes, plus 60 fate"
    assert [m["label"] for m in body["milestones"]] == ["C0", "C1", "C2", "C3", "C4", "C5", "C6"]
    assert body["milestones"][0]["success_chance"] == pytest.approx(1.0, abs=1e-6)
    assert body["milestones"][0]["average_wishes"] == pytest.approx(93.45, abs=0.01)
    assert body["published_worst_case"] == 180


async def test_a_weapon_ladder_uses_refinements(authed_client: AsyncClient) -> None:
    response = await authed_client.post("/api/v1/wishes/plan", json={"banner": "weapon"})
    assert response.status_code == 200
    body = response.json()
    assert [m["label"] for m in body["milestones"]] == ["R1", "R2", "R3", "R4", "R5"]
    assert body["published_worst_case"] == 160


async def test_acquaint_fate_is_not_a_field(authed_client: AsyncClient) -> None:
    """Owner ruling, 2026-09-22. An unknown field must not silently inflate the budget."""
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"banner": "character", "acquaint_fate": 500}
    )
    assert response.status_code == 200
    assert response.json()["budget"] == 0


async def test_projected_income_adds_to_the_budget(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"banner": "character", "primogems": 1_600, "extra_wishes": 90},
    )
    assert response.json()["budget"] == 100


async def test_banked_losses_change_the_answer(authed_client: AsyncClient) -> None:
    """If this ever stops mattering, Capturing Radiance has stopped being modelled."""
    chances = []
    for lost in (0, 3):
        response = await authed_client.post(
            "/api/v1/wishes/plan",
            json={"banner": "character", "primogems": 28_800, "lost_fifty_fifties": lost},
        )
        assert response.status_code == 200
        chances.append(response.json()["milestones"][1]["success_chance"])
    assert chances[1] - chances[0] > 0.2


async def test_the_unreachable_state_is_refused(authed_client: AsyncClient) -> None:
    """Guaranteed with no 50/50s lost: arming the guarantee requires losing one."""
    response = await authed_client.post(
        "/api/v1/wishes/plan",
        json={"banner": "character", "guaranteed": True, "lost_fifty_fifties": 0},
    )
    assert response.status_code == 422
    assert "guarantee" in response.json()["detail"].lower()


async def test_radiance_on_the_weapon_banner_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"banner": "weapon", "lost_fifty_fifties": 2}
    )
    assert response.status_code == 400


async def test_pity_beyond_hard_pity_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"banner": "character", "pity": 90}
    )
    assert response.status_code == 400


async def test_owning_copies_shortens_the_ladder(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"banner": "character", "owned_copies": 5}
    )
    assert [m["label"] for m in response.json()["milestones"]] == ["C5", "C6"]


async def test_a_negative_wallet_is_rejected_by_the_schema(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/wishes/plan", json={"banner": "character", "primogems": -1}
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
