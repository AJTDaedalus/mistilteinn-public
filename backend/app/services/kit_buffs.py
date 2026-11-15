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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.formula.genshin import sheets, weapon_passives
from app.pando.calculator import Calculator
from app.services import artifact_optimizer, build_assembler
from app.services.talent_boosts import TalentBoostError
from app.services.team_talent_levels import RaisedTalent, raised_talents

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
class MemberWeapon:
    """One member's weapon in the estimate: whether its passive is modelled (task 12)."""

    build_id: str
    wielder: str
    #: The weapon's name, or None for a build with no weapon.
    weapon: str | None
    refinement: int | None
    #: A passive file's status, or `no_passive_data` when nobody has written one — said as
    #: "no weapon passive modelled" — or `no_weapon` for a build that wields none.
    status: str
    verified: bool
    is_subject: bool
    #: The source id its buffs travel under, when it has a file.
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class TeamKit:
    """Every sheet's resolution for the subject, and every member's coverage."""

    sources: list[sheets.ResolvedKit]
    members: list[MemberKit]
    #: Each giver's pass-1 value of every stat one of their effects read, for the reader.
    giver_stats: dict[str, dict[str, float]]
    #: Each source's giver build id.
    giver_builds: dict[str, str]
    #: The subject's rows at each level the team's talent-level raises can reach (`DECISIONS.md`
    #: §42); empty when no kit raises a talent of theirs.
    raised_talents: list[RaisedTalent] = field(default_factory=list)
    #: Every member's weapon and whether its passive reaches the estimate (task 12).
    weapons: list[MemberWeapon] = field(default_factory=list)


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


def giver_of(
    build: Build, registry: NodeRegistry, talent_raises: dict[str, int] | None = None,
) -> sheets.Giver:
    """A build as the giver a sheet resolves against; `talent_raises` are the levels the
    team's unconditional talent-level raises add to them (`member_raises`)."""
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
            for p in character.ascension_passives
            if p.unlock_ascension in sheets.PASSIVE_PHASES
        },
        registry=registry,
        talent_raises=dict(talent_raises or {}),
    )


def member_raises(
    members: Sequence[Build], receiver: Build, subject_build_id: str,
    elements: Sequence[str | None],
) -> dict[str, int]:
    """The talent levels every member's **unconditional** raises add to `receiver` as a giver
    (`sheets.talent_raises`, `DECISIONS.md` §42): Tartaglia's +1 Normal Attack reaches every
    member, so a buff a teammate reads off a Normal Attack row is read one level up, as GO does."""
    out: dict[str, int] = {}
    for giver in members:
        character = giver.character
        sheet = sheets.sheet_for(str(character.nanoka_id)) if character is not None else None
        if sheet is None:
            continue
        found = sheets.talent_raises(
            sheet, constellation=giver.constellation_level,
            ascension_phase=giver.ascension_phase,
            giver_is_receiver=str(giver.id) == str(receiver.id),
            receiver_is_subject=str(receiver.id) == subject_build_id,
            receiver_element=_element(receiver), team_elements=elements,
        )
        for talent, levels in found.items():
            out[talent] = out.get(talent, 0) + levels
    return out


def subject_raised_talents(
    subject: Build, sources: Sequence[sheets.ResolvedKit],
) -> list[RaisedTalent]:
    """The subject's rows at every level the resolved kits' `talent_level` effects can lift
    them to, conditional ones included: the browser gates those per row."""
    raises: dict[str, int] = {}
    for source in sources:
        for effect in source.bonus.effects:
            if effect.stat == "talent_level" and effect.talent is not None:
                raises[effect.talent] = raises.get(effect.talent, 0) + int(effect.value)
    if not raises or subject.character is None:
        return []
    try:
        return raised_talents(subject.character, subject.constellation_level,
                              dict(subject.talent_levels or {}), raises)
    except TalentBoostError as exc:
        raise KitBuffsError(str(exc)) from exc


def _element(build: Build) -> str | None:
    """A member's element, lower case, or None (a Traveler body with none)."""
    character = build.character
    if character is None or character.element is None:
        return None
    return str(character.element).lower()


def _team_max(members: Sequence[Build], subject_build_id: str) -> dict[str, float]:
    """The highest pass-1 value of each stat a sheet in this team reads team-wide
    (`ValueRef.times_team_max`, Nahida's A1), over every member **but the subject**.

    Pass 1 for each, so no kit buff is in it (rule 1). The subject is left out because their
    stats move with every candidate; a value that reads this is withheld when the subject is
    its giver, and otherwise says in its sheet that the subject's own stat never enters it.
    """
    wanted = sorted({
        stat for b in members if b.character is not None
        for sheet in [sheets.sheet_for(str(b.character.nanoka_id))] if sheet is not None
        for stat in sheets.team_stats_read(sheet)
    })
    if not wanted:
        return {}
    others = [b for b in members if str(b.id) != subject_build_id]
    out: dict[str, float] = {}
    for stat in wanted:
        values = [float(Calculator(pass_one(b)).compute(sheets.GIVER_STATS[stat]))
                  for b in others]
        if values:
            out[stat] = max(values)
    return out


