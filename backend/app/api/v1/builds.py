"""Build endpoints — full CRUD."""

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.dependencies import DBSession, get_owned_build_repo, get_owned_team_repo
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.agent import Agent
from app.models.build import Build
from app.models.disc import Disc
from app.repositories.build import BuildRepository
from app.repositories.team import TeamRepository
from app.schemas.build import (
    BuffDescriptor,
    BuffGroup,
    BuildBuffsResponse,
    BuildCreate,
    BuildEquipDiscsRequest,
    BuildPriorityUpdate,
    BuildRead,
    BuildUpdate,
)
from app.schemas.common import PaginatedResponse
from app.services.modifier_loader import (
    load_agent_modifiers,
    load_disc_set_modifiers,
    load_wengine_modifiers,
)
from app.services.modifiers import Condition, ModifierSource, mindscape_allows
from app.services.snapshot_builder import buff_id
from app.services.support_selection import select_support_members

router = APIRouter(prefix="/builds", tags=["builds"])


def _build_read(build: Build) -> BuildRead:
    return BuildRead(
        id=build.id,
        agent_id=build.agent_id,
        agent_specialty=str(build.agent.specialty),
        w_engine_id=build.w_engine_id,
        w_engine_level=build.w_engine_level,
        w_engine_refinement=build.w_engine_refinement,
        mindscape_level=build.mindscape_level,
        core_skill_level=build.core_skill_level,
        potential_rank=build.potential_rank,
        agent_level=build.agent_level,
        skill_levels=build.skill_levels,
        notes=build.notes,
        disabled_buffs=build.disabled_buffs or [],
        active_conditions=build.active_conditions or [],
        stack_counts=build.stack_counts or {},
        optimizer_priority=build.optimizer_priority,
    )


class EquipDiscRequest(BaseModel):
    """Body for ``PUT /builds/{id}/discs/{slot}``."""

    disc_id: str | None  # null clears the slot


