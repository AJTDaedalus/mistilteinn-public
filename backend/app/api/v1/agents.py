"""Agent endpoints — read-only, data is seeded from import."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_agent_repo
from app.repositories.agent import AgentRepository
from app.schemas.agent import AgentRead, AgentSummary
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=PaginatedResponse[AgentSummary])
async def list_agents(
    repo: Annotated[AgentRepository, Depends(get_agent_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    element: str | None = None,
    specialty: str | None = None,
    rarity: str | None = None,
) -> PaginatedResponse[AgentSummary]:
    """List agents, optionally filtered by element, specialty, or rarity."""
    agents = await repo.get_all(
        offset=offset,
        limit=limit,
        element=element,
        specialty=specialty,
        rarity=rarity,
    )
    total = await repo.count(element=element, specialty=specialty, rarity=rarity)
    return PaginatedResponse(
        items=[AgentSummary.model_validate(a) for a in agents],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: str,
    repo: Annotated[AgentRepository, Depends(get_agent_repo)],
) -> AgentRead:
    """Fetch a single agent by id, including full kit metadata."""
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentRead.model_validate(agent)
