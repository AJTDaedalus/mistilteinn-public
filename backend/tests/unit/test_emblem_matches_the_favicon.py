"""The emblem exists twice, and the two copies must stay one mark.

`src/app/shared/emblem/emblem.ts` draws the Mitya ornament from CSS custom properties, so it
follows the palette. `public/favicon.svg` cannot: a favicon renders **outside the app**, where
no custom property exists to resolve, so it carries literal colours and duplicates the
geometry.

Two copies of a mark is two marks. This is what stops the duplicate becoming a *different*
emblem the next time either one moves.

Written in Python rather than in the frontend suite for a practical reason and a precedent:
the browser tsconfig has no Node types, so a spec cannot read a file off disk — and this repo
already checks cross-file agreement this way in `test_wgsl_matches_the_host.py`, which
compares the WGSL shader's struct against the TypeScript field offsets.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
COMPONENT = FRONTEND / "src" / "app" / "shared" / "emblem" / "emblem.ts"
FAVICON = FRONTEND / "public" / "favicon.svg"

_CIRCLE = re.compile(r'<circle[^>]*?cx="([\d.]+)"[^>]*?cy="([\d.]+)"[^>]*?r="([\d.]+)"')
_ELLIPSE = re.compile(r'<ellipse[^>]*?rx="([\d.]+)"[^>]*?ry="([\d.]+)"')


def _nodes(markup: str) -> set[tuple[str, str, str]]:
    return set(_CIRCLE.findall(markup))


def test_both_copies_place_the_same_nodes():
    """Every gem and bead, at the same place and the same size, in both files."""
    component, favicon = _nodes(COMPONENT.read_text()), _nodes(FAVICON.read_text())

    assert component, "no circles found in the component — has the template changed shape?"
    only_component = sorted(component - favicon)
    only_favicon = sorted(favicon - component)
    drift = (
        f"the emblem and the favicon have drifted.\n"
        f"  only in emblem.ts:   {only_component}\n"
        f"  only in favicon.svg: {only_favicon}"
    )
    assert not only_component, drift
    assert not only_favicon, drift


def test_both_copies_draw_the_same_orbits():
    component = set(_ELLIPSE.findall(COMPONENT.read_text()))
    favicon = set(_ELLIPSE.findall(FAVICON.read_text()))

    assert component == favicon, f"orbit geometry differs: {component} vs {favicon}"
    assert len(_ELLIPSE.findall(FAVICON.read_text())) == 3, "the mark is three orbits"


def test_the_favicon_carries_literal_colours_and_the_component_does_not():
    """Each is right for where it renders, and neither should drift into the other's habit.

    A `var(--brass)` in the favicon resolves to nothing in a browser tab. A hex in the
    component is a second palette, drifting from `_tokens.scss` the moment either changes.
    """
    assert "var(--" not in FAVICON.read_text(), (
        "favicon.svg uses a CSS custom property, which resolves to nothing outside the app"
    )
    template = COMPONENT.read_text()
    template = template[template.index("<svg") : template.index("</svg>")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", template), (
        "emblem.ts hard-codes a colour; it should read the token so the palette has one home"
    )


def test_the_favicon_is_linked_from_the_document():
    """A mark nobody points at is a mark nobody sees — the shape that hid the unreachable
    routes A.3's review caught."""
    index = (FRONTEND / "src" / "index.html").read_text()
    assert 'href="favicon.svg"' in index
    assert 'type="image/svg+xml"' in index
