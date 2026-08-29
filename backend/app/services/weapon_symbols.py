"""The class symbol for a weapon type — Genshin's own sword/bow/polearm/claymore/catalyst mark.

## Derived from the database, not from memory

Genshin names these sprites after the *normal-attack talent* they illustrate, so the mapping
is `talents.icon` for every character of a given class:

    SELECT c.weapon_type, t.icon, count(*)
    FROM talents t JOIN characters c ON c.id = t.character_id
    WHERE t.icon LIKE 'Skill_A_%'
    GROUP BY 1, 2

At nanoka 7.0.51 each class returns exactly one icon, unanimously — 54 swords, 29 catalysts,
24 polearms, 21 bows, 20 claymores, no disagreement inside any class.

**The catalyst is `Skill_A_Catalyst_MD`**, which no guess would have produced: the other four
are numbered and that one is not, and its `_MD` suffix follows no pattern the others share. It
is the reason this is a query rather than five lines written from memory — the exact failure
mode `CLAUDE.md` names as fairy's hardest-won lesson.

`tests/integration/test_weapon_symbols_match_the_database.py` re-runs that query against the
seeded database and fails on any disagreement, so a re-pin that renames a sprite is caught
here rather than by a reader noticing the wrong mark on a card.

## The sixth class has no symbol, and gets none

`WeaponType` has six members. Only five appear above: `WEAPON_CROSSBOW` is carried by two
unreleased Traveler variants that have **no talents seeded at all**, so there is no icon to
derive and nothing to draw. `symbol_for` returns `None`, which every consumer already handles
— `CatalogueIcon` renders nothing for a null basename. Substituting a sword mark because it is
the commonest would put a wrong weapon class on a card, silently, forever.
"""

from __future__ import annotations

from app.models.enums import WeaponType

#: `WeaponType` → the nanoka basename of its class symbol. Derived; see the module docstring.
#: Absent means *genuinely absent upstream*, never "not looked up yet".
_SYMBOLS: dict[WeaponType, str] = {
    WeaponType.SWORD: "Skill_A_01",
    WeaponType.BOW: "Skill_A_02",
    WeaponType.POLEARM: "Skill_A_03",
    WeaponType.CLAYMORE: "Skill_A_04",
    WeaponType.CATALYST: "Skill_A_Catalyst_MD",
}


def symbol_for(weapon_type: WeaponType | str | None) -> str | None:
    """The class symbol's basename, or `None` when there is none to show.

    Accepts the enum or either index's raw spelling, because characters and weapons disagree
    about how to spell the crossbow class (`WEAPON_CROSSBOW` against `ITEM_TPS_WEAPON`) and
    `WeaponType.parse` is the one place that reconciles them.
    """
    if weapon_type is None:
        return None
    if not isinstance(weapon_type, WeaponType):
        weapon_type = WeaponType.parse(str(weapon_type))
        if weapon_type is None:
            return None
    return _SYMBOLS.get(weapon_type)


def all_symbols() -> tuple[str, ...]:
    """Every symbol basename, for the icon downloader to vendor."""
    return tuple(_SYMBOLS.values())