@router.get("", response_model=PaginatedResponse[BuildRead])
async def list_builds(
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[BuildRead]:
    """List the caller's saved agent builds."""
    builds = await repo.get_all(offset=offset, limit=limit)
    total = await repo.count()
    return PaginatedResponse(
        items=[_build_read(b) for b in builds],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=BuildRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_build(
    request: Request,
    body: BuildCreate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """Create a build for an agent (one build per agent per owner)."""
    try:
        stub = await repo.create(body.model_dump())
    except IntegrityError as exc:
        if "uq_builds_owner_agent" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail="A build for this agent already exists",
            ) from exc
        raise
    build = await repo.get_by_id(stub.id)
    if build is None:
        raise HTTPException(status_code=500, detail="Build creation failed")
    return _build_read(build)


@router.put("/priority", response_model=list[BuildRead])
@limiter.limit(WRITE_LIMIT)
async def set_build_priority(
    request: Request,
    body: BuildPriorityUpdate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> list[BuildRead]:
    """Assign dense priority ranks to builds in the given order.

    Builds not in the list have their priority set to NULL. Returns the
    ordered builds with their new ranks.
    """
    try:
        ordered = await repo.set_priority_order(body.ordered_build_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Re-fetch with eager-loaded relationships so _build_read can access agent etc.
    builds = []
    for b in ordered:
        full = await repo.get_by_id(str(b.id))
        if full is not None:
            builds.append(_build_read(full))
    return builds


@router.get("/{build_id}", response_model=BuildRead)
async def get_build(
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """Fetch a single build by id."""
    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found")
    return _build_read(build)


@router.patch("/{build_id}", response_model=BuildRead)
@limiter.limit(WRITE_LIMIT)
async def update_build(
    request: Request,
    build_id: str,
    body: BuildUpdate,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """Partially update a build's levels, W-Engine, or notes."""
    updated = await repo.update(build_id, body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Build not found")
    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found")
    return _build_read(build)


@router.delete("/{build_id}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def delete_build(
    request: Request,
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> None:
    """Delete a build."""
    deleted = await repo.delete(build_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Build not found")


_MINDSCAPE_PREFIX = "M"


def _group_key_for(mod_source: str, source_label: str) -> str:
    """Bucket modifiers by the ability/mindscape they belong to.

    ``core_skill`` → ``"core"`` (one group regardless of how many stats).
    ``mindscape`` + label like ``"M3: ..."`` → ``"M3"``.
    Anything else falls back to the source string as the key so unknown
    modifier kinds still get a sensible group bucket.
    """
    if mod_source == "core_skill":
        return "core"
    if mod_source == "mindscape" and source_label.startswith(_MINDSCAPE_PREFIX):
        # "M1: CRIT Rate" → "M1"
        head = source_label.split(":", 1)[0].strip()
        return head or "mindscape"
    return mod_source or "other"


def _kit_text_for(
    agent: Agent,
    group_key: str,
    *,
    core_tier: int,
) -> tuple[str, str]:
    """Look up the in-game flavor text for an ability/mindscape group.

    Returns (name, description) — both empty strings if the agent's
    relationships aren't loaded or the level row is missing. The core
    skill description is matched on ``build.core_skill_level + 1``
    (DB stores levels 1..7, ZO tiers are 0..5 → DB level 6 = F-tier).
    """
    if group_key == "core":
        rows = sorted(agent.core_skills, key=lambda r: r.level)
        if not rows:
            return ("Core Passive", "")
        # Pick the row matching the build's core tier; fall back to last.
        target_level = core_tier + 1
        match = next((r for r in rows if r.level == target_level), rows[-1])
        return (match.name or "Core Passive", match.description or "")

    if group_key.startswith(_MINDSCAPE_PREFIX) and group_key[1:].isdigit():
        level = int(group_key[1:])
        match = next((m for m in agent.mindscapes if m.level == level), None)
        if match is None:
            return (f"Mindscape {level}", "")
        return (
            match.name or f"Mindscape {level}: {match.name}",
            match.description or "",
        )

    return ("", "")


def _agent_buff_groups(
    role: str,
    agent: Agent,
    *,
    core_tier: int,
    mc_level: int,
    disabled: set[str],
) -> list[BuffGroup]:
    """List one agent's kit modifiers grouped by ability + mindscape.

    Only mindscape modifiers at or below ``mc_level`` are included —
    matching the snapshot_builder's level filter so the toggle list
    reflects what can actually affect the calculation.

    Within each group the buffs are sorted by source_label for stable order.
    """
    raw_groups: dict[str, list[BuffDescriptor]] = {}
    for mod in load_agent_modifiers(str(agent.hakushin_id)):
        # Mirror snapshot_builder exactly — including the C2 variant gate, or the
        # toggle list would show both variants of a mindscape-upgraded buff.
        if not mindscape_allows(mod, mc_level):
            continue
        bid = buff_id(agent.hakushin_id, mod.source_label)
        descriptor = BuffDescriptor(
            id=bid,
            role=role,
            agent_name=agent.name,
            source=mod.source.value,
            source_label=mod.source_label,
            stat=mod.stat,
            value=mod.value,
            target=mod.target.value,
            conditions=[c.value for c in mod.conditions],
            enabled=bid not in disabled,
            max_stacks=mod.max_stacks,
        )
        gk = _group_key_for(mod.source.value, mod.source_label)
        raw_groups.setdefault(gk, []).append(descriptor)

    out: list[BuffGroup] = []
    for gk in sorted(raw_groups.keys(), key=_group_sort_key):
        name, description = _kit_text_for(agent, gk, core_tier=core_tier)
        out.append(
            BuffGroup(
                role=role,
                agent_name=agent.name,
                group_key=gk,
                name=name,
                description=description,
                buffs=sorted(raw_groups[gk], key=lambda b: b.source_label),
            )
        )
    return out


def _group_sort_key(gk: str) -> tuple[int, str]:
    """Stable order: core first, then mindscapes by number, then anything else."""
    if gk == "core":
        return (0, "")
    if gk.startswith(_MINDSCAPE_PREFIX) and gk[1:].isdigit():
        return (1, f"{int(gk[1:]):02d}")
    return (2, gk)


@router.get("/{build_id}/buffs", response_model=BuildBuffsResponse)
async def list_build_buffs(
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    team_repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
    team_id: str | None = Query(default=None),
    active_index: int = Query(default=0, ge=0, le=2),
) -> BuildBuffsResponse:
    """List kit modifiers grouped by ability/mindscape for DPS + supports.

    Pass team_id + active_index to resolve supports from a Team.
    Without team_id, only the DPS build's modifiers are returned.
    """
    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found")
    disabled = set(build.disabled_buffs or [])
    core_tier = build.core_skill_level if build.core_skill_level is not None else 5
    mc_level = build.mindscape_level if build.mindscape_level is not None else 0

    groups: list[BuffGroup] = []
    if build.agent is not None:
        groups.extend(
            _agent_buff_groups(
                "dps",
                build.agent,
                core_tier=core_tier,
                mc_level=mc_level,
                disabled=disabled,
            )
        )

    if team_id:
        team = await team_repo.get_by_id(team_id)
        if team is None:
            raise HTTPException(status_code=404, detail=f"Team not found: {team_id}")
        members = [team.build1, team.build2, team.build3]
        support_builds = select_support_members(members, active_index)
    else:
        support_builds = []

    for i, support_build in enumerate(support_builds, 1):
        if support_build.agent is None:
            continue
        role = f"support{i}"
        support_disabled = set(support_build.disabled_buffs or [])
        support_mc = support_build.mindscape_level or 0
        csl = support_build.core_skill_level
        support_core_tier = csl if csl is not None else 5
        groups.extend(
            _agent_buff_groups(
                role,
                support_build.agent,
                core_tier=support_core_tier,
                mc_level=support_mc,
                disabled=support_disabled,
            )
        )

    return BuildBuffsResponse(build_id=build_id, groups=groups)


@router.put("/{build_id}/discs/{slot}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def equip_disc(
    request: Request,
    build_id: str,
    slot: int,
    body: EquipDiscRequest,
    session: DBSession,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> None:
    """Atomically assign a disc to ``slot`` on the build.

    Unequips any disc already in that slot, then equips the new one
    (validating that its ``slot`` field matches). Pass ``disc_id=None``
    to clear the slot without equipping anything new.
    """
    if not 1 <= slot <= 6:  # noqa: PLR2004 — ZZZ disc slots
        raise HTTPException(status_code=422, detail=f"Invalid slot: {slot}")

    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found")

    # Drop whatever is currently in this slot.
    await session.execute(
        update(Disc)
        .where(Disc.build_id == build_id)
        .where(Disc.build_slot == slot)
        .values(build_id=None, build_slot=None),
    )

    if body.disc_id is None:
        return

    # Equip the new disc — validate slot match first.
    disc_q = await session.execute(
        select(Disc).where(Disc.id == body.disc_id),
    )
    disc = disc_q.scalar_one_or_none()
    if disc is None:
        raise HTTPException(status_code=404, detail="Disc not found")

    disc_slot = disc.slot.value if hasattr(disc.slot, "value") else disc.slot
    if int(disc_slot) != slot:
        raise HTTPException(
            status_code=422,
            detail=f"Disc is for slot {disc_slot}, not {slot}",
        )

    disc.build_id = build_id
    disc.build_slot = slot


@router.patch("/{build_id}/equip-discs", response_model=BuildRead)
@limiter.limit(WRITE_LIMIT)
async def equip_all_discs(
    request: Request,
    build_id: str,
    body: BuildEquipDiscsRequest,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> BuildRead:
    """Atomically replace all six disc slots on a build in one transaction.

    Each disc is validated: it must exist and its stored ``slot`` must match
    the payload key. Discs currently equipped on this build but absent from
    the payload are detached. Discs in the payload that belong to another
    build are stolen (re-attached here).

    Returns the updated ``BuildRead``.
    """
    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found")

    try:
        updated = await repo.equip_all(build_id, body.discs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _build_read(updated)


# ---- Modifier conditions endpoint -------------------------------------------

_SKIP_CONDITIONS = {
    Condition.ALWAYS,
    Condition.ENEMY_STUNNED,
    Condition.SAME_ELEMENT_IN_TEAM,
    # Equipper conditions are resolved automatically at snapshot time against the
    # support's own specialty/element — not user-toggleable.
    Condition.EQUIPPER_IS_ATTACK,
    Condition.EQUIPPER_IS_STUN,
    Condition.EQUIPPER_IS_ANOMALY,
    Condition.EQUIPPER_IS_SUPPORT,
    Condition.EQUIPPER_IS_DEFENSE,
    Condition.EQUIPPER_IS_RUPTURE,
    Condition.EQUIPPER_IS_PHYSICAL,
    Condition.EQUIPPER_IS_FIRE,
    Condition.EQUIPPER_IS_ICE,
    Condition.EQUIPPER_IS_ELECTRIC,
    Condition.EQUIPPER_IS_ETHER,
    Condition.EQUIPPER_IS_WIND,
    Condition.EQUIPPER_IS_LUMIFLUX,
    Condition.EQUIPPER_IS_PYROIS,
}


class BuildConditionItem(BaseModel):
    """A modifier-chain condition the build can toggle, with its buff sources."""

    condition: str
    label: str
    sources: list[str]
    max_stacks: int = 1


def _condition_label(cond_str: str) -> str:
    return cond_str.replace("_", " ").title()


def _add_mod_conditions(
    cond_sources: dict[str, list[str]],
    cond_max_stacks: dict[str, int],
    mods: list,
    known: set[str],
    mc_filter: int | None = None,
) -> None:
    for mod in mods:
        if mc_filter is not None and mod.source == ModifierSource.MINDSCAPE:
            lbl = mod.source_label
            if lbl.startswith("M") and lbl[1:2].isdigit() and int(lbl[1]) > mc_filter:
                continue
        for cond in mod.conditions:
            cv = cond.value if hasattr(cond, "value") else str(cond)
            if cv not in known or Condition(cv) in _SKIP_CONDITIONS:
                continue
            cond_sources.setdefault(cv, [])
            if mod.source_label and mod.source_label not in cond_sources[cv]:
                cond_sources[cv].append(mod.source_label)
            if mod.max_stacks > 1:
                cond_max_stacks[cv] = max(cond_max_stacks.get(cv, 1), mod.max_stacks)


@router.get("/{build_id}/conditions", response_model=list[BuildConditionItem])
async def list_build_conditions(
    build_id: str,
    repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
) -> list[BuildConditionItem]:
    """Return the non-trivial conditions that the build's modifier chain uses.

    Excludes ``always`` and ``enemy_stunned`` (the latter is auto-injected
    by stun markers). The frontend uses this list to render the conditions
    checklist on the calculate page.
    """
    build = await repo.get_by_id(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found")

    cond_sources: dict[str, list[str]] = {}
    cond_max_stacks: dict[str, int] = {}
    known = {c.value for c in Condition}

    agents = [(build, build.mindscape_level)]
    for b, mc in agents:
        if b.agent:
            _add_mod_conditions(
                cond_sources,
                cond_max_stacks,
                load_agent_modifiers(str(b.agent.hakushin_id)),
                known,
                mc_filter=mc or 0,
            )

    if build.w_engine:
        ref = getattr(build, "w_engine_refinement", 1) or 1
        _add_mod_conditions(
            cond_sources,
            cond_max_stacks,
            load_wengine_modifiers(str(build.w_engine.hakushin_id), refinement=ref),
            known,
        )

    all_builds = [build]
    for b in all_builds:
        set_counts: dict[int, int] = Counter()
        for disc in b.discs or []:
            if disc.disc_set and hasattr(disc.disc_set, "hakushin_id"):
                set_counts[disc.disc_set.hakushin_id] += 1
        for set_hid, count in set_counts.items():
            disc_mods = load_disc_set_modifiers(str(set_hid))
            filtered = [
                m
                for m in disc_mods
                if (m.source == ModifierSource.DISC_SET_2PC and count >= 2)  # noqa: PLR2004
                or (m.source == ModifierSource.DISC_SET_4PC and count >= 4)  # noqa: PLR2004
            ]
            _add_mod_conditions(cond_sources, cond_max_stacks, filtered, known)

    return [
        BuildConditionItem(
            condition=cv,
            label=_condition_label(cv),
            sources=sources,
            max_stacks=cond_max_stacks.get(cv, 1),
        )
        for cv, sources in sorted(cond_sources.items())
    ]
