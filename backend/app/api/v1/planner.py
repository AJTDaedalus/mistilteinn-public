"""The leveling planner: what it costs to take a character and weapon where you want them.

`docs/DESIGN_planner.md`. Two routes — the options a plan can be built from, and the plan.

**A plan is a `POST` that writes nothing.** It carries a nested body (per-talent targets, a
list of crafting characters) that would not survive a query string, and it is expensive enough
to be worth not putting in a URL a browser will pre-fetch. Nothing is stored.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.build import Build
from app.models.user import User
from app.models.weapon import OwnedWeapon
from app.services.planner import service
from app.services.planner.costs import PlanError, Progress
from app.services.planner.economy import economy

router = APIRouter(prefix="/planner", tags=["planner"])

_Session = Annotated[AsyncSession, Depends(get_db)]
_User = Annotated[User, Depends(get_current_user)]


# -- options ---------------------------------------------------------------------------


class TalentOption(BaseModel):
    """One levelable talent. An alternate sprint has no cost ladder and is not offered."""

    talent_id: str
    name: str
    talent_type: str
    icon: str | None = None


class BuildOption(BaseModel):
    """A build the user could read a starting state from.

    **A build may be hypothetical** — this app lets you gear a character you do not own — so
    the planner names which build it read and shows the levels it took, rather than quietly
    treating a scenario as the account's truth.
    """

    build_id: str
    name: str | None = None
    character_level: int
    ascension_phase: int
    talent_levels: dict[str, int]
    weapon_id: str | None = None
    weapon_level: int
    #: **Null when this account holds no physical copy for the build.** `builds` has a
    #: `weapon_level` and no weapon ascension column, and an earlier version substituted the
    #: *character's* phase here — so a build at 90/6 holding a level-20 weapon prefilled
    #: "weapon from 20/6", `ascension_bill(6, 6)` charged nothing, and all six weapon
    #: ascension bills vanished from the plan without a word. The real value lives on
    #: `owned_weapons`; when there is no row, the page asks rather than guesses.
    weapon_ascension: int | None = None


class OwnedWeaponOption(BaseModel):
    """One physical copy the user owns. Duplicates are separate rows, as the game has them."""

    owned_weapon_id: str
    weapon_id: str | None
    level: int
    ascension: int
    refinement: int


class CraftingBonusRead(BaseModel):
    """A character whose passive changes what crafting costs."""

    character_id: str
    character_name: str
    passive_name: str
    effect: str
    chance: float
    classes: list[str]
    #: False for refunds and bonus materials: the chance is published and the size is not, so
    #: applying them would move a real number by an invented amount.
    applicable: bool
    description: str


class PlannerOptions(BaseModel):
    """Everything the page needs to build a request."""

    level_caps: dict[int, int]
    talents: list[TalentOption] = Field(default_factory=list)
    builds: list[BuildOption] = Field(default_factory=list)
    owned_weapons: list[OwnedWeaponOption] = Field(default_factory=list)
    bonuses: list[CraftingBonusRead] = Field(default_factory=list)
    #: Sources that cost resin at a rate nobody publishes — `weekly_boss`, `ley_line_exp`,
    #: `ley_line_mora`. Surfaced so the page can explain a blank resin cell rather than
    #: leaving the user to guess.
    uncurated_sources: list[str] = Field(default_factory=list)


# -- plan ------------------------------------------------------------------------------


class ProgressIn(BaseModel):
    """A level and an ascension phase. They move independently."""

    level: int = Field(ge=1, le=90)
    ascension: int = Field(ge=0, le=6)


class TalentTargetIn(BaseModel):
    """Where one talent is and where it should end up."""

    talent_id: str
    current: int = Field(ge=1, le=15)
    target: int = Field(ge=1, le=15)


class PlanRequest(BaseModel):
    """One character, optionally one weapon, and where each should end up."""

    character_id: str
    character_from: ProgressIn
    character_to: ProgressIn
    talents: list[TalentTargetIn] = Field(default_factory=list)
    weapon_id: str | None = None
    weapon_from: ProgressIn | None = None
    weapon_to: ProgressIn | None = None
    #: Characters whose crafting passive should be applied. **At most one per material
    #: class matters**: only one character crafts a given batch, so `craft_multiplier` takes
    #: the best rather than stacking. Sending more is not an error, it is just not additive.
    bonus_character_ids: list[str] = Field(default_factory=list)
    #: Mora the account holds, when the user has told us.
    #:
    #: **Not in a GOOD export.** No scanner reports a mora balance, so unlike every other
    #: quantity on this page it cannot be imported and has to be typed. `None` means "not
    #: told", which the response distinguishes from zero: a plan that says you are 3M short
    #: when you never said what you have is a worse answer than one that says nothing.
    mora_owned: int | None = Field(default=None, ge=0)


class ResinEstimateRead(BaseModel):
    """Expected resin for one material, and the tier it is actually farmed at."""

    root_id: int
    source_type: str
    resin_per_run: int
    expected_per_run: float
    expected_runs: float
    expected_resin: float
    resin_per_unit: float
    curated: bool


class HistogramBinRead(BaseModel):
    """One bar of the resin distribution: `[low, high)` holding `probability`."""

    low: int
    high: int
    probability: float


class ResinTotalRead(BaseModel):
    """A section's resin: the average, the shape, and everything with no number."""

    expected: float
    #: Resin-farmable, rate not supplied.
    unpriced: list[int]
    #: No resin cost at all — gems, common enemy drops, local specialties.
    not_farmable: list[int]
    #: Non-material costs with no rate: `"mora"`, `"character EXP"`.
    unpriced_sources: list[str]
    histogram: list[HistogramBinRead]


