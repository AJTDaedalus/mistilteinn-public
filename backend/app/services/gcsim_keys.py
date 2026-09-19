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
| characters | 150 | 124 | 26 |
| weapons | 286 | 237 | 49 |
| artifact sets | 65 | 55 | 10 |

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

**Which Traveler elements gcsim implements is read from the snapshot, never stated here.**
This paragraph used to say "six, not seven — there is no Cryo Traveler"; the 2026-09-19
re-pin implemented one (gcsim `25e6ef499`), so the refusal now lists the elements it finds.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.models.enums import TalentType

if TYPE_CHECKING:
    from collections.abc import Iterable

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


#: Actions the rotation model **could** name but deliberately does not offer.
#:
#: `swap` is excluded because it is **implicit** — `pkg/simulation/run.go:154` has the
#: evaluator insert swaps when the next character is not active, so emitting our own would
#: double them.
_NOT_AUTHORED = frozenset({"swap"})

#: Entries in gcsim's action **enum** that its own **parser** has no token for, each with the
#: reason it is not a move a rotation can name. Owner ruling, 2026-09-19: *a move gcsim
#: implements cannot be silently ignored* — so every enum entry is either authorable or listed
#: here, and `tests/unit/test_every_gcsim_action_is_accounted_for.py` fails on one that is
#: neither. A future action that **is** a move arrives as a red test, not as a silent gap.
_NOT_A_MOVE: dict[str, str] = {
    "wait": (
        "a sequencer construct, not an action a character performs. DESIGN_rotation.md §2 "
        "keeps timing out of the model: exposing it invites the user back into frame counting"
    ),
    "delay": (
        "the same — a timing control between actions, and the model has no frame field for "
        "it to fill"
    ),
    "special_skill": (
        "a **cooldown bucket**, not a move (gcsim 1de5a4243). It holds the CD for kits whose "
        "skill has a second form, and the forms themselves are authored as ordinary actions: "
        "Varka's Four Winds through `charge` (internal/characters/varka/charge.go:96) and "
        "Odette's recast through `skill` (internal/characters/odette/skill.go:113). gcsim's "
        "tokenizer has no `special_skill` token, so emitting one is a config gcsim rejects"
    ),
}


def gcsim_actions() -> tuple[str, ...]:
    """Every name in gcsim's action enum at the pin, in enum order.

    **Not the same as what a config may name.** Use `parser_actions()` for that; this is the
    wider list, and the difference is what `_NOT_A_MOVE` accounts for.
    """
    return tuple(_snapshot()["actions"])  # type: ignore[index]


def parser_actions() -> tuple[str, ...]:
    """Every action name gcsim's tokenizer accepts at the pin (`pkg/gcs/ast/keys.go`)."""
    return tuple(_snapshot()["parser_actions"])  # type: ignore[index]


def unauthorable_actions() -> dict[str, str]:
    """`{enum action: why it is not a move}` — the reviewed list, for tests and tooling."""
    return dict(_NOT_A_MOVE)


def authorable_actions() -> tuple[str, ...]:
    """The actions a rotation step may name.

    Derived by subtraction from **the parser's** table rather than written out, so a re-pin
    that adds an action offers it automatically and one that removes an action stops offering
    it. A hand-kept list would drift silently in the direction that matters most — offering
    something gcsim would reject.

    It reads the parser's table and not the enum because those two diverged at
    gcsim `1de5a4243`: `special_skill` is in the enum and in no config, so deriving from the
    enum would have offered every character an action the parser refuses by name.
    """
    return tuple(a for a in parser_actions() if a not in _NOT_AUTHORED)


#: The parameters that become an **action a user can author**, and the suffix each one takes.
#:
#: A hold-E is a different move to a tap-E from the player's side; gcsim calls it a parameter
#: only because its syntax has parameters. The owner's ruling (2026-08-30) is that this model
#: stays **parameterless** and expresses the difference in the action vocabulary instead — so
#: `skill_hold` is an action here and becomes `skill[hold=1]` in the compiler, which is the
#: only place the parameter exists.
#:
#: **Three, and each earns its place.** `hold` covers 37 skills, 19 aimed shots and one charged
#: attack. `short_hold` is not redundant with it: Dahlia and both Geo Travelers declare
#: `short_hold` and no `hold`, so offering `hold` alone would leave exactly the characters the
#: owner said not to leave out. `recast` is Fischl's and Mavuika's second press.
VARIANT_PARAMS: dict[str, str] = {
    "hold": "hold",
    "short_hold": "short_hold",
    "recast": "recast",
}

