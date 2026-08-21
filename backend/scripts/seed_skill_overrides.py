"""Apply skill-override JSON files to seeded Attack rows.

Usage (standalone):
    python -m scripts.seed_skill_overrides
    python -m scripts.seed_skill_overrides --strict

Called automatically at the end of seed_db.py.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.data.loaders.skill_overrides import (
    AgentOverride,
    HitMode,
    MoveOverride,
    load_skill_overrides,
)
from app.models.agent import Agent, Attack

if TYPE_CHECKING:
    from app.models.enums import RowCondition

logger = logging.getLogger(__name__)


class UnresolvableOverrideError(ValueError):
    """--strict: an override's agent_name or move key doesn't bind to real DB rows."""


async def apply_skill_overrides(
    session: AsyncSession,
    overrides: dict[str, AgentOverride] | None = None,
    *,
    strict: bool = False,
) -> None:
    """Apply hit_mode and variant_label overrides to Attack rows.

    Idempotent: safe to re-run after the initial seed or on incremental re-seeds.

    Default (``strict=False``): an unresolvable ``agent_name`` or move key logs a
    warning and is skipped, so ad hoc partial seeds still work. ``strict=True`` raises
    :class:`UnresolvableOverrideError` instead — for CI/release seeding, where a silent
    no-op override (docs/DESIGN_move_key_resolution.md's whole reason for existing) is a
    build failure, not a warning to scroll past.
    """
    if overrides is None:
        overrides = load_skill_overrides()

    for agent_override in overrides.values():
        # Resolve agent by canonical name
        result = await session.execute(
            select(Agent).where(Agent.name == agent_override.agent_name)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            message = f"Agent {agent_override.agent_name!r} not found in DB"
            if strict:
                raise UnresolvableOverrideError(f"{message} — cannot apply its overrides")
            logger.warning("%s — skipping override", message)
            continue

        for move_name, move_override in agent_override.moves.items():
            # BEFORE the mode branch, deliberately. A split lifts rows out of this move, and
            # everything after must act on the rows that REMAIN. Ordered after, the dispatch
            # stamps `hit_mode` on a row that is about to become a different move — which is
            # exactly what happened on the first run of this code: Trigger's `Counter` left
            # `Silenced Shot` already carrying `hit_mode='channel'`, so a standalone move
            # claimed to be a channel with no spec behind it.
            if move_override.split_moves:
                await _apply_split_moves(
                    session,
                    agent.id,
                    move_name,
                    move_override.split_moves,
                    strict=strict,
                )
            if move_override.hit_mode == HitMode.VARIANT:
                await _apply_variant(session, agent.id, move_name, move_override, strict=strict)
            elif move_override.hit_mode in _WHOLE_MOVE_MODES:
                await _apply_whole_move_mode(
                    session, agent.id, move_name, move_override.hit_mode, strict=strict
                )
            else:  # pragma: no cover - guards a future enum member, not a reachable input
                raise UnresolvableOverrideError(
                    f"hit_mode {move_override.hit_mode.value!r} has no seeder branch "
                    f"(agent={agent_override.agent_name!r} move={move_name!r}). Add one — "
                    "an unhandled mode used to fall out of this dispatch silently, leaving "
                    "the rows at their imported value while the move file claimed otherwise."
                )
            # Runs after the mode branch, and independently of it: a row gate is orthogonal
            # to how the move's hits group (D-CH5). Both `_apply_variant` and
            # `_apply_whole_move_mode` may have rewritten these rows, so read them fresh.
            if move_override.row_conditions:
                await _apply_row_conditions(
                    session,
                    agent.id,
                    move_name,
                    move_override.row_conditions,
                    strict=strict,
                )


# Modes that are a property of the whole move, applied by setting every row. VARIANT is
# excluded because it also partitions the rows and needs its own branch.
_WHOLE_MOVE_MODES = frozenset({HitMode.ATOMIC, HitMode.SEQUENTIAL, HitMode.CHANNEL})


async def _apply_whole_move_mode(
    session: AsyncSession,
    agent_id: str,
    move_name: str,
    hit_mode: HitMode,
    *,
    strict: bool = False,
) -> None:
    """Stamp *hit_mode* on every row of *move_name* and clear any stale variant label.

    Shared by `atomic`, `sequential` and `channel`: all three say something about the move as
    a whole rather than about individual rows, so the update is the same and only the value
    differs. Keeping them on one branch is what makes the `else` above able to fail loudly —
    a per-mode `elif` chain is how `channel` came to be dropped in silence.
    """
    result = await session.execute(
        update(Attack)
        .where(Attack.agent_id == agent_id, Attack.name == move_name)
        .values(hit_mode=hit_mode.value, variant_label=None)
    )
    if result.rowcount == 0:
        message = f"No Attack rows found for agent={agent_id} move={move_name!r}"
        if strict:
            raise UnresolvableOverrideError(
                f"{message} — cannot apply {hit_mode.value} override"
            )
        logger.warning("%s — %s override is a no-op", message, hit_mode.value)
        return
    logger.info("Set hit_mode=%s: agent=%s move=%s", hit_mode.value, agent_id, move_name)




async def _apply_split_moves(
    session: AsyncSession,
    agent_id: str,
    move_name: str,
    splits: dict[str, str],
    *,
    strict: bool = False,
) -> None:
    """Rename rows out of *move_name* into moves of their own (D-CH6).

    The only override that mutates ``attacks.name``. A move name is what L4 resolves and what a
    saved combo references, so this is deliberately noisy: a ``param_name`` that matches nothing
    raises under ``strict`` rather than no-op'ing, and a split that would empty the parent move
    raises always -- that is not a split, it is a rename, and it would break every step naming
    the original.
    """
    result = await session.execute(
        select(Attack).where(Attack.agent_id == agent_id, Attack.name == move_name)
    )
    rows = list(result.scalars().all())
    by_param: dict[str, list[Attack]] = {}
    for row in rows:
        if row.param_name:
            by_param.setdefault(row.param_name, []).append(row)

    moving = {p for p in splits if p in by_param}
    staying = [r for r in rows if r.param_name not in moving]
    if rows and not staying:
        raise UnresolvableOverrideError(
            f"split_moves would move EVERY row of agent={agent_id} move={move_name!r} — that is "
            "a rename, not a split, and it would break every step that names the original move"
        )

    for param, new_name in splits.items():
        targets = by_param.get(param)
        if not targets:
            # Already split is NOT the same as mis-authored, and by `param_name` alone the two
            # look identical. `apply_skill_overrides` runs on every seed and may also be run
            # standalone against a DB that has already been through it, so a split has to be
            # idempotent — every other override is, because re-setting a column to the value it
            # already holds is a no-op, whereas a rename cannot find its own source twice.
            already = await session.execute(
                select(Attack).where(
                    Attack.agent_id == agent_id,
                    Attack.name == new_name,
                    Attack.param_name == param,
                )
            )
            if already.scalars().first() is not None:
                logger.debug(
                    "split already applied: agent=%s param=%s -> %r",
                    agent_id,
                    param,
                    new_name,
                )
                continue
            message = (
                f"split_moves names param_name {param!r} on agent={agent_id} move={move_name!r}, "
                f"which owns {sorted(by_param)}, and no row already sits at {new_name!r} — "
                "no row to split"
            )
            if strict:
                raise UnresolvableOverrideError(message)
            logger.warning("%s — split is a no-op", message)
            continue
        for row in targets:
            row.name = new_name
            row.hit_index = 0
        logger.info(
            "Split rows out of %r into %r: agent=%s param=%s (%d row(s))",
            move_name,
            new_name,
            agent_id,
            param,
            len(targets),
        )


async def _apply_row_conditions(
    session: AsyncSession,
    agent_id: str,
    move_name: str,
    conditions: dict[str, RowCondition],
    *,
    strict: bool = False,
) -> None:
    """Stamp `select_when` on the rows named by `param_name` (D-CH5).

    Rows not named keep NULL — unconditional — so an absent entry can never *hide* a row.
    A ``param_name`` matching nothing is the failure worth being loud about: it means the
    curator is wrong about which rows this agent owns, which is the per-agent-scoping error
    #77 shipped. Scoped to this agent's rows for the same reason.
    """
    result = await session.execute(
        select(Attack).where(Attack.agent_id == agent_id, Attack.name == move_name)
    )
    rows = list(result.scalars().all())
    by_param: dict[str, list[Attack]] = {}
    for row in rows:
        if row.param_name:
            by_param.setdefault(row.param_name, []).append(row)

    for param, condition in conditions.items():
        targets = by_param.get(param)
        if not targets:
            message = (
                f"row_conditions names param_name {param!r} on agent={agent_id} "
                f"move={move_name!r}, which owns {sorted(by_param)} — no row to gate"
            )
            if strict:
                raise UnresolvableOverrideError(message)
            logger.warning("%s — row condition is a no-op", message)
            continue
        for row in targets:
            row.select_when = condition
        logger.info(
            "Set select_when=%s: agent=%s move=%s param=%s (%d row(s))",
            condition.value,
            agent_id,
            move_name,
            param,
            len(targets),
        )


async def _apply_variant(
    session: AsyncSession,
    agent_id: str,
    move_name: str,
    move_override: MoveOverride,
    *,
    strict: bool = False,
) -> None:
    # Fetch all rows for this move ordered by original hit_index
    result = await session.execute(
        select(Attack)
        .where(Attack.agent_id == agent_id, Attack.name == move_name)
        .order_by(Attack.hit_index)
    )
    all_attacks = list(result.scalars().all())

    if not all_attacks:
        message = f"No Attack rows found for agent={agent_id} move={move_name!r}"
        if strict:
            raise UnresolvableOverrideError(f"{message} — cannot apply variant override")
        logger.warning("%s — skipping variant override", message)
        return

    # Reference row: clone non-damage fields for synthetic rows
    ref = all_attacks[0]

    # Separate unassigned rows (no variant_label yet) from already-labeled rows.
    # On re-runs the seeder may find rows already renumbered to 0-based per variant,
    # so index-based lookup only applies to unassigned rows.
    unassigned: dict[int, Attack] = {
        a.hit_index: a for a in all_attacks if a.variant_label is None
    }
    already_labeled: dict[str, Attack] = {
        a.variant_label: a for a in all_attacks if a.variant_label is not None
    }

    for variant_spec in move_override.variants:
        if variant_spec.fields is not None:
            # Synthetic row: the importer didn't produce this variant.
            # Clone identity fields from the reference row and override stats.
            # Idempotency: skip if a synthetic row with this (agent, name, variant_label)
            # already exists.
            existing_result = await session.execute(
                select(Attack).where(
                    Attack.agent_id == agent_id,
                    Attack.name == move_name,
                    Attack.variant_label == variant_spec.label,
                )
            )
            if existing_result.scalar_one_or_none() is not None:
                logger.debug(
                    "Synthetic row already exists: agent=%s move='%s' variant='%s' — skipping",
                    agent_id,
                    move_name,
                    variant_spec.label,
                )
                continue
            f = variant_spec.fields
            session.add(
                Attack(
                    agent_id=agent_id,
                    hakushin_skill_id=ref.hakushin_skill_id,
                    skill_key=ref.skill_key,
                    name=move_name,
                    hit_index=0,
                    hit_mode=HitMode.VARIANT,
                    variant_label=variant_spec.label,
                    element=ref.element,
                    damage_base=f.damage_base,
                    damage_growth=f.damage_growth,
                    stun_base=f.stun_base,
                    stun_growth=f.stun_growth,
                    energy_gain=f.energy_gain,
                    anomaly_buildup=f.anomaly_buildup,
                )
            )
        else:
            for new_idx, orig_idx in enumerate(variant_spec.hit_indices or []):
                attack = unassigned.get(orig_idx)
                if attack is None:
                    # Row may already be labeled from a prior run — just ensure mode is correct.
                    already = already_labeled.get(variant_spec.label)
                    if already is not None:
                        already.hit_mode = HitMode.VARIANT
                        logger.debug(
                            "Row already labeled: agent=%s move='%s' variant='%s' — "
                            "refreshing hit_mode",
                            agent_id,
                            move_name,
                            variant_spec.label,
                        )
                    else:
                        logger.error(
                            "hit_index=%d not found for agent=%s move='%s' variant='%s'",
                            orig_idx,
                            agent_id,
                            move_name,
                            variant_spec.label,
                        )
                    continue
                attack.hit_mode = HitMode.VARIANT
                attack.variant_label = variant_spec.label
                attack.hit_index = new_idx

    logger.info(
        "Set hit_mode=variant: agent=%s move=%s (%d variants)",
        agent_id,
        move_name,
        len(move_override.variants),
    )


async def _main(*, strict: bool = False) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        await apply_skill_overrides(session, strict=strict)

    await engine.dispose()
    logger.info("Skill overrides applied.")


def cli() -> None:
    """CLI entry point: apply every skill_overrides/ file to the seeded app DB."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="hard error on an unresolvable agent_name or move key instead of warn-and-skip",
    )
    args = parser.parse_args()
    asyncio.run(_main(strict=args.strict))


if __name__ == "__main__":
    cli()
