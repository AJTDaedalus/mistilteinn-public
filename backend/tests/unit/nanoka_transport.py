"""A `NanokaTransport` that serves committed fixtures instead of the network.

Every importer test in Chunks D runs against this. Two reasons, both learned upstream:

1. A test that fetches nanoka goes red when a patch ships, on a machine with no network,
   or when nanoka is down — and the usual fix is to let it skip, at which point it stops
   proving anything while still reporting green. `tests/fixtures/nanoka_gi/PROVENANCE.md`
   says the same thing about the index fixtures.
2. Chunk E's E.6 asserts that no gate, test or importer reaches the network at run time.
   Writing the offline seam in D.1 is cheaper than retrofitting it there.

`from_committed_fixtures()` serves exactly what is committed and raises `KeyError` on
anything else, so a test asking for a payload nobody captured fails loudly instead of
quietly exercising a default.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"

#: The version the committed fixtures were captured at. See the fixtures' PROVENANCE.md.
FIXTURE_VERSION = "7.0.51"


class FixtureTransport:
    """Serves indexes and detail payloads from in-memory dicts.

    Records every call in `calls`, so a test can assert *what* the importer asked for —
    the URL grammar and the request count are the parts of a transport worth pinning.
    """

    def __init__(
        self,
        *,
        indexes: dict[str, dict[str, Any]] | None = None,
        details: dict[tuple[str, str], dict[str, Any]] | None = None,
        version: str = FIXTURE_VERSION,
        fail: set[tuple[str, str]] | None = None,
    ) -> None:
        self.indexes = indexes or {}
        self.details = details or {}
        self.version = version
        #: Entity/id pairs whose detail fetch raises, for exercising the failure path.
        self.fail = fail or set()
        self.calls: list[tuple[str, ...]] = []
        self.closed = False

    async def resolve_version(self) -> str:
        self.calls.append(("version",))
        return self.version

    async def fetch_index(self, entity: str) -> dict[str, Any]:
        self.calls.append(("index", entity))
        return self.indexes[entity]

    async def fetch_detail(self, entity: str, entity_id: int | str) -> dict[str, Any]:
        self.calls.append(("detail", entity, str(entity_id)))
        if (entity, str(entity_id)) in self.fail:
            msg = f"simulated fetch failure for {entity} {entity_id}"
            raise RuntimeError(msg)
        return self.details[entity, str(entity_id)]

    async def close(self) -> None:
        self.closed = True

    @classmethod
    def from_committed_fixtures(cls) -> FixtureTransport:
        """Serve `tests/fixtures/nanoka_gi/` — the three indexes and three details."""
        indexes = {
            entity: json.loads((FIXTURE_DIR / f"{entity}.json").read_text())
            for entity in ("character", "weapon", "artifact")
        }
        details: dict[tuple[str, str], dict[str, Any]] = {}
        for path in sorted((FIXTURE_DIR / "detail").glob("*.json")):
            entity, _, raw_id = path.stem.rpartition("_")
            details[entity, raw_id] = json.loads(path.read_text())
        return cls(indexes=indexes, details=details)
