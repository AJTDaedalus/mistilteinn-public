"""The team's kit buffs for one optimized character: the two-pass evaluation.

Math-fallback P2, task 9 (`docs/DESIGN_team_math_fallback.md` §2.6). A teammate's buff often
reads the **teammate's** stats — Bennett's burst is a ratio of Bennett's base ATK, Kazuha's A4
a fraction of Kazuha's Elemental Mastery — so before any buff can be a number, each giver's
own stats have to be. The order is fixed and there is no cycle:

1. **Pass 1, every member's own stats.** From their build alone: character, weapon, equipped
   artifacts, and the static bonuses of the sets they wear (`artifact_optimizer.
   build_combination_log`, the one definition of "what a set of artifacts is worth"). No kit
   buff from anyone — their own or a teammate's — enters this pass.
2. **Pass 2, every giver's sheet, in the giver's pass-1 context**, resolved for the optimized
   character as receiver (`sheets.resolve`).

So a giver stat a buff reads never includes another kit's buff, and a buff can never feed
itself. GO evaluates the whole team graph at once, so where a teammate's kit raises a stat
another giver's buff reads (a Sucrose EM share read by Kazuha's A4) the two differ; each sheet
names that case in its `unmodelled` list rather than leaving it to be discovered.

**The optimized character is a giver too.** Their own sheet resolves against their equipped
build for constants only (base ATK does not move with artifacts); a self buff reading a stat
that does move becomes a per-candidate conversion (`sheets.SELF_CONVERSIONS`) or is withheld.
Their equipped artifacts never leak into the estimate as a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.formula.genshin import sheets
from app.services import artifact_optimizer, build_assembler

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.build import Build
    from app.pando.calculator import NodeRegistry


class KitBuffsError(ValueError):
    """A request the two-pass evaluation cannot answer, said as a sentence."""


@dataclass(frozen=True, slots=True)
class MemberKit:
    """One member's place in the estimate: whether their kit is modelled, and how."""

    build_id: str
    name: str
    #: `modelled`, `partial`, `unmodelled`, `no_damage_effect` — or `no_sheet` when nobody has
    #: written one, which the estimate says as "no kit buffs modelled".
    status: str
    verified: bool
    is_subject: bool


@dataclass(frozen=True, slots=True)
class TeamKit:
    """Every sheet's resolution for the subject, and every member's coverage."""

    sources: list[sheets.ResolvedKit]
    members: list[MemberKit]
    #: Each giver's pass-1 value of every stat one of their effects read, for the reader.
    giver_stats: dict[str, dict[str, float]]
    #: Each source's giver build id.
    giver_builds: dict[str, str]


def pass_one(build: Build) -> NodeRegistry:
    """A member's own stats, from their build alone (pass 1)."""
    worn = {a.artifact_set.nanoka_id: a.artifact_set for a in build.artifacts
            if a.artifact_set is not None}
    log, _ = artifact_optimizer.build_combination_log(
        build_assembler.base_contributions(build),
        build_assembler.candidates(build.artifacts),
        artifact_optimizer.bonuses_by_set(build_assembler.set_bonuses(list(worn.values()))),
    )
    return log.registry


def giver_of(build: Build, registry: NodeRegistry) -> sheets.Giver:
    """A build as the giver a sheet resolves against."""
    character = build.character
    if character is None:
        msg = f"build {build.id} has no character, so it has no kit"
        raise KitBuffsError(msg)
    rows = {
        (str(talent.talent_type), scaling.level): sheets.TalentRow(
            labels=list(scaling.labels or []), params=list(scaling.params or []),
        )
        for talent in character.talents
        for scaling in talent.scalings
    }
    return sheets.Giver(
        name=character.name,
        nanoka_id=str(character.nanoka_id),
        constellation=build.constellation_level,
        ascension_phase=build.ascension_phase,
        talent_levels=dict(build.talent_levels or {}),
        talent_rows=rows,
        constellation_params={
            c.position: list(c.param_list or []) for c in character.constellations
        },
        passive_params={
            p.unlock_ascension: list(p.param_list or [])
            for p in character.ascension_passives if p.unlock_ascension in (1, 4)
        },
        registry=registry,
    )


def team_kit(members: Sequence[Build], subject_build_id: str) -> TeamKit:
    """Pass 1 for every member with a sheet, then pass 2 for the subject as receiver."""
    if not any(str(b.id) == subject_build_id for b in members):
        msg = "the optimized build must be one of the team's members"
        raise KitBuffsError(msg)
    sources: list[sheets.ResolvedKit] = []
    coverage: list[MemberKit] = []
    giver_stats: dict[str, dict[str, float]] = {}
    giver_builds: dict[str, str] = {}
    for build in members:
        character = build.character
        name = character.name if character is not None else "Build"
        is_subject = str(build.id) == subject_build_id
        sheet = sheets.sheet_for(str(character.nanoka_id)) if character is not None else None
        if sheet is None:
            coverage.append(MemberKit(
                build_id=str(build.id), name=name, status="no_sheet", verified=False,
                is_subject=is_subject,
            ))
            continue
        giver = giver_of(build, pass_one(build))
        resolved = sheets.resolve(sheet, giver, giver_is_subject=is_subject)
        sources.append(resolved)
        giver_stats[resolved.source_id] = sheets.stats_read(sheet, giver)
        giver_builds[resolved.source_id] = str(build.id)
        coverage.append(MemberKit(
            build_id=str(build.id), name=name, status=resolved.status,
            verified=resolved.verified, is_subject=is_subject,
        ))
    return TeamKit(
        sources=sources, members=coverage, giver_stats=giver_stats, giver_builds=giver_builds,
    )
