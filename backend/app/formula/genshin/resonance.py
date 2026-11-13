"""Elemental resonance: which ones a team has, and what each does to damage.

Math-fallback P1, task 6 (`docs/TASKS_team_math_fallback.md`). The game grants a resonance
when a **four-member** party has two or more members of one element; one more, Protective
Canopy, needs four different elements. None of it is in the nanoka payloads, so every number
below is a constant, cited twice:

- **Genshin Optimizer** `libs/gi/sheets/src/Resonance.tsx` at commit
  `2c13fc40c4694fd8beae513493c4c8a7537173c6` — the comparator for the formula estimate
  (`docs/DECISIONS.md` §38). Line numbers are into that file.
- **gcsim** `pkg/simulation/setup.go:106-340` (`SetupResonance`) at the pin in
  `backend/app/data/gcsim/keys.json` (`b107b5dc`), as the cross-reference.

They agree on every value used here.

## The tally

GO: `teamSize = sum(...allElementKeys.map((ele) => tally[ele]))` (`Resonance.tsx:54`) and each
resonance is `greaterEq(teamSize, 4, greaterEq(tally.<ele>, 2, …))`. gcsim: `len(chars) < 4`
returns early (`setup.go:108-110`), then `count[c.Base.Element]++` and `v < 2` skips
(`:111-120`). So:

- **four members, or nothing** — three Pyro characters in a three-member team have no Fervent
  Flames;
- **two of an element is enough and four is no better** — a resonance applies once;
- **each member counts once**, whoever they are. A Traveler counts as the element of the
  variant on the team (each variant is its own catalogue character with its own element).

**One divergence, and it cannot happen with a real character.** A member with **no element**
(the two unreleased Traveler bodies the catalogue holds with a null element) counts toward
gcsim's team size and not toward GO's. This follows GO, the comparator: such a member is
dropped from the tally and from the size.

## What reaches damage

- **Fervent Flames** (Pyro): ATK +25%. Static.
- **Soothing Waters** (Hydro): Max HP +25%. Static.
- **Shattering Ice** (Cryo): CRIT Rate +15% against a Cryo-affected or Frozen enemy.
  A condition, off by default.
- **Enduring Rock** (Geo): DMG +15% while shielded, and Geo RES -20% on hit while shielded.
  Two conditions, off.
- **Sprawling Greenery** (Dendro): EM +50; +30 after Burning, Quicken or Bloom; +20 after
  Aggravate, Spread, Hyperbloom or Burgeon. Static, plus two conditions, off.
- **High Voltage** (Electro), **Impetuous Winds** (Anemo), **Protective Canopy** (four
  elements): particles; stamina, movement and cooldown; the wearer's own RES. No damage effect.

Moonsign is not a resonance in this sense and is not here: it is Nod-Krai's lunar-reaction
system (`Resonance.tsx:463`), and Lunar reactions are P3 (G11).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.formula.genshin import tags
from app.formula.genshin.formula_effects import (
    NO_DAMAGE,
    Bonus,
    Condition,
    Effect,
    Unmodelled,
    When,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

GO_RESONANCE = "libs/gi/sheets/src/Resonance.tsx"
GCSIM_RESONANCE = "pkg/simulation/setup.go"

#: Party size every resonance needs. GO `Resonance.tsx:54` + `greaterEq(teamSize, 4, …)`;
#: gcsim `setup.go:108-110`.
TEAM_SIZE = 4
#: Members of one element an elemental resonance needs. GO `greaterEq(tally.<ele>, 2, …)`;
#: gcsim `setup.go:118` (`v < 2` skips).
SAME_ELEMENT = 2
#: Distinct elements Protective Canopy needs. GO `greaterEq(tally.ele, 4, …)` at `:59`.
DISTINCT_ELEMENTS = 4


@dataclass(frozen=True, slots=True)
class Resonance:
    """One resonance: what triggers it, what it does, and where that is written down."""

    key: str
    name: str
    #: The element two members must share, or None for Protective Canopy.
    element: str | None
    bonus: Bonus
    citation: str


def _toggle(key: str, label: str) -> Condition:
    return Condition(key=key, label=label, kind="toggle", default=0,
                     default_reason="situational")


def _on(key: str) -> tuple[When, ...]:
    return (When(condition=key, values=(1,)),)


RESONANCES: tuple[Resonance, ...] = (
    Resonance(
        key="fervent_flames", name="Fervent Flames", element="pyro",
        bonus=Bonus(effects=(Effect(stat="atk_pct", value=0.25),)),
        citation=f"GO {GO_RESONANCE}:81-86 (atk_ 0.25); gcsim {GCSIM_RESONANCE}:122-133",
    ),
    Resonance(
        key="soothing_waters", name="Soothing Waters", element="hydro",
        bonus=Bonus(effects=(Effect(stat="hp_pct", value=0.25),)),
        citation=f"GO {GO_RESONANCE}:114-119 (hp_ 0.25); gcsim {GCSIM_RESONANCE}:134-146",
    ),
    Resonance(
        key="shattering_ice", name="Shattering Ice", element="cryo",
        bonus=Bonus(
            conditions=(_toggle("enemy_cryo", "Enemy affected by Cryo or Frozen"),),
            effects=(Effect(stat="crit_rate", value=0.15, when=_on("enemy_cryo")),),
        ),
        citation=(
            f"GO {GO_RESONANCE}:147-158 (critRate_ 0.15, cond ShatteringIce); "
            f"gcsim {GCSIM_RESONANCE}:147-163 (CR .15 when the target's aura has Cryo or Frozen)"
        ),
    ),
    Resonance(
        key="enduring_rock", name="Enduring Rock", element="geo",
        bonus=Bonus(
            conditions=(
                _toggle("shielded", "Protected by a shield"),
                _toggle("shielded_hit", "Hit while shielded (enemy Geo RES -20%)"),
            ),
            effects=(
                Effect(stat="dmg_bonus", value=0.15, when=_on("shielded")),
                Effect(stat="enemy_res", value=-0.2, elements=("geo",),
                       when=_on("shielded_hit")),
            ),
            unmodelled=(
                Unmodelled(what="Shield Strength +15%",
                           reason=f"{NO_DAMAGE}: shields are not damage"),
            ),
        ),
        citation=(
            f"GO {GO_RESONANCE}:271-301 (all_dmg_ 0.15 cond EnduringRock; geo_enemyRes_ -0.2 "
            f"cond EnduringRockHit); gcsim {GCSIM_RESONANCE}:208-252 (DmgP .15, Geo RES -0.2)"
        ),
    ),
    Resonance(
        key="sprawling_greenery", name="Sprawling Greenery", element="dendro",
        bonus=Bonus(
            conditions=(
                _toggle("after_burning_quicken_bloom", "After Burning, Quicken or Bloom"),
                _toggle("after_aggravate_spread",
                        "After Aggravate, Spread, Hyperbloom or Burgeon"),
            ),
            effects=(
                Effect(stat="elemental_mastery", value=50.0),
                Effect(stat="elemental_mastery", value=30.0,
                       when=_on("after_burning_quicken_bloom")),
                Effect(stat="elemental_mastery", value=20.0,
                       when=_on("after_aggravate_spread")),
            ),
        ),
        citation=(
            f"GO {GO_RESONANCE}:368-395 (eleMas 50, +30, +20); "
            f"gcsim {GCSIM_RESONANCE}:282-338 (EM 50, 30, 20)"
        ),
    ),
    Resonance(
        key="high_voltage", name="High Voltage", element="electro",
        bonus=Bonus(unmodelled=(
            Unmodelled(what="Electro particles on reactions",
                       reason=f"{NO_DAMAGE}: energy is not modelled in the estimate (G13)"),
        )),
        citation=f"GO {GO_RESONANCE}:202-225 (no stat); gcsim {GCSIM_RESONANCE}:181-207",
    ),
    Resonance(
        key="impetuous_winds", name="Impetuous Winds", element="anemo",
        bonus=Bonus(unmodelled=(
            Unmodelled(what="Stamina -15%, movement SPD +10%, CD -5%",
                       reason=f"{NO_DAMAGE}: no rotation timing in the estimate"),
        )),
        citation=f"GO {GO_RESONANCE}:227-242; gcsim {GCSIM_RESONANCE}:271-281",
    ),
    Resonance(
        key="protective_canopy", name="Protective Canopy", element=None,
        bonus=Bonus(unmodelled=(
            Unmodelled(what="All Elemental and Physical RES +15%",
                       reason=f"{NO_DAMAGE}: the wearer's own resistance"),
        )),
        citation=f"GO {GO_RESONANCE}:56-62 (no gcsim counterpart: it changes no damage)",
    ),
)

_BY_KEY = {r.key: r for r in RESONANCES}


@dataclass(frozen=True, slots=True)
class Tally:
    """A team's elements, as the resonance rules count them."""

    #: Members with a known element. The size GO compares with four.
    size: int
    #: `{element: members}`, lower-case channel names.
    elements: dict[str, int]


def tally(member_elements: Iterable[str | None]) -> Tally:
    """Count a team's members by element. Each member once; an element-less one not at all."""
    counted = Counter(e.lower() for e in member_elements if e)
    for element in counted:
        if element not in tags.VISIONS:
            raise ValueError(f"{element!r} is not one of the seven elements {tags.VISIONS}")
    return Tally(size=sum(counted.values()), elements=dict(counted))


def active(member_elements: Iterable[str | None]) -> tuple[Resonance, ...]:
    """Every resonance this team has, in `RESONANCES` order. Empty below four members."""
    counted = tally(member_elements)
    if counted.size < TEAM_SIZE:
        return ()
    out = [
        r for r in RESONANCES
        if r.element is not None and counted.elements.get(r.element, 0) >= SAME_ELEMENT
    ]
    if len(counted.elements) >= DISTINCT_ELEMENTS:
        out.append(_BY_KEY["protective_canopy"])
    return tuple(out)
