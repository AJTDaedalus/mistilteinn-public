"""Assemble a plan: load a character, a weapon and a user's stock, and price the difference.

`docs/DESIGN_planner.md`. The arithmetic is in `costs.py` and `resin.py`; this module is the
part that talks to the database and decides what a *section* is.

Four sections, because the owner asked to see them apart: **levels** (EXP and its books),
**ascension** (the six phases), **talents** (three bills, one per talent), and **weapon**
(that weapon's levels and phases together). The cumulative summary is the four re-added, and
it is computed from the merged material needs rather than by summing the sections' resin —
two sections needing the same book family are farming one domain, and adding their run counts
would bill it twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.character import AscensionPassive, Character, Talent
from app.models.planner import (
    CharacterAscensionCost,
    CharacterTalentCost,
    Material,
    WeaponAscensionCost,
)
from app.models.weapon import Weapon
from app.repositories.user_material import UserMaterialRepository
from app.services.planner import costs, resin
from app.services.planner.costs import PlanError, Progress
from app.services.planner.crafting import CraftingBonus, MaterialClass, classify, craft_multiplier
from app.services.planner.economy import Economy, MaterialSource, economy

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

#: Material id prefixes, derived from which cost table each one appears in (see
#: `docs/RESEARCH_leveling_planner_data.md`). `104` in a talent bill is a talent book; `114`
#: is a weapon ascension material. `112` (common drops) and `113` (boss drops) appear in both
#: and belong to neither crafting category, so no bonus touches them.
#: Talent books. **`1043`, not `104`**: the wider prefix also covers `1041` elemental gems and
#: `1040` EXP items, neither of which any crafting passive names.
#: Mora's icon. The snapshot carries no name or icon for mora, since it is a currency rather
#: than a drop, so the plan's mora row supplies its own. `scripts/download_icons.py` reads this
#: constant: the art is not committed, and an icon no catalogue row names is one the downloader
#: would otherwise never fetch.
MORA_ICON = "UI_ItemIcon_202"

_TALENT_BOOK_PREFIX = "1043"
_WEAPON_MATERIAL_PREFIX = "114"
#: Monster drops, the "Character and Weapon Enhancement Materials" category. They appear in
#: **both** bills — talent levelling and character ascension each want them — so unlike talent
#: books this one is not gated on which bill is being built.
_ENHANCEMENT_PREFIX = "112"


@dataclass
class MaterialLine:
    """One material a plan needs, and what the user already holds of it."""

    material_id: int
    name: str
    icon: str | None
    rarity: int
    required: int
    owned: int
    still_needed: int
    resin: resin.ResinEstimate | None
    #: One of four, and they mean genuinely different things:
    #:
    #: * `"priced"` — `resin` carries a number.
    #: * `"satisfied"` — you already hold enough; there is nothing to farm.
    #: * `"not_farmable"` — no resin cost at all (a gem, a common drop, a local specialty).
    #: * `"unknown"` — it costs resin at a rate nobody publishes.
    #:
    #: **`satisfied` exists because looking at the page found it missing.** A material with
    #: nothing outstanding fell through to `unknown` and rendered a "?", which claims the rate
    #: is not known — false, and about the one row the user least needs to worry about.
    resin_status: str
    #: Weekdays this material's domain is open, `[]` when it is not a domain drop.
    domain_days: list[str]
    #: Units of this material craftable from surplus **below** it in the same family.
    #:
    #: Kept apart from `owned` on purpose: folding them together would tell a user they hold
    #: twelve Philosophies when they hold three and can make nine, and the nine cost mora and a
    #: trip to a crafting bench.
    from_surplus: int = 0
    #: Whether `owned` came from `user_materials` — and so whether correcting it on the page
    #: would change anything.
    #:
    #: **False for the mora row only, and that row is why the flag exists.** Its `owned` is
    #: the balance the user typed into the plan request, because GOOD carries no currency
    #: field and nothing stores one. An editable cell there would write a `user_materials`
    #: row nothing reads, re-price, and come back showing the typed number again — an edit
    #: that appears to save and silently does nothing, which is the exact failure this whole
    #: surface exists to remove.
    stock_backed: bool = True


@dataclass
class Section:
    """One bill: its materials, its mora and its resin."""

    key: str
    label: str
    #: `None` when the mora cannot be known — levelling mora depends on the uncurated
    #: mora-per-EXP divisor, and `None` is not zero.
    mora: int | None
    materials: list[MaterialLine] = field(default_factory=list)
    resin: resin.ResinTotal = field(default_factory=resin.ResinTotal)
    exp: costs.ExpBill | None = None
    #: `(material id, count, catalogue row)` for the EXP denominations the shortfall needs.
    #: Resolved here rather than in the API so the route does not re-query for names.
    exp_books: list[tuple[int, int, Material]] = field(default_factory=list)


@dataclass
class Plan:
    """A whole plan: the sections, the cumulative summary and what could not be priced."""

    character_name: str
    character_icon: str | None
    weapon_name: str | None
    weapon_icon: str | None
    sections: list[Section]
    total: Section
    bonuses_applied: list[CraftingBonus]
    bonuses_available: list[CraftingBonus]
    #: Set when a talent target was asked for above 10. Rendered as a note, not an empty list.
    talent_free_levels: bool = False
    #: True when this account has no stored materials at all.
    #:
    #: **Not the same as holding none.** Nothing records whether a past GOOD import carried a
    #: `materials` map — `store_good_import` distinguishes "the scanner did not report" from
    #: "the account reported nothing" at import time and keeps neither — so an empty stock and
    #: an unimported one look identical here. A page that totals zero without saying which
    #: shows a user a bill for materials they may already have, which is what was reported
    #: about the character EXP books.
    stock_is_empty: bool = False


def _class_of(material_id: int, in_talent_bill: bool) -> MaterialClass | None:
    text = str(material_id)
    if text.startswith(_TALENT_BOOK_PREFIX) and in_talent_bill:
        return MaterialClass.TALENT
    if text.startswith(_WEAPON_MATERIAL_PREFIX):
        return MaterialClass.WEAPON_ASCENSION
    if text.startswith(_ENHANCEMENT_PREFIX):
        return MaterialClass.ENHANCEMENT
    return None


def _family_chain(eco: Economy, material_id: int) -> list[int]:
    """The crafting ladder under `material_id`, root first, ending at it.

    Cycle-safe for the same reason `craft_root` is: a malformed tree must not hang a request.
    """
    chain = [material_id]
    seen = {material_id}
    current = material_id
    while (step := eco.craft_step(current)) is not None and step.input not in seen:
        chain.append(step.input)
        seen.add(step.input)
        current = step.input
    chain.reverse()
    return chain


def _convert_surplus(
    eco: Economy,
    needs: Mapping[int, int],
    stock: Mapping[int, int],
    craft_multipliers: Mapping[int, float],
) -> tuple[dict[int, int], int]:
    """`({material id: extra units craftable from surplus below it}, mora that costs)`.

    **Excess of a lower rarity is not dead stock.** Gems, monster drops, talent books and
    weapon ascension materials all convert upward 3:1, so a player holding thirty Teachings and
    needing six Philosophies is not short six Philosophies. Netting each tier against its own
    stock and stopping there — which is what this did — bills them for materials they can make
    from what is already in the bag.

    **Bottom-up, once per family.** A tier's own requirement is satisfied before anything flows
    up, because spending Guides on Philosophies you do not need in order to be short of Guides
    you do is not a trade anybody would make. Two needed materials in one family share a single
    pass, so no unit of stock is spent twice.

    Only upward: the game publishes no recipe that breaks a higher tier down, so a surplus of
    Philosophies cannot pay for Teachings.
    """
    extra: dict[int, int] = {}
    mora = 0
    # One pass per family, keyed by root, so two needed tiers of one ladder cannot both spend
    # the same lower-tier stock.
    families: dict[int, list[int]] = {}
    for material_id in needs:
        chain = _family_chain(eco, material_id)
        root = chain[0]
        # The longest chain wins: it is the one that reaches every tier the others do.
        if len(chain) > len(families.get(root, ())):
            families[root] = chain

    for chain in families.values():
        carried = 0
        for index, material_id in enumerate(chain):
            available = stock.get(material_id, 0) + carried
            if carried:
                extra[material_id] = extra.get(material_id, 0) + carried
            spent = min(available, needs.get(material_id, 0))
            surplus = available - spent
            if index + 1 >= len(chain) or surplus <= 0:
                carried = 0
                continue
            step = eco.craft_step(chain[index + 1])
            if step is None or step.input_count <= 0:
                carried = 0
                continue
            batches = surplus // step.input_count
            mora += batches * step.mora
            # The crafting passive applies to a conversion exactly as it does to farming: a
            # batch is worth `craft_multiplier` outputs. Floored, because a fractional
            # Philosophy is not a thing you can hold.
            multiplier = craft_multipliers.get(chain[index + 1], 1.0)
            carried = int(batches * step.output_count * multiplier)
    return extra, mora


def _line(
    material_id: int,
    catalogue: Mapping[int, Material],
    eco: Economy,
    *,
    name: str,
    icon: str | None = None,
    required: int,
    owned: int,
    still: int,
    stock_backed: bool = True,
) -> MaterialLine:
    """A material row for something that is not farmed per-unit: EXP books, mora.

    `resin` is null and the status is `not_farmable` **not because they cost nothing** — both
    come off ley lines — but because their resin is already priced as a pool by
    `resin.total`, and a per-unit estimate here would bill it a second time.
    """
    row = catalogue.get(material_id)
    return MaterialLine(
        material_id=material_id,
        name=row.name if row else (eco.name(material_id) or name),
        icon=row.icon if row else (eco.icon(material_id) or icon),
        rarity=row.rarity if row else (eco.rarity(material_id) or 0),
        required=required,
        owned=owned,
        still_needed=still,
        resin=None,
        resin_status="satisfied" if still == 0 else "not_farmable",
        domain_days=[],
        stock_backed=stock_backed,
    )


def _append_exp_rows(
    section: Section,
    eco: Economy,
    exp: costs.ExpBill | None,
    exp_items: Sequence[costs.ExpItem],
    stock: Mapping[int, int],
    catalogue: Mapping[int, Material],
) -> None:
    """EXP as books in the materials table, on the same three columns as everything else.

    **The books you already hold are spent first, largest denomination down.** That is the one
    thing that makes the row arithmetic true: `Remaining = Required - Owned`.

    The first version split the *whole* requirement from scratch and put your stock beside it,
    which produced "Required 418, Owned 204, Remaining 0" and was reported as a bug — correctly.
    It was defensible only by explaining that EXP is a pool and the two numbers were different
    decompositions, and a row that needs a paragraph to stop looking wrong is wrong.

    Allocating held books first gives 204 Hero's Wit against 204 owned and 857 Adventurer's
    Experience against 860, which needs no explanation. Only what is genuinely short is topped
    up, by `books_for`, which is where "favour the higher rarity, fill the gap with lower"
    still applies.
    """
    if exp is None or not exp_items or exp.exp_required <= 0:
        return
    ordered = sorted(exp_items, key=lambda entry: entry.exp, reverse=True)

    outstanding = exp.exp_required
    used: dict[int, int] = {}
    for item in ordered:
        held = stock.get(item.id, 0)
        if outstanding <= 0 or held <= 0:
            continue
        # Ceiling, because a book is spent whole: the last one covers whatever is left and the
        # overflow is wasted, which is what happens at the altar too.
        wanted = -(-outstanding // item.exp)
        take = min(held, wanted)
        used[item.id] = take
        outstanding -= take * item.exp

    extra = dict(costs.books_for(max(0, outstanding), exp_items))
    for item in ordered:
        required = used.get(item.id, 0) + extra.get(item.id, 0)
        if required <= 0:
            continue
        section.materials.append(
            _line(
                item.id, catalogue, eco,
                name=str(item.id),
                required=required,
                owned=stock.get(item.id, 0),
                still=extra.get(item.id, 0),
            ),
        )


def _append_mora_row(
    section: Section,
    eco: Economy,
    mora: int | None,
    mora_owned: int | None,
    catalogue: Mapping[int, Material],
) -> None:
    """Mora as a row, on the same three columns as everything else.

    **No `Crafted` for it, and none for the EXP books either** — nothing converts into mora.
    The column simply reads as absent for these rows.

    An untyped balance counts as zero, which reads as "you need all of it". That is the
    conservative answer and the input to correct it is at the top of the same page.
    """
    if mora is None or mora <= 0:
        return
    owned = mora_owned or 0
    section.materials.append(
        _line(
            eco.mora_item_id, catalogue, eco,
            name="Mora",
            # The snapshot carries no name or icon for mora — it is a currency rather than a
            # drop — so the row supplies both instead of rendering a nameless gap.
            icon=MORA_ICON,
            required=mora,
            # Not stock: `user_materials` has no mora row and never will.
            stock_backed=False,
            # **Not clamped to `required`.** It was `min(owned, mora)`, which kept the
            # subtraction non-negative by reporting a balance the user does not have: told
            # eleven million against a bill of five, the row said they owned five. The
            # shortfall is already floored at zero, so the clamp bought nothing and cost the
            # one number on the row the user supplied themselves.
            owned=owned,
            still=max(0, mora - owned),
        ),
    )


def _rows_by_key(rows: Sequence[Any], key: str) -> dict[int, tuple[int, list]]:
    return {getattr(row, key): (row.mora, row.items) for row in rows}


def _book_ids(*bills: costs.ExpBill | None) -> set[int]:
    """The EXP denominations any bill names, so their icons and names can be looked up."""
    return {
        material_id
        for bill in bills
        if bill is not None
        for material_id, _ in bill.books
    }


async def _load_catalogue(session: AsyncSession, ids: set[int]) -> dict[int, Material]:
    if not ids:
        return {}
    result = await session.execute(select(Material).where(Material.id.in_(ids)))
    return {row.id: row for row in result.scalars()}


def _build_section(
    key: str,
    label: str,
    needs: Mapping[int, int],
    mora: int | None,
    stock: Mapping[int, int],
    catalogue: Mapping[int, Material],
    *,
    exp: costs.ExpBill | None = None,
    exp_items: Sequence[costs.ExpItem] = (),
    character_exp: int = 0,
    craft_multipliers: Mapping[int, float] | None = None,
    mora_owned: int | None = None,
    eco: Economy,
) -> Section:
    """Turn `{material id: required}` into a rendered section, net of what is held.

    **EXP denominations are never in `needs`.** They are a pool, not per-item stock, and
    `exp_bill` has already netted them off — so listing the books it returned as material rows
    subtracted the same stock a second time and reported "satisfied" for books the user still
    had to farm. They are rendered from `exp.books` instead, and priced through
    `character_exp`, which is the unit a ley line actually yields.

    `eco` is the price list *with the catalogue's rarities* (`Economy.with_rarities`), so a
    boss material newer than the snapshot is still placed at the right boss.
    """
    section = Section(key=key, label=label, mora=mora, exp=exp)
    # **Excess of a lower rarity converts upward 3:1** — gems, monster drops, talent books and
    # weapon ascension materials all do — so a tier's shortfall is not `required - owned`.
    craftable, craft_mora = _convert_surplus(eco, needs, stock, craft_multipliers or {})
    if craft_mora and mora is not None:
        section.mora = mora + craft_mora
    outstanding: dict[int, int] = {}
    for material_id, required in sorted(needs.items()):
        owned = stock.get(material_id, 0)
        made = craftable.get(material_id, 0)
        still = max(0, required - owned - made)
        row = catalogue.get(material_id)
        outstanding[material_id] = still
        multiplier = (craft_multipliers or {}).get(material_id, 1.0)
        estimate = resin.estimate(eco, material_id, still, craft_multiplier=multiplier)
        if estimate is not None:
            status = "priced"
        elif still == 0:
            status = "satisfied"
        elif eco.source_of(material_id) is MaterialSource.NONE:
            # Elemental gems, common enemy drops and local specialties. Their resin cost is
            # genuinely zero — the gems ride along with a world-boss run already paid for.
            status = "not_farmable"
        else:
            status = "unknown"
        section.materials.append(
            MaterialLine(
                material_id=material_id,
                name=row.name if row else str(material_id),
                icon=row.icon if row else eco.icon(material_id),
                rarity=row.rarity if row else (eco.rarity(material_id) or 0),
                required=required,
                owned=owned,
                from_surplus=made,
                still_needed=still,
                resin=estimate,
                resin_status=status,
                domain_days=eco.domain_days(material_id),
            ),
        )
    if exp is not None:
        for material_id, count in exp.books:
            row = catalogue.get(material_id)
            section.exp_books.append(
                (
                    material_id,
                    count,
                    row
                    or Material(
                        id=material_id,
                        name=eco.name(material_id) or str(material_id),
                        icon=eco.icon(material_id),
                        rarity=eco.rarity(material_id) or 0,
                    ),
                ),
            )
    _append_exp_rows(section, eco, exp, exp_items, stock, catalogue)
    _append_mora_row(section, eco, mora, mora_owned, catalogue)
    # **Net of the mora already held.** Ley-line resin for mora you are not going to farm is
    # not a cost, and the whole point of asking for the balance is that it changes the answer.
    section.resin = resin.total(
        eco, outstanding,
        mora=max(0, (mora or 0) - (mora_owned or 0)),
        character_exp=character_exp,
        craft_multipliers=dict(craft_multipliers or {}),
    )
    _share_pooled_resin(section, eco)
    return section


def _share_pooled_resin(section: Section, eco: Economy) -> None:
    """Give the mora and EXP rows their share of the ley-line pool, so the rows sum to the total.

    `_line` leaves those rows' `resin` null because the pool is priced once, in `resin.total`,
    and a per-unit estimate would bill it twice. That was right while nothing displayed a
    per-row figure. A Resin column does, and with the pool on no row it read short of the
    header by exactly the pool — so the pool is *split* here, never re-priced: the mora row
    takes the mora pool whole, and the EXP book rows divide the EXP pool by the points each
    row still needs. The shares add back to the pool exactly.
    """
    pooled = section.resin.pooled
    exp_rows = [
        index
        for index, line in enumerate(section.materials)
        if line.still_needed > 0 and eco.source_of(line.material_id) is MaterialSource.LEY_LINE_EXP
    ]
    points = {item.id: item.exp for item in eco.character_exp_items}
    exp_weight = sum(section.materials[i].still_needed * points[section.materials[i].material_id]
                     for i in exp_rows)
    shares: dict[int, tuple[int, float]] = {}
    if eco.mora_item_id in pooled:
        for index, line in enumerate(section.materials):
            if line.material_id == eco.mora_item_id and line.still_needed > 0:
                shares[index] = (eco.mora_item_id, pooled[eco.mora_item_id])
    if resin.EXP_PROBE in pooled and exp_weight > 0:
        for index in exp_rows:
            line = section.materials[index]
            weight = line.still_needed * points[line.material_id] / exp_weight
            shares[index] = (resin.EXP_PROBE, pooled[resin.EXP_PROBE] * weight)
    for index, (probe, expected) in shares.items():
        line = section.materials[index]
        rate = eco.rate(probe)
        if rate is None:  # pragma: no cover - a pool exists only where a rate did
            continue
        section.materials[index] = replace(
            line,
            resin=resin.ResinEstimate(
                material_id=line.material_id,
                root_id=probe,
                source_type=rate.source_type,
                resin_per_run=rate.resin,
                expected_per_run=rate.expected_per_run,
                expected_runs=expected / rate.resin,
                expected_resin=expected,
                resin_per_unit=expected / line.still_needed,
                curated=rate.curated,
            ),
            resin_status="priced",
        )


def _craft_multipliers(
    needs: Mapping[int, int], bonuses: list[CraftingBonus], *, in_talent_bill: bool,
) -> dict[int, float]:
    """`{material id: what one crafting batch is worth}` for the selected characters.

    **Never applied to the requirement.** The game still wants six Philosophies; the passive
    only means you craft them from fewer inputs. An earlier version reduced `required` itself,
    so a plan needing six reported five and a user holding exactly five was told they were
    done.
    """
    if not bonuses:
        return {}
    eco = economy()
    out: dict[int, float] = {}
    for material_id in needs:
        material_class = _class_of(material_id, in_talent_bill)
        if material_class is None or eco.craft_step(material_id) is None:
            continue
        multiplier = craft_multiplier(bonuses, material_class)
        if multiplier > 1.0:
            out[material_id] = multiplier
    return out


async def available_bonuses(session: AsyncSession) -> list[CraftingBonus]:
    """Every character whose passive changes what crafting a planner material costs."""
    result = await session.execute(
        select(
            Character.id, Character.name, AscensionPassive.name, AscensionPassive.description,
        ).join(Character, Character.id == AscensionPassive.character_id),
    )
    found = [bonus for row in result.all() if (bonus := classify(*row))]
    return sorted(found, key=lambda bonus: (bonus.effect.value, bonus.character_name))


async def _weapon_bill(
    session: AsyncSession,
    stock: Mapping[int, int],
    selected: list[CraftingBonus],
    weapon_id: str | None,
    weapon_from: Progress | None,
    weapon_to: Progress | None,
) -> tuple[Weapon | None, dict[int, int], int | None, costs.ExpBill | None, dict[int, float]]:
    """The weapon's whole bill: its phases and its ore, or empties when none was asked for.

    Levels and ascension are one section for a weapon because nobody thinks of them apart —
    unlike a character, where "ascend but stay at 80" is a decision worth its own row.
    """
    if not (weapon_id and weapon_from and weapon_to):
        return None, {}, 0, None, {}
    eco = economy()
    weapon = await session.get(Weapon, weapon_id)
    if weapon is None:
        msg = f"no weapon {weapon_id!r}"
        raise PlanError(msg)
    costs.validate_move(weapon_from, weapon_to, eco.weapon_level_caps, "weapon")
    rows = (
        await session.execute(
            select(WeaponAscensionCost).where(WeaponAscensionCost.weapon_id == weapon_id),
        )
    ).scalars().all()
    needs, phase_mora = costs.ascension_bill(
        _rows_by_key(rows, "phase"), weapon_from.ascension, weapon_to.ascension,
        what=weapon.name,
    )
    multipliers = _craft_multipliers(needs, selected, in_talent_bill=False)
    exp = costs.exp_bill(
        eco,
        costs.weapon_exp_between(weapon.xp_requirements or {}, weapon_from.level, weapon_to.level),
        stock,
        "weapon",
    )
    mora = None if exp.mora is None else phase_mora + exp.mora
    return weapon, needs, mora, exp, multipliers


async def build_plan(
    session: AsyncSession,
    owner_id: str,
    *,
    character_id: str,
    character_from: Progress,
    character_to: Progress,
    talents: Mapping[str, tuple[int, int]],
    weapon_id: str | None = None,
    weapon_from: Progress | None = None,
    weapon_to: Progress | None = None,
    bonus_character_ids: Sequence[str] = (),
    #: Mora the user says they hold. `None` counts as zero for the bill, which reads as
    #: "you need all of it" — the conservative answer when nobody has said.
    mora_owned: int | None = None,
) -> Plan:
    """Price a whole plan. Raises `PlanError` for a state the game cannot produce."""
    eco = economy()
    character = (
        await session.execute(
            select(Character)
            .where(Character.id == character_id)
            .options(selectinload(Character.talents)),
        )
    ).scalar_one_or_none()
    if character is None:
        msg = f"no character {character_id!r}"
        raise PlanError(msg)

    costs.validate_move(character_from, character_to, eco.character_level_caps, "character")

    all_bonuses = await available_bonuses(session)
    selected = [b for b in all_bonuses if b.character_id in set(bonus_character_ids)]

    # -- levels
    exp_required = costs.character_exp_between(
        character.level_exp or [], character_from.level, character_to.level,
    )
    stock = await UserMaterialRepository(session, owner_id).counts()
    exp = costs.exp_bill(eco, exp_required, stock, "character")

    # -- ascension
    ascension_rows = (
        await session.execute(
            select(CharacterAscensionCost).where(
                CharacterAscensionCost.character_id == character_id,
            ),
        )
    ).scalars().all()
    ascension_needs, ascension_mora = costs.ascension_bill(
        _rows_by_key(ascension_rows, "phase"), character_from.ascension, character_to.ascension,
        what=character.name,
    )

    # -- talents
    talent_rows = (
        await session.execute(
            select(CharacterTalentCost).where(
                CharacterTalentCost.character_id == character_id,
            ),
        )
    ).scalars().all()
    by_talent: dict[str, dict[int, tuple[int, list]]] = {}
    for row in talent_rows:
        by_talent.setdefault(row.talent_id, {})[row.level] = (row.mora, row.items)
    talent_needs: dict[int, int] = {}
    talent_mora = 0
    free_levels = False
    for talent_id, (current, target) in talents.items():
        if target > costs.MAX_TALENT_LEVEL:
            free_levels = True
        items, mora = costs.talent_bill(by_talent.get(talent_id, {}), current, target)
        talent_mora += mora
        for material_id, count in items.items():
            talent_needs[material_id] = talent_needs.get(material_id, 0) + count
    talent_multipliers = _craft_multipliers(talent_needs, selected, in_talent_bill=True)
    # **Ascension gets them too, and did not before.** A character's ascension bill is mostly
    # monster drops, which are the "Character and Weapon Enhancement Materials" class — so
    # Sucrose and Dori apply here. Nothing claimed them while that class did not exist.
    ascension_multipliers = _craft_multipliers(ascension_needs, selected, in_talent_bill=False)

    # -- weapon
    weapon, weapon_needs, weapon_mora, weapon_exp, weapon_multipliers = await _weapon_bill(
        session, stock, selected, weapon_id, weapon_from, weapon_to,
    )

    catalogue = await _load_catalogue(
        session,
        set(ascension_needs)
        | set(talent_needs)
        | set(weapon_needs)
        | _book_ids(exp, weapon_exp),
    )
    priced = eco.with_rarities({row.id: row.rarity for row in catalogue.values()})

    # **Levels and ascension are one section**, the way the weapon's already were. Owner:
    # "it's a little odd we lump weapon levels and ascension together but not characters".
    # Nobody thinks of them apart — you take a character to 90 and ascend on the way — and
    # splitting them put an EXP-only table with no materials beside a materials-only table
    # with no EXP.
    advancement_mora = (
        None if exp.mora is None or ascension_mora is None else exp.mora + ascension_mora
    )
    sections = [
        _build_section(
            "advancement", "Character advancement", ascension_needs, advancement_mora, stock,
            catalogue, exp=exp, exp_items=eco.character_exp_items,
            character_exp=exp.exp_short, craft_multipliers=ascension_multipliers,
            mora_owned=mora_owned, eco=priced,
        ),
        _build_section(
            "talents", "Character talents", talent_needs, talent_mora, stock, catalogue,
            craft_multipliers=talent_multipliers, mora_owned=mora_owned, eco=priced,
        ),
    ]
    if weapon is not None:
        sections.append(
            # **No `character_exp` here.** Weapon levelling spends Enhancement Ore, which
            # `MaterialSource` classifies as costing no resin at all; feeding its shortfall
            # into the ley-line rate invented 163 resin out of a Blossom of Revelation that
            # yields *character* EXP.
            _build_section(
                "weapon", "Weapon advancement", weapon_needs, weapon_mora, stock, catalogue,
                exp=weapon_exp, exp_items=eco.weapon_exp_items,
                craft_multipliers=weapon_multipliers, mora_owned=mora_owned, eco=priced,
            ),
        )

    # The cumulative summary merges the *needs* and re-prices them, rather than adding the
    # sections' resin. Two sections wanting the same book family are farming one domain.
    merged: dict[int, int] = {}
    for source in (ascension_needs, talent_needs, weapon_needs):
        for material_id, count in source.items():
            merged[material_id] = merged.get(material_id, 0) + count
    mora_values = [section.mora for section in sections]
    total_mora = (
        None if any(value is None for value in mora_values) else sum(mora_values)  # type: ignore[arg-type]
    )
    # **The summary carries no EXP line, and that is deliberate.** Character EXP and weapon
    # EXP are different pools -- books against Enhancement Ore -- and adding them produced a
    # summary claiming a shortfall of 9,047,100 while both halves were separately covered.
    # Each section shows its own bill; only the *resin* for the character-EXP shortfall is
    # carried here, because that is a real ley-line cost the total should price once.
    total = _build_section(
        "total", "Everything", merged, total_mora, stock, catalogue,
        character_exp=exp.exp_short,
        craft_multipliers={**ascension_multipliers, **talent_multipliers, **weapon_multipliers},
        mora_owned=mora_owned, eco=priced,
    )

    return Plan(
        character_name=character.name,
        character_icon=character.icon,
        weapon_name=weapon.name if weapon else None,
        weapon_icon=weapon.icon if weapon else None,
        sections=sections,
        total=total,
        bonuses_applied=selected,
        bonuses_available=all_bonuses,
        talent_free_levels=free_levels,
        stock_is_empty=not stock,
    )


async def talents_of(session: AsyncSession, character_id: str) -> list[Talent]:
    """The character's levelable talents — the ones that actually have a cost ladder.

    An alternate sprint has no rows in `character_talent_costs`, so it is filtered out here
    rather than offered as a talent the user can plan and then priced at zero.
    """
    levelable = (
        await session.execute(
            select(CharacterTalentCost.talent_id)
            .where(CharacterTalentCost.character_id == character_id)
            .distinct(),
        )
    ).scalars().all()
    if not levelable:
        return []
    result = await session.execute(
        select(Talent).where(Talent.id.in_(levelable)).order_by(Talent.nanoka_id),
    )
    return list(result.scalars())
