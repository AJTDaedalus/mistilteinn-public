"""A missing static asset must 404, not answer `200 text/html`.

**This is the mechanism behind the incident the art commit describes, and it outlived the
fix.** Committing `frontend/public/icons/` put the files in the image, but the SPA fallback
that hid their absence was still in place — so the *next* gap (a patch's new characters not
yet vendored, or a request landing mid-deploy) would reproduce it exactly.

Two things go wrong when `/icons/foo.webp` falls through to `index.html`:

1. **Caches are poisoned for hours.** Cloudflare classifies by extension: it sees `.webp`,
   treats the HTML body as a static asset and stores it. Measured 2026-08-28 —
   `UI_AvatarIcon_Ayaka.webp` served `content-type: text/html` at `age=4422` while the origin
   had the file, because a pre-deploy probe had been cached under `max-age=14400`.

2. **The status code stops carrying information.** A basename that exists and one that does
   not both return `200`, so the obvious check —  `curl -o /dev/null -w '%{http_code}'` — is
   green no matter what. That is why production went months with no art and every layer
   reporting success. Only `content-type` differed.

The config is parsed as text rather than by running nginx: the assertion is about which
`location` block owns the path, which is a property of the file, and a test that needed a
container would not run in the unit lane at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONF = (
    Path(__file__).resolve().parents[3] / "frontend" / "nginx.prod.conf"
).read_text()

#: Directories of vendored static files. Anything added here needs its own `=404` location.
#:
#: **`/gcsim/` was added to the config and not to this tuple**, in the very change that added
#: it — so deleting that `location` block would have left this suite green while production
#: served `200 text/html` for `wasm_exec.js` again, which is the exact regression that change
#: exists to prevent. The same diff extended `test_gcsim_pin_is_single.py` for the same reason
#: and did not think to look here.
ASSET_PREFIXES = ("/icons/", "/gcsim/")


def _location_body(prefix: str) -> str | None:
    """The body of `location <prefix> { … }`, or None when no such block exists."""
    match = re.search(
        rf"location\s+{re.escape(prefix)}\s*\{{(.*?)\n    \}}", CONF, re.DOTALL,
    )
    return match.group(1) if match else None


@pytest.mark.parametrize("prefix", ASSET_PREFIXES)
def test_the_asset_directory_has_its_own_location(prefix: str) -> None:
    assert _location_body(prefix) is not None, (
        f"no `location {prefix}` block — requests fall through to the SPA, which answers "
        f"200 text/html for a file that is not there"
    )


@pytest.mark.parametrize("prefix", ASSET_PREFIXES)
def test_a_missing_asset_is_a_404(prefix: str) -> None:
    body = _location_body(prefix)
    assert body is not None
    assert "=404" in body, (
        f"`location {prefix}` does not end in `=404`, so a missing file is served as "
        f"index.html under an asset URL"
    )
    # `$uri` must still be tried first, or the block 404s everything including real files.
    assert "$uri" in body, f"`location {prefix}` never tries the file itself"


def test_the_spa_fallback_is_declared_after_the_asset_locations() -> None:
    """`location /` is a prefix match, so nginx's longest-prefix rule already wins.

    Asserted anyway because the ordering is what a reader checks, and a future edit that
    replaced the asset block with a regex location *would* become order-dependent.
    """
    fallback = CONF.index("location / {")
    for prefix in ASSET_PREFIXES:
        assert CONF.index(f"location {prefix}") < fallback, (
            f"`location {prefix}` is declared after the SPA fallback"
        )


def test_the_spa_fallback_still_exists() -> None:
    """Guards the guard: an Angular app whose deep links 404 is broken in the other direction.

    `/builds` must reach `index.html`; `/icons/x.webp` must not.
    """
    assert "try_files $uri $uri/ /index.html;" in CONF