class MaterialLineRead(BaseModel):
    """One material row."""

    material_id: int
    name: str
    icon: str | None
    rarity: int
    required: int
    owned: int
    #: Units craftable from surplus lower in the same family, 3:1 in almost every recipe.
    #:
    #: **Separate from `owned`, and the separation is the honesty.** Holding three Philosophies
    #: and being able to make nine more from spare Teachings is not the same as holding twelve:
    #: the nine cost mora and a bench, and the section's mora already includes that.
    from_surplus: int = 0
    still_needed: int
    resin: ResinEstimateRead | None
    resin_status: str
    domain_days: list[str]


class ExpBookRead(BaseModel):
    """One EXP denomination and how many of it the shortfall needs.

    Carries its own name and icon because these are **not** material rows: EXP is a pool that
    `exp_bill` has already netted against stock, so listing them in the materials table
    subtracted the same stock twice. They are rendered from the EXP line instead, and need
    their own art to do it.
    """

    material_id: int
    count: int
    name: str
    icon: str | None = None


class ExpBillRead(BaseModel):
    """The EXP half of levelling. `mora` is null while the divisor is uncurated — not zero."""

    exp_required: int
    exp_owned: int
    exp_short: int
    #: An object list rather than a positional pair: a `[number, number]` tuple in the schema
    #: generates a fixed-length client type that a JSON array cannot satisfy, and the names
    #: are worth having anyway.
    books: list[ExpBookRead]
    mora: int | None


class SectionRead(BaseModel):
    """One bill."""

    key: str
    label: str
    mora: int | None
    materials: list[MaterialLineRead]
    resin: ResinTotalRead
    exp: ExpBillRead | None


class MoraRead(BaseModel):
    """The plan's mora, and the shortfall when the user has said what they hold."""

    #: Null when any section could not be priced, matching `SectionRead.mora`.
    required: int | None
    #: What the user typed, or null when they did not.
    owned: int | None = None
    #: `required - owned`, floored at zero. Null when either side is unknown, because a
    #: shortfall computed against a number nobody gave is a number nobody should act on.
    short: int | None = None


