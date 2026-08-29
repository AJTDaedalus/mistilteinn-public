"""Map this repo's catalogue onto gcsim's config keys.

gcsim names things in its own vocabulary, and **its package directory names are not its
config keys** — the package for Blizzard Strayer is `blizzard` while the key is
`blizzardstrayer`. The authority is `pkg/core/keys/*.dm.go`, which gcsim generates itself,
and `app/data/gcsim/keys.json` is that list committed at the pin
(`scripts/gcsim/build_key_snapshot.py`).

## Normalise, then refuse

Most names match once both sides are reduced to lowercase alphanumerics — the same mechanism
`good_import_service` uses for GOOD's `setKey`, and it fails the same way: **an unmatched
name is refused, naming it**, never guessed at or silently dropped.

Refusing matters more here than it looks. gcsim cannot simulate a character it does not
implement, so a wrong-but-plausible key would either error deep inside the simulator or —
worse — simulate *a different character* and return a number that looks entirely reasonable.

Measured at the pin, against the committed nanoka fixtures:

| | catalogue | matched | unmatched |
|---|---:|---:|---:|
| characters | 150 | 105 | 45 |
| weapons | 284 | 231 | 53 |
| artifact sets | 65 | 53 | 12 |

The unmatched are not mapping failures. They are **things gcsim does not implement at this
pin**: characters released after it (Kachina, Nefer, Vesna…), low-rarity sets nobody
optimises (Adventurer, Lucky Dog), the five one-piece "Prayers" circlets, and nanoka's
internal placeholder weapons (`Weapon: Sword`). Refusing them is the correct answer, and a
re-pin is what changes it.

## Travelers are structured, not aliased

The one case normalisation cannot reach. nanoka calls every variant "Traveler" and
distinguishes them by key — `10000005-2` is the Aether body with element 2 — while gcsim
uses `aetherpyro`, `luminedendro`, and so on. So this is derived from the body id and the
element rather than listed, which also means a new element needs no new alias.

**gcsim has six Traveler elements at this pin, not seven**: there is no Cryo Traveler. A
Cryo Traveler is refused like anything else it does not implement.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.enums import Element

_SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "gcsim" / "keys.json"

_NOT_ALNUM = re.compile(r"[^a-z0-9]+")

#: nanoka's Traveler body ids → gcsim's name for that body. `10000117` / `10000118`
#: ("Manekin" / "Manekina") are unreleased bodies gcsim does not implement.
_TRAVELER_BODIES = {"10000005": "aether", "10000007": "lumine"}


class GcsimKeyError(LookupError):
    """gcsim has no key for this, at this pin."""


@cache
def _snapshot() -> dict[str, object]:
    return json.loads(_SNAPSHOT.read_text())


def pinned_commit() -> str:
    """The gcsim commit this key vocabulary was derived from."""
    return str(_snapshot()["pinned_commit_sha"])


#: Actions the rotation model exposes to a user, as a subset of what gcsim accepts.
#:
#: `swap` is excluded because it is **implicit** — `pkg/simulation/run.go:154` has the
#: evaluator insert swaps when the next character is not active, so emitting our own would
#: double them. `wait` and `delay` are excluded because they are timing controls, and
#: `DESIGN_rotation.md` §2 keeps timing out of the model: exposing them invites the user back
#: into frame counting, which is the thing being removed.
_NOT_AUTHORED = frozenset({"swap", "wait", "delay"})


def gcsim_actions() -> tuple[str, ...]:
    """Every action name gcsim's parser accepts at the pin, in enum order."""
    return tuple(_snapshot()["actions"])  # type: ignore[index]


def authorable_actions() -> tuple[str, ...]:
    """The actions a rotation step may name.

    Derived by subtraction from gcsim's own list rather than written out, so a re-pin that
    adds an action offers it automatically and one that removes an action stops offering it.
    A hand-kept list would drift silently in the direction that matters most — offering
    something gcsim would reject.
    """
    return tuple(a for a in gcsim_actions() if a not in _NOT_AUTHORED)


def normalise(name: str) -> str:
    """`"Gladiator's Finale"` and `"GladiatorsFinale"` both reduce to `gladiatorsfinale`."""
    return _NOT_ALNUM.sub("", name.lower())


@cache
def character_alias(spelling: str) -> str | None:
    """The canonical key for one of gcsim's accepted spellings, or `None`.

    **gcsim accepts short names and this repo did not know it.** `pkg/shortcut/*.dm.go` maps
    `arle`→`arlecchino`, `esco`→`escoffier`, `chev`→`chevreuse`, and 57 more — a table generated
    by gcsim's own pipeline exactly like the key files. Reading a real community config refused
    it with *"no character on this team is gcsim's `arle`"*, about a character who was on the
    team (`references/gcsim_db/arlecchino-citlali-escoffier-bennett.txt`).

    Resolution is **one direction only**: an alias resolves to a key, and nothing here ever
    emits an alias. What this repo writes stays canonical, so a config it produced reads the
    same as one it produced yesterday.
    """
    aliases = _snapshot().get("character_aliases", {})
    return aliases.get(normalise(spelling))  # type: ignore[union-attr]


def _resolve(kind: str, name: str, *, what: str) -> str:
    keys = set(_snapshot()[kind])  # type: ignore[arg-type]
    key = normalise(name)
    if key not in keys:
        msg = (
            f"gcsim has no {what} key for {name!r} (normalised {key!r}) at pin "
            f"{pinned_commit()[:12]}. It is most likely released after the pin, or is one "
            f"gcsim does not implement. Simulating it is not possible; re-pin deliberately "
            f"if it should be."
        )
        raise GcsimKeyError(msg)
    return key


def weapon_key(name: str) -> str:
    """The gcsim key for a weapon, by display name."""
    return _resolve("weapons", name, what="weapon")


def artifact_set_key(name: str) -> str:
    """The gcsim key for an artifact set, by display name."""
    return _resolve("artifact_sets", name, what="artifact set")


def character_key(nanoka_id: str, name: str, element: Element | str | None = None) -> str:
    """The gcsim key for a character.

    `nanoka_id` decides the Traveler path, because every Traveler variant is named
    "Traveler" and only the id says which body it is.
    """
    body, _, _variant = nanoka_id.partition("-")
    if body in _TRAVELER_BODIES:
        return _traveler_key(body, nanoka_id, element)
    return _resolve("characters", name, what="character")


def _traveler_key(body: str, nanoka_id: str, element: Element | str | None) -> str:
    if element is None:
        msg = (
            f"{nanoka_id} is a Traveler variant, and gcsim names those by element "
            f"(`aetherpyro`, `luminedendro`, …). Without the element there is nothing to "
            f"resolve, and picking one would silently simulate a different character."
        )
        raise GcsimKeyError(msg)

    key = f"{_TRAVELER_BODIES[body]}{normalise(str(element))}"
    if key not in set(_snapshot()["characters"]):  # type: ignore[arg-type]
        msg = (
            f"gcsim has no {key!r} at pin {pinned_commit()[:12]}. It implements six Traveler "
            f"elements, not seven — there is no Cryo Traveler."
        )
        raise GcsimKeyError(msg)
    return key
