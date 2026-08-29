"""The vendored catalogue art is in the repository, and stays there.

**This exists because the previous arrangement failed silently in production.**
`frontend/public/icons/` was gitignored on the reasoning that "a repository is not a CDN",
with `scripts/download_icons.py` named as the reproduction. Nothing ever ran that script on
the prod box, and nothing could have noticed: `Dockerfile.prod` does `COPY . .` from a tree
where the directory did not exist, nginx's SPA fallback answered every `/icons/*.webp` with
`200 text/html`, and `CatalogueIcon` hid each failed `<img>` exactly as it was designed to.
The site served no art at all and every layer reported success.

The measurement that settled it (2026-08-28, `docs/DECISIONS.md`): **446 distinct files,
9.6 MB** — against fairy's committed **207 files at 27 MB**.

That was the set as first committed; it is **907 files at 33 MB** now, with the character
portraits and the enemy art since. The decision is the same and the number is not, which is
why the assertions below are a floor and a git query rather than a count.

The rule that ignored them compared *file counts* and concluded this set was the heavier of
the two. It is roughly a third of it.

So the art is committed, and these tests are the thing that would have caught the silence.
They are deliberately DB-free — `download_icons.py --check` is the audit that knows what the
catalogue names, and it needs a seeded database. This one only asks whether what we vendored
is actually in the repository, which is the question CI can always answer.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ICONS = REPO / "frontend" / "public" / "icons"

#: `git check-ignore`'s two *answers*. Any other status is an error, and an error is not an
#: answer — see the assertion that uses them.
_IGNORED = 0
_NOT_IGNORED = 1

#: A floor, not the count. Pinning the exact number would fail every time a patch adds a
#: character, which trains people to edit the assertion rather than read it. The failure this
#: guards against is the directory being *empty or absent*, and any floor near the real size
#: catches that.
MINIMUM = 400


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the repository. Fixed argv, absolute binary, never a shell."""
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        [shutil.which("git") or "git", *args],
        cwd=REPO, capture_output=True, text=True, check=False,
    )


def test_the_icon_directory_exists_and_is_populated() -> None:
    assert ICONS.is_dir(), f"{ICONS} is missing — run `python -m scripts.download_icons`"
    assert len(list(ICONS.glob("*.webp"))) >= MINIMUM


def test_every_vendored_icon_is_tracked_by_git() -> None:
    """An icon on one developer's disk is an icon production does not have.

    This is the assertion that fails the moment somebody re-adds the ignore rule: the files
    keep working locally and stop existing for everyone else, which is precisely the shape
    that went unnoticed before.
    """
    listing = _git("ls-files", "frontend/public/icons")
    assert listing.returncode == 0, listing.stderr
    tracked = {Path(line).name for line in listing.stdout.splitlines() if line}
    on_disk = {path.name for path in ICONS.glob("*.webp")}

    assert on_disk, "no icons on disk"
    untracked = sorted(on_disk - tracked)
    assert not untracked, (
        f"{len(untracked)} vendored icons are not committed, so production will not have "
        f"them: {untracked[:5]}"
    )


def test_the_icon_directory_is_not_gitignored() -> None:
    """`check-ignore` asks git itself rather than parsing `.gitignore` by hand.

    A negation pattern, a nested `.gitignore`, or a rule written against a parent directory
    all produce the same outcome and none of them are visible in a substring search.
    """
    probe = "frontend/public/icons/UI_AvatarIcon_Ayaka.webp"
    result = _git("check-ignore", "-q", probe)

    # **`== 1`, not `!= 0`.** `check-ignore` exits 0 when the path is ignored, 1 when it is
    # not, and **128 on error** — not a repository, git missing, bad arguments. `!= 0` counted
    # 128 as a pass, so this guard went green wherever it could not run at all: the documented
    # `docker compose run --rm backend pytest` mounts `/app` with no `.git`, and the check
    # against re-adding the ignore rule would have reported clean while checking nothing.
    # That is precisely the green-by-absence shape this file exists to prevent, in the file
    # that exists to prevent it.
    assert result.returncode != _IGNORED, (
        f"{probe} is ignored — production would ship without art"
    )
    assert result.returncode == _NOT_IGNORED, (
        f"`git check-ignore` could not answer (exit {result.returncode}): "
        f"{result.stderr.strip() or 'no stderr'}. A check that could not run is not a pass."
    )


@pytest.mark.parametrize(
    "name",
    [
        "UI_AvatarIcon_",
        "UI_Gacha_AvatarIcon_",
        "UI_EquipIcon_",
        "UI_RelicIcon_",
        "UI_MonsterIcon_",
    ],
)
def test_every_catalogue_family_is_present(name: str) -> None:
    """Each source draws from its own basename family, and each is checked.

    A run that fetched only some of them leaves a UI that looks half-finished rather than
    broken, so the count floor above would not catch it — **and did not**: the enemy icons
    are 341 files, so losing all of them leaves 566, comfortably above `MINIMUM`, with every
    family this test knew about still resolving. Green, and no art on the codex page.

    The list grows with `download_icons.SOURCES`; the character portraits are a second family
    from the same source and are named separately for the same reason.
    """
    assert list(ICONS.glob(f"{name}*.webp")), f"no {name}* icons vendored"
