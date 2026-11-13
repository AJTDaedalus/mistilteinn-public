"""The formula estimate's buff data: conditional set bonuses and elemental resonance.

Math-fallback P1, tasks 6 and 7 (`docs/DESIGN_team_math_fallback.md` §2). Read-only, and
catalogue-level like `/characters` — neither route knows whose team it is, so neither needs a
caller. The browser's synthetic recipe (`frontend/src/app/sim/formula-recipe.ts`) applies
what these return; nothing here multiplies anything.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_artifact_set_repo, get_character_repo
from app.formula.genshin import resonance, set_effects
from app.formula.genshin.formula_effects import status_of
from app.repositories.artifact_set import ArtifactSetRepository
from app.repositories.character import CharacterRepository
from app.schemas.formula import (
    FormulaBonusRead,
    FormulaResonanceRead,
    FormulaSetEffectsRead,
    FormulaSetTierRead,
    FormulaTeamResonanceRead,
)

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
