"""Spending one budget across several goals, and the order it is spent in.

**Why a campaign is not two ladders.** Planning a character and their weapon separately makes
each answer assume it owns the whole wallet, so both can read "almost certain" when affording
both is impossible. `test_two_ladders_would_double_count_the_wallet` pins the size of that
error, because it is the reason this module exists.
"""

from __future__ import annotations

import pytest

from app.services.wishes import (
    BannerKind,
    Leg,
    PlanInput,
    Strategy,
    UnreachableStateError,
    campaign_for,
    plan_campaign,
    plan_wishes,
    refund_tiers,
    refunded_budget,
)

CHARACTER = Leg(BannerKind.CHARACTER, "Furina", target_copies=1)
WEAPON = Leg(BannerKind.WEAPON, "Splendor", target_copies=1)


def chance(milestones, label: str) -> float:
    return next(m.success_chance for m in milestones if m.label == label)


# --- the reason this exists ------------------------------------------------------------


def test_two_ladders_would_double_count_the_wallet() -> None:
    """At 160 wishes a per-banner view says 99% and 100%; both is really about 40%."""
    budget = 160
    alone_character = plan_wishes(PlanInput(BannerKind.CHARACTER), budget).milestones[0]
    alone_weapon = plan_wishes(PlanInput(BannerKind.WEAPON), budget).milestones[0]
    together = plan_campaign([CHARACTER, WEAPON], budget).milestones

    assert alone_character.success_chance > 0.98
    assert alone_weapon.success_chance > 0.98
    assert chance(together, "Furina C0") == pytest.approx(alone_character.success_chance)
    assert chance(together, "Splendor R1") < 0.5


def test_a_later_goal_is_never_likelier_than_an_earlier_one() -> None:
    plan = plan_campaign([CHARACTER, WEAPON], 300).milestones
    chances = [m.success_chance for m in plan]
    assert chances == sorted(chances, reverse=True)


def test_the_cost_of_both_is_the_sum_of_their_costs() -> None:
    """Two legs cost what they cost separately — the budget is shared, the price is not."""
    solo_character = plan_wishes(PlanInput(BannerKind.CHARACTER), 0).milestones[0]
    solo_weapon = plan_wishes(PlanInput(BannerKind.WEAPON), 0).milestones[0]
    both = plan_campaign([CHARACTER, WEAPON], 0).milestones[-1]
    assert both.average_wishes == pytest.approx(
        solo_character.average_wishes + solo_weapon.average_wishes, abs=0.01
    )


def test_a_single_leg_campaign_is_the_single_banner_ladder() -> None:
    """`plan_wishes` is a wrapper, so the two must not be able to disagree."""
    ladder = plan_wishes(PlanInput(BannerKind.CHARACTER, pity=30), 250).milestones
    campaign = plan_campaign(
        [Leg(BannerKind.CHARACTER, pity=30, target_copies=7)], 250
    ).milestones
    assert [m.average_wishes for m in ladder] == [m.average_wishes for m in campaign]


# --- what crosses a leg boundary --------------------------------------------------------


def test_pity_belongs_to_the_first_leg_of_its_banner() -> None:
    """Obtaining a copy is a 5-star, and a 5-star resets pity. A second leg starts at zero."""
    deep = plan_campaign(
        [Leg(BannerKind.CHARACTER, "A", pity=80, target_copies=1),
         Leg(BannerKind.CHARACTER, "B", target_copies=1)], 0
    ).milestones
    fresh = plan_campaign(
        [Leg(BannerKind.CHARACTER, "A", target_copies=1),
         Leg(BannerKind.CHARACTER, "B", target_copies=1)], 0
    ).milestones
    first_saving = fresh[0].average_wishes - deep[0].average_wishes
    second_saving = fresh[1].average_wishes - deep[1].average_wishes
    assert first_saving > 20, "80 pity should shorten the first goal a lot"
    assert second_saving == pytest.approx(first_saving, abs=0.01), (
        "the saving must not grow: the second character does not inherit the pity"
    )


