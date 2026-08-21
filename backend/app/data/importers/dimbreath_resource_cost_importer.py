"""Seed agent resource costs from the committed Dimbreath resource-costs extract.

Two independent paths over the same file, and they answer different questions:

* :meth:`seed_ex_energy_costs` sets the one-scalar ``Agent.ex_energy_cost``, which is
  correct for the ~50 single-mode agents and is a *judgement* for the rest.
* :meth:`seed_resource_cost_rows` copies every priced action verbatim into
  ``agent_resource_costs``, making no judgement at all.

The second does not replace the first: the scalar stays the simulator's fallback for any
agent with no cost-key binding (docs/DESIGN_channeled_moves.md 4.5).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.models.agent import Agent, AgentResourceCost

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_EXTRACT_PATH = Path(__file__).parent.parent / "dimbreath" / "schema" / "resource_costs.json"


class DimbreathResourceCostImporter:
    """Seeds agent costs from the extract, matching by avatar_id → hakushin_id."""

    def __init__(self, session: AsyncSession, extract_path: Path = _EXTRACT_PATH) -> None:
        self.session = session
        self.extract_path = extract_path

    async def seed_ex_energy_costs(self) -> int:
        """Set ex_energy_cost on all matched agents. Returns count of updated rows."""
        extract = json.loads(self.extract_path.read_text())
        agents_data = extract["agents"]

        # Build avatar_id → entry map
        by_avatar_id: dict[int, dict] = {
            int(entry["avatar_id"]): entry for entry in agents_data.values()
        }

        # Load all DB agents indexed by hakushin_id
        result = await self.session.execute(select(Agent))
        db_agents: dict[int, Agent] = {a.hakushin_id: a for a in result.scalars().all()}

        # Warn about DB agents with no extract entry
        extract_avatar_ids = set(by_avatar_id.keys())
        for hid, agent in db_agents.items():
            if hid not in extract_avatar_ids:
                logger.warning(
                    "DB agent %r (hakushin_id=%d) has no extract entry"
                    " — ex_energy_cost left unchanged",
                    agent.name,
                    hid,
                )

        # Update matched agents
        updated = 0
        for avatar_id, entry in by_avatar_id.items():
            db_agent = db_agents.get(avatar_id)
            if db_agent is None:
                logger.warning(
                    "Extract agent %r (avatar_id=%d) has no DB row — skipping",
                    entry.get("db_name", "?"),
                    avatar_id,
                )
                continue

            raw = entry.get("ex_energy_cost")
            new_cost = int(raw) if raw is not None else None
            db_agent.ex_energy_cost = new_cost
            updated += 1

        await self.session.flush()
        logger.info("DimbreathResourceCostImporter: updated ex_energy_cost for %d agents", updated)
        return updated

    async def seed_resource_cost_rows(self) -> int:
        """Replace ``agent_resource_costs`` from the extract. Returns rows written.

        Copies ``costs[]`` **verbatim** — value, per_sec and resource exactly as upstream
        priced them. Deliberately no judgement here: picking which of Burnice's six costs is
        "the" cost is what :meth:`seed_ex_energy_costs` has to do and gets wrong, and this
        table exists so that nothing has to.

        Replace, not upsert. A key that disappears upstream must disappear here too — an
        orphaned row is worse than a missing one, because a move spec can still bind to it and
        get a stale price with no signal that it is stale. Deleting per agent (rather than
        truncating) leaves agents the extract does not mention alone.

        An agent absent from the extract lands with **zero** rows. Zero rows is the honest
        state for "upstream has not priced this yet"; a guessed row would be the
        ``ex_energy_cost`` failure — a fallback that reads as an answer.
        """
        extract = json.loads(self.extract_path.read_text())
        by_avatar_id: dict[int, dict] = {
            int(entry["avatar_id"]): entry for entry in extract["agents"].values()
        }

        result = await self.session.execute(select(Agent))
        db_agents: dict[int, Agent] = {a.hakushin_id: a for a in result.scalars().all()}

        written = 0
        for avatar_id, entry in by_avatar_id.items():
            db_agent = db_agents.get(avatar_id)
            if db_agent is None:
                continue
            await self.session.execute(
                delete(AgentResourceCost).where(AgentResourceCost.agent_id == db_agent.id)
            )
            for cost in entry.get("costs") or []:
                key = cost.get("key")
                value = cost.get("value")
                if not key or value is None:
                    logger.warning(
                        "DimbreathResourceCostImporter: %r has a cost with no key or value "
                        "(%r) — skipped",
                        entry.get("db_name", "?"),
                        cost,
                    )
                    continue
                self.session.add(
                    AgentResourceCost(
                        agent_id=db_agent.id,
                        cost_key=str(key),
                        value=float(value),
                        per_sec=bool(cost.get("per_sec", False)),
                        # "Energy" only as the shape of the data, not as an assumption:
                        # every extract row carries `resource`, and Windbloom/Heat/Rp are
                        # exactly the ones a silent default would mislabel.
                        resource=str(cost.get("resource") or "Energy"),
                    )
                )
                written += 1

        await self.session.flush()
        logger.info("DimbreathResourceCostImporter: wrote %d resource-cost rows", written)
        return written
