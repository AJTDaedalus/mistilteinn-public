"""What gcsim can simulate of a catalogue entry, at the pin — **computed on read, never stored**.

Owner ruling D-F1 (`docs/DECISIONS.md` §38, `DESIGN_team_math_fallback.md` §1): gcsim status
is a fact about *(entry, gcsim pin)*, not about the game. A re-pin rewrites `keys.json` without
a re-seed — the v2.50.0 re-pin moved four characters from `none` to `full` — so a stored column
would be stale from that moment. Everything here is a pure function of the committed key
snapshot and the row's own name, and it changes exactly when the pin does.

## Three answers for a character, two for a weapon or set

- **`none`** — gcsim has no key. `reason` is gcsim_keys' own refusal text, the sentence a
  search would have died with, published before the search instead of after it.
- **`partial`** — gcsim knows the character but lacks a **core move**: the normal attack, the
  charged (or aimed) attack, the skill or the burst.
- **`full`** — every core move is implemented.

`missing_actions` names **every** move gcsim lacks of the ones the game gives them, core or
not, from `character_implemented_actions` (probed against gcsim itself by
`scripts/gcsim/probe_implemented_actions.py`). So a character gcsim cannot plunge with still
says so in the tooltip even where the badge says nothing.

**"Every move the game gives them" is not gcsim's ten base actions.** Taken literally, every
non-bow character would be `partial` for want of `aim` — an aimed shot is a bow's charged
attack, not a move a sword user lacks. So the expected set is the authorable actions with the
one the weapon class does not have removed: **a bow's charged attack is `aim`, so a bow user is
not expected to have `charge`; everyone else is not expected to have `aim`.** That is the
game's own rule, and it is the same one `gcsim_keys.implemented_actions` documents for Ganyu,
whose charged attack *is* the aimed shot. A bow user who does implement `charge` (Tartaglia's
melee stance) is not penalised for it, because nothing extra is ever counted against anyone.

**Plunges do not make a character `partial`** (owner, 2026-11-13). gcsim implements plunges for
about half the roster, so before the ruling 70 of 89 `partial` characters were partial for that
alone, and a badge on most of the roster says nothing a reader can act on. A plunge authored
for them still fails at run time, which is why plunges stay in `missing_actions`; they just do
not decide the status. `dash`, `jump` and `walk` are movement and are treated the same way.
`test_gcsim_status.py` pins the numbers.

**Weapons and artifact sets have no `partial`.** gcsim publishes no per-weapon or per-set
implementation table at the pin, so the only honest statuses are "has a key" and "does not".
Claiming more would be inventing a third state from nothing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from app.models.enums import WeaponType
from app.services import gcsim_keys

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.models.enums import Element


class GcsimSupport(StrEnum):
    """How much of an entry gcsim can simulate at the pin."""

    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class GcsimStatus(NamedTuple):
    """One entry's answer. A tuple so the schema layer owns the wire shape."""

    status: GcsimSupport
    key: str | None
    pin: str
    missing_actions: tuple[str, ...]
    reason: str | None


def expected_actions(weapon_type: WeaponType | str | None) -> tuple[str, ...]:
    """The base actions the game gives a character of this weapon class, in gcsim's order."""
    not_this_class = "charge" if weapon_type == WeaponType.BOW else "aim"
    return tuple(a for a in gcsim_keys.authorable_actions() if a != not_this_class)


#: The moves whose absence makes a character `partial`: normal, charged (a bow's is `aim`),
#: skill and burst. Plunges and movement are listed in `missing_actions` but do not count.
CORE_ACTIONS = frozenset({"attack", "charge", "aim", "skill", "burst"})


def for_character(
    nanoka_id: str,
    name: str,
    element: Element | str | None,
    weapon_type: WeaponType | str | None,
) -> GcsimStatus:
    """A character's gcsim status."""
    pin = gcsim_keys.pinned_commit()
    try:
        key = gcsim_keys.character_key(nanoka_id, name, element)
    except gcsim_keys.GcsimKeyError as refusal:
        return GcsimStatus(GcsimSupport.NONE, None, pin, (), str(refusal))
    implemented = gcsim_keys.implemented_actions(key)
    # An empty table means the snapshot predates the capture, not a character with no moves —
    # the rule `gcsim_keys.offerable_actions` follows, and the direction it already fails in.
    missing = tuple(
        a for a in expected_actions(weapon_type) if implemented and a not in implemented
    )
    status = GcsimSupport.PARTIAL if CORE_ACTIONS.intersection(missing) else GcsimSupport.FULL
    return GcsimStatus(status, key, pin, missing, None)


def _keyed(resolve: Callable[[str], str], name: str) -> GcsimStatus:
    pin = gcsim_keys.pinned_commit()
    try:
        key = resolve(name)
    except gcsim_keys.GcsimKeyError as refusal:
        return GcsimStatus(GcsimSupport.NONE, None, pin, (), str(refusal))
    return GcsimStatus(GcsimSupport.FULL, key, pin, (), None)


def for_weapon(name: str) -> GcsimStatus:
    """A weapon's gcsim status: `full` or `none` — see the module docstring."""
    return _keyed(gcsim_keys.weapon_key, name)


def for_artifact_set(name: str) -> GcsimStatus:
    """An artifact set's gcsim status: `full` or `none` — see the module docstring."""
    return _keyed(gcsim_keys.artifact_set_key, name)