class PlanRead(BaseModel):
    """A whole plan."""

    character_name: str
    character_icon: str | None
    weapon_name: str | None
    weapon_icon: str | None
    sections: list[SectionRead]
    total: SectionRead
    bonuses_applied: list[CraftingBonusRead]
    #: True when a talent target above 10 was asked for. Those levels come free from C3/C5,
    #: and the page says so rather than rendering an empty list.
    talent_free_levels: bool
    #: The two-point per-run model behind `histogram`, restated for whoever renders it.
    histogram_note: str
    #: What the whole plan costs in mora, against what the user says they hold.
    mora: MoraRead
    #: True when this account has no stored materials at all.
    #:
    #: **"You hold none" and "you never imported an inventory" are different facts** and the
    #: page has to be able to say which. Nothing records whether a past import carried a
    #: `materials` map, so an empty stock is indistinguishable from an unimported one — and
    #: reporting the second as the first shows a user a bill for materials they already have.
    #: Reported here so the page can say so instead of quietly totalling zero.
    stock_is_empty: bool


_HISTOGRAM_NOTE = (
    "The average is derived from the drop rates the game publishes. The spread is modelled: "
    "no table resolves a drop id, so a run is assumed to yield floor or ceil of its mean. "
    "That is the narrowest distribution with the right average, so real farming varies more "
    "than this shows."
)


def _bonus_read(bonus: object) -> CraftingBonusRead:
    return CraftingBonusRead(
        character_id=bonus.character_id,  # type: ignore[attr-defined]
        character_name=bonus.character_name,  # type: ignore[attr-defined]
        passive_name=bonus.passive_name,  # type: ignore[attr-defined]
        effect=bonus.effect.value,  # type: ignore[attr-defined]
        chance=bonus.chance,  # type: ignore[attr-defined]
        classes=sorted(c.value for c in bonus.classes),  # type: ignore[attr-defined]
        applicable=bonus.applicable,  # type: ignore[attr-defined]
        description=bonus.description,  # type: ignore[attr-defined]
    )


@router.get("/options", response_model=PlannerOptions)
async def planner_options(
    session: _Session,
    user: _User,
    character_id: Annotated[str | None, Query()] = None,
) -> PlannerOptions:
    """What a plan can be built from, optionally narrowed to one character's talents."""
    eco = economy()
    talents: list[TalentOption] = []
    builds: list[BuildOption] = []
    if character_id:
        talents = [
            TalentOption(
                talent_id=talent.id,
                name=talent.name,
                talent_type=talent.talent_type.value,
                icon=talent.icon,
            )
            for talent in await service.talents_of(session, character_id)
        ]
        rows = list(
            (
                await session.execute(
                    select(Build).where(
                        Build.owner_id == user.id, Build.character_id == character_id,
                    ),
                )
            ).scalars(),
        )
        # The physical copy equipped to each build, which is where a weapon's ascension phase
        # actually lives. One query for all of them rather than one per build.
        equipped = {
            row.build_id: row
            for row in (
                await session.execute(
                    select(OwnedWeapon).where(
                        OwnedWeapon.owner_id == user.id,
                        OwnedWeapon.build_id.in_([build.id for build in rows] or [""]),
                    ),
                )
            ).scalars()
        }
        builds = [
            BuildOption(
                build_id=build.id,
                name=build.name,
                character_level=build.character_level,
                ascension_phase=build.ascension_phase,
                talent_levels=build.talent_levels or {},
                weapon_id=build.weapon_id,
                weapon_level=build.weapon_level,
                weapon_ascension=(
                    equipped[build.id].ascension if build.id in equipped else None
                ),
            )
            for build in rows
        ]

    owned = (
        await session.execute(select(OwnedWeapon).where(OwnedWeapon.owner_id == user.id))
    ).scalars()
    return PlannerOptions(
        level_caps=eco.character_level_caps,
        talents=talents,
        builds=builds,
        owned_weapons=[
            OwnedWeaponOption(
                owned_weapon_id=row.id,
                weapon_id=row.weapon_id,
                level=row.level,
                ascension=row.ascension,
                refinement=row.refinement,
            )
            for row in owned
        ],
        bonuses=[_bonus_read(b) for b in await service.available_bonuses(session)],
        uncurated_sources=eco.uncurated_sources(),
    )


