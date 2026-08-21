"""Fetch + cache + merge for Dimbreath ZenlessData (read-only cartography).

Core responsibilities (Phase 0 of the cartography plan):

* Pull any repo file at a **pinned commit SHA** (reproducible), caching the raw
  bytes locally so the 43 MB TextMap is downloaded at most once.
* Merge a TextMap language as ``base ⊕ overwrite`` (overwrite wins) — the
  mandatory layering rule. Beta / newest agents live only in the overwrite layer.

Provenance (mirror URL + pinned SHA) is read from
``app/data/dimbreath/schema/provenance.json`` so the whole toolkit pins to one
commit by default. Pass ``--sha`` to override.

CLI::

    python -m scripts.dimbreath.fetch --lang en --merge
        # downloads + merges EN TextMap, asserts the FengHua anchor, prints stats

    python -m scripts.dimbreath.fetch --file FileCfg/AvatarSkillTemplateTb.json
        # fetch a single raw file (cached), print top-level shape

This module is import-friendly: other cartography scripts call
``load_textmap()`` / ``fetch_json()`` directly.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────
# This file lives at backend/scripts/dimbreath/fetch.py.
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]  # .../backend
DIMBREATH_ROOT = _BACKEND / "app" / "data" / "dimbreath"
SCHEMA_DIR = DIMBREATH_ROOT / "schema"
CACHE_DIR = DIMBREATH_ROOT / "cache"
PROVENANCE_PATH = SCHEMA_DIR / "provenance.json"

_USER_AGENT = "fairy-dimbreath-cartography/1.0 (read-only)"
_TIMEOUT = 120  # seconds; the TextMap base is ~43 MB


# ── Provenance ─────────────────────────────────────────────────────────────
def load_provenance() -> dict[str, Any]:
    """Return the pinned-provenance record (mirror URL + commit SHA)."""
    with PROVENANCE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def pinned_sha() -> str:
    return load_provenance()["pinned_commit_sha"]


def live_master_sha() -> str:
    """Query the mirror for the current ``master`` commit SHA (for drift checks)."""
    prov = load_provenance()
    url = prov["access"]["branch_api"]
    data = _http_get(url)
    return json.loads(data)["commit"]["id"]


# ── Raw fetch + cache ──────────────────────────────────────────────────────
def _http_get(url: str) -> bytes:
    if not url.startswith("https://"):  # only the pinned https mirror is allowed
        raise ValueError(f"refusing non-https URL: {url!r}")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 - https-guarded above
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 - https-guarded above
            return resp.read()
    except urllib.error.HTTPError as exc:  # pragma: no cover - network
        raise RuntimeError(f"HTTP {exc.code} fetching {url}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network
        raise RuntimeError(f"network error fetching {url}: {exc.reason}") from exc


def _cache_path(path: str, sha: str) -> Path:
    """Cache key is (sha, repo-path); sha-pinned so it never goes stale silently."""
    safe = path.replace("/", "__")
    return CACHE_DIR / sha[:12] / safe


def fetch_raw(path: str, sha: str | None = None, *, refresh: bool = False) -> bytes:
    """Fetch a repo file's raw bytes at a pinned SHA, caching under ``cache/``.

    ``path`` is repo-relative, e.g. ``TextMap/TextMap_ENTemplateTb.json``.
    """
    sha = sha or pinned_sha()
    cached = _cache_path(path, sha)
    if cached.exists() and not refresh:
        return cached.read_bytes()

    prov = load_provenance()
    url = prov["access"]["raw_commit"].format(sha=sha, path=path)
    data = _http_get(url)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def fetch_json(path: str, sha: str | None = None, *, refresh: bool = False) -> Any:
    """Fetch + parse a JSON repo file at a pinned SHA (cached)."""
    return json.loads(fetch_raw(path, sha, refresh=refresh))


# ── TextMap layering ───────────────────────────────────────────────────────
def textmap_paths(lang: str) -> tuple[str, str]:
    """Return (base_path, overwrite_path) for a language code (e.g. ``EN``)."""
    lang = lang.upper()
    base = f"TextMap/TextMap_{lang}TemplateTb.json"
    overwrite = f"TextMap/TextMap_{lang}OverwriteTemplateTb.json"
    return base, overwrite


def merge(base: dict[str, Any], overwrite: dict[str, Any]) -> dict[str, Any]:
    """Apply the layering rule: effective text = base ⊕ overwrite (overwrite wins)."""
    merged = dict(base)
    merged.update(overwrite)
    return merged


def load_textmap(
    lang: str = "en", sha: str | None = None, *, refresh: bool = False
) -> dict[str, str]:
    """Return the merged (base ⊕ overwrite) TextMap dict for a language.

    Always merges — never return the base alone. New/beta agents (Velina's
    Windbloom cost, etc.) exist only in the overwrite layer.
    """
    base_path, overwrite_path = textmap_paths(lang)
    base = fetch_json(base_path, sha, refresh=refresh)
    overwrite = fetch_json(overwrite_path, sha, refresh=refresh)
    return merge(base, overwrite)


def layer_of(
    key: str, lang: str = "en", sha: str | None = None
) -> str | None:
    """Report which layer a key came from: ``overwrite``, ``base``, or ``None``.

    Useful as a beta-vs-live signal when mapping a value.
    """
    base_path, overwrite_path = textmap_paths(lang)
    overwrite = fetch_json(overwrite_path, sha)
    if key in overwrite:
        return "overwrite"
    base = fetch_json(base_path, sha)
    return "base" if key in base else None


# ── CLI ────────────────────────────────────────────────────────────────────
_FENGHUA_ANCHOR = ("Velina_Property_FengHuaCostValue_01", "90")


def _cmd_merge(lang: str, sha: str | None) -> int:
    base_path, overwrite_path = textmap_paths(lang)
    base = fetch_json(base_path, sha)
    overwrite = fetch_json(overwrite_path, sha)
    merged = merge(base, overwrite)

    print(f"lang={lang.upper()}  sha={(sha or pinned_sha())[:12]}")
    print(f"  base keys      = {len(base):,}")
    print(f"  overwrite keys = {len(overwrite):,}")
    print(f"  merged keys    = {len(merged):,}")

    if lang.lower() == "en":
        anchor_key, expected = _FENGHUA_ANCHOR
        got = merged.get(anchor_key)
        in_base = base.get(anchor_key)
        ok = got == expected
        print(
            f"  anchor {anchor_key} = {got!r} "
            f"(expected {expected!r}); base layer = {in_base!r}"
        )
        if not ok:
            print("  ANCHOR FAILED — merge did not reproduce the overwrite value", file=sys.stderr)
            return 1
        print("  anchor OK — base ⊕ overwrite merge verified")
    return 0


def _cmd_file(path: str, sha: str | None) -> int:
    data = fetch_json(path, sha)
    if isinstance(data, dict):
        print(f"{path}: dict, {len(data):,} keys")
    elif isinstance(data, list):
        print(f"{path}: list, {len(data):,} rows")
        if data and isinstance(data[0], dict):
            print(f"  first-row columns ({len(data[0])}): {list(data[0])[:12]} ...")
    else:
        print(f"{path}: {type(data).__name__}")
    return 0


def _cmd_drift(sha: str | None) -> int:
    pinned = sha or pinned_sha()
    live = live_master_sha()
    print(f"pinned = {pinned}")
    print(f"live   = {live}")
    if pinned == live:
        print("in sync")
        return 0
    print(f"DRIFT: master has advanced (checked {datetime.now(UTC).isoformat()})")
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dimbreath fetch+cache+merge (read-only).")
    ap.add_argument("--lang", default="en", help="TextMap language code (default: en)")
    ap.add_argument("--merge", action="store_true", help="merge base⊕overwrite and verify anchor")
    ap.add_argument("--file", help="fetch a single repo file (cached) and print its shape")
    ap.add_argument("--drift", action="store_true", help="compare pinned SHA against live master")
    ap.add_argument("--sha", help="override the pinned commit SHA")
    args = ap.parse_args(argv)

    if args.drift:
        return _cmd_drift(args.sha)
    if args.file:
        return _cmd_file(args.file, args.sha)
    if args.merge:
        return _cmd_merge(args.lang, args.sha)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