def test_a_weapon_leg_cannot_clear_the_radiance_counter() -> None:
    """Capturing Radiance is the character banner's. A weapon pull is invisible to it.

    If the weapon leg reset the counter, banked losses would stop mattering for a character
    planned after a weapon — silently, and only in campaigns.
    """
    def second_character(lost: int) -> float:
        return plan_campaign(
            [
                Leg(BannerKind.CHARACTER, "A", lost_fifty_fifties=lost, target_copies=1),
                Leg(BannerKind.WEAPON, "W", target_copies=1),
                Leg(BannerKind.CHARACTER, "B", target_copies=1),
            ],
            0,
        ).milestones[-1].average_wishes

    assert second_character(2) < second_character(0) - 15


def test_the_counter_is_declared_once_for_a_campaign() -> None:
    """It is one account-wide counter, so a later character cannot re-enter it."""
    with pytest.raises(ValueError, match="first leg of a campaign"):
        plan_campaign(
            [
                Leg(BannerKind.CHARACTER, "A", target_copies=1),
                Leg(BannerKind.WEAPON, "W", target_copies=1),
                Leg(BannerKind.CHARACTER, "B", lost_fifty_fifties=2, target_copies=1),
            ],
            0,
        )


# --- validation -------------------------------------------------------------------------


def test_an_empty_campaign_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one leg"):
        plan_campaign([], 100)


def test_a_target_below_what_is_owned_is_refused() -> None:
    with pytest.raises(ValueError, match="target_copies"):
        plan_campaign([Leg(BannerKind.CHARACTER, owned_copies=3, target_copies=2)], 100)


def test_a_target_above_the_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="target_copies"):
        plan_campaign([Leg(BannerKind.WEAPON, target_copies=6)], 100)


def test_the_unreachable_state_is_refused_in_a_campaign_too() -> None:
    with pytest.raises(UnreachableStateError):
        plan_campaign([Leg(BannerKind.CHARACTER, guaranteed=True, target_copies=1)], 100)


def test_labels_name_the_character_and_the_rung() -> None:
    labels = [m.label for m in plan_campaign(
        [Leg(BannerKind.CHARACTER, "Furina", target_copies=2),
         Leg(BannerKind.WEAPON, "Splendor", target_copies=2)], 0).milestones]
    assert labels == ["Furina C0", "Furina C1", "Splendor R1", "Splendor R2"]


def test_an_unlabelled_leg_reads_as_the_bare_rung() -> None:
    plan = plan_campaign([Leg(BannerKind.CHARACTER, target_copies=2)], 0)
    labels = [m.label for m in plan.milestones]
    assert labels == ["C0", "C1"]


# --- strategy ---------------------------------------------------------------------------


def _shape(legs: list[Leg]) -> list[tuple[str, int, int]]:
    return [(leg.banner.value, leg.owned_copies, leg.target_copies or 0) for leg in legs]


def test_every_strategy_reaches_c6_and_r5() -> None:
    for strategy in Strategy:
        legs = campaign_for(strategy, CHARACTER, WEAPON)
        assert _shape(legs)[-1][2] in (5, 7)
        assert max(t for b, _, t in _shape(legs) if b == "character") == 7
        assert max(t for b, _, t in _shape(legs) if b == "weapon") == 5


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        (
            Strategy.C0_FIRST,
            [("character", 0, 1), ("weapon", 0, 1), ("character", 1, 7), ("weapon", 1, 5)],
        ),
        (
            Strategy.C2_FIRST,
            [("character", 0, 3), ("weapon", 0, 1), ("character", 3, 7), ("weapon", 1, 5)],
        ),
        # C6 first leaves nothing for the second character leg, so the two merge.
        (Strategy.C6_FIRST, [("character", 0, 7), ("weapon", 0, 5)]),
        # Weapon first, then the character all the way, then the rest of the refinements.
        (Strategy.WEAPON_FIRST, [("weapon", 0, 1), ("character", 0, 7), ("weapon", 1, 5)]),
    ],
)
def test_strategy_ordering(strategy: Strategy, expected: list) -> None:
    assert _shape(campaign_for(strategy, CHARACTER, WEAPON)) == expected