@router.post("/plan", response_model=PlanRead)
async def create_plan(payload: PlanRequest, session: _Session, user: _User) -> PlanRead:
    """Price a plan. Writes nothing."""
    try:
        plan = await service.build_plan(
            session,
            user.id,
            character_id=payload.character_id,
            character_from=Progress(**payload.character_from.model_dump()),
            character_to=Progress(**payload.character_to.model_dump()),
            talents={t.talent_id: (t.current, t.target) for t in payload.talents},
            weapon_id=payload.weapon_id,
            weapon_from=(
                Progress(**payload.weapon_from.model_dump()) if payload.weapon_from else None
            ),
            weapon_to=Progress(**payload.weapon_to.model_dump()) if payload.weapon_to else None,
            bonus_character_ids=payload.bonus_character_ids,
            mora_owned=payload.mora_owned,
        )
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    required = plan.total.mora
    # **`short` needs both sides.** A shortfall against a number nobody gave is a number nobody
    # should act on, and a plan whose mora could not be priced at all has nothing to subtract
    # from — `SectionRead.mora` is already nullable for exactly that case.
    short = (
        max(0, required - payload.mora_owned)
        if required is not None and payload.mora_owned is not None
        else None
    )
    return PlanRead(
        character_name=plan.character_name,
        character_icon=plan.character_icon,
        weapon_name=plan.weapon_name,
        weapon_icon=plan.weapon_icon,
        sections=[_section_read(s) for s in plan.sections],
        total=_section_read(plan.total),
        bonuses_applied=[_bonus_read(b) for b in plan.bonuses_applied],
        talent_free_levels=plan.talent_free_levels,
        histogram_note=_HISTOGRAM_NOTE,
        mora=MoraRead(required=required, owned=payload.mora_owned, short=short),
        stock_is_empty=plan.stock_is_empty,
    )


def _section_read(section: service.Section) -> SectionRead:
    return SectionRead(
        key=section.key,
        label=section.label,
        mora=section.mora,
        materials=[
            MaterialLineRead(
                material_id=line.material_id,
                name=line.name,
                icon=line.icon,
                rarity=line.rarity,
                required=line.required,
                owned=line.owned,
                from_surplus=line.from_surplus,
                still_needed=line.still_needed,
                resin=(
                    ResinEstimateRead(
                        root_id=line.resin.root_id,
                        source_type=line.resin.source_type,
                        resin_per_run=line.resin.resin_per_run,
                        expected_per_run=line.resin.expected_per_run,
                        expected_runs=line.resin.expected_runs,
                        expected_resin=line.resin.expected_resin,
                        resin_per_unit=line.resin.resin_per_unit,
                        curated=line.resin.curated,
                    )
                    if line.resin
                    else None
                ),
                resin_status=line.resin_status,
                domain_days=line.domain_days,
            )
            for line in section.materials
        ],
        resin=ResinTotalRead(
            expected=section.resin.expected,
            unpriced=section.resin.unpriced,
            not_farmable=section.resin.not_farmable,
            unpriced_sources=section.resin.unpriced_sources,
            histogram=[
                HistogramBinRead(low=b.low, high=b.high, probability=b.probability)
                for b in section.resin.histogram
            ],
        ),
        exp=(
            ExpBillRead(
                exp_required=section.exp.exp_required,
                exp_owned=section.exp.exp_owned,
                exp_short=section.exp.exp_short,
                books=[
                    ExpBookRead(
                        material_id=material_id,
                        count=count,
                        name=book.name,
                        icon=book.icon,
                    )
                    for material_id, count, book in section.exp_books
                ],
                mora=section.exp.mora,
            )
            if section.exp
            else None
        ),
    )
