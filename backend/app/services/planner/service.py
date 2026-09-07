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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.character import AscensionPassive, Character, Talent
from app.models.planner import (
    CharacterAscensionCost,
    CharacterTalentCost,
    Material,
    UserMaterial,
    WeaponAscensionCost,
)
from app.models.weapon import Weapon
from app.services.planner import costs, resin
from app.services.planner.costs import PlanError, Progress
from app.services.planner.crafting import CraftingBonus, MaterialClass, classify, craft_multiplier
from app.services.planner.economy import economy

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

#: Material id prefixes, derived from which cost table each one appears in (see
#: `docs/RESEARCH_leveling_planner_data.md`). `104` in a talent bill is a talent book; `114`
#: is a weapon ascension material. `112` (common drops) and `113` (boss drops) appear in both
#: and belong to neither crafting category, so no bonus touches them.
_TALENT_BOOK_PREFIX = "104"
_WEAPON_MATERIAL_PREFIX = "114"


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
    #: `"priced"`, `"unknown"` (resin-farmable at an unpublished rate) or `"not_farmable"`
    #: (overworld or a local specialty — genuinely zero resin). The UI must render the last
    #: two differently: one is a gap in our data, the other is a fact about the game.
    resin_status: str
    #: Weekdays this material's domain is open, `[]` when it is not a domain drop.
    domain_days: list[str]


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


def _class_of(material_id: int, in_talent_bill: bool) -> MaterialClass | None:
    text = str(material_id)
    if text.startswith(_TALENT_BOOK_PREFIX) and in_talent_bill:
        return MaterialClass.TALENT
    if text.startswith(_WEAPON_MATERIAL_PREFIX):
        return MaterialClass.WEAPON_ASCENSION
    return None


def _rows_by_key(rows: Sequence[Any], key: str) -> dict[int, tuple[int, list]]:
    return {getattr(row, key): (row.mora, row.items) for row in rows}


async def _load_stock(session: AsyncSession, owner_id: str) -> dict[int, int]:
    result = await session.execute(
        select(UserMaterial.material_id, UserMaterial.count).where(
            UserMaterial.owner_id == owner_id,
        ),
    )
    return dict(result.all())


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
) -> Section:
    """Turn `{material id: required}` into a rendered section, net of what is held."""
    eco = economy()
    uncurated = set(eco.uncurated())
    section = Section(key=key, label=label, mora=mora, exp=exp)
    outstanding: dict[int, int] = {}
    for material_id, required in sorted(needs.items()):
        owned = stock.get(material_id, 0)
        still = max(0, required - owned)
        row = catalogue.get(material_id)
        outstanding[material_id] = still
        estimate = resin.estimate(eco, material_id, still)
        if estimate is not None:
            status = "priced"
        elif eco.craft_root(material_id) in uncurated:
            status = "unknown"
        else:
            status = "not_farmable"
        section.materials.append(
            MaterialLine(
                material_id=material_id,
                name=row.name if row else str(material_id),
                icon=row.icon if row else eco.icon(material_id),
                rarity=row.rarity if row else (eco.rarity(material_id) or 0),
                required=required,
                owned=owned,
                still_needed=still,
                resin=estimate,
                resin_status=status,
                domain_days=eco.domain_days(material_id),
            ),
        )
    section.resin = resin.total(eco, outstanding)
    return section


def _apply_bonuses(
    needs: dict[int, int], bonuses: list[CraftingBonus], *, in_talent_bill: bool,
) -> dict[int, int]:
    """Reduce crafted-material requirements by the selected characters' double-product odds.

    A 10% chance of a double batch makes each batch worth 1.10, so the *inputs* a plan needs
    fall by that factor. Only materials that are actually crafted from a lower tier are
    affected; a base-tier drop is farmed, not crafted, and no passive touches it.
    """
    if not bonuses:
        return dict(needs)
    eco = economy()
    out: dict[int, int] = {}
    for material_id, count in needs.items():
        material_class = _class_of(material_id, in_talent_bill)
        if material_class is None or eco.craft_step(material_id) is None:
            out[material_id] = count
            continue
        multiplier = craft_multiplier(bonuses, material_class)
        out[material_id] = max(1, round(count / multiplier)) if count else 0
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
) -> tuple[Weapon | None, dict[int, int], int | None, costs.ExpBill | None]:
    """The weapon's whole bill: its phases and its ore, or empties when none was asked for.

    Levels and ascension are one section for a weapon because nobody thinks of them apart —
    unlike a character, where "ascend but stay at 80" is a decision worth its own row.
    """
    if not (weapon_id and weapon_from and weapon_to):
        return None, {}, 0, None
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
    )
    needs = _apply_bonuses(needs, selected, in_talent_bill=False)
    exp = costs.exp_bill(
        eco,
        costs.weapon_exp_between(weapon.xp_requirements or {}, weapon_from.level, weapon_to.level),
        stock,
        "weapon",
    )
    for material_id, count in exp.books:
        needs[material_id] = needs.get(material_id, 0) + count
    mora = None if exp.mora is None else phase_mora + exp.mora
    return weapon, needs, mora, exp


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
    stock = await _load_stock(session, owner_id)
    exp = costs.exp_bill(eco, exp_required, stock, "character")
    level_needs = dict(exp.books)

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
    talent_needs = _apply_bonuses(talent_needs, selected, in_talent_bill=True)

    # -- weapon
    weapon, weapon_needs, weapon_mora, weapon_exp = await _weapon_bill(
        session, stock, selected, weapon_id, weapon_from, weapon_to,
    )

    catalogue = await _load_catalogue(
        session,
        set(level_needs) | set(ascension_needs) | set(talent_needs) | set(weapon_needs),
    )

    sections = [
        _build_section(
            "levels", "Character levels", level_needs, exp.mora, stock, catalogue, exp=exp,
        ),
        _build_section(
            "ascension", "Character ascension", ascension_needs, ascension_mora, stock, catalogue,
        ),
        _build_section("talents", "Talents", talent_needs, talent_mora, stock, catalogue),
    ]
    if weapon is not None:
        sections.append(
            _build_section(
                "weapon", "Weapon", weapon_needs, weapon_mora, stock, catalogue, exp=weapon_exp,
            ),
        )

    # The cumulative summary merges the *needs* and re-prices them, rather than adding the
    # sections' resin. Two sections wanting the same book family are farming one domain.
    merged: dict[int, int] = {}
    for source in (level_needs, ascension_needs, talent_needs, weapon_needs):
        for material_id, count in source.items():
            merged[material_id] = merged.get(material_id, 0) + count
    mora_values = [section.mora for section in sections]
    total = _build_section(
        "total",
        "Everything",
        merged,
        None if any(value is None for value in mora_values) else sum(mora_values),  # type: ignore[arg-type]
        stock,
        catalogue,
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
