"""Wire shapes for the formula estimate's buff data (math-fallback P1, tasks 6 and 7).

`app/formula/genshin/formula_effects.py` is the vocabulary and the authority; these are its
response twins, named `Formula*` because `SetEffectRead` already exists for another feature
and two schemas sharing a name rename *each other* in the generated TypeScript.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from app.formula.genshin.formula_effects import Bonus

if TYPE_CHECKING:
    from app.services.team_talent_levels import RaisedTalent


class FormulaWhenRead(BaseModel):
    """The effect applies only while `condition` holds one of `values`."""

    condition: str
    values: list[float | str]


class FormulaConditionRead(BaseModel):
    """One assumption a user owns, with its default and why that is the default."""

    key: str
    label: str
    kind: Literal["toggle", "stacks", "choice", "number"]
    default: float | str
    #: `self` — the wearer triggers it in ordinary play, so it defaults on at its maximum;
    #: `situational` — it depends on the enemy, the team or the moment, so it defaults off;
    #: `usual` — a kit condition at its curated usual value; `teammate` — a teammate's kit
    #: buff, on at its maximum (`DECISIONS.md` §40 (ii)).
    default_reason: Literal["self", "situational", "usual", "teammate"]
    #: Why the default is what it is, in one line, for a kit condition.
    default_note: str | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None


class FormulaTalentRowRead(BaseModel):
    """One of the hit owner's own talent rows an effect is scoped to. See
    `formula_effects.TalentRowScope`."""

    talent: str
    label: str


class FormulaEffectRead(BaseModel):
    """One buff, as a number and the scope it reaches. See `formula_effects.Effect`."""

    stat: str
    value: float
    elements: list[str] | None = None
    element_from: list[str] | None = None
    moves: list[str] | None = None
    rows: list[FormulaTalentRowRead] | None = None
    reactions: list[str] | None = None
    when: list[FormulaWhenRead]
    per: str | None = None
    by_stack: list[float] | None = None
    per_team: Literal["same_element_others", "different_element"] | None = None
    per_team_max: int | None = None
    cap: float | None = None
    threshold: float | None = None
    weapon_types: list[str] | None = None
    #: `talent_level` only: the talent whose level it raises (`FormulaTeamKitRead.
    #: raised_talents` carries the receiver's rows at the raised levels).
    talent: str | None = None


class FormulaUnmodelledRead(BaseModel):
    """A part of a bonus the estimate does not apply, and why."""

    what: str
    reason: str


class FormulaBonusRead(BaseModel):
    """Conditions, the effects they gate, and what is left out."""

    conditions: list[FormulaConditionRead]
    effects: list[FormulaEffectRead]
    unmodelled: list[FormulaUnmodelledRead]

    @classmethod
    def of(cls, bonus: Bonus) -> FormulaBonusRead:
        """The wire form of a validated `Bonus`."""
        return cls.model_validate(bonus.model_dump(mode="json"))


class FormulaSetTierRead(BaseModel):
    """One conditional tier of one set."""

    set_id: int
    set_name: str
    pieces: int
    #: `modelled`, `partial` (some parts named in `bonus.unmodelled`), `unmodelled` (a damage
    #: effect exists and none of it is applied), `no_damage_effect` (healing, shields,
    #: energy: nothing is missing), `stale` (the seeded numbers changed since curation) or
    #: `uncurated` (no entry yet). The last two apply nothing and say why in `problem`.
    status: Literal["modelled", "partial", "unmodelled", "no_damage_effect", "stale", "uncurated"]
    bonus: FormulaBonusRead
    #: GO sheet file and lines at the pinned commit.
    citation: str
    problem: str | None = None


class FormulaSetEffectsRead(BaseModel):
    """Every conditional tier of every catalogue set, resolved against the seeded numbers."""

    #: Genshin Optimizer commit the structure was transcribed from.
    go_commit: str
    tiers: list[FormulaSetTierRead]


class FormulaResonanceRead(BaseModel):
    """One active resonance."""

    key: str
    name: str
    #: The element two members share, or null for Protective Canopy.
    element: str | None
    #: `modelled`, `partial` or `no_damage_effect` (High Voltage's particles, for instance).
    status: Literal["modelled", "partial", "unmodelled", "no_damage_effect"]
    bonus: FormulaBonusRead
    citation: str


class FormulaTeamResonanceRead(BaseModel):
    """A team's tally and the resonances it has."""

    #: Members with a known element — the count the four-member rule reads.
    team_size: int
    #: `{element: members}`, lower case.
    elements: dict[str, int]
    active: list[FormulaResonanceRead]
    #: Why `active` is empty when it is, so an empty list is not mistaken for "none apply".
    note: str | None = None


