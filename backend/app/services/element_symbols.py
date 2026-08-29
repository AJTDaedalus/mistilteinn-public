"""The vision emblem for an element — Genshin's own flame, droplet, leaf and so on.

## Where these come from, and why no game-data search finds them

nanoka serves them under the element's plain name — `Pyro.webp`, `Anemo.webp` — with **no
prefix at all**, which is why a sweep of `UI_*` shapes returns nothing. They are a
nanoka-authored family keyed by the strings its own UI switches on, not a slice of the game's
assets: the real internal names, from `ElementStateExcelConfigData`, are
`UI_Buff_Element_Fire/Water/Grass/Elect/Wind/Frost/Roach`, and **every one of those 404s
here**. Deriving from upstream data would have found the wrong names.

`docs/RESEARCH_element_symbols.md` records the probe, the negative sweep of the game's own
vocabulary, and the limits of a probe-based negative.

Verified by opening them, not by trusting the filenames: seven 64×64 emblems, each in its
element's colour, uploaded together. A basename that merely *sounds* right is the failure this
repo names as fairy's worst, and this CDN answers `200 text/html` for files it does not have —
so `download_icons` checks the content type rather than the status.

## An allowlist, not `element.value`

The mapping is one-to-one and could be `f"{element}.webp"`. It is written out instead, because
that string would then be *constructed* from any element-shaped input: a re-pin adding an
eighth vision would silently request art nobody has vendored, and the card would show a
broken mark rather than nothing.

**`Physical` is not here and must not be.** It is a damage type, not a vision — the
ZZZ-shaped trap `DESIGN §2.6` names — and it has no emblem in this family either. The literal
`"None"` two Traveler rows carry likewise resolves to nothing to draw.
"""

from __future__ import annotations

from app.models.enums import Element

#: `Element` → the nanoka basename of its vision emblem. Case-sensitive: `pyro` 404s.
_SYMBOLS: dict[Element, str] = {
    Element.ANEMO: "Anemo",
    Element.CRYO: "Cryo",
    Element.DENDRO: "Dendro",
    Element.ELECTRO: "Electro",
    Element.GEO: "Geo",
    Element.HYDRO: "Hydro",
    Element.PYRO: "Pyro",
}


def symbol_for(element: Element | str | None) -> str | None:
    """The emblem's basename, or `None` when there is nothing to draw.

    Accepts the enum or the source's spelling, since a summary schema holds the enum and a
    caller may hold either. Anything unrecognised — `"None"`, `"Physical"`, a vision from a
    future patch — is `None` rather than a guessed basename.
    """
    if element is None:
        return None
    if not isinstance(element, Element):
        try:
            element = Element(str(element))
        except ValueError:
            return None
    return _SYMBOLS.get(element)


def all_symbols() -> tuple[str, ...]:
    """Every emblem basename, for the icon downloader to vendor."""
    return tuple(_SYMBOLS.values())


def all_visions() -> tuple[tuple[str, str], ...]:
    """Every vision and its emblem, in the order the game lists them.

    For a filter bar: a page offering vision chips needs the seven **and** their art, and
    building `f"{element}.webp"` client-side is the thing the module docstring argues against
    one level down. The allowlist is here; publishing it costs one endpoint and means the
    client never constructs a basename.

    Physical and the literal `"None"` are absent for the reasons above — they are not visions
    and have no emblem in this family.
    """
    return tuple((element.value, symbol) for element, symbol in _SYMBOLS.items())
