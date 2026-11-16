"""The formula estimate's buff data: conditional set bonuses and elemental resonance.

Math-fallback P1, tasks 6 and 7 (`docs/DESIGN_team_math_fallback.md` §2). Read-only, and
catalogue-level like `/characters` — neither route knows whose team it is, so neither needs a
caller. `/kit-buffs` (P2, task 9) is the exception: it reads the caller's own builds. The
browser's synthetic recipe (`frontend/src/app/sim/formula-recipe.ts`) applies
what these return; nothing here multiplies anything.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import (
    get_artifact_set_repo,
    get_character_repo,
    get_owned_build_repo,
    get_weapon_repo,
)
from app.formula.genshin import resonance, set_effects
from app.formula.genshin.formula_effects import status_of
from app.repositories.artifact_set import ArtifactSetRepository
from app.repositories.build import BuildRepository
from app.repositories.character import CharacterRepository
from app.repositories.weapon import WeaponRepository
from app.schemas.formula import (
    FormulaBonusRead,
    FormulaDripRead,
    FormulaEnergyMemberRead,
    FormulaFavoniusRead,
    FormulaKitMemberRead,
    FormulaKitSourceRead,
    FormulaParticleSourceRead,
    FormulaProcRead,
    FormulaRaisedTalentRead,
    FormulaRefundRead,
    FormulaResonanceEnergyRead,
    FormulaResonanceRead,
    FormulaSetEffectsRead,
    FormulaSetTierRead,
    FormulaTeamEnergyRead,
    FormulaTeamKitRead,
    FormulaTeamResonanceRead,
    FormulaWeaponMemberRead,
)
from app.services import formula_energy, kit_buffs
from app.services.build_assembler import BuildAssemblyError
from app.services.stat_calculator import StatInputError

router = APIRouter(prefix="/formula", tags=["formula"])

#: More than the catalogue's 65, so one page is every set.
_SET_PAGE = 500
#: A party is four; more than that is not a team this rule has an answer for.
_MAX_MEMBERS = 4


@router.get("/set-effects", response_model=FormulaSetEffectsRead)
async def set_effects_route(
    sets: Annotated[ArtifactSetRepository, Depends(get_artifact_set_repo)],
) -> FormulaSetEffectsRead:
    """Every conditional set tier, resolved against the seeded `param_list`s.

    A static tier is absent: it is already a stat pool the kernel applies
    (`/artifacts/set-bonuses`). A conditional tier is **always present**, including the ones
    applying nothing, each with a `status` saying which kind of nothing it is.
    """
    tiers: list[FormulaSetTierRead] = []
    for row in await sets.search(limit=_SET_PAGE):
        affixes = [
            set_effects.AffixRow(
                pieces=a.pieces_required, param_list=list(a.param_list or []),
                add_props=[dict(p) for p in (a.add_props or [])],
            )
            for a in row.affixes
        ]
        tiers.extend(
            FormulaSetTierRead(
                set_id=tier.set_id, set_name=row.name, pieces=tier.pieces, status=tier.status,
                bonus=FormulaBonusRead.of(tier.bonus), citation=tier.citation,
                problem=tier.problem,
            )
            for tier in set_effects.resolve_set(row.nanoka_id, affixes)
        )
    tiers.sort(key=lambda t: (t.set_id, t.pieces))
    return FormulaSetEffectsRead(go_commit=set_effects.curated().go_commit, tiers=tiers)


@router.get("/resonance", response_model=FormulaTeamResonanceRead)
async def resonance_route(
    characters: Annotated[CharacterRepository, Depends(get_character_repo)],
    character_id: Annotated[list[str], Query(max_length=_MAX_MEMBERS)],
) -> FormulaTeamResonanceRead:
    """The resonances a party of these catalogue characters has.

    Each id is one member: a team names each character once, and the tally counts members,
    so a repeated id would be a fifth body the game does not allow.
    """
    if len(set(character_id)) != len(character_id):
        raise HTTPException(status_code=422, detail="a character appears in a team once")
    elements: list[str | None] = []
    for cid in character_id:
        character = await characters.get_by_id(cid)
        if character is None:
            raise HTTPException(status_code=404, detail=f"no character {cid}")
        elements.append(str(character.element) if character.element is not None else None)

    counted = resonance.tally(elements)
    active = resonance.active(elements)
    note = None
    if counted.size < resonance.TEAM_SIZE:
        note = (
            f"resonance needs {resonance.TEAM_SIZE} members with an element; "
            f"this team has {counted.size}"
        )
    return FormulaTeamResonanceRead(
        team_size=counted.size,
        elements=counted.elements,
        active=[
            FormulaResonanceRead(
                key=r.key, name=r.name, element=r.element, status=status_of(r.bonus),
                bonus=FormulaBonusRead.of(r.bonus), citation=r.citation,
            )
            for r in active
        ],
        note=note,
    )


@router.get("/kit-buffs", response_model=FormulaTeamKitRead)
async def kit_buffs_route(
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    weapons_repo: Annotated[WeaponRepository, Depends(get_weapon_repo)],
    subject_build_id: str,
    member_build_id: Annotated[list[str], Query(max_length=_MAX_MEMBERS)],
    subject_weapon_id: str | None = None,
    subject_weapon_refinement: Annotated[int | None, Query(ge=1, le=5)] = None,
) -> FormulaTeamKitRead:
    """Every member's kit buffs for the optimized build, from the two-pass evaluation.

    `member_build_id` is the team, the optimized build included; each of the caller's own. A
    member with no sheet is listed as `no_sheet` rather than omitted, so the estimate can name
    who contributes no kit buffs.

    `subject_weapon_id` resolves the optimized character with a **candidate** weapon (owner
    approval 2026-11-14, `docs/DECISIONS.md` §45): its passive instead of the equipped one's, and
    their pass-1 stats on its base ATK and substat; `subject_weapon_refinement` defaults to the
    build's own, as the gcsim weapon comparison does.
    """
    if len(set(member_build_id)) != len(member_build_id):
        raise HTTPException(status_code=422, detail="a build appears in a team once")
    members = []
    for build_id in member_build_id:
        build = await builds.get_with_kit(build_id)
        if build is None:
            raise HTTPException(status_code=404, detail=f"No build {build_id!r}")
        members.append(build)
    candidate = None
    if subject_weapon_id is not None:
        found = await weapons_repo.get_many_with_refinements([subject_weapon_id])
        if not found:
            raise HTTPException(status_code=404, detail=f"weapon {subject_weapon_id} not found")
        candidate = found[0]
        subject = next((b for b in members if str(b.id) == subject_build_id), None)
        character = subject.character if subject is not None else None
        if character is not None and candidate.weapon_type != character.weapon_type:
            raise HTTPException(
                status_code=422,
                detail=f"{character.name} cannot wield {candidate.name} "
                       f"({candidate.weapon_type}, not {character.weapon_type})",
            )
    try:
        team = kit_buffs.team_kit(
            members, subject_build_id, subject_weapon=candidate,
            subject_refinement=subject_weapon_refinement,
        )
    except (kit_buffs.KitBuffsError, BuildAssemblyError, StatInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FormulaTeamKitRead(
        sources=[
            FormulaKitSourceRead(
                id=s.source_id, label=s.label, giver=s.giver,
                build_id=team.giver_builds[s.source_id],
                status=s.status,  # type: ignore[arg-type]
                verified=s.verified, bonus=FormulaBonusRead.of(s.bonus), citation=s.citation,
                giver_stats=team.giver_stats[s.source_id],
                kind="weapon" if s.source_id.startswith("weapon:") else "kit",
                stack_rank=s.stack_rank,
                procs=[FormulaProcRead.model_validate(p.model_dump(mode="json"))
                       for p in s.procs],
            )
            for s in team.sources
        ],
        members=[
            FormulaKitMemberRead(
                build_id=m.build_id, name=m.name,
                status=m.status,  # type: ignore[arg-type]
                verified=m.verified, is_subject=m.is_subject,
            )
            for m in team.members
        ],
        raised_talents=[FormulaRaisedTalentRead.of(t) for t in team.raised_talents],
        weapons=[
            FormulaWeaponMemberRead(
                build_id=w.build_id, wielder=w.wielder, weapon=w.weapon,
                refinement=w.refinement,
                status=w.status,  # type: ignore[arg-type]
                verified=w.verified, is_subject=w.is_subject, source_id=w.source_id,
            )
            for w in team.weapons
        ],
    )


@router.get("/energy", response_model=FormulaTeamEnergyRead)
async def energy_route(
    builds: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    subject_build_id: str,
    member_build_id: Annotated[list[str], Query(max_length=_MAX_MEMBERS)],
) -> FormulaTeamEnergyRead:
    """The team's energy data for the formula estimate (math-fallback P3, task 14).

    Each member's burst cost and cooldown (game data) and Elemental Skill particles per cast
    (curated, each count cited to gcsim at the pin), flat refunds and a Favonius proc with the
    member's own ER and crit rate, the drip gcsim's waiting model emits, and Electro
    resonance's particle when the team has the resonance (refinements, DECISIONS §49).
    A member with no curated count is listed as `no_particle_data`, never omitted. The
    browser's `formula-energy.ts` does the arithmetic; nothing here multiplies anything.
    """
    if len(set(member_build_id)) != len(member_build_id):
        raise HTTPException(status_code=422, detail="a build appears in a team once")
    members = []
    for build_id in member_build_id:
        # The kit loader: a Favonius proc reads the weapon's refinement rows.
        build = await builds.get_with_kit(build_id)
        if build is None:
            raise HTTPException(status_code=404, detail=f"No build {build_id!r}")
        members.append(build)
    try:
        team = formula_energy.team_energy(members, subject_build_id)
    except formula_energy.FormulaEnergyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    drip = team.drip or formula_energy.drip()
    return FormulaTeamEnergyRead(
        members=[
            FormulaEnergyMemberRead(
                build_id=m.build_id, name=m.name, element=m.element,
                burst_energy_cost=m.burst_energy_cost, burst_cooldown=m.burst_cooldown,
                is_subject=m.is_subject, status=m.status,
                sources=[
                    FormulaParticleSourceRead(
                        label=s.label, per=s.per, particles=s.particles,
                        collector=s.collector, interval=s.interval,
                        max_seconds=s.max_seconds, note=s.note, citation=s.citation,
                        on=s.on, chance=s.chance, shared_icd=s.shared_icd,
                    )
                    for s in m.sources
                ],
                refunds=[
                    FormulaRefundRead(
                        label=r.label, per=r.per, count=r.count, recipients=r.recipients,
                        scaling=r.scaling, amount=r.amount, unavailable=r.unavailable,
                        note=r.note, citation=r.citation,
                        requires_constellation=r.requires_constellation, basis=r.basis,
                        condition=r.condition,
                        absorbs=list(r.absorbs) if r.absorbs else None,
                        interval=r.interval, max_seconds=r.max_seconds, on=r.on,
                    )
                    for r in m.refunds
                ],
                favonius=FormulaFavoniusRead(
                    weapon=m.favonius.weapon, refinement=m.favonius.refinement,
                    chance=m.favonius.chance, cooldown_seconds=m.favonius.cooldown_seconds,
                    particles=m.favonius.particles, citation=m.favonius.citation,
                ) if m.favonius else None,
                energy_recharge=m.energy_recharge, crit_rate=m.crit_rate, note=m.note,
            )
            for m in team.members
        ],
        drip=FormulaDripRead(
            particles=drip.particles, interval_seconds=drip.interval_seconds,
            config=drip.config, citation=drip.citation,
        ),
        gcsim_commit=team.gcsim_commit,
        resonance=FormulaResonanceEnergyRead(
            name=team.resonance.spec.name, element=team.resonance.spec.element,
            particles=team.resonance.spec.particles,
            cooldown_seconds=team.resonance.spec.cooldown_seconds,
            trigger_elements=list(team.resonance.spec.trigger_elements),
            team_can_trigger=team.resonance.team_can_trigger,
            note=team.resonance.spec.note, citation=team.resonance.spec.citation,
            default_procs_per_second=team.resonance.spec.default_procs_per_second,
            default_note=team.resonance.spec.default_note,
        ) if team.resonance else None,
    )
