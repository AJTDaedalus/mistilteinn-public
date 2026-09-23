"""The wish planner: odds of reaching a constellation or refinement on a given budget.

`docs/DESIGN_wish_planner.md`. Two routes — the ladder, and the income table it can be
budgeted against.

**A plan is a `POST` that writes nothing** and is not cached. The whole calculation is a few
discrete convolutions; looking a result up would cost more than producing it.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.character import Character
from app.models.enums import Rarity
from app.models.roster import CharacterRosterEntry
from app.models.user import User
from app.models.weapon import Weapon
from app.models.wish_banner import WishBanner
from app.models.wish_income import WishIncome
from app.services.roster import is_mannequin
from app.services.wishes import (
    BannerKind,
    Leg,
    Strategy,
    UnreachableStateError,
    campaign_for,
    plan_campaign,
    radiance_win_rates,
    rates_for,
    refund_tiers,
    refunded_budget,
)
from app.services.wishes.planner import (
    MAX_CONSTELLATION,
    MAX_REFINEMENT,
    wishes_from,
)
from app.services.wishes.rates import ACCOUNT_REFUND, primogems_per_wish
from app.services.wishes.refund import RefundInputs, expected_refund

#: Highest Capturing Radiance counter the model has a rate for. **Derived, not typed**: the
#: table's last entry is 1.0 ("you cannot lose a fourth"), so its length is the answer and a
#: change to the data file cannot leave this behind.
MAX_LOST_FIFTY_FIFTIES = len(radiance_win_rates()) - 1

router = APIRouter(prefix="/wishes", tags=["wishes"])

_Session = Annotated[AsyncSession, Depends(get_db)]
_User = Annotated[User, Depends(get_current_user)]

#: Generous ceilings that still refuse a value which can only be a typo or an attempt to make
#: the server convolve a very long array.
MAX_PRIMOGEMS = 10_000_000
MAX_FATE = 100_000
MAX_EXTRA_WISHES = 100_000
#: Banners a page asks for at a time, and the most it may ask for. Eight is the owner's
#: "show more" step; the ceiling stops a caller pulling all 291 in one request.
BANNER_PAGE = 8
MAX_BANNER_PAGE = 60


class WishTarget(BaseModel):
    """One banner's starting position within a plan."""

    banner: BannerKind
    label: str = Field(
        "", max_length=60, description="What to call this target's rungs — a character name."
    )
    pity: int = Field(0, ge=0, description="Wishes since the last 5-star on this banner.")
    guaranteed: bool = Field(
        False, description="Whether the next 5-star is guaranteed to be the promotional item."
    )
    lost_fifty_fifties: int = Field(
        0, ge=0, le=MAX_LOST_FIFTY_FIFTIES,
        description=(
            "50/50s lost since the last one WON — the Capturing Radiance counter. It is one "
            "account-wide counter, so only the FIRST target of a plan may set it."
        ),
    )
    owned_copies: int = Field(0, ge=0, description="Copies already held. C2 is 3; R3 is 3.")
    banner_slug: str | None = Field(
        None, max_length=200,
        description=(
            "A banner from `/wishes/banners`. **Per target, because a custom plan is several "
            "characters on several banners** and each has its own featured 4-stars — which "
            "are two thirds of every 4-star pulled, so they decide the refund."
        ),
    )
    target_copies: int | None = Field(
        None, ge=1,
        description=(
            "Total copies to reach. Only used by a custom plan; a simple plan's goals come "
            "from its strategy."
        ),
    )


