"""E.6 — the runtime reads committed snapshots; it never fetches them."""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from tests.unit.conftest import NetworkAccessDeniedError

_APP = Path(__file__).resolve().parents[2] / "app"

#: Modules allowed to speak to the outside world at all. `nanoka_gi_importer` is the one,
#: and only `scripts/seed_db.py` runs it — deliberately, by hand. Nothing else in `app/`
#: may grow a fetch without this list changing in the same commit.
_NETWORK_CAPABLE = {"app/data/importers/nanoka_gi_importer.py"}

#: Modules whose import means the file can open a connection. Matched against **parsed
#: imports**, not against the file's text — several modules name these in a docstring while
#: importing nothing, and a substring check would report those as offenders.
_NETWORK_MODULES = ("httpx", "urllib.request", "urllib3", "requests", "socket", "aiohttp")


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
