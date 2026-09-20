"""Permanent stat buffs a Traveler carries from completed story quests.

The game gives *the Traveler* — and only the Traveler — a handful of permanent stat bonuses
for finishing certain quests. They are not a talent, an ascension row or a constellation, so
nothing in the payloads publishes them, and this repo's chain did not model them at all.
**gcsim applies all of them by default**, so `/explain` and a gcsim run disagreed on every
Traveler build by more than a fifth.

Owner ruling, 2026-09-19: **match gcsim.**

## Source

`internal/characters/traveler/common/storybuffs.go:38-57` at the pin in
`docs/CROSSVAL_gcsim.md`, read off gcsim's own table rather than from any wiki. Each entry
below names the quest gcsim's comment names.

**They are the Traveler's, all three.** The one called `skirk_story_buff` upstream is what
the *Traveler* gets for completing Skirk's story quest — it is not a buff to Skirk, and no
other character in gcsim has a story buff of any kind
(`grep -rl TravelerStoryBuffs internal/` finds the seven Traveler packages and nothing else).

## Default-on, like gcsim

gcsim reads three `params` and defaults each to 1 when absent (`storybuffs.go:26-36`), so an
ordinary config gets all three. Modelling them as optional here would reproduce the
disagreement for anyone who did not know to switch them on, which is the thing being fixed.
A config that *disables* one is expressible in gcsim and is not expressible here; that is a
gap worth knowing rather than a reason to make the default worse.

## Base, not flat

Two of these add to **base** ATK and HP, which every percentage bonus then multiplies —
`Q_BASE_ATK`, not `Q_FLAT_ATK`. Putting them in the flat term instead would be a small error
on a naked Traveler and a growing one on a built Traveler, and it would only show up as a
drift against gcsim that looked like a formula bug.
"""

from __future__ import annotations

from typing import NamedTuple

from app.formula.genshin import tags


class StoryBuff(NamedTuple):
    """One completed quest, and what it permanently grants."""

    #: gcsim's own parameter name, so a reader can find it upstream.
    key: str
    #: The quest, as gcsim's comment names it.
    quest: str
    #: `{quantity tag: amount}`, in this repo's vocabulary.
    grants: dict[str, float]


#: Every Traveler story buff gcsim implements at the pin, in the order it applies them.
TRAVELER_STORY_BUFFS: tuple[StoryBuff, ...] = (
    StoryBuff(
        key="base_atk_buff",
        quest="Chapter III: Act I (Sumeru Archon Quest)",
        grants={tags.Q_BASE_ATK: 3.0},
    ),
    StoryBuff(
        key="skirk_story_buff",
        quest="Crystallina Chapter: Act I (Skirk's Story Quest)",
        grants={
            tags.Q_BASE_ATK: 7.0,
            tags.Q_ELEMENTAL_MASTERY: 15.0,
            tags.Q_BASE_HP: 50.0,
        },
    ),
    StoryBuff(
        key="true_moon_story_buff",
        # gcsim assumes every resonance is done, and says so at `storybuffs.go:21`. That
        # assumption is the difference between this and a smaller buff, so it is repeated
        # here rather than left upstream.
        quest=(
            "Song of the Welkin Moon: Act VIII — True Moon (Nod Krai Archon Quest), "
            "with every resonance completed"
        ),
        grants={
            tags.Q_CRIT_RATE: 0.1,
            tags.Q_CRIT_DMG: 0.2,
            tags.Q_ATK_PCT: 0.2,
            tags.Q_HP_PCT: 0.2,
            tags.Q_DEF_PCT: 0.2,
            tags.Q_ENERGY_RECHARGE: 0.2,
            tags.Q_ELEMENTAL_MASTERY: 60.0,
        },
    ),
)