class FormulaKitSourceRead(BaseModel):
    """One team member's kit, resolved for the optimized character (math-fallback P2).

    Same `bonus` vocabulary as a set tier or a resonance, with every number already resolved
    in the **giver's** context (`app/formula/genshin/sheets.py`): Bennett's ATK bonus arrives
    as flat ATK computed from Bennett's own base ATK. The browser gates each effect by its
    `when`, exactly as it does a set bonus.
    """

    #: `kit:<sheet slug>`. Condition keys are `<id>/<condition>`.
    id: str
    label: str
    #: The giver's name, and the team member whose build it was resolved from.
    giver: str
    build_id: str
    #: `modelled`, `partial`, `unmodelled` or `no_damage_effect`, computed from `bonus`.
    status: Literal["modelled", "partial", "unmodelled", "no_damage_effect"]
    #: True when a GO-cited fixture checks this sheet (`go_fixtures.json`); false is
    #: **unverified**, and a surface showing it must say so.
    verified: bool
    bonus: FormulaBonusRead
    #: GO sheet files at the pinned commit, each applied effect's lines, and gcsim's where it
    #: implements the same buff.
    citation: str
    #: The giver's pass-1 value of every stat an effect read, so a number can be redone by hand.
    giver_stats: dict[str, float]


class FormulaKitMemberRead(BaseModel):
    """Whether one member's kit reaches the estimate."""

    build_id: str
    name: str
    #: A sheet's status, or `no_sheet`: base stats, sets and resonance still count, and the
    #: estimate says "no kit buffs modelled" for this member.
    status: Literal["modelled", "partial", "unmodelled", "no_damage_effect", "no_sheet"]
    verified: bool
    is_subject: bool


class FormulaScalingTermRead(BaseModel):
    """A further scaling term of a mixed-stat hit (`ATK + EM`)."""

    stat: str
    multiplier: float


class FormulaRaisedHitRead(BaseModel):
    """One of the optimized character's hits read `raise_by` levels above its unraised level,
    as `/builds/{id}/search-context` would read it there (`team_talent_levels`)."""

    label: str
    index: int
    raise_by: int
    multiplier: float
    scaling_stat: str
    extra_terms: list[FormulaScalingTermRead]


class FormulaRaisedUnavailableRead(BaseModel):
    """A raise that reads no row (past the table's last level), and why."""

    raise_by: int
    reason: str


class FormulaRaisedTalentRead(BaseModel):
    """A talent of the optimized character a kit's `talent_level` effect raises, and its rows at
    each raise (owner approval 2026-11-14, `DECISIONS.md` §42). For the formula estimate only:
    gcsim applies these raises itself, and single-hit surfaces have no party to raise them."""

    talent: str
    #: Stored level plus constellation boosts: the level `/search-context` reads a row at.
    level: int
    #: The most the team's kits add here, every condition on.
    max_raise: int
    rows: list[FormulaRaisedHitRead]
    unavailable: list[FormulaRaisedUnavailableRead]

    @classmethod
    def of(cls, raised: RaisedTalent) -> FormulaRaisedTalentRead:
        """The wire form of `team_talent_levels.RaisedTalent`."""
        return cls(
            talent=raised.talent, level=raised.level, max_raise=raised.max_raise,
            rows=[
                FormulaRaisedHitRead(
                    label=r.hit.label, index=r.hit.index, raise_by=r.raise_by,
                    multiplier=r.hit.multiplier, scaling_stat=str(r.hit.scaling_stat),
                    extra_terms=[FormulaScalingTermRead(stat=str(x.stat), multiplier=x.multiplier)
                                 for x in r.hit.extra_terms],
                )
                for r in raised.rows
            ],
            unavailable=[FormulaRaisedUnavailableRead(raise_by=n, reason=why)
                         for n, why in raised.unavailable],
        )


class FormulaTeamKitRead(BaseModel):
    """Every member's kit buffs for one optimized character, from the two-pass evaluation."""

    sources: list[FormulaKitSourceRead]
    members: list[FormulaKitMemberRead]
    #: The optimized character's rows at the levels the team's talent-level raises reach.
    raised_talents: list[FormulaRaisedTalentRead] = []
