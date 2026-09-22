"""Ordering one character's campaign, and the starglitter a campaign pays back.

Both exist so the page can offer what Fribbels offers without the frontend deciding any of
it: the leg order is a rule with a published shape, and the refund is arithmetic over cited
rates. `docs/DESIGN_wish_planner.md` §7.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from app.services.wishes.planner import MAX_CONSTELLATION, MAX_REFINEMENT, Leg
from app.services.wishes.rates import BannerKind, refund_tiers


class Strategy(StrEnum):
    """Which goal to reach first when one budget covers a character and their weapon.

    After the primary goal the order is always *character to C0 → weapon to R1 → character to
    C6 → weapon to R5*, which is the rule Fribbels' warp planner documents and the reason a
    strategy is a single choice rather than a sortable list.
    """

    WEAPON_FIRST = "r1_first"
    C0_FIRST = "c0_first"
    C1_FIRST = "c1_first"
    C2_FIRST = "c2_first"
    C3_FIRST = "c3_first"
    C4_FIRST = "c4_first"
    C5_FIRST = "c5_first"
    C6_FIRST = "c6_first"


#: Constellation each `C{n}_FIRST` aims at first. `WEAPON_FIRST` has none.
_PRIMARY_CONSTELLATION = {
    Strategy.C0_FIRST: 0,
    Strategy.C1_FIRST: 1,
    Strategy.C2_FIRST: 2,
    Strategy.C3_FIRST: 3,
    Strategy.C4_FIRST: 4,
    Strategy.C5_FIRST: 5,
    Strategy.C6_FIRST: 6,
}


def campaign_for(
    strategy: Strategy, character: Leg, weapon: Leg | None = None
) -> list[Leg]:
    """Return the ordered legs for one character, optionally with their signature weapon.

    Args:
        character: The character banner's starting state. Its `target_copies` is ignored —
            the strategy decides the goals.
        weapon: The weapon banner's starting state, or None to plan the character alone.

    Returns:
        Legs in spending order, each carrying the state that belongs to it. Goals already
        met are dropped rather than emitted as zero-length legs.
    """
    character_cap = MAX_CONSTELLATION + 1
    goals: list[tuple[BannerKind, int]] = []

    if strategy is Strategy.WEAPON_FIRST:
        goals += [(BannerKind.WEAPON, 1), (BannerKind.CHARACTER, 1)]
    else:
        goals.append((BannerKind.CHARACTER, _PRIMARY_CONSTELLATION[strategy] + 1))
        goals.append((BannerKind.WEAPON, 1))

    goals.append((BannerKind.CHARACTER, character_cap))
    goals.append((BannerKind.WEAPON, MAX_REFINEMENT))

    return _legs(goals, character, weapon)


def _legs(
    goals: list[tuple[BannerKind, int]], character: Leg, weapon: Leg | None
) -> list[Leg]:
    """Turn (banner, target) goals into legs, dropping any already satisfied.

    A goal is expressed as a *total* to hold, so "reach C6" after "reach C2" is one leg for
    the four copies between them rather than a second leg for seven.
    """
    held = {
        BannerKind.CHARACTER: character.owned_copies,
        BannerKind.WEAPON: weapon.owned_copies if weapon else MAX_REFINEMENT,
    }
    seen: set[BannerKind] = set()
    legs: list[Leg] = []

    for banner, target in goals:
        source = character if banner is BannerKind.CHARACTER else weapon
        if source is None or target <= held[banner]:
            continue
        # Two goals in a row on the same banner are one leg. `r1_first` reaches the weapon,
        # then the character's C0, then C6 — and those last two are consecutive.
        if legs and legs[-1].banner is banner:
            legs[-1] = replace(legs[-1], target_copies=target)
            held[banner] = target
            continue
        first = banner not in seen
        seen.add(banner)
        legs.append(
            Leg(
                banner=banner,
                label=source.label,
                # Pity, the guarantee and the counter belong to the first leg on their
                # banner. A later leg on the same banner starts after a 5-star, by
                # definition, so it has none of them.
                pity=source.pity if first else 0,
                guaranteed=source.guaranteed if first else False,
                lost_fifty_fifties=source.lost_fifty_fifties if first else 0,
                owned_copies=held[banner],
                target_copies=target,
                # **Carried, not dropped.** `campaign_for` rebuilds the legs, and losing the
                # slug here silently sent every plan back to the constant tier — the refund
                # read as unavailable while a banner was plainly picked.
                banner_slug=source.banner_slug,
            )
        )
        held[banner] = target
    return legs


def refunded_budget(wishes: int, tier: str) -> int:
    """Return `wishes` grown by the starglitter a campaign of that size pays back.

    Spending a wish earns starglitter, which buys wishes, which earn more — so the multiplier
    is the compounded `r / (1 - r)` stored in `banner_rates.json`, and `1 + tier` is exactly
    `1 / (1 - r)`.

    **It rounds down and ignores 5-star contributions**, so every tier under-states the
    refund rather than over-stating it. A planner that promised wishes a player does not have
    would be worse than one that is slightly pessimistic.

    Raises:
        KeyError: If `tier` is not one the rates file describes.
    """
    if wishes < 0:
        raise ValueError("wishes must not be negative")
    return int(wishes * (1.0 + refund_tiers()[tier]))
