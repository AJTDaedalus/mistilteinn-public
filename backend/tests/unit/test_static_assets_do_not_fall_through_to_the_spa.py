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


def test_the_spa_index_is_never_cached() -> None:
    """`index.html` is the only file Angular does not fingerprint.

    Every chunk carries its hash in its name and is cached hard on purpose. `index.html` is the
    **map** from the app to that build's chunk names, so a browser holding an old one asks a
    new release for chunks it no longer has — and the symptom is a single lazy route that will
    not open while every already-loaded page keeps working. Nothing is broken server-side,
    which is why every check answers 200.

    It carried no `Cache-Control` at all, so the browser applied its own heuristic.
    """
    block = re.search(r"location\s*=\s*/index\.html\s*\{(.*?)\n    \}", CONF, re.DOTALL)

    assert block is not None, "index.html has no location of its own, so it sets no headers"
    assert "no-cache" in block.group(1)


def test_the_index_location_repeats_the_security_headers() -> None:
    """**`add_header` in a location replaces the inherited set rather than adding to it.**

    So a location that adds `Cache-Control` and nothing else silently serves `index.html` — the
    document every page is delivered inside — with no CSP, no `X-Frame-Options` and no
    `nosniff`. That is a strictly worse trade than the caching bug it fixes, and it is invisible
    unless something asks.
    """
    block = re.search(r"location\s*=\s*/index\.html\s*\{(.*?)\n    \}", CONF, re.DOTALL)
    assert block is not None
    body = block.group(1)

    for header in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        assert header in body, f"{header} is inherited nowhere and would be dropped here"


def test_every_gcsim_asset_is_copied_into_the_bundle() -> None:
    """nginx can only serve what the build put there.

    The rules above stop a *present* asset falling through to the SPA. This is the other half:
    an asset the build never copied is missing for a different reason and produces the same
    symptom — and `angular.json` names each gcsim file individually rather than globbing the
    directory, so adding one to the image does not add it to the bundle.

    `BUILT_FROM` records which gcsim commit produced the wasm. It was written into the image
    and **not** copied here, so `/gcsim/BUILT_FROM` 404'd in production and "which gcsim is
    prod running?" had no answer from outside — asked, and unanswerable, right after a re-pin
    broke three deploys.
    """
    import json

    angular = json.loads(
        (Path(__file__).resolve().parents[3] / "frontend" / "angular.json").read_text(),
    )
    build = angular["projects"]["mistilteinn"]["architect"]["build"]["options"]
    globs = {
        asset["glob"]
        for asset in build["assets"]
        if isinstance(asset, dict) and asset.get("input") == "gcsim"
    }

    # `*.LICENSE.txt` is gcsim's MIT notice and Go's BSD one. Both artifacts are
    # redistributed to every visitor and both licences require the notice to travel with
    # them — see tests/unit/test_gcsim_licence_ships_with_the_wasm.py.
    assert globs == {"gcsim.wasm", "wasm_exec.js", "BUILT_FROM", "*.LICENSE.txt"}, (
        f"the bundle copies {sorted(globs)} out of gcsim/. A file the build skips is a 404 "
        f"in production, and a file nobody asked for is dead weight in a 40 MB directory."
    )
