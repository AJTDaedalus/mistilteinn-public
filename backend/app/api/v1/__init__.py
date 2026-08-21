"""API v1 — aggregates every resource router under the ``/api/v1`` prefix."""

from fastapi import APIRouter

from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.buff_presets import router as buff_presets_router
from app.api.v1.builds import router as builds_router
from app.api.v1.combos import router as combos_router
from app.api.v1.damage import router as damage_router
from app.api.v1.disc_sets import router as disc_sets_router
from app.api.v1.discs import router as discs_router
from app.api.v1.enemies import router as enemies_router
from app.api.v1.health import router as health_router
from app.api.v1.optimizer import router as optimizer_router
from app.api.v1.scorer import router as scorer_router
from app.api.v1.simulate import router as simulate_router
from app.api.v1.teams import router as teams_router
from app.api.v1.w_engines import router as w_engines_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(health_router)
v1_router.include_router(auth_router)
v1_router.include_router(agents_router)
v1_router.include_router(w_engines_router)
v1_router.include_router(disc_sets_router)
v1_router.include_router(discs_router)
v1_router.include_router(builds_router)
v1_router.include_router(teams_router)
v1_router.include_router(buff_presets_router)
v1_router.include_router(combos_router)
v1_router.include_router(enemies_router)
v1_router.include_router(damage_router)
v1_router.include_router(optimizer_router)
v1_router.include_router(scorer_router)
v1_router.include_router(simulate_router)
