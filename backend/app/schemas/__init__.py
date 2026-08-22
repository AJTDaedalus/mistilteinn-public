"""Pydantic request/response schemas — re-exports the per-resource schema modules.

**Port state.** B.5 deleted the ZZZ resource schemas: `agent`, `disc`, `w_engine`, `damage`,
`optimizer`, `scorer`, `simulate`, `buff_preset`, and `build`. What survives is
transport-shaped rather than game-shaped — auth, pagination, teams, and job status.

`auth.py` is deliberately not re-exported here, matching fairy: its routes import it
directly, and the names (`LoginRequest`, `TokenResponse`) are generic enough that
re-exporting them at package level invites collisions.

The Genshin schemas arrive with the surfaces that need them — Chunk F (damage), Chunk G
(optimizer, builds, artifacts, GOOD import).
"""

from app.schemas.common import PaginatedResponse
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate

__all__ = [
    "PaginatedResponse",
    "TeamCreate",
    "TeamRead",
    "TeamUpdate",
]
