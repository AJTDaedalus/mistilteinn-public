"""Health-check endpoint — liveness probe for load balancers/uptime monitors."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Report that the API process is up and able to serve requests."""
    return {"status": "ok"}
