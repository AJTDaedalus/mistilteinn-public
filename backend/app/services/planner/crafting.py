"""Characters whose passive changes what crafting costs.

The 26 relevant passives are **already in this database** — `ascension_passives`, seeded from
nanoka since Chunk C. Nothing new is imported; this module classifies what is there.

## Three effect shapes, and only one of them is usable

* **double the product**, with a stated chance — Sucrose 10% on both categories, Ayaka /
  Albedo / Alhaitham / Wriothesley 10% on weapon ascension materials, Eula / Layla 10% on
  character talent materials. Exact: expected output per batch is `1 + p`, so the inputs a
  plan needs fall by that factor. **Applied.**
* **refund a portion**, with a stated chance — Xingqiu 25%, Mona 25%, Dori 25%. The *chance*
  is published and **"a portion" is not**, in any table in the pinned dump. Reported so the
  user knows the character helps, never applied, because inventing the portion would move a
  real number by an invented amount.
**A third shape is deliberately not classified at all.** Yae Miko and Prune have a chance at
*1 regional Character Talent Material*, which would need the regional material family modelled
to price. Owner ruling: that modelling is not wanted, so these are not planner-relevant
passives and `classify` returns `None` for them — the same answer it gives a cooking passive.
They were reported-but-never-applied for a while, which put two rows a user could do nothing
with at the top of a column, above the ones they could.

Cooking, furnishing and weapon-forging passives match the same vocabulary and are **not**
planner-relevant. Diluc's "refunds 15% of the ore used when crafting Claymore-type weapons" is
forging a weapon, not ascending one. Filter by effect, never by "has a crafting passive".

## Why this is a parse and not a table of ids

Matching English descriptions is fragile, so it is not trusted: the set is small and fixed,
and `tests/unit/test_planner_crafting.py` holds all twelve descriptions **verbatim** from the
seeded catalogue and asserts each still resolves to the same effect. A patch that rewords a
passive fails that test rather than silently dropping a bonus from every plan.

That file was cited here before it existed — this paragraph was the argument that the fragile
parse was safe, and the thing it pointed at was not written. Found by review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class MaterialClass(StrEnum):
    """The crafting categories a passive can name."""

    TALENT = "talent"
    WEAPON_ASCENSION = "weapon_ascension"


class Effect(StrEnum):
    """What the passive does when it fires."""

    DOUBLE = "double"
    REFUND = "refund"


@dataclass(frozen=True)
class CraftingBonus:
    """One character's crafting passive, classified."""

    character_id: str
    character_name: str
    passive_name: str
    effect: Effect
    chance: float
    classes: frozenset[MaterialClass]
    #: False for `REFUND`: the chance is published and the *size* is not, so applying it would
    #: move a real number by an invented amount.
    applicable: bool
    description: str


_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

#: Phrases that name a planner category. Cooking ("dish", "Cooking"), furnishings and weapon
#: forging ("ore used when crafting <type>-type weapons") deliberately match none of them.
_TALENT = re.compile(r"Character Talent Material", re.IGNORECASE)
_WEAPON = re.compile(r"Weapon Ascension Material", re.IGNORECASE)
#: Three spellings for the same pair of categories, all live at 7.0.54: Sucrose says
#: "Character and Weapon Enhancement Materials" and Dori just "Character and Weapon
#: Materials". Dori was missed by a stricter pattern that required the middle word.
_BOTH = re.compile(
    r"Character and Weapon (?:Enhancement |Ascension )?Materials", re.IGNORECASE,
)

_DOUBLE = re.compile(r"double the product|receive double|obtain double", re.IGNORECASE)
_REFUND = re.compile(r"refund a portion|recover some of the materials", re.IGNORECASE)
_BONUS = re.compile(r"get 1 regional Character Talent Material", re.IGNORECASE)


def classify(
    character_id: str, character_name: str, passive_name: str, description: str,
) -> CraftingBonus | None:
    """Classify one passive, or `None` when it does not change a planner material's cost."""
    text = description or ""
    classes: set[MaterialClass] = set()
    if _BOTH.search(text):
        classes = {MaterialClass.TALENT, MaterialClass.WEAPON_ASCENSION}
    else:
        if _TALENT.search(text):
            classes.add(MaterialClass.TALENT)
        if _WEAPON.search(text):
            classes.add(MaterialClass.WEAPON_ASCENSION)
    # **Not planner-relevant**, and refused before the effect branches so a description
    # carrying both shapes cannot fall through to one of them. See the module docstring.
    if _BONUS.search(text):
        return None
    if _DOUBLE.search(text):
        effect, applicable = Effect.DOUBLE, True
    elif _REFUND.search(text):
        effect, applicable = Effect.REFUND, False
    else:
        return None
    if not classes:
        return None
    match = _PERCENT.search(text)
    if match is None:
        return None
    return CraftingBonus(
        character_id=character_id,
        character_name=character_name,
        passive_name=passive_name,
        effect=effect,
        chance=float(match.group(1)) / 100.0,
        classes=frozenset(classes),
        applicable=applicable,
        description=text,
    )


def craft_multiplier(bonuses: list[CraftingBonus], material_class: MaterialClass) -> float:
    """How many outputs one crafting batch is worth, given the selected characters.

    A 10% chance of double output makes a batch worth `1.10` on average, so the inputs a plan
    needs are divided by this. Only one character crafts a given batch, so the **best**
    applicable bonus is taken rather than the product of several — stacking them would invent
    an interaction the game does not have.
    """
    applicable = [
        bonus.chance
        for bonus in bonuses
        if bonus.applicable
        and bonus.effect is Effect.DOUBLE
        and material_class in bonus.classes
    ]
    return 1.0 + max(applicable, default=0.0)