def wielder_of(build: Build, registry: NodeRegistry) -> weapon_passives.Wielder | None:
    """A build as the wielder its weapon's passive resolves against, or None without one."""
    weapon = build.weapon
    if weapon is None:
        return None
    refinement = int(build.refinement or 1)
    row = next((r for r in weapon.refinements if r.level == refinement), None)
    name = build.character.name if build.character is not None else "Build"
    return weapon_passives.Wielder(
        name=name, refinement=refinement,
        params=list(row.param_list or []) if row is not None else [],
        registry=registry,
    )


def team_weapons(
    members: Sequence[Build], subject_build_id: str, elements: Sequence[str | None],
    subject_element: str | None,
) -> tuple[list[sheets.ResolvedKit], list[MemberWeapon], dict[str, dict[str, float]],
           dict[str, str]]:
    """Every member's weapon passive resolved for the subject (task 12), in the wielder's
    pass-1 context like a kit sheet; and every member's weapon coverage.

    Two members wielding the same weapon each give their own source: the first is
    `weapon:<slug>`, the next `weapon:<slug>:2`, so their conditions stay apart.
    """
    sources: list[sheets.ResolvedKit] = []
    coverage: list[MemberWeapon] = []
    stats: dict[str, dict[str, float]] = {}
    builds: dict[str, str] = {}
    seen: dict[str, int] = {}
    for build in members:
        is_subject = str(build.id) == subject_build_id
        name = build.character.name if build.character is not None else "Build"
        weapon = build.weapon
        if weapon is None:
            coverage.append(MemberWeapon(
                build_id=str(build.id), wielder=name, weapon=None, refinement=None,
                status="no_weapon", verified=False, is_subject=is_subject))
            continue
        passive = weapon_passives.passive_for(weapon.nanoka_id)
        refinement = int(build.refinement or 1)
        if passive is None:
            coverage.append(MemberWeapon(
                build_id=str(build.id), wielder=name, weapon=weapon.name, refinement=refinement,
                status="no_passive_data", verified=False, is_subject=is_subject))
            continue
        wielder = wielder_of(build, pass_one(build))
        assert wielder is not None
        resolved = weapon_passives.resolve(
            passive, wielder, wielder_is_subject=is_subject,
            receiver_element=subject_element, team_elements=elements,
        )
        base_id = resolved.source_id
        seen[base_id] = seen.get(base_id, 0) + 1
        if seen[base_id] > 1:
            resolved = sheets.ResolvedKit(
                source_id=f"{base_id}:{seen[base_id]}", label=resolved.label,
                giver=resolved.giver, bonus=resolved.bonus, citation=resolved.citation,
                verified=resolved.verified, status=resolved.status,
            )
        sources.append(resolved)
        stats[resolved.source_id] = weapon_passives.stats_read(passive, wielder)
        builds[resolved.source_id] = str(build.id)
        coverage.append(MemberWeapon(
            build_id=str(build.id), wielder=name, weapon=weapon.name, refinement=refinement,
            status=resolved.status, verified=resolved.verified, is_subject=is_subject,
            source_id=resolved.source_id))
    return sources, coverage, stats, builds


def team_kit(members: Sequence[Build], subject_build_id: str) -> TeamKit:
    """Pass 1 for every member with a sheet, then pass 2 for the subject as receiver."""
    if not any(str(b.id) == subject_build_id for b in members):
        msg = "the optimized build must be one of the team's members"
        raise KitBuffsError(msg)
    sources: list[sheets.ResolvedKit] = []
    coverage: list[MemberKit] = []
    giver_stats: dict[str, dict[str, float]] = {}
    giver_builds: dict[str, str] = {}
    # Every member's element, the subject's included, for the few effects that read them
    # (Linnea's C2 reaches Hydro and Geo receivers; Vesna's A4 counts Anemo and Cryo members).
    elements = [_element(b) for b in members]
    subject_element = next(_element(b) for b in members if str(b.id) == subject_build_id)
    team_max = _team_max(members, subject_build_id)
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
        giver = giver_of(build, pass_one(build),
                         member_raises(members, build, subject_build_id, elements))
        resolved = sheets.resolve(
            sheet, giver, giver_is_subject=is_subject, receiver_element=subject_element,
            team_elements=elements, team_max=team_max,
        )
        sources.append(resolved)
        giver_stats[resolved.source_id] = sheets.stats_read(sheet, giver, team_max)
        giver_builds[resolved.source_id] = str(build.id)
        coverage.append(MemberKit(
            build_id=str(build.id), name=name, status=resolved.status,
            verified=resolved.verified, is_subject=is_subject,
        ))
    subject = next(b for b in members if str(b.id) == subject_build_id)
    raised = subject_raised_talents(subject, sources)
    # Weapon passives (task 12) after the kits: the same receiver, the same pass-1 contexts.
    weapon_sources, weapons, weapon_stats, weapon_builds = team_weapons(
        members, subject_build_id, elements, subject_element)
    return TeamKit(
        sources=[*sources, *weapon_sources], members=coverage,
        giver_stats={**giver_stats, **weapon_stats},
        giver_builds={**giver_builds, **weapon_builds},
        raised_talents=raised, weapons=weapons,
    )