class WishPlanRequest(BaseModel):
    """A player's wallet, and either one character to plan or an explicit list of goals.

    **Two shapes, one route.** `character` (plus an optional `weapon` and a `strategy`) is
    Fribbels' Simple mode: the whole ladder for one character, ordered by the strategy.
    `targets` is its Multi Target: an ordered list of goals across several characters,
    spending the same budget down the list.
    """

    character: WishTarget | None = Field(
        None, description="Simple mode: the character to plan, with `weapon` and `strategy`."
    )
    weapon: WishTarget | None = Field(
        None, description="Simple mode: their signature weapon, or null to plan alone."
    )
    strategy: Strategy = Field(
        Strategy.C0_FIRST, description="Simple mode: which goal to reach first."
    )
    targets: list[WishTarget] = Field(
        default_factory=list, max_length=12,
        description="Custom mode: goals in spending order. Each needs `target_copies`.",
    )
    starglitter_refund: str = Field(
        ACCOUNT_REFUND,
        description=(
            "How much of the budget comes back as Masterless Starglitter. `account` (the "
            "default) prices it exactly from the caller's own roster against the banner's "
            "featured 4-stars, and falls back to `none` when the account cannot answer. The "
            "constants are none, low (every 4-star a weapon), average (an even split), high "
            "(every 4-star a maxed character)."
        ),
    )
    primogems: int = Field(0, ge=0, le=MAX_PRIMOGEMS)
    intertwined_fate: int = Field(
        0, ge=0, le=MAX_FATE,
        description="Acquaint Fate is deliberately not accepted: it buys the standard banner.",
    )
    extra_wishes: int = Field(
        0, ge=0, le=MAX_EXTRA_WISHES,
        description="Projected income the caller has opted into, in whole wishes.",
    )


class WishHistogramBin(BaseModel):
    """One bar of the exact distribution of wishes to a rung."""

    start: int
    end: int
    probability: float


class WishMilestoneRead(BaseModel):
    """One rung of the ladder."""

    copies: int
    label: str = Field(description='What a player calls this rung: "C3", "R2".')
    success_chance: float = Field(ge=0.0, le=1.0)
    average_wishes: float
    median_wishes: int | None = Field(
        description="Wishes at which the chance first reaches 50%, or null if it never does."
    )
    histogram: list[WishHistogramBin] = Field(
        default_factory=list,
        description=(
            "The exact distribution of wishes needed, binned for drawing. **The population, "
            "not a sample** — no sampling error, identical on every run. Sent for the rungs "
            "the page can chart; empty on the rest to keep the payload small."
        ),
    )


class WishPlanRead(BaseModel):
    """The ladder, and the budget it was measured against."""

    budget: int = Field(description="Wishes available: primogems/160 + fate + projected income.")
    milestones: list[WishMilestoneRead]
    wallet_wishes: int = Field(description="Wishes the wallet alone is worth, before refund.")
    refund_source: str = Field(
        "tier",
        description=(
            "`roster` when the refund was computed exactly from the account and the banner's "
            "featured 4-stars, `tier` when it came from the chosen constant, and `none` when "
            "the account was asked for and could not answer. The third is distinct because "
            "it is the only one the caller did not choose: it is a request that declined."
        ),
    )
    refunded_wishes: int = Field(
        description="Wishes the starglitter refund adds. Zero when the tier is `none`."
    )
    published_worst_case: int = Field(
        description=(
            "The largest number of wishes HoYoverse advertises may be needed for one copy, "
            "for the plan's first banner. Published, NOT read off the fitted pity curve — "
            "the curve's far tail is not identified and would understate it."
        )
    )


class WishIncomeVersionRead(BaseModel):
    """One game version's income at all three tiers."""

    version: str
    is_estimate: bool = Field(
        description="The workbook's own `est.` marker — a forecast, not a settled total."
    )
    f2p: float
    welkin: float
    welkin_bp: float


class WishIncomeRead(BaseModel):
    """The income table, and when it was last refreshed."""

    versions: list[WishIncomeVersionRead]
    fetched_at: str | None = Field(
        description=(
            "When the store last read the workbook. Present so a page can say how old these "
            "numbers are: stale projected income is the failure mode that goes wrong silently."
        )
    )


