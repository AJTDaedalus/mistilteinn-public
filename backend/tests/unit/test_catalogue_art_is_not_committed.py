"""The catalogue art is not in the repository, and production still gets it.

**Owner ruling, 2026-11-10:** the art is HoYoverse's, and the repository is going public under
AGPLv3, which is not a licence anyone here can grant over someone else's art. So
`frontend/public/icons/` is gitignored again, and `scripts/download_icons.py` fills it, locally
and on the prod host. `docs/DECISIONS.md` §4.

**The last time the art was ignored, production served none of it for weeks, silently.**
Nothing ran the script on the box, the image was built from a tree without the directory, and
nginx's SPA fallback answered every `/icons/*.webp` with `200 text/html`, which `CatalogueIcon`
hid exactly as designed. The previous version of this file asserted the art *was* committed,
because committing it was the fix for that.

So this file pins the replacement, end to end, without a database or a network:

- nothing under the icon directory is tracked, and git itself says the directory is ignored;
- `docker-compose.prod.yml` mounts the host directory into nginx;
- `deploy-prod.yml` runs the downloader **before** the rebuild (Cloudflare caches a 404 for
  hours, so a gap is expensive) and again after a re-seed, and probes an icon's content type;
- the downloader asks for the icons no catalogue row names, Mora among them.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from app.services import element_symbols, weapon_symbols
from app.services.planner.service import MORA_ICON
from scripts import download_icons

REPO = Path(__file__).resolve().parents[3]
ICONS = REPO / "frontend" / "public" / "icons"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-prod.yml"
PROD_COMPOSE = REPO / "docker-compose.prod.yml"

#: `git check-ignore`'s answers. Any other status, 128 above all, is an error, and an error is
#: not an answer.
_IGNORED = 0
_NOT_IGNORED = 1


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the repository. Fixed argv, absolute binary, never a shell."""
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        [shutil.which("git") or "git", *args],
        cwd=REPO, capture_output=True, text=True, check=False,
    )


def _deploy_steps(job: str) -> list[dict[str, Any]]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"][job]["steps"]


def _index(steps: list[dict[str, Any]], needle: str) -> int:
    hits = [i for i, step in enumerate(steps) if needle in step.get("run", "")]
    assert hits, f"no step runs {needle!r}"
    return hits[0]


def test_no_catalogue_art_is_tracked() -> None:
    """By extension rather than by directory, so art committed anywhere else is caught too.

    Every `.webp` this repository ever held was catalogue art, and `references/` carried three
    pieces of game art as committed exceptions until the same ruling.
    """
    listing = _git("ls-files", "*.webp", "references/*.png")
    assert listing.returncode == 0, listing.stderr
    tracked = [line for line in listing.stdout.splitlines() if line]
    assert not tracked, f"{len(tracked)} art files are committed: {tracked[:5]}"


def test_the_icon_directory_is_gitignored() -> None:
    """Git itself answers, rather than a substring search over `.gitignore`.

    **`== 0`, and a separate check that git could answer at all.** `check-ignore` exits 128
    when it cannot run, inside a container with no `.git` for example, and a guard that read
    128 as an answer would be green wherever it checked nothing.
    """
    result = _git("check-ignore", "-q", "frontend/public/icons/UI_AvatarIcon_Ayaka.webp")
    assert result.returncode in (_IGNORED, _NOT_IGNORED), (
        f"`git check-ignore` could not answer (exit {result.returncode}): "
        f"{result.stderr.strip() or 'no stderr'}. A check that could not run is not a pass."
    )
    assert result.returncode == _IGNORED, "the icon directory is not ignored"


def test_prod_nginx_mounts_the_vendored_directory() -> None:
    """The image never carries the art, so without this mount prod serves none."""
    assert "./frontend/public/icons:/usr/share/nginx/html/icons:ro" in PROD_COMPOSE.read_text()


def test_the_deploy_mounts_the_directory_the_downloader_writes() -> None:
    """Derived from the script's own `OUT`, so moving it fails here rather than in prod.

    The backend image keeps its code at `/app`, so `<root>/frontend/public/icons` resolves to
    `/frontend/public/icons` inside the container. A mount anywhere else would download every
    icon into a container that is deleted a second later, and report success.
    """
    inside = "/" + str(download_icons.OUT.relative_to(REPO))
    for job in ("deploy", "reseed"):
        steps = _deploy_steps(job)
        runs = [s["run"] for s in steps if "scripts.download_icons" in s.get("run", "")]
        for step in runs:
            assert f'frontend/public/icons:{inside}"' in step, f"{job} mounts the wrong path"
            assert "mkdir -p frontend/public/icons" in step, (
                f"{job} lets Docker create the bind source, as root, and the download then "
                "cannot write into it"
            )


def test_the_deploy_vendors_before_it_rebuilds() -> None:
    steps = _deploy_steps("deploy")
    assert _index(steps, "scripts.download_icons") < _index(steps, "$COMPOSE up -d --build"), (
        "art vendored after the rebuild leaves a window of 404s, which Cloudflare caches"
    )


def test_the_deploy_vendors_again_with_the_new_image() -> None:
    """The pre-rebuild pass runs the old image, which cannot know about an icon this deploy added.

    Mora was missing from prod after the first deploy without committed art for exactly that
    reason.
    """
    steps = _deploy_steps("deploy")
    rebuild = _index(steps, "$COMPOSE up -d --build")
    later = [
        i for i, step in enumerate(steps)
        if i > rebuild and "scripts.download_icons" in step.get("run", "")
    ]
    assert later, "nothing vendors art with the rebuilt backend image"
    probe = _index(steps, "icons/UI_AvatarIcon_Ayaka.webp")
    assert later[0] < probe, "the probe must check what the post-rebuild pass fetched"
    assert MORA_ICON in steps[probe]["run"], "the probe should check an icon no row names"


def test_a_reseed_vendors_art_for_what_it_added() -> None:
    steps = _deploy_steps("reseed")
    assert _index(steps, "scripts.seed_db") < _index(steps, "scripts.download_icons")


def test_the_deploy_checks_the_content_type_of_an_icon() -> None:
    """A 200 cannot tell a file from the SPA fallback. Only the type can."""
    steps = _deploy_steps("deploy")
    at = _index(steps, "icons/UI_AvatarIcon_Ayaka.webp")
    assert "image/webp" in steps[at]["run"]
    assert at > _index(steps, "$COMPOSE up -d --build"), "the probe must run against the new stack"


class _NoRows:
    """A session over an empty catalogue: whatever `wanted()` returns is what no row names."""

    async def __aenter__(self) -> _NoRows:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=list), all=list)


@pytest.fixture
def per_entity_icons(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    monkeypatch.setattr(download_icons, "async_session_factory", _NoRows)
    return {basename for basename, _ in asyncio.run(download_icons.wanted())}


@pytest.mark.parametrize(
    "basename",
    [MORA_ICON, *weapon_symbols.all_symbols(), *element_symbols.all_symbols()],
)
def test_the_downloader_asks_for_icons_no_row_names(
    per_entity_icons: set[str], basename: str,
) -> None:
    """These were on disk because someone committed them, which a fresh clone no longer has.

    Mora is the one a fresh download found missing: the planner draws it on every bill, it was
    committed by hand, and the downloader had never been told about it.
    """
    assert basename in per_entity_icons