#: Every other parameter gcsim's generated tables declare at the pin, listed rather than
#: inferred.
#:
#: **This exists so that a re-pin cannot introduce a variant silently.**
#: `tests/unit/test_variant_params_are_classified.py` asserts every parameter in the snapshot
#: appears in exactly one of these two collections, so a new one fails a test rather than
#: quietly not being offered. That is the same discipline `authorable_actions()` follows by
#: deriving from `astr` instead of restating it.
#:
#: They fall into three groups, and none of them names a different move:
#:
#: - **hit geometry** — `collision`, `travel`, `weakspot`, `c2_travel`, and their kin. Whether
#:   a plunge connects on the way down, how long a projectile flies. The owner scoped this
#:   chunk to kit variants only, so these keep gcsim's defaults.
#: - **quantities and delays** — `hold_ticks`, `hits`, `ticks`, `max_amulets`, everything
#:   `*_delay`. These are numbers, and a number per step is the parameter field by another
#:   name. Every character declaring `hold_ticks` also declares `hold`, so none is left out.
#: - **kit minutiae** — `glide_cancel`, `prestack`, `bunny`, `jade`. Execution detail for one
#:   character each, which a rotation builder that fits on a screen does not ask about.
NOT_OFFERED_PARAMS: frozenset[str] = frozenset({
    "a4_delay", "amulet_delay", "bomb_delay", "bomblets", "bounce", "buffered", "bullets",
    "bunny", "c2_travel", "c6_travel", "charge_cancel", "collision", "construct_limit",
    "counter", "direction", "early_cancel", "enter", "enter_delay", "extend", "f", "final",
    "glide_cancel", "hits", "hold_c4", "hold_nostele", "hold_ticks", "illusion_delay",
    "jade", "kindling_travel", "man_chai_delay", "marked", "max_amulets", "mine",
    "mine_delay", "no_limit", "no_meteorite", "nobehind", "noscreen", "perfect",
    "pickup_droplets", "prestack", "release", "screen", "short", "ticks", "travel",
    "ushihit", "vivid_travel", "weakspot", "wreath"
})


def character_action_params(key: str) -> dict[str, tuple[str, ...]]:
    """`{action: (param, …)}` for one gcsim character key, or `{}` if it declares none.

    Read from gcsim's own generated per-character validation table
    (`internal/characters/<pkg>/zz_<key>.dm.go`), captured verbatim by
    `scripts/gcsim/build_key_snapshot.py`. It is the **contract**, not the implementation:
    grepping each character's hand-written Go for `p["hold"]` finds the same thing by reading
    what the code does rather than what gcsim says it accepts, and the two would disagree the
    first time a parameter was read without being declared.
    """
    table = _snapshot().get("character_action_params", {})
    per_action = table.get(key, {})  # type: ignore[union-attr]
    return {action: tuple(params) for action, params in per_action.items()}


def characters_with_action_params() -> tuple[str, ...]:
    """Every character key the generated tables cover, for tests and tooling to sweep."""
    table = _snapshot().get("character_action_params", {})
    return tuple(table)  # type: ignore[arg-type]


def declared_params() -> frozenset[str]:
    """Every parameter any character declares at the pin. For the classification test."""
    table = _snapshot().get("character_action_params", {})
    return frozenset(
        param
        for per_action in table.values()  # type: ignore[union-attr]
        for params in per_action.values()
        for param in params
    )


def variant_action(action: str, param: str) -> str:
    """The action key for a variant: `("skill", "hold")` -> `"skill_hold"`."""
    return f"{action}_{VARIANT_PARAMS[param]}"


def split_variant(action: str) -> tuple[str, str | None]:
    """`"skill_hold"` -> `("skill", "hold")`; a plain action -> `(action, None)`.

    Longest suffix first, so `skill_short_hold` resolves to `short_hold` rather than to `hold`
    with a base of `skill_short` — which is not an action and would compile to nothing.
    """
    for param in sorted(VARIANT_PARAMS, key=len, reverse=True):
        suffix = f"_{VARIANT_PARAMS[param]}"
        if action.endswith(suffix):
            base = action[: -len(suffix)]
            if base in parser_actions():
                return base, param
    return action, None


