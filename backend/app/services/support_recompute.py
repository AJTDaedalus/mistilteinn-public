"""ORM-free support disc recompute kit for the rank pipeline (Phase 3 — R3.13/R3.14).

Built once from an ORM Build in the async resolve phase; picklable for
process-pool workers.  Provides set-count, scaling-stat, and team-modifier
recomputation for hypothetical support disc loadouts without any DB/ORM access.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

from app.services.modifier_loader import (
    load_agent_modifiers,
    load_disc_set_modifiers,
    load_wengine_modifiers,
)
from app.services.modifiers import ModifierSource, ModifierTarget, mindscape_allows
from app.services.snapshot_builder import (
    _MAX_CORE_TIER,
    _bake_hp_scaled_modifier,
    _bake_stat_scaled_modifier,
    _core_base_deltas,
    _scaled_base_stat,
    _wengine_ascension,
    buff_id,
    resolve_equipper_conditions,
)
from app.services.stat_calculator import accumulate_disc_stats

if TYPE_CHECKING:
    from app.services.build_damage_service import BuildSnapshot
    from app.services.modifiers import Modifier
    from app.services.rank_pipeline import PlainBuildDisc

_MIN_2PC = 2
_MIN_4PC = 4


@dataclass
class SupportRecomputeKit:
    """All data needed to recompute support set counts, total HP, and team mods ORM-free.

    Built from an ORM Build in the async resolve phase; picklable for workers.
    Fields without defaults must come first (R3.13); R3.14 fields default to
    empty so existing callers that construct the kit directly are unaffected.
    """

    # Agent HP base: level-scaled + core flat HP already applied.
    agent_base_hp: int
    # Core HP% contribution (basis points, initial bracket).
    core_hp_pct: int
    # W-engine hp_pct modifier sum (basis points, initial bracket).
    we_initial_hp_pct: int
    # W-engine final_hp_pct modifier sum (basis points, combat bracket).
    we_combat_hp_pct: int
    # W-engine secondary stat HP% (basis points, ascension-scaled).
    we_secondary_hp_pct: int
    # Disc set modifiers for all sets present in the support's loadout.
    disc_set_modifiers: dict[int, list[Modifier]]
    # Current support disc loadout — used as the default for recomputation.
    build_discs: list[PlainBuildDisc]
    # --- R3.14: team-modifier recompute fields (default to empty) ---
    # Support agent hakushin_id string (for modifier loading).
    agent_hakushin_id: str = ""
    # Support agent display name (written as owner_name on emitted modifiers).
    agent_name: str = ""
    # Support agent specialty string (for equipper_is_* condition resolution).
    agent_specialty: str = ""
    # Support agent element string (for equipper_is_* condition resolution).
    agent_element: str = ""
    # Agent kit modifiers pre-filtered by mindscape level, disabled_buffs, and
    # equipper conditions — but NOT yet HP-scaled (HP changes per disc swap).
    agent_kit_mods_prefiltered: list[Modifier] = field(default_factory=list)
    # W-Engine target=team modifiers, pre-loaded with owner_name set.
    we_team_mods: list[Modifier] = field(default_factory=list)
    # Support agent base ATK (for base_atk-scaling modifier baking).
    agent_base_atk: int = 0
    # Support *build* id, as a string. Identity for the "is this support already
    # folded into the primary snapshot?" guard in
    # rebuild_primary_snapshot_with_support (issue #121) -- a name is not enough,
    # since a team may hold two builds of the same agent. "" (hand-constructed
    # kits in tests) opts out of the guard.
    build_id: str = ""


def recompute_set_counts(discs: list[PlainBuildDisc]) -> dict[int, int]:
    """Count equipped discs per set from a plain (ORM-free) disc list."""
    counts: Counter[int] = Counter()
    for disc in discs:
        if disc.set_hakushin_id:
            counts[disc.set_hakushin_id] += 1
    return dict(counts)


def recompute_total_hp(kit: SupportRecomputeKit, discs: list[PlainBuildDisc]) -> int:
    """Recompute total HP for a hypothetical support disc loadout.

    ORM-free mirror of snapshot_builder._support_total_hp.  Disc flat HP and
    HP% accumulate from the provided loadout; agent base and W-engine
    contributions are pre-baked into the kit.
    """
    disc_stat_dicts = [
        {
            "main_stat_type": d.main_stat_type,
            "main_stat_value": d.main_stat_value,
            "substats": d.substats,
        }
        for d in discs
    ]
    disc = accumulate_disc_stats(disc_stat_dicts)

    set_counts = recompute_set_counts(discs)
    disc_set_initial_hp_pct = 0
    disc_set_combat_hp_pct = 0
    for set_hid, count in set_counts.items():
        for smod in kit.disc_set_modifiers.get(set_hid, []):
            is_2pc = smod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
            is_4pc = smod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
            if is_2pc or is_4pc:
                if smod.stat == "hp_pct":
                    disc_set_initial_hp_pct += smod.value
                elif smod.stat == "final_hp_pct":
                    disc_set_combat_hp_pct += smod.value

    initial_hp_pct = (
        kit.core_hp_pct
        + disc.hp_pct
        + kit.we_initial_hp_pct
        + kit.we_secondary_hp_pct
        + disc_set_initial_hp_pct
    )
    combat_hp_pct = kit.we_combat_hp_pct + disc_set_combat_hp_pct
    initial_hp = int(kit.agent_base_hp * (1 + initial_hp_pct / 10000) + disc.flat_hp)
    return int(initial_hp * (1 + combat_hp_pct / 10000))


def build_support_recompute_kit(  # noqa: PLR0912, PLR0915
    support_build: object,
    build_discs: list[PlainBuildDisc],
    disabled_buffs: list[str] | None = None,
) -> SupportRecomputeKit:
    """Construct a SupportRecomputeKit from an ORM Build.

    Must be called in the async DB-resolve phase.  ``build_discs`` is the
    already-converted PlainBuildDisc list for the support (avoids a second
    ORM iteration).

    ``disabled_buffs``: request-scoped override (DESIGN_buff_context.md §2.1/
    §7 Q1, Task A6). When supplied (not None), replaces
    ``support_build.disabled_buffs`` entirely. None (default) preserves the
    old build-column read.
    """
    agent = support_build.agent
    level = support_build.agent_level or 60
    core_tier = (
        support_build.core_skill_level
        if support_build.core_skill_level is not None
        else _MAX_CORE_TIER
    )

    base_hp = _scaled_base_stat(
        agent.base_hp,
        agent.hp_growth,
        level,
        agent.promotion_stats,
        "hp",
    )
    core_base = _core_base_deltas(agent.core_stats, core_tier)
    base_hp += core_base.get("hp", 0)

    core_hp_pct = 0
    if agent.core_stats and core_tier < len(agent.core_stats):
        hp_raw = agent.core_stats[core_tier].get("hp_")
        if hp_raw:
            core_hp_pct = int(hp_raw * 10000)

    # R3.14: agent metadata for team-modifier recompute.
    hid = str(agent.hakushin_id)
    agent_name = agent.name
    sup_specialty = (
        agent.specialty.value if hasattr(agent.specialty, "value") else str(agent.specialty)
    )
    sup_element = agent.element.value if hasattr(agent.element, "value") else str(agent.element)
    mc_level = getattr(support_build, "mindscape_level", None) or 0
    disabled = (
        set(disabled_buffs)
        if disabled_buffs is not None
        else set(getattr(support_build, "disabled_buffs", None) or [])
    )

    # Calculate base ATK for scaling modifiers
    base_atk = _scaled_base_stat(
        agent.base_atk,
        agent.atk_growth,
        level,
        agent.promotion_stats,
        "atk",
    )
    base_atk += core_base.get("atk", 0)

    we_initial_hp_pct = 0
    we_combat_hp_pct = 0
    we_secondary_hp_pct = 0
    we_team_mods: list[Modifier] = []
    if support_build.w_engine is not None:
        ref = getattr(support_build, "w_engine_refinement", 1) or 1
        for wmod in load_wengine_modifiers(
            str(support_build.w_engine.hakushin_id),
            refinement=ref,
        ):
            if wmod.stat == "hp_pct":
                we_initial_hp_pct += wmod.value
            elif wmod.stat == "final_hp_pct":
                we_combat_hp_pct += wmod.value
            if wmod.target in (ModifierTarget.TEAM, ModifierTarget.ACTIVE):
                if wmod.scaling_stat == "base_atk" and wmod.scaling_ratio > 0:
                    wmod = _bake_stat_scaled_modifier(wmod, base_atk)
                we_team_mods.append(dc_replace(wmod, owner_name=agent_name))

        sec_type = support_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        if sec_type == "hp_pct":
            sec_value = support_build.w_engine.secondary_stat_value or 0
            we_level = support_build.w_engine_level or 60
            ascension = _wengine_ascension(we_level)
            we_secondary_hp_pct = round(sec_value * (1.0 + 0.3 * ascension))

    all_set_ids = {d.set_hakushin_id for d in build_discs}
    disc_set_modifiers = {sid: load_disc_set_modifiers(str(sid)) for sid in all_set_ids}

    # R3.14: pre-filter agent kit mods (mindscape, disabled, equipper conditions).
    # HP-scaling is NOT applied here — it depends on HP which changes per disc swap.
    agent_kit_mods_prefiltered: list[Modifier] = []
    for mod in load_agent_modifiers(hid):
        if not mindscape_allows(mod, mc_level):
            continue
        if buff_id(hid, mod.source_label) in disabled:
            continue
        if mod.target not in (ModifierTarget.TEAM, ModifierTarget.ACTIVE):
            continue
        resolved = resolve_equipper_conditions(mod, sup_specialty, sup_element, agent_name)
        if resolved is None:
            continue
        if resolved.scaling_stat == "base_atk" and resolved.scaling_ratio > 0:
            resolved = _bake_stat_scaled_modifier(resolved, base_atk)
        agent_kit_mods_prefiltered.append(dc_replace(resolved, owner_name=agent_name))

    return SupportRecomputeKit(
        agent_base_hp=base_hp,
        core_hp_pct=core_hp_pct,
        we_initial_hp_pct=we_initial_hp_pct,
        we_combat_hp_pct=we_combat_hp_pct,
        we_secondary_hp_pct=we_secondary_hp_pct,
        disc_set_modifiers=disc_set_modifiers,
        build_discs=build_discs,
        agent_hakushin_id=hid,
        agent_name=agent_name,
        agent_specialty=sup_specialty,
        agent_element=sup_element,
        agent_kit_mods_prefiltered=agent_kit_mods_prefiltered,
        we_team_mods=we_team_mods,
        agent_base_atk=base_atk,
        build_id=str(getattr(support_build, "id", "") or ""),
    )


def support_team_mods_orm_free(
    kit: SupportRecomputeKit,
    discs: list[PlainBuildDisc],
) -> list[Modifier]:
    """ORM-free mirror of snapshot_builder._support_modifiers for a hypothetical disc loadout.

    Returns the support's team-modifier contributions to the primary DPS snapshot.
    Mirrors the three source groups from _support_modifiers:
      - Agent kit mods (pre-filtered at kit-build time; HP-scaling applied here).
      - W-Engine target=team mods (pre-loaded in the kit).
      - Disc-set target=team mods recomputed from the hypothetical disc loadout.
    """
    result: list[Modifier] = []
    support_hp: int | None = None

    # Agent kit mods — HP-scale lazily (HP varies per disc swap).
    for mod in kit.agent_kit_mods_prefiltered:
        if mod.hp_scale_per_unit:
            if support_hp is None:
                support_hp = recompute_total_hp(kit, discs)
            result.append(_bake_hp_scaled_modifier(mod, support_hp))
        else:
            result.append(mod)

    # W-Engine team mods — pre-loaded at kit-build time.
    result.extend(kit.we_team_mods)

    # Disc-set team mods — recomputed from the hypothetical loadout.
    set_counts = recompute_set_counts(discs)
    for set_hid, count in set_counts.items():
        for smod in kit.disc_set_modifiers.get(set_hid, []):
            is_2pc = smod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
            is_4pc = smod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
            if (is_2pc or is_4pc) and smod.target in (ModifierTarget.TEAM, ModifierTarget.ACTIVE):
                resolved = resolve_equipper_conditions(
                    smod,
                    kit.agent_specialty,
                    kit.agent_element,
                    kit.agent_name,
                )
                if resolved is not None:
                    if resolved.scaling_stat == "base_atk" and resolved.scaling_ratio > 0:
                        resolved = _bake_stat_scaled_modifier(resolved, kit.agent_base_atk)
                    result.append(dc_replace(resolved, owner_name=kit.agent_name))

    return result


def rebuild_primary_snapshot_with_support(
    primary_snap_without_support: BuildSnapshot,
    kit: SupportRecomputeKit,
    support_discs: list[PlainBuildDisc],
) -> BuildSnapshot:
    """Primary snapshot re-baked with the support's team mods for a hypothetical disc loadout.

    Args:
        primary_snap_without_support: Primary DPS snapshot carrying **none** of
            *this* support's team-modifier contributions. This function
            *appends*, so a caller that leaves them in gets them counted twice.
            Other teammates' contributions are fine -- expected, in fact: rank
            builds this snapshot with ``support_builds=`` set to every support
            **except** the one being scored (issue #121), so a three-agent
            team's other support still buffs the primary's damage while the
            scored support's own mods come solely from this re-bake.
        kit: SupportRecomputeKit for the support build.
        support_discs: Hypothetical support disc loadout to score.

    Returns:
        A new BuildSnapshot with the recomputed support team mods appended, and
        this support recorded in ``folded_supports`` so the result cannot pass
        itself off as support-free to ``resolve_stateful_am_step_lists``.

    Raises:
        ValueError: if the snapshot already has this support folded in.
    """
    # Issue #121: the precondition above used to be enforced only by a comment
    # at each call site. `folded_supports` records exactly which supports
    # `build_snapshot_from_db` folded in, so it can be checked here instead --
    # by build id, which (unlike an `owner_name` scan) cannot mistake the
    # primary's own kit for a support's contribution, nor confuse two builds of
    # the same agent.
    _folded_ids = {bid for bid, _name in primary_snap_without_support.folded_supports}
    if kit.build_id and kit.build_id in _folded_ids:
        msg = (
            f"rebuild_primary_snapshot_with_support appends {kit.agent_name!r}'s "
            "team modifiers, but the snapshot already has them folded in "
            f"(folded_supports={list(primary_snap_without_support.folded_supports)}). "
            "That double-counts the support being scored. Build the primary "
            "snapshot with every support EXCEPT this one (issue #121)."
        )
        raise ValueError(msg)
    support_mods = support_team_mods_orm_free(kit, support_discs)
    # Record the append in `folded_supports` too, so the returned snapshot keeps
    # the invariant the guards rely on: "empty tuple" must mean "carries no
    # teammate's contributions". Without this the result is support-folded but
    # advertises itself as support-free, and `resolve_stateful_am_step_lists`
    # would accept it -- the exact silent double-count #121 exists to stop. It
    # also makes a second re-bake with the same kit raise instead of stacking.
    # A kit with no `build_id` (hand-constructed, tests) opts out of both, as
    # documented on `SupportRecomputeKit.build_id`.
    folded = primary_snap_without_support.folded_supports
    if kit.build_id:
        folded = (*folded, (kit.build_id, kit.agent_name))
    return dc_replace(
        primary_snap_without_support,
        modifiers=[*primary_snap_without_support.modifiers, *support_mods],
        folded_supports=folded,
    )
