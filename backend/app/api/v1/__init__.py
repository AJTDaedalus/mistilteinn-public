"""API v1 — aggregates every resource router under the ``/api/v1`` prefix.

**Port state.** B.6 deleted the ZZZ resource routers: agents, w_engines, disc_sets, discs,
builds, buff_presets, combos, enemies, damage, optimizer, scorer, simulate. What is left is
the infrastructure surface — health, auth, and team CRUD.

The Genshin surface returns with the code behind it: characters/weapons/artifacts after the
Chunk D importer seeds them, damage after Chunk F, and optimizer/builds/artifacts after
Chunk G (G.6).
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.catalogue import router as catalogue_router
from app.api.v1.health import router as health_router
from app.api.v1.teams import router as teams_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(health_router)
v1_router.include_router(auth_router)
v1_router.include_router(teams_router)
v1_router.include_router(catalogue_router)