def offerable_actions(key: str | None) -> tuple[str, ...]:
    """The actions **this character** may be given, base ten first then their variants.

    `None` — a character gcsim does not implement at this pin — gets the base ten. They cannot
    be simulated at all, so a rotation naming them fails for that reason and not for want of a
    hold button; offering fewer actions would report the wrong problem.
    """
    base = authorable_actions()
    if key is None:
        return base
    declared = character_action_params(key)
    variants = [
        variant_action(action, param)
        for action in base
        for param in declared.get(action, ())
        if param in VARIANT_PARAMS
    ]
    return (*base, *variants)


def all_offerable_actions() -> tuple[str, ...]:
    """Every action any character can be given — the base ten plus every variant in use.

    The superset the *schema* validates against. Per-character refusal happens where the team
    is known, because that is the only place a character's key is in hand.
    """
    table = _snapshot().get("character_action_params", {})
    variants = {
        variant_action(action, param)
        for per_action in table.values()  # type: ignore[union-attr]
        for action, params in per_action.items()
        if action in authorable_actions()
        for param in params
        if param in VARIANT_PARAMS
    }
    return (*authorable_actions(), *sorted(variants))


#: Which of gcsim's actions **is** a levelled talent, and which one.
#:
#: The two vocabularies are not the same and looked like they were: gcsim writes `skill`, the
#: catalogue stores `TalentType.ELEMENTAL_SKILL`. A builder labelling an action with the
#: character's own name for it needs the correspondence, and keying it by the *action* means
#: no client ever performs the mapping.
#:
#: **Three, not ten.** `dash`, `jump` and `walk` are not abilities at all. `charge`, `aim`,
#: `high_plunge` and `low_plunge` scale off the normal-attack talent but are **not** what the
#: game calls by that name — labelling a charged attack "Akara" would be a wrong name rather
#: than a missing one, so they keep their key. That is the same choice `weapon_symbols` makes
#: about the crossbow: absent beats plausible.
_ACTION_TALENTS: dict[str, TalentType] = {
    "attack": TalentType.NORMAL_ATTACK,
    "skill": TalentType.ELEMENTAL_SKILL,
    "burst": TalentType.ELEMENTAL_BURST,
}


def ability_names(talents: Iterable[Any]) -> dict[str, str]:
    """`action -> the character's own name for it`, for the three actions that are talents.

    Takes rows rather than a character so it needs no import from `app.models`, and skips a
    talent with no name rather than storing an empty string — absent is the honest answer and
    the caller already falls back to the action key.
    """
    by_type = {
        getattr(talent, "talent_type", None): getattr(talent, "name", "")
        for talent in talents
    }
    return {
        action: by_type[talent_type]
        for action, talent_type in _ACTION_TALENTS.items()
        if by_type.get(talent_type)
    }


def ability_icons(talents: Iterable[Any]) -> dict[str, str]:
    """`action -> the game's sprite basename for it`, for the three actions that are talents.

    The mirror of `ability_names`, and keyed the same way and for the same reason: gcsim writes
    `skill`, the catalogue stores `TalentType.ELEMENTAL_SKILL`, and a client that performed
    that mapping itself would be the second place it lived.

    A talent with no icon is skipped rather than published as an empty string — `CatalogueIcon`
    renders nothing for a null basename, and "absent" is the honest answer for a row the
    catalogue has no art for.
    """
    by_type = {
        getattr(talent, "talent_type", None): getattr(talent, "icon", None)
        for talent in talents
    }
    return {
        action: by_type[talent_type]
        for action, talent_type in _ACTION_TALENTS.items()
        if by_type.get(talent_type)
    }


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
    known = set(_snapshot()["characters"])  # type: ignore[arg-type]
    if key not in known:
        # Which elements exist is read from the snapshot, not stated. It used to say "six,
        # not seven — there is no Cryo Traveler", which the 2026-09-19 re-pin made false
        # (gcsim 25e6ef499). A sentence that names a number goes stale on exactly the event
        # it is meant to describe.
        have = sorted(
            k.removeprefix(_TRAVELER_BODIES[body])
            for k in known
            if k.startswith(_TRAVELER_BODIES[body])
        )
        msg = (
            f"gcsim has no {key!r} at pin {pinned_commit()[:12]}. The Traveler elements it "
            f"implements are: {', '.join(have)}."
        )
        raise GcsimKeyError(msg)
    return key
