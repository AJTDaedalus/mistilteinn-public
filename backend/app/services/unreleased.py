"""Weapon classes the game has not shipped, and the one place that names them.

`WeaponType` has six members because the source index has six. Five are in the game. The
sixth, `WEAPON_CROSSBOW`, is carried at nanoka 7.0.51 by **two unreleased Traveler variants**
and **eight unreleased weapons** — `Shatanaya's Frostsilver`, three `Frag Crystal` rows, and
four more. Those names have not been published by anyone but a datamine.

Reported from Discord (#271): *"crossbow doesnt actually exist anyway and also could be kinda
leaks touching which is a no no for you"*. The complaint arrived about a filter chip, which is
the surface a player happened to notice; the eight weapon names sitting in `/weapons` are the
larger half of the same thing.

## Hidden from lists, not unseeded

The same shape as `practice_dummies`, and for the same reason: `verify_seed` counts rows
against the source index, so a seeder that dropped ten would have to explain the gap to every
count downstream — including the prune guard, which refuses to delete an implausible share of
a table precisely because a silent shrink is indistinguishable from a truncated download.
Hiding is a read-time decision and is reversed by deleting one `where`, which is what the
patch that releases the class will do.

## Named by class, not by row

Listing the ten ids would be a list to maintain, and a patch that adds an eleventh crossbow row
before releasing the class would walk straight past it. The class is the fact.

**`symbol_for` returning `None` is a consequence of this, not the cause.** A class the game has
not shipped has no characters with talents, so there is no normal-attack sprite to derive —
`weapon_symbols` is downstream of this file's fact, and says so.
"""

from __future__ import annotations

from app.models.enums import WeaponType

#: Classes present in the source index and absent from the game.
#:
#: Delete a member here when the class ships; nothing else needs to change.
UNRELEASED_WEAPON_CLASSES: frozenset[WeaponType] = frozenset({WeaponType.CROSSBOW})


def is_unreleased_class(weapon_type: WeaponType | str | None) -> bool:
    """Whether this weapon class is one the game has not shipped.

    Accepts either index's raw spelling, because characters say `WEAPON_CROSSBOW` and weapons
    say `ITEM_TPS_WEAPON` — `WeaponType.parse` is the one place that reconciles them, and a
    caller holding a raw string should not have to know which index it came from.
    """
    if weapon_type is None:
        return False
    if not isinstance(weapon_type, WeaponType):
        weapon_type = WeaponType.parse(str(weapon_type))
        if weapon_type is None:
            return False
    return weapon_type in UNRELEASED_WEAPON_CLASSES