def test_a_character_planned_alone_has_no_weapon_legs() -> None:
    assert _shape(campaign_for(Strategy.C0_FIRST, CHARACTER)) == [("character", 0, 7)]


def test_goals_already_met_are_dropped() -> None:
    legs = campaign_for(
        Strategy.C0_FIRST,
        Leg(BannerKind.CHARACTER, "F", owned_copies=3),
        Leg(BannerKind.WEAPON, "S", owned_copies=1),
    )
    assert _shape(legs) == [("character", 3, 7), ("weapon", 1, 5)]


def test_pity_rides_on_the_first_leg_of_its_banner_only() -> None:
    legs = campaign_for(
        Strategy.C0_FIRST,
        Leg(BannerKind.CHARACTER, "F", pity=70, lost_fifty_fifties=2),
        Leg(BannerKind.WEAPON, "S", pity=40),
    )
    character_legs = [leg for leg in legs if leg.banner is BannerKind.CHARACTER]
    weapon_legs = [leg for leg in legs if leg.banner is BannerKind.WEAPON]
    assert character_legs[0].pity == 70
    assert character_legs[0].lost_fifty_fifties == 2
    assert all(leg.pity == 0 for leg in character_legs[1:])
    assert all(leg.lost_fifty_fifties == 0 for leg in character_legs[1:])
    assert weapon_legs[0].pity == 40
    assert all(leg.pity == 0 for leg in weapon_legs[1:])


def test_the_strategy_changes_what_is_reached_first() -> None:
    """The point of the control: on a tight budget, order decides what you get."""
    budget = 190
    weapon_first = plan_campaign(campaign_for(Strategy.WEAPON_FIRST, CHARACTER, WEAPON), budget)
    character_first = plan_campaign(campaign_for(Strategy.C0_FIRST, CHARACTER, WEAPON), budget)
    # Each ordering makes its own primary goal likelier, and the other one less likely.
    assert chance(weapon_first.milestones, "Splendor R1") > chance(
        character_first.milestones, "Splendor R1"
    )
    assert chance(character_first.milestones, "Furina C0") > chance(
        weapon_first.milestones, "Furina C0"
    )


# --- starglitter refund -------------------------------------------------------------------


def test_no_refund_leaves_the_budget_alone() -> None:
    assert refunded_budget(200, "none") == 200


def test_the_tiers_are_ordered_and_modest() -> None:
    tiers = refund_tiers()
    assert tiers["none"] == 0.0
    assert 0 < tiers["low"] < tiers["average"] < tiers["high"] < 0.2


@pytest.mark.parametrize(
    ("tier", "expected"), [("low", 207), ("average", 217), ("high", 224)]
)
def test_refund_on_two_hundred_wishes(tier: str, expected: int) -> None:
    """Priced on the 13.057% consolidated 4-star rate, not the 10-pull guarantee.

    The tiers are points on the axis that drives the refund — how much of the 4-star roster
    is maxed — because 71.67% of 4-stars are characters whatever the pool looks like, and a
    character pays 0, 2 or 5 depending only on how far along it is.
    """
    assert refunded_budget(200, tier) == expected


def test_a_first_copy_pays_nothing_so_the_floor_is_low() -> None:
    """The wiki's quantity table lists duplicates only: a 4-star character you do not own
    returns a constellation and no starglitter. So `low` has to sit well under the
    owns-everything floor rather than at it."""
    tiers = refund_tiers()
    assert tiers["low"] < 0.055, "an account still collecting earns less than one that is not"


def test_the_refund_rounds_down() -> None:
    """A planner that promises wishes a player does not have is worse than a pessimistic one."""
    assert refunded_budget(1, "high") == 1


def test_an_unknown_tier_is_refused_rather_than_ignored() -> None:
    with pytest.raises(KeyError):
        refunded_budget(200, "generous")


def test_a_negative_wallet_is_refused() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        refunded_budget(-1, "none")