@router.post("/plan", response_model=WishPlanRead)
async def create_plan(
    payload: WishPlanRequest, session: _Session, user: _User,
) -> WishPlanRead:
    """Return the odds of each goal in the plan, on one shared budget.

    Milestones are **cumulative**: a rung's chance is the chance of reaching it *and*
    everything before it. That is the whole difference from asking about each banner
    separately, where both answers silently assume they own the entire wallet.
    """
    try:
        legs = _legs_for(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    wallet = wishes_from(payload.primogems, payload.intertwined_fate) + payload.extra_wishes

    # The account beats the tier when it can answer. A banner names its featured 4-stars and
    # the roster knows their constellations, which is the axis the tiers only approximate.
    # Validated whichever source wins. Moving this into the `else` branch alone meant a bogus
    # tier answered 200 as soon as a banner was picked, and was never reported.
    # **The control means what it says.** `account` asks for the exact figure; a tier asks
    # for that constant and gets it even when the roster could have answered better. Deciding
    # for the caller is what made the dropdown a control that changed nothing — it sat there
    # reading "8.7% (Average)" while the roster quietly priced the plan.
    wants_account = payload.starglitter_refund == ACCOUNT_REFUND
    tier = "none" if wants_account else payload.starglitter_refund
    try:
        tier_budget = refunded_budget(wallet, tier)
    except KeyError as error:
        raise HTTPException(
            status_code=400,
            detail=f"unknown starglitter refund tier: {payload.starglitter_refund!r}",
        ) from error

    # **Validated before anything prices it.** The refund pre-pass runs the ladder itself, so
    # an unreachable leg used to raise from *there* — outside the handler thirty lines down —
    # and the caller got a 500 "Internal server error" in place of the sentence explaining
    # what was contradictory. Reachable straight from the UI: tick Guaranteed, leave the
    # 50/50 counter at 0, pick any banner.
    try:
        plan_campaign(legs, budget=0)
    except UnreachableStateError as error:
        # 422 rather than 400: the body is well-formed and each field is individually valid;
        # it is the combination that describes a situation the game cannot produce.
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # **Priced per leg, because a campaign can span banners.** A custom plan is several
    # characters on several banners and each one's featured 4-stars decide its own refund —
    # pricing the whole plan off one banner was wrong the moment a second row existed.
    exact = (
        await _converged_refund(session, str(user.id), legs, wallet)
        if wants_account else None
    )
    if exact is not None:
        budget, refund_source = wallet + int(exact), "roster"
    else:
        # **Falls back to nothing, not to a tier.** A tier the caller did not pick is a number
        # they have no reason to trust, and `none` is the only honest answer to "use my
        # account" from an account that cannot say.
        budget = tier_budget
        if not wants_account:
            refund_source = "tier"
        elif not any(leg.banner_slug for leg in legs):
            # **Distinct, because it is not the roster's fault.** Lumping this in with `none`
            # made the page's own default state — type a wallet, do not open the picker —
            # tell a fully-imported account it had no constellation data.
            refund_source = "no_banner"
        else:
            refund_source = "none"

    plan = plan_campaign(legs, budget=budget)

    return WishPlanRead(
        budget=plan.budget,
        wallet_wishes=wallet,
        refunded_wishes=budget - wallet,
        refund_source=refund_source,
        milestones=[
            WishMilestoneRead(
                copies=milestone.copies,
                label=milestone.label,
                success_chance=milestone.success_chance,
                average_wishes=milestone.average_wishes,
                median_wishes=milestone.median_wishes,
                histogram=_histogram(milestone.pmf),
            )
            for milestone in plan.milestones
        ],
        published_worst_case=rates_for(legs[0].banner).published_worst_case,
    )


def _legs_for(payload: WishPlanRequest) -> list[Leg]:
    """Turn either request shape into one ordered list of legs.

    Raises:
        ValueError: If neither shape is given, both are, or a custom target omits its goal.
    """
    if payload.targets and payload.character is not None:
        raise ValueError("send either `character` (simple) or `targets` (custom), not both")

    if payload.targets:
        missing = [t.label or t.banner.value for t in payload.targets if t.target_copies is None]
        if missing:
            raise ValueError(f"custom targets need `target_copies`: {missing}")
        return [_leg(target) for target in payload.targets]

    if payload.character is None:
        raise ValueError("a plan needs a `character` or a list of `targets`")
    if payload.character.banner is not BannerKind.CHARACTER:
        raise ValueError("`character` must be a character-banner target")
    if payload.weapon is not None and payload.weapon.banner is not BannerKind.WEAPON:
        raise ValueError("`weapon` must be a weapon-banner target")

    return campaign_for(
        payload.strategy,
        _leg(payload.character),
        _leg(payload.weapon) if payload.weapon else None,
    )


#: Bars in a milestone's histogram. Enough to show the pity humps, few enough to send.
HISTOGRAM_BINS = 40
#: Below this a bin is empty for drawing purposes; it trims a long, invisible tail.
HISTOGRAM_FLOOR = 1e-6
#: Catalogue names shared by more than one row, so a name-keyed lookup cannot resolve them.
#: Sixteen Travelers, and the practice mannequins (`Manekin`/`Manekina`, seven each).
_AMBIGUOUS_NAMES = frozenset({"Traveler", "Manekin", "Manekina"})


# **Every rung carries its histogram, now that the chart follows the one you click.**
#
# This used to be `CHARTED_RUNGS = 3`, from when the page drew one chart pinned to the first
# rung — "the whole ladder would be twelve charts nobody asked for" was true then. It stopped
# being true when the ladder became the selector: a C0-C6 plus R1-R5 plan is twelve rungs, so
# nine of twelve chips rendered disabled with nothing saying why, and a four-row custom plan
# could not chart its fourth row.
#
# The cost is one binning pass per rung over a PMF the convolution already produced — twelve
# small arrays of `HISTOGRAM_BINS` bins, not twelve charts.


def _histogram(pmf: list[float] | None) -> list[WishHistogramBin]:
    """Bin an exact PMF for drawing, trimmed to where the mass actually is."""
    if not pmf:
        return []
    values = np.asarray(pmf)
    live = np.flatnonzero(values > HISTOGRAM_FLOOR)
    if live.size == 0:
        return []
    lo, hi = int(live[0]), int(live[-1]) + 1
    edges = np.linspace(lo, hi, HISTOGRAM_BINS + 1).astype(int)
    return [
        WishHistogramBin(
            start=int(a), end=int(b), probability=float(values[a:b].sum()),
        )
        for a, b in pairwise(edges)
        if b > a
    ]


#: How many compounding passes past the first the refund may take before it is called done.
_REFUND_PASSES = 6
#: Stop compounding once a pass moves the refund by less than this many wishes.
_REFUND_TOLERANCE = 0.25


async def _converged_refund(
    session: AsyncSession, owner_id: str, legs: list[Leg], wallet: int,
) -> float | None:
    """The refund at its fixed point, or None if the account cannot price any leg.

    **Compounded, as the tier is.** The refund buys wishes which themselves refund, so pricing
    it over `wallet` alone and stopping drops the second order — and switching a banner on
    could then make the reported refund *fall*.

    Iterated rather than done twice. The comment this replaces claimed "the third is under a
    wish"; measured on a 900-wish wallet against a maxed forty-character roster the passes run
    96.82, 107.23, 108.42, 108.53 to a fixed point of 108.40 — so the third pass is worth
    **1.19** wishes, not under one, and two passes understate a large campaign. Monotone and
    bounded (`expected_refund` increases in `pulls`, and the refund rate is far below 1), so
    this converges; the cap is belt and braces.
    """
    refund = await _refund_for_campaign(session, owner_id, legs, wallet)
    if refund is None:
        return None
    for _ in range(_REFUND_PASSES):
        nxt = await _refund_for_campaign(session, owner_id, legs, wallet + int(refund))
        if nxt is None or abs(nxt - refund) < _REFUND_TOLERANCE:
            return nxt if nxt is not None else refund
        refund = nxt
    return refund


async def _refund_for_campaign(
    session: AsyncSession, owner_id: str, legs: list[Leg], budget: int,
) -> float | None:
    """The refund across a whole campaign, priced per leg.

    Each leg is on its own banner, so each has its own featured 4-stars and its own refund
    rate, and the budget is divided between them before either is priced.

    **Filled in spending order, not in proportion to the whole campaign's cost.** A campaign
    spends sequentially: with a small wallet every wish lands on the first leg's banner. The
    proportional split this replaces gave a 90-wish wallet 53 wishes on the character banner
    and 36 on the weapon banner — for a plan whose *first* goal averages 93.4 wishes, so 36 of
    them were priced on a banner the player cannot reach, and the refund came out 22 % low.

    It also stops at what the plan actually costs. A 2,000-wish wallet aimed at one C0 goal
    spends about 93 wishes, and pricing the refund over all 2,000 reported wishes back that
    nobody would ever earn.

    Returns None when **no** leg could be priced from the account, which is the signal to fall
    back to the caller's choice. A leg that cannot be priced — no banner named, or a banner the
    table does not know — consumes its share of the budget and earns nothing, which
    under-states rather than invents. **Both unpriceable cases are treated the same way**: they
    used to diverge, with a missing slug redistributing its spending onto the named banners
    (doubling the reported refund) while an unknown slug correctly dropped it.
    """
    if budget <= 0 or not any(leg.banner_slug for leg in legs):
        return None

    # Expected cost of each leg, from the ladder itself. Cheap: the plan is a few
    # convolutions and this runs once per refund pass.
    plan = plan_campaign(legs, budget=0)
    spent_by_slug: dict[str, float] = {}
    remaining = float(budget)
    previous = 0.0
    for milestone in plan.milestones:
        cost = milestone.average_wishes - previous
        previous = milestone.average_wishes
        if remaining <= 0:
            break
        spend = min(remaining, cost)
        remaining -= spend
        # An unslugged milestone still consumes the budget; it simply earns nothing.
        if milestone.banner_slug:
            spent_by_slug[milestone.banner_slug] = (
                spent_by_slug.get(milestone.banner_slug, 0.0) + spend
            )

    refund = 0.0
    priced = False
    for slug, spend in spent_by_slug.items():
        leg_refund = await _refund_from_account(session, owner_id, slug, int(spend))
        if leg_refund is not None:
            refund += leg_refund
            priced = True
    return refund if priced else None


async def _refund_from_account(
    session: AsyncSession, owner_id: str, banner_slug: str, pulls: int,
) -> float | None:
    """The exact refund for this account on this banner, or None if it cannot be computed.

    **None rather than a guess.** An unknown banner, or a roster that has said nothing about
    any 4-star, is a reason to fall back to the caller's tier and say so — not to invent an
    account.

    **The banner decides the kind, not the plan's first leg.** Reading it off `legs[0]` meant
    picking a weapon banner while the strategy happened to start on the character leg priced
    five *weapon* names as unowned *characters*; the mirror case threw away three real
    constellations. The row knows what it is.
    """
    row = (await session.execute(
        select(WishBanner).where(WishBanner.slug == banner_slug),
    )).scalar_one_or_none()
    if row is None:
        return None
    banner = BannerKind(row.kind)

    # **Owned 4-star characters only.** Without the rarity filter every 5-star the account
    # owns joined the pool a non-featured *4-star* draw spreads over, diluting it; without
    # the ownership filter a character explicitly marked not-owned still contributed, because
    # un-owning one keeps its stored constellation.
    rows = (
        await session.execute(
            select(Character.nanoka_id, Character.name, CharacterRosterEntry.constellation)
            .join(CharacterRosterEntry, CharacterRosterEntry.character_id == Character.id)
            .where(
                CharacterRosterEntry.owner_id == owner_id,
                CharacterRosterEntry.owned.is_(True),
                Character.rarity == Rarity.FOUR_STAR,
            ),
        )
    ).all()

    featured_names = set(row.featured_four)
    featured: list[int | None] = [None] * len(row.featured_four)
    roster: list[int | None] = []
    for nanoka_id, name, constellation in rows:
        # Sixteen Travelers share the name `Traveler` and fourteen mannequins share two more,
        # so keying by name collapses thirty rows to three and lets whichever the database
        # returned last win. Mannequins are not ownable characters at all.
        if is_mannequin(nanoka_id):
            continue
        if name in featured_names:
            featured[row.featured_four.index(name)] = constellation
        elif constellation is not None:
            # **An unknown constellation is left out, not passed through.** `None` means
            # "not owned" to `payout`, which gives the first copy away free — so forwarding a
            # NULL would understate exactly the accounts the column was added for.
            roster.append(constellation)

    if not roster and all(value is None for value in featured):
        return None

    return expected_refund(
        RefundInputs(
            banner=banner,
            # The weapon banner's featured 4-stars are weapons: a flat 2 apiece, no roster.
            featured=tuple(featured) if banner is BannerKind.CHARACTER else (),
            roster=tuple(roster),
        ),
        pulls,
    )


def _leg(target: WishTarget) -> Leg:
    return Leg(
        banner=target.banner,
        label=target.label,
        pity=target.pity,
        guaranteed=target.guaranteed,
        lost_fifty_fifties=target.lost_fifty_fifties,
        owned_copies=target.owned_copies,
        target_copies=target.target_copies,
        banner_slug=target.banner_slug,
    )


@router.get("/income", response_model=WishIncomeRead)
async def read_income(session: _Session, user: _User) -> WishIncomeRead:
    """Return wish income per game version, at the three spending tiers.

    Served from `wish_income`, which `scripts/refresh_wish_income.py` fills on a timer. This
    route never reaches the workbook: `app/` has one request-time fetch and a third-party
    spreadsheet on the request path would be a second.

    An empty store is **not** an error — it means the refresher has not run yet, and a page
    can say so. Inventing numbers to fill it would be worse.
    """
    rows = (
        await session.execute(select(WishIncome).order_by(WishIncome.major, WishIncome.minor))
    ).scalars().all()

    by_version: dict[str, dict[str, object]] = {}
    for row in rows:
        entry = by_version.setdefault(
            row.version, {"version": row.version, "is_estimate": row.is_estimate}
        )
        entry[row.tier] = row.wishes

    versions = [
        WishIncomeVersionRead(
            version=str(entry["version"]),
            is_estimate=bool(entry["is_estimate"]),
            f2p=float(entry.get("f2p", 0.0)),  # type: ignore[arg-type]
            welkin=float(entry.get("welkin", 0.0)),  # type: ignore[arg-type]
            welkin_bp=float(entry.get("welkin_bp", 0.0)),  # type: ignore[arg-type]
        )
        for entry in by_version.values()
    ]
    fetched_at = max((row.fetched_at for row in rows), default=None)
    return WishIncomeRead(
        versions=versions,
        fetched_at=fetched_at.isoformat() if fetched_at else None,
    )


class WishFeaturedItem(BaseModel):
    """A featured character or weapon, with whatever art the catalogue has for it."""

    name: str
    icon: str | None = Field(
        None,
        description=(
            "Catalogue basename, or null when the name does not resolve — a character newer "
            "than the pinned catalogue. **Null renders nothing rather than a broken image**, "
            "which is why banners store names and resolve here rather than storing ids."
        ),
    )
    owned_copies: int | None = Field(
        None,
        description=(
            "Constellations of this character the caller already holds, from their roster — "
            "so picking a goal off a banner does not ask them to retype what an import "
            "already knows. **Null is 'nobody has said', not zero**: an account that never "
            "imported, a character it has no row for, a row written before the column "
            "existed, or a weapon (there is no weapon roster, so refinement cannot be read)."
        ),
    )


class WishBannerRead(BaseModel):
    """One banner run, for the picker."""

    slug: str
    name: str
    kind: str
    starts_at: str | None
    ends_at: str | None
    featured_five: list[WishFeaturedItem]
    featured_four: list[WishFeaturedItem]
    signature_banner: str | None = Field(
        None,
        description=(
            "The concurrent *weapon* banner's slug — where this character's signature weapon "
            "is pulled. **Resolved here, not by the client.** The picker holds one page of "
            "banners and a phase's weapon banner is not guaranteed to be on it: over the "
            "committed table, 2 of the 6 character banners on the default first page have "
            "their partner at index 8. A client filtering its own page therefore reported "
            "*no weapon banner* — indistinguishable from a phase that genuinely had none, "
            "except that no phase does, so the null was always a pagination artefact."
        ),
    )
    alongside: list[str] = Field(
        default_factory=list,
        description=(
            "Slugs of the banners running at the same time — what makes a weapon somebody's "
            "signature. Picking a character can therefore also select the weapon banner "
            "running beside them, which is the only way the weapon leg gets priced at the "
            "weapon banner's own 4-star economics. **It does not say which of a weapon "
            "banner's two 5-stars belongs to which character**; nothing in the source does, "
            "and inferring it from list order would be a guess."
        ),
    )


class WishBannerList(BaseModel):
    """Banners newest first, with how many there are in total."""

    banners: list[WishBannerRead]
    total: int
    fetched_at: str | None


@router.get("/banners", response_model=WishBannerList)
async def list_banners(
    session: _Session,
    user: _User,
    kind: BannerKind | None = None,
    limit: int = Query(BANNER_PAGE, ge=1, le=MAX_BANNER_PAGE),
    offset: int = Query(0, ge=0),
) -> WishBannerList:
    """Banners newest first, paged.

    **Paged rather than capped.** `CLAUDE.md` records the planner's materials tab being
    "fixed" by truncating a 514-row list at 80, which made the page short by hiding the data.
    `total` is sent so the page can say how many more there are rather than guess.
    """
    query = select(WishBanner)
    if kind is not None:
        query = query.where(WishBanner.kind == kind.value)

    # Counted, not materialised: `len(all())` loaded all 291 rows with their JSONB on every
    # eight-row page.
    total = int(
        (await session.execute(
            select(func.count()).select_from(query.subquery()),
        )).scalar_one()
    )
    rows = (
        await session.execute(
            # **NULLs last.** `starts_at` is nullable and Postgres sorts NULLs *first* under
            # DESC, so a wiki page missing `time_start` would take the picker's opening eight
            # slots ahead of every real banner.
            query.order_by(WishBanner.starts_at.desc().nulls_last(), WishBanner.slug.desc())
            .offset(offset)
            .limit(limit),
        )
    ).scalars().all()
    # Resolved here rather than stored: a name that has no catalogue row renders nothing,
    # and a stale id would render nothing *silently* (#263).
    wanted = {n for row in rows for n in row.featured_five + row.featured_four}
    art: dict[str, str | None] = {}
    if wanted:
        for table in (Character, Weapon):
            art.update(
                (name, icon)
                for name, icon in (
                    await session.execute(
                        select(table.name, table.icon).where(table.name.in_(wanted)),
                    )
                ).all()
            )

    # **The caller's own constellations, by name.** The same resolve-by-name the art uses,
    # for the same reason: a stored id would be the row id of whichever database the capture
    # ran against, which is #263's silent miss. Owned characters only — an un-owned row keeps
    # its stored constellation, and reporting it would offer a goal from a character the user
    # has said they do not have.
    held: dict[str, int] = {}
    if wanted:
        held = dict(
            (
                await session.execute(
                    select(Character.name, CharacterRosterEntry.constellation)
                    .join(
                        CharacterRosterEntry,
                        CharacterRosterEntry.character_id == Character.id,
                    )
                    .where(
                        CharacterRosterEntry.owner_id == str(user.id),
                        CharacterRosterEntry.owned.is_(True),
                        CharacterRosterEntry.constellation.isnot(None),
                        Character.name.in_(wanted),
                    )
                )
            ).all(),
        )

    # **The same duplicate-name guard `_refund_from_account` applies forty lines up.** Sixteen
    # Travelers share one name and fourteen practice mannequins share two more, so keying by
    # name lets whichever row the database returned last win. Harmless today only because no
    # banner features those names — which is exactly the kind of thing that stops being true
    # without anyone noticing, so it is filtered rather than relied upon.
    held = {
        name: constellation
        for name, constellation in held.items()
        if name not in _AMBIGUOUS_NAMES
    }

    # Which of the concurrent banners is the weapon one. Resolved over the whole table rather
    # than the page, because the page is exactly what the client could already see.
    partners = {slug for row in rows for slug in (row.alongside or [])}
    weapon_slugs: set[str] = set()
    if partners:
        weapon_slugs = {
            slug
            for (slug,) in (
                await session.execute(
                    select(WishBanner.slug).where(
                        WishBanner.slug.in_(partners), WishBanner.kind == "weapon",
                    ),
                )
            ).all()
        }

    def signature_of(row: WishBanner) -> str | None:
        if row.kind != "character":
            return None
        # **One weapon banner a phase**, so this is unambiguous — unlike the reverse, where a
        # weapon banner runs beside two character banners and carries two weapons, and nothing
        # in the source says which is whose.
        return next((s for s in (row.alongside or []) if s in weapon_slugs), None)

    def items(names: list[str]) -> list[WishFeaturedItem]:
        return [
            WishFeaturedItem(name=n, icon=art.get(n), owned_copies=held.get(n))
            for n in names
        ]

    # Over the table, not over the page: taken from `rows` it changed as the user clicked
    # "show more", and read null on any page past the end of a populated table.
    latest = (await session.execute(select(func.max(WishBanner.fetched_at)))).scalar_one_or_none()
    return WishBannerList(
        banners=[
            WishBannerRead(
                slug=row.slug, name=row.name, kind=row.kind,
                starts_at=row.starts_at, ends_at=row.ends_at,
                featured_five=items(list(row.featured_five)),
                featured_four=items(list(row.featured_four)),
                signature_banner=signature_of(row),
                alongside=list(row.alongside or []),
            )
            for row in rows
        ],
        total=total,
        fetched_at=latest.isoformat() if latest else None,
    )


@router.get("/limits", response_model=dict)
async def read_limits(user: _User) -> dict:
    """Static facts the page needs to build its controls without hardcoding them."""
    return {
        "primogems_per_wish": primogems_per_wish(),
        "max_constellation": MAX_CONSTELLATION,
        "max_refinement": MAX_REFINEMENT,
        "banners": {
            banner.value: {
                "hard_pity": rates_for(banner).hard_pity,
                "published_worst_case": rates_for(banner).published_worst_case,
                "capturing_radiance": rates_for(banner).capturing_radiance,
            }
            for banner in BannerKind
        },
        # Offering "guaranteed with 0 losses" would let the page build a state the service
        # refuses; the control has to know that here rather than discover it in a 422.
        "max_lost_fifty_fifties": MAX_LOST_FIFTY_FIFTIES,
        "strategies": [strategy.value for strategy in Strategy],
        "starglitter_refund_tiers": refund_tiers(),
        # The page builds its dropdown from this, so the sentinel is not a
        # string the client spells for itself.
        "account_refund": ACCOUNT_REFUND,
        "banner_page": BANNER_PAGE,
    }
