"""Fetch + cache YuanShenResources files at a pinned commit (read-only cartography).

    cd backend && python -m scripts.yuanshen.fetch --lang en --merge
    cd backend && python -m scripts.yuanshen.fetch \
        --file ExcelBinOutput/ReliquaryExcelConfigData.json
    cd backend && python -m scripts.yuanshen.fetch --tree ExcelBinOutput
    cd backend && python -m scripts.yuanshen.fetch --drift

Ported from fairy's `scripts/dimbreath/fetch.py`, keeping the three properties that made
that toolkit trustworthy and replacing everything host- or game-specific:

* **Pinned commit SHA**, read from `app/data/yuanshen/schema/provenance.json`, so every
  file in a run comes from one commit and a re-run is reproducible. `--drift` compares it
  against the live branch.
* **Local byte cache**, keyed by `(sha, path)`. `TextMapEN.json` is **54 MB**; it is
  downloaded at most once per pinned commit and never goes stale silently, because a new
  SHA is a new cache directory.
* **An anchor assertion** on the TextMap, so a fetch that returns something structurally
  valid but wrong fails loudly rather than seeding a plausible database.

Two differences from the ZZZ original, both established by probing the repository rather
than assumed (see `docs/LOG_mistilteinn.md`, E.1):

1. **The host is GitLab**, so raw access is the Files API with a URL-encoded path
   (`TextMap%2FTextMapEN.json`) rather than a `raw/commit/<sha>/<path>` URL, and listing a
   directory is the paginated Tree API.
2. **The TextMap layering is a different shape, and merging is still mandatory.** ZZZ
   published `TextMap_<LANG>TemplateTb.json` plus an `..OverwriteTemplateTb.json` whose
   entries won. Genshin publishes `TextMap<LANG>.json` and `TextMap_Medium<LANG>.json`,
   and measured at the pinned commit those two are **almost disjoint**: 589,892 and
   231,397 keys sharing only 363, with identical values wherever they do overlap. So the
   rule is a **union**, not an overwrite — and it is not optional, because the names
   Chunk F and Chunk H need live **only in the `_Medium` layer**. `AvatarExcelConfigData`
   id 10000002 resolves to "Kamisato Ayaka" through `_Medium` alone; reading the 54 MB
   `TextMapEN.json` by itself — the obvious thing to do — yields no character or weapon
   names at all, silently.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# This file lives at backend/scripts/yuanshen/fetch.py.
_BACKEND = Path(__file__).resolve().parents[2]
YUANSHEN_ROOT = _BACKEND / "app" / "data" / "yuanshen"
SCHEMA_DIR = YUANSHEN_ROOT / "schema"
CACHE_DIR = YUANSHEN_ROOT / "cache"
SNAPSHOT_DIR = YUANSHEN_ROOT / "snapshot"
PROVENANCE_PATH = SCHEMA_DIR / "provenance.json"

#: Identifies the project to GitLab. nanoka 403s urllib's default User-Agent (C.2's
#: operational note); GitLab does not, but sending one is politer and one less thing to
#: rediscover.
USER_AGENT = "mistilteinn-yuanshen-cartography/1.0 (+read-only)"

#: `TextMapEN.json` is 54 MB and the tree endpoints are slow on a 1,935-entry directory.
TIMEOUT_SECONDS = 300


class YuanShenFetchError(RuntimeError):
    """A fetch failed, or returned something the toolkit will not use."""


# -- Provenance ---------------------------------------------------------------------

def load_provenance() -> dict[str, Any]:
    """The pinned-provenance record: project, branch, commit SHA, access URLs."""
    with PROVENANCE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def pinned_sha() -> str:
    """The commit every fetch defaults to."""
    return str(load_provenance()["pinned_commit_sha"])


def live_branch_sha(branch: str | None = None) -> str:
    """The current head of the tracked branch, for `--drift`."""
    provenance = load_provenance()
    branch = branch or provenance["branch"]
    url = provenance["access"]["branch_api"].format(branch=branch)
    return str(json.loads(_http_get(url))["commit"]["id"])


# -- Raw fetch + cache --------------------------------------------------------------

def _http_get(url: str) -> bytes:
    if not url.startswith("https://"):
        msg = f"refusing non-https URL: {url!r}"
        raise YuanShenFetchError(msg)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - https-guarded above
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        msg = f"HTTP {exc.code} fetching {url}"
        raise YuanShenFetchError(msg) from exc
    except urllib.error.URLError as exc:
        msg = f"network error fetching {url}: {exc.reason}"
        raise YuanShenFetchError(msg) from exc


def cache_path(path: str, sha: str) -> Path:
    """Where a repo file's bytes live locally.

    Keyed by the SHA, so a re-pin is a new directory rather than a stale hit — the cache
    can never quietly serve one commit's data for another's.
    """
    return CACHE_DIR / sha[:12] / path.replace("/", "__")


def fetch_raw(path: str, sha: str | None = None, *, refresh: bool = False) -> bytes:
    """A repo file's raw bytes at a pinned SHA, cached under `cache/<sha12>/`.

    `path` is repo-relative, e.g. `TextMap/TextMapEN.json`.
    """
    sha = sha or pinned_sha()
    cached = cache_path(path, sha)
    if cached.exists() and not refresh:
        return cached.read_bytes()

    url = load_provenance()["access"]["raw_commit"].format(
        # GitLab's Files API takes the path as a single URL-encoded segment, so the `/`
        # separators have to be escaped too — `safe=""` is doing the work here.
        path=urllib.parse.quote(path, safe=""),
        sha=sha,
    )
    data = _http_get(url)
    cached.parent.mkdir(parents=True, exist_ok=True)
    # Written through a temp file and renamed. A Ctrl-C part way through the 54 MB
    # TextMapEN.json would otherwise leave a truncated file that every later call happily
    # serves from disk, with `rm -rf cache/` as the only recovery.
    partial = cached.with_suffix(cached.suffix + ".partial")
    partial.write_bytes(data)
    partial.replace(cached)
    return data


def fetch_json(path: str, sha: str | None = None, *, refresh: bool = False) -> Any:
    """Fetch and parse a JSON repo file at a pinned SHA (cached)."""
    return json.loads(fetch_raw(path, sha, refresh=refresh))


def list_tree(path: str, sha: str | None = None) -> list[dict[str, Any]]:
    """Every entry under `path`, following GitLab's pagination.

    Not cached: it is small, and E.3 turns its result into a committed catalog. The
    pagination matters — `ExcelBinOutput/` holds **1,935** files and the default page size
    is 20, so a single-page read would silently see 1% of the repository.
    """
    sha = sha or pinned_sha()
    template = load_provenance()["access"]["tree_api"]
    page_size = _page_size(template)
    entries: list[dict[str, Any]] = []
    page = 1
    while True:
        url = template.format(sha=sha, path=urllib.parse.quote(path, safe=""), page=page)
        batch = json.loads(_http_get(url))
        entries.extend(batch)
        if len(batch) < page_size:
            return entries
        page += 1


def _page_size(template: str) -> int:
    """The `per_page` the tree URL asks for, read out of the URL rather than duplicated.

    "Stop when a page comes back short" is only correct against the size actually
    requested. Holding that number as a second constant beside the template made the two
    silently separable: lower `per_page` in `provenance.json` and the first page would end
    the loop, so `build_table_catalog` would catalog 20 of 1,935 tables and report success —
    the exact failure pagination is here to prevent.
    """
    match = re.search(r"[?&]per_page=(\d+)", template)
    if match is None:
        msg = f"the tree_api template does not set per_page: {template!r}"
        raise YuanShenFetchError(msg)
    return int(match.group(1))


# -- TextMap ------------------------------------------------------------------------

def textmap_path(lang: str, *, medium: bool = False) -> str:
    """The repo path for a language's TextMap.

    There is exactly one layer. `_Medium` is a **different, smaller file** (20 MB against
    54 MB for EN), not an overwrite of the full one — see `load_textmap`.
    """
    lang = lang.upper()
    return f"TextMap/TextMap_Medium{lang}.json" if medium else f"TextMap/TextMap{lang}.json"


def load_textmap(
    lang: str = "en", sha: str | None = None, *, refresh: bool = False,
) -> dict[str, str]:
    """The effective TextMap for a language: `{hash: display string}`, **both layers**.

    fairy's equivalent said "always merges — never return the base alone", because ZZZ's
    beta content lived only in the overwrite layer. The same warning applies here for a
    different reason: the two Genshin files are near-disjoint partitions rather than
    layers, and every character and weapon name is in `_Medium`. A caller that wants one
    layer on its own can say so with `load_textmap_layer`; nothing in this toolkit should.
    """
    full = load_textmap_layer(lang, sha, medium=False, refresh=refresh)
    medium = load_textmap_layer(lang, sha, medium=True, refresh=refresh)
    # `full` last only as a tie-break; the 363 shared keys hold identical values at the
    # pinned commit, so the order is documentation rather than a decision.
    return {**medium, **full}


def load_textmap_layer(
    lang: str = "en", sha: str | None = None, *, medium: bool = False, refresh: bool = False,
) -> dict[str, str]:
    """One TextMap file, unmerged. Use `load_textmap` unless you are comparing layers."""
    return fetch_json(textmap_path(lang, medium=medium), sha, refresh=refresh)


def layer_of(key: str | int, lang: str = "en", sha: str | None = None) -> str | None:
    """Which file a hash came from: `"full"`, `"medium"`, or None.

    The diagnostic for "the name resolves for me and not in CI": almost every entity name
    is `_Medium`-only.
    """
    key = str(key)
    if key in load_textmap_layer(lang, sha, medium=False):
        return "full"
    if key in load_textmap_layer(lang, sha, medium=True):
        return "medium"
    return None


# -- CLI ----------------------------------------------------------------------------

def _cmd_textmap(lang: str, sha: str | None, *, refresh: bool = False) -> int:
    from scripts.yuanshen.anchors import check_textmap_anchors  # noqa: PLC0415 - CLI-only

    full = load_textmap_layer(lang, sha, medium=False, refresh=refresh)
    medium = load_textmap_layer(lang, sha, medium=True, refresh=refresh)
    textmap = load_textmap(lang, sha)
    print(f"lang={lang.upper()}  sha={(sha or pinned_sha())[:12]}")
    print(f"  TextMap{lang.upper()}        = {len(full):,} keys")
    print(f"  TextMap_Medium{lang.upper()} = {len(medium):,} keys")
    print(f"  union            = {len(textmap):,} keys "
          f"({len(set(full) & set(medium)):,} shared)")
    if lang.lower() != "en":
        print("  (anchors are EN-only; nothing asserted)")
        return 0

    failures = check_textmap_anchors(textmap)
    for line in failures:
        print(f"  ANCHOR FAILED — {line}", file=sys.stderr)
    if failures:
        return 1
    print("  anchors OK — the TextMap resolves the values the nanoka payloads name")
    return 0


def _cmd_file(path: str, sha: str | None, *, refresh: bool = False) -> int:
    data = fetch_json(path, sha, refresh=refresh)
    if isinstance(data, dict):
        print(f"{path}: dict, {len(data):,} keys")
    elif isinstance(data, list):
        print(f"{path}: list, {len(data):,} rows")
        if data and isinstance(data[0], dict):
            print(f"  first-row columns ({len(data[0])}): {list(data[0])[:12]} …")
    else:
        print(f"{path}: {type(data).__name__}")
    return 0


def _cmd_tree(path: str, sha: str | None) -> int:
    entries = list_tree(path, sha)
    print(f"{path}: {len(entries):,} entries")
    for entry in entries[:20]:
        print(f"  {entry['type']:5} {entry['name']}")
    if len(entries) > 20:  # noqa: PLR2004 - a display cutoff, not a rule
        print(f"  … {len(entries) - 20:,} more")
    return 0


def _cmd_drift(sha: str | None) -> int:
    provenance = load_provenance()
    pinned = sha or pinned_sha()
    live = live_branch_sha()
    print(f"branch = {provenance['branch']}")
    print(f"pinned = {pinned}")
    print(f"live   = {live}")
    if pinned == live:
        print("in sync")
        return 0
    print(f"DRIFT: the branch has advanced (checked {datetime.now(UTC).isoformat()})")
    print("Re-pinning is a deliberate, reviewed step: update provenance.json, rebuild the")
    print("snapshot, and check the anchors in the same commit.")
    return 2


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the requested command."""
    parser = argparse.ArgumentParser(
        description="Fetch YuanShenResources files at a pinned commit (read-only).",
    )
    parser.add_argument("--lang", default="en", help="TextMap language code (default: en)")
    parser.add_argument(
        "--merge",
        action="store_true",
        help="merge both TextMap layers and assert the anchors",
    )
    parser.add_argument(
        "--textmap", action="store_true", help="the same thing, under its accurate name",
    )
    parser.add_argument("--file", help="fetch one repo file (cached) and print its shape")
    parser.add_argument("--tree", help="list a repo directory at the pinned commit")
    parser.add_argument("--drift", action="store_true", help="compare the pin against live")
    parser.add_argument("--sha", help="override the pinned commit SHA")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download rather than reading the cache, for a cache you do not trust",
    )
    args = parser.parse_args(argv)

    if args.drift:
        return _cmd_drift(args.sha)
    if args.tree:
        return _cmd_tree(args.tree, args.sha)
    if args.file:
        return _cmd_file(args.file, args.sha, refresh=args.refresh)
    if args.merge or args.textmap:
        return _cmd_textmap(args.lang, args.sha, refresh=args.refresh)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
