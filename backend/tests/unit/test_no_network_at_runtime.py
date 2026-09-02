"""E.6 — the runtime reads committed snapshots; it never fetches them."""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from tests.unit.conftest import NetworkAccessDeniedError

_APP = Path(__file__).resolve().parents[2] / "app"

#: Modules allowed to speak to the outside world at all. Nothing else in `app/` may grow a
#: fetch without this list changing in the same commit.
#:
#: - `nanoka_gi_importer` — the catalogue. Only `scripts/seed_db.py` runs it, by hand.
#: - `gcsim_share` — **the first request-time fetch this app has**, and the entry worth
#:   pausing on. E.6's rule is that the runtime reads committed snapshots rather than
#:   fetching them, and that rule is about *game data*: a number this app computes with must
#:   be pinned and reproducible. A gcsim database entry is neither — it is a document the
#:   user is asking to import, named by a link they pasted, and it is written to this
#:   database as steps the moment it arrives. Nothing downstream re-fetches it.
#:
#:   What it does change: a request now holds a worker while a third party answers. The
#:   transport carries a 20-second timeout and a size ceiling for that reason, and the
#:   endpoint requires a signed-in caller so it cannot be used as an open proxy.
_NETWORK_CAPABLE = {
    "app/data/importers/nanoka_gi_importer.py",
    "app/services/gcsim_share.py",
}

#: Modules whose import means the file can open a connection. Matched against **parsed
#: imports**, not against the file's text — several modules name these in a docstring while
#: importing nothing, and a substring check would report those as offenders.
_NETWORK_MODULES = (
    "httpx",
    "httpcore",
    "urllib.request",
    "urllib3",
    "requests",
    "aiohttp",
    "socket",
    # `socket` catches raw use but not the stdlib HTTP client sitting on top of it, and
    # `from http.client import HTTPSConnection` would otherwise sail through the gate whose
    # entire purpose is "nothing here fetches".
    "http.client",
    "ftplib",
    "telnetlib",
    "smtplib",
    "asyncio.open_connection",
)


def _python_sources() -> list[Path]:
    return sorted(path for path in _APP.rglob("*.py") if "__pycache__" not in path.parts)


def _imported_modules(path: Path) -> set[str]:
    """Every module name a file imports, dotted and normalised."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_only_the_declared_module_can_reach_the_network():
    """A live fetch anywhere else in `app/` is a snapshot that stopped being a snapshot."""
    offenders = []
    for path in _python_sources():
        relative = path.relative_to(_APP.parent).as_posix()
        if relative in _NETWORK_CAPABLE:
            continue
        for imported in sorted(_imported_modules(path)):
            if any(
                imported == module or imported.startswith(f"{module}.")
                for module in _NETWORK_MODULES
            ):
                offenders.append(f"{relative}: imports {imported}")

    assert offenders == []


def test_the_runtime_never_imports_the_snapshot_toolkit():
    """`scripts/yuanshen/` fetches from GitLab; importing it from `app/` would put a
    network call one accident away from the request path."""
    offenders = [
        path.relative_to(_APP.parent).as_posix()
        for path in _python_sources()
        if any(name.startswith("scripts.yuanshen") for name in _imported_modules(path))
    ]

    assert offenders == []


def test_reading_the_main_stat_pools_needs_no_network():
    """The pools come off disk. Importing under the socket guard proves it."""
    from app.models.artifact import main_stats_for
    from app.models.enums import ArtifactSlot

    assert len(main_stats_for(ArtifactSlot.GOBLET)) == 12


def test_the_guard_itself_works():
    """A gate never observed failing is not a gate."""
    with pytest.raises(NetworkAccessDeniedError):
        socket.socket().connect(("gitlab.com", 443))


def test_the_import_check_would_catch_a_stdlib_http_client(tmp_path: Path):
    """The list is only as good as what is on it — this is the entry that is easy to miss."""
    module = tmp_path / "sneaky.py"
    module.write_text("from http.client import HTTPSConnection\n", encoding="utf-8")

    imported = _imported_modules(module)

    assert any(
        name == module_name or name.startswith(f"{module_name}.")
        for name in imported
        for module_name in _NETWORK_MODULES
    )
