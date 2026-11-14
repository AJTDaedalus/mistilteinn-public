"""A kit's talent-level raise, read on the optimized character's own rows (formula estimate only).

Owner approval 2026-11-14 (`docs/DECISIONS.md` §42, `DESIGN_team_math_fallback.md` §2.6). Three
kits raise a talent's level for whoever receives them, and none of it is a constellation:

- Tartaglia's **Master of Weaponry**, +1 Normal Attack for the whole party, himself included
  (GO `teamBuff.char.auto.add(dm.passive.auto_boost)`, `pando Tartaglia.ts:78,107-108`; WR
  `teamBuff.premod.autoBoost: nodePassive`, `index.tsx:192,202-205`; gcsim
  `char.SetTag(keys.ChildePassive, 1)` for every member, `tartaglia.go:52-54`, read in
  `character.go:221-234`);
- Skirk's **Mutual Weapons Mentorship**, +1 Elemental Skill for the whole party when every
  member is Hydro or Cryo with at least one of each (GO `teamBuff.char.skill.add(a0SkillBoost)`,
  `pando Skirk.ts:206-219,290-291`; gcsim `keys.SkirkPassive`, `skirk.go:69-96`,
  `character.go:236-249`);
- Lohen's **High Spirits**, +1 to his **own** Elemental Skill after he uses it (GO
  `ownBuff.char.skill.add(a0HighSpirits.ifOn(1))`, `pando Lohen.ts:197-199`; WR
  `premod.skillBoost: a0HighSpirits_skillBoost`, `index.tsx:176-177,298-303`). gcsim has no Lohen.

**Where the raise is read, and where it is not.** The sheet effect (`talent_level`) travels to
the browser with its `when`, like any kit buff, and the formula recipe swaps a row's multiplier
for the one this module publishes at the raised level, per row of the target, after gating the
`when` (`formula-recipe.ts:raiseRow`). It is **not** read by:

- **gcsim**: it applies all three itself (`TalentLvlAttack`/`TalentLvlSkill`), and the config
  carries stored levels, which gcsim refuses above 10 anyway (`gcsim_config._talents`);
- **`/hits`, `/explain`, `/search-context`** (single-hit Optimize): a build there has no
  party, so there is no giver to raise anything. They keep the stored level plus constellation
  boosts (`talent_boosts.effective_talent_levels`). The formula estimate is the surface that
  knows the team, so it is where a teammate's raise is read;
- **the planner and storage**: a passive costs no books.

**Ordering and caps.** The level read is `stored + constellation boosts + kit raises`, a sum, so
the order is immaterial; it is how GO (`premod.<t> = base + <t>Boost`) and gcsim (`add` in
`TalentLvlAttack`) both compute it. Stored levels are at most 10 (`MAX_STORED_TALENT_LEVEL`),
a constellation adds 3, Tartaglia or Skirk 1: **14**. Lohen at C3 with High Spirits in Skirk's
party reaches **15**, the table's last row (GO adds without a cap; gcsim caps the total boost at
+5, which none of its kits reaches). Past the table's last row nothing is read: that raise is
published as unavailable, and the browser leaves the row at its unraised level and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.enums import TalentType
from app.services.talent_boosts import effective_talent_levels
from app.services.talent_hits import AvailableHit, available_hits

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.services.talent_boosts import _Character


@dataclass(frozen=True, slots=True)
class RaisedHit:
    """One hit of a raised talent, read at the base level plus `raise_by`."""

    hit: AvailableHit
    raise_by: int


@dataclass(frozen=True, slots=True)
class RaisedTalent:
    """One talent the optimized character may receive a raise in, and its rows at each raise."""

    talent: str
    #: The level a row of this talent is read at without any kit raise: stored + constellation.
    level: int
    #: The most the team's kits can add here, every condition on.
    max_raise: int
    rows: tuple[RaisedHit, ...]
    #: `(raise, reason)` for each raise that reads no row (past the table's last level).
    unavailable: tuple[tuple[int, str], ...]


def raised_talents(
    character: _Character, constellation: int, stored: Mapping[str, int],
    raises: Mapping[str, int],
) -> list[RaisedTalent]:
    """The optimized character's rows at each level the team's raises can reach.

    `raises` is the most each talent can be raised, summed over every `talent_level` effect
    the subject receives (conditional ones too: the browser decides those per row). Each level
    from base + 1 to base + `raises[talent]` is published, so a row whose condition holds for
    only some raises still finds its multiplier. The rows are `talent_hits.available_hits` at
    that level — the same parse `/search-context` reads a row with — so a raised multiplier and
    an unraised one cannot come from two parses.
    """
    base = effective_talent_levels(character, constellation, stored)
    out: list[RaisedTalent] = []
    for talent, top in sorted(raises.items()):
        if top <= 0:
            continue
        level = base.get(talent)
        if level is None:
            out.append(RaisedTalent(
                talent=talent, level=0, max_raise=top, rows=(),
                unavailable=tuple((r, f"the build has no {talent} level")
                                  for r in range(1, top + 1)),
            ))
            continue
        published = {
            s.level for t in character.talents if str(t.talent_type) == talent  # type: ignore[attr-defined]
            for s in t.scalings
        }
        rows: list[RaisedHit] = []
        unavailable: list[tuple[int, str]] = []
        for raise_by in range(1, top + 1):
            at = level + raise_by
            if at not in published:
                unavailable.append((raise_by, (
                    f"{talent} has no published row at level {at} (the table stops at "
                    f"{max(published, default=0)})"
                )))
                continue
            rows.extend(
                RaisedHit(hit=hit, raise_by=raise_by)
                for hit in available_hits(character, {**base, talent: at})  # type: ignore[arg-type]
                if str(hit.talent) == talent
            )
        out.append(RaisedTalent(
            talent=talent, level=level, max_raise=top, rows=tuple(rows),
            unavailable=tuple(unavailable),
        ))
    return out


__all__ = ["RaisedHit", "RaisedTalent", "TalentType", "raised_talents"]
