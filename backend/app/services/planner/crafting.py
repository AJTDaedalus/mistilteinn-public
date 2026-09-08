"""Characters whose passive changes what crafting costs.

The 26 relevant passives are **already in this database** — `ascension_passives`, seeded from
nanoka since Chunk C. Nothing new is imported; this module classifies what is there.

## Three effect shapes, and only one of them is usable

* **double the product**, with a stated chance — Sucrose 10% on both categories, Ayaka /
  Albedo / Alhaitham / Wriothesley 10% on weapon ascension materials, Eula / Layla 10% on
  character talent materials. Exact: expected output per batch is `1 + p`, so the inputs a
  plan needs fall by that factor. **Applied.**
* **refund a portion**, with a stated chance. Xingqiu 25%, Mona 25%, Dori 25%. **Applied**,
  since 2026-09-07. This was reported-but-never-applied on the grounds that "a portion" was
  unquantified; it is quantified, and the description says so: the refund is *one count of one
  material used*. The owner supplied the source, and the derivation is on the wiki's
  [Crafting page](https://genshin-impact.fandom.com/wiki/Crafting#Efficiency).
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
    """The crafting categories a passive can name.

    **Three, and they are the game's own.** The wiki's Crafting page lists exactly these as
    separate recipe categories — 46 Character Talent Material recipes, 72 Weapon Ascension
    Material recipes and 104 Character and Weapon Enhancement Material recipes — and every
    crafting passive names exactly one of them.

    Elemental gems are *Character Ascension Materials*, a fourth category no passive names, so
    they are deliberately absent rather than forgotten (owner, 2026-09-07).
    """

    TALENT = "talent"
    WEAPON_ASCENSION = "weapon_ascension"
    #: Monster drops: Slime Condensate, Chaos Core, Concealed Talon, Heavy Horn. Used by both
    #: character ascension and weapon ascension, which is what "Character and Weapon" means
    #: here — **not** the union of the other two classes.
    ENHANCEMENT = "enhancement"


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
    #: Whether the effect can be priced. True for both live effects since 2026-09-07 — see
    #: `craft_multiplier` for the refund's arithmetic and why it was withheld before.
    applicable: bool
    description: str


_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

#: Phrases that name a planner category. Cooking ("dish", "Cooking"), furnishings and weapon
#: forging ("ore used when crafting <type>-type weapons") deliberately match none of them.
_TALENT = re.compile(r"Character Talent Material", re.IGNORECASE)
_WEAPON = re.compile(r"Weapon Ascension Material", re.IGNORECASE)
#: The monster-drop category. Sucrose spells it in full; Dori writes "Character and Weapon
#: Materials", and her talent page resolves the ambiguity by linking that short form straight
#: at `Character and Weapon Enhancement Material`.
#:
#: **This used to map to `{TALENT, WEAPON_ASCENSION}`**, reading "Character and Weapon" as the
#: union of the other two classes. It is not a union; it is the game's name for a third
#: category. The misreading gave Sucrose and Dori bonuses on talent books and weapon ascension
#: materials they do not have, and none on the monster drops they do. Corrected against the
#: wiki's own crafting-talent table, 2026-09-07.
_ENHANCEMENT = re.compile(
    r"Character and Weapon (?:Enhancement )?Materials", re.IGNORECASE,
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
    # Checked first. The enhancement phrase contains neither of the other category names, so
    # the order is belt-and-braces rather than load-bearing.
    if _ENHANCEMENT.search(text):
        classes = {MaterialClass.ENHANCEMENT}
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
        effect, applicable = Effect.REFUND, True
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


#: Materials one craft consumes, for the refund arithmetic below.
#:
#: **Measured, not assumed.** `CombineExcelConfigData` holds 249 recipes the planner can walk
#: and 245 are 3-in-1-out; the four that are not are Fabric and the three Dyes, furnishing
#: recipes that no crafting passive names and no plan bills.
#: `tests/unit/test_planner_crafting.py` pins that, so a patch adding a talent book on a
#: different ratio fails a test instead of quietly mispricing the refund.
INPUTS_PER_CRAFT = 3


def craft_multiplier(bonuses: list[CraftingBonus], material_class: MaterialClass) -> float:
    """How many outputs one crafting batch is worth, given the selected characters.

    The inputs a plan needs are divided by this, so a larger number is a cheaper plan.

    **Double is the simple arm.** A 10% chance of double output makes a batch worth `1.10`.

    **Refund is not, and reading it as one is the trap.** "25% chance to refund a portion"
    does *not* mean a quarter of the materials come back. The description says one count of
    one material, and a craft consumes three, so the expected return is `p/3` per material —
    about 8.3% at p=25%, not 25%. Those refunds are themselves craftable, so the true figure
    is the sum of a geometric series:

        x0[p/3 + (p/3)^2 + ...] = x0 / (1 - p/3)  materials usable
                                = x0 / (3 - p)    products

    so a batch is worth `3 / (3 - p)`, which is **1.0909** at 25%. That is why a 10% double
    beats a 25% refund, a result the source states outright and which reads backwards until
    the arithmetic is done.

    Derivation and both figures:
    https://genshin-impact.fandom.com/wiki/Crafting#Efficiency

    Only one character crafts a given batch, so the **best** bonus is taken rather than the
    product of several — stacking them would invent an interaction the game does not have.
    """
    best = 1.0
    for bonus in bonuses:
        if not bonus.applicable or material_class not in bonus.classes:
            continue
        if bonus.effect is Effect.DOUBLE:
            best = max(best, 1.0 + bonus.chance)
        elif bonus.effect is Effect.REFUND:
            best = max(best, INPUTS_PER_CRAFT / (INPUTS_PER_CRAFT - bonus.chance))
    return best
