"""Telling the Travelers apart.

`docs/RESEARCH_traveler_identity.md`. The catalogue holds **sixteen** rows named `Traveler` —
seven elements for each of two bodies, plus two unreleased bodies with no element at all — and
`characters.name` is the literal string `"Traveler"` for every one of them.

## The icon is the only signal there is

There is no gender column, no title, no disambiguating field, and upstream has none either:
nanoka's index publishes one `en` value (`"Traveler"`) and one `desc` for all sixteen. The
**icon basename** is the whole of it — `UI_AvatarIcon_PlayerBoy` against
`UI_AvatarIcon_PlayerGirl`.

That is why this is keyed on the icon rather than on anything more comfortable, and why
`test_traveler.py` asserts both basenames are still present in the committed capture: a nanoka
bump that renames them would silently collapse sixteen names back into one, and the roster tab
would go back to offering sixteen checkboxes all announcing *"I have Traveler"*.

## Derived at the boundary, never stored

A display name is presentation, so it is computed where a schema is built — the same rule
`element_symbols` and `weapon_symbols` already follow. Storing it would mean a migration every
time a body or an element is added, and a second copy of the truth to keep in step with the
first.

## What this deliberately does not do

It does not model the Traveler *correctly*. The game has one Traveler per account, of one body,
with elements unlocked by progress; this catalogue has sixteen separate characters and the
roster asks sixteen separate ownership questions. Naming them is what makes that mess legible;
fixing it is a schema change entangled with the already-recorded "builds sharing one artifact
set" decision, and the research doc says so rather than pretending otherwise.
"""

from __future__ import annotations

#: Icon basename → the name the game gives that body. Read off the seeded catalogue, where
#: these two are carried by all sixteen `Traveler` rows and by nothing else.
#:
#: **Aether and Lumine are the game's own names for them**, used in gcsim's character keys
#: (`aetheranemo`, `lumineanemo`) — so this repo already spells them this way where it has to
#: name a body at all. `gcsim_keys._TRAVELER_BODIES` maps the same distinction from the id
#: side; this maps it from the art, because a schema has the icon and not always the id.
TRAVELER_BODIES = {
    "UI_AvatarIcon_PlayerBoy": "Aether",
    "UI_AvatarIcon_PlayerGirl": "Lumine",
}

#: The one name that is ambiguous. Checked as well as the icon so that a future character who
#: happens to reuse the art — a story double, an alternate — is not renamed behind its back.
TRAVELER_NAME = "Traveler"


def body_of(icon: str | None) -> str | None:
    """`"Aether"`, `"Lumine"`, or None for a character that is not a Traveler."""
    return TRAVELER_BODIES.get(icon or "")


def display_name(
    *, name: str, icon: str | None = None, element: str | None = None,
) -> str:
    """The name to put on a card. Every character but a Traveler is returned unchanged.

        Traveler + PlayerGirl + Dendro  →  "Traveler (Lumine · Dendro)"
        Traveler + PlayerBoy  + None    →  "Traveler (Aether)"
        Nahida                          →  "Nahida"

    **The element is inside the parentheses rather than appended**, because the pair is one
    identity: `Traveler (Lumine) · Dendro` reads as a Lumine card that happens to be Dendro,
    and `Traveler (Lumine · Dendro)` reads as the character the player actually has. The
    element chip beside it is not a substitute — two of the sixteen have no element, and seven
    pairs share one.
    """
    body = body_of(icon)
    if name != TRAVELER_NAME or body is None:
        return name
    inside = f"{body} · {element}" if element else body
    return f"{name} ({inside})"
