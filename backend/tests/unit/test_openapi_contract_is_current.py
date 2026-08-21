"""`frontend/openapi.json` must match the app it claims to describe.

Nothing compared the two before, and it drifted twice:

* fairy's committed spec was stale against fairy's own backend — `HitMode` had gained a
  `channel` member the file did not know about (found in A.9).
* This repo's spec went stale again **inside a single PR**: A.9 regenerated it, then B.6
  deleted twelve routers, leaving a committed contract declaring 44 paths for an app
  serving 7 (found in the Chunk A+B review).

Both times the frontend stayed green, because `npm run codegen` regenerates
`api.types.ts` from this file on `pretest` — so the SPA type-checks happily against
endpoints that 404 at runtime, and any reader treating the file as the API description is
misled.

This test needs no server and no database: it builds the app in-process and compares.
Regenerate with the backend running:

    cd frontend && npm run openapi:fetch
"""

import json
from pathlib import Path

from app.main import create_app

_SPEC = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"


def _committed() -> dict:
    return json.loads(_SPEC.read_text())


def test_committed_spec_exists():
    assert _SPEC.is_file(), f"{_SPEC} is missing"


def test_committed_paths_match_the_app():
    live = create_app().openapi()
    assert sorted(_committed()["paths"]) == sorted(live["paths"]), (
        "frontend/openapi.json declares different paths than the app serves. "
        "Run `cd frontend && npm run openapi:fetch` with the backend up."
    )


def test_committed_operations_match_the_app():
    """Path set alone would miss a route that changed method or lost an operation."""
    live = create_app().openapi()
    committed = _committed()
    live_ops = {(p, m) for p, item in live["paths"].items() for m in item}
    committed_ops = {(p, m) for p, item in committed["paths"].items() for m in item}
    assert committed_ops == live_ops


def test_committed_schema_names_match_the_app():
    """Catches a renamed or dropped Pydantic model even when the routes are unchanged."""
    live = create_app().openapi()
    committed = _committed()
    assert sorted(committed.get("components", {}).get("schemas", {})) == sorted(
        live.get("components", {}).get("schemas", {}),
    )
