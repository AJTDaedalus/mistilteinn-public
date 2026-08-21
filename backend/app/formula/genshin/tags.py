"""Genshin tag vocabulary — the single place the DAG's strings are spelled.

A `Tag` is a multi-axis coordinate (`app.formula.tags`); this module names the axes and
their legal values for Genshin, so that "ATK%" is one string in one place rather than a
literal repeated across the stat graph, the damage sheets, the modifier translator and the
optimizer.

**This is where DESIGN §1 A6 starts.** A vocabulary that is data is what lets a character's
kit be data: a modifier says *which quantity, in which scope, from which source*, and the
evaluator reads it — no per-character branch. A vocabulary that is scattered string literals
is how the branch gets written instead, because there is nothing to declare against.

## Provenance

The value sets below are read from gcsim at the commit pinned in `docs/CROSSVAL_gcsim.md`
(`3647a07a7cc3004bc1e79d9bb5f7444de20dceaa`), not from memory:

* quantities — `pkg/core/attributes/stats.go:12-40` (the `Stat` constants)
* elements — `pkg/core/attributes/element.go:13-27` (the `Element` constants)
* scopes — `pkg/core/attacks/attack.go:5-20` (the pre-reaction `AttackTag` constants)

Where this repo's own committed payloads already name a value (`StatType` in
`app/models/enums.py`, derived in C.2 from nanoka), the payload spelling wins and the gcsim
name is recorded beside it — the two agree on meaning, not on spelling, and only one of them
is the vocabulary the database speaks.
"""

from __future__ import annotations

from app.formula.tags import Tag

# ---- Category names -------------------------------------------------------

#: Quantity: what a node or contribution *is* (`atk_pct`, `crit_rate`, `pyro_dmg_bonus`).
Q = "q"
#: Where a contribution came from (`character`, `weapon`, `artifact`, `artifact_set`, …).
SRC = "src"
#: Which attack a scope-gated contribution applies to — see `SCOPES`.
#:
#: **A category in a registration is a requirement, not a label.** `NodeRegistry.gather`
#: returns entries whose tag is a *subset* of the read context, so `{q: dmg_bonus, scope:
#: charged}` is found only when the context says `scope=charged`, while a plain
#: `{q: dmg_bonus}` is found under every scope. That is exactly the gate a scope-gated buff
#: needs — and it is the reason attribution is **not** done with a `src` category: adding
#: one would make the contribution invisible to every read that did not name that source.
#: Attribution lives in `app.formula.genshin.explain` instead.
SCOPE = "scope"
#: Damage channel, for the eight `*_dmg_bonus` quantities and for a hit's own element.
ELEM = "elem"
#: Per-character formula sheet slug (`"kamisato_ayaka"`). Namespaces every formula a single
#: character registers, so two characters' "burst" formulas cannot collide.
SHEET = "sheet"
#: Formula identifier within a sheet (`"normal_1"`, `"burst_cutting"`).
NAME = "name"
#: Condition name, for kit effects that are only active in some states.
COND = "cond"

# `SHEET`, `NAME` and `COND` are declared here — this module is the vocabulary, and an axis
# that exists in the design should be named in one place — but they have **no constructor
# yet**. F.4 adds `formula_tag(sheet, name)` alongside the first sheet that needs it, and
# Chunk H adds the condition constructor. A6 is not a licence to build ahead of need: a
# helper with no caller is untested code that reads as a supported interface.


# ---- Damage channels ------------------------------------------------------

#: The seven visions, lower-cased. Source: gcsim `element.go` `ElementString`. Ordered as
#: `app.models.enums.Element` declares them (alphabetical) rather than as gcsim's enum,
#: because nothing here depends on the ordinal and a stable order makes diffs readable.
VISIONS: tuple[str, ...] = ("anemo", "cryo", "dendro", "electro", "geo", "hydro", "pyro")

#: The eight channels damage and resistance are indexed by: the seven visions plus physical.
#: `Element` deliberately excludes physical (C.2: "it is a damage type, not a vision"), so
#: this is the union that the DMG-bonus and RES tables actually key on.
DAMAGE_CHANNELS: tuple[str, ...] = (*VISIONS, "physical")


# ---- Attack scopes --------------------------------------------------------

#: What a scope-gated buff can be gated on. Source: gcsim's `AttackTag` constants **before**
#: `ReactionAttackStartDelim` — everything after that delimiter is a reaction's own damage
#: instance, which Chunk F does not model (F.6 is amplifying reactions only, and those
#: multiply an existing hit rather than creating a tagged one of their own).
#:
#: `charged` is gcsim's `AttackTagExtra`; the community and the game's own UI call it a
#: Charged Attack, and this repo's talent descriptions (`"Charged Attack DMG|{param8:F1P}"`,
#: `character_10000002.json`) spell it that way too. The gcsim name is recorded here rather
#: than adopted, because the payloads are what the importer reads.
SCOPES: tuple[str, ...] = (
    "normal",          # gcsim AttackTagNormal
    "charged",         # gcsim AttackTagExtra
    "plunge",          # gcsim AttackTagPlunge
    "skill",           # gcsim AttackTagElementalArt
    "skill_hold",      # gcsim AttackTagElementalArtHold
    "burst",           # gcsim AttackTagElementalBurst
    "weapon_skill",    # gcsim AttackTagWeaponSkill
)

#: Physical-damage interactions and shield-break multipliers key off *how* a hit lands, not
#: what talent produced it. Source: gcsim `attack.go:52-59` (`StrikeType`), and the same
#: vocabulary appears in the nanoka payloads' `attack[].strike_type` — one of the few places
#: the two sources use identical spellings, which is why it is worth keeping.
STRIKE_TYPES: tuple[str, ...] = ("default", "pierce", "blunt", "slash", "spear")


# ---- Quantities -----------------------------------------------------------
# Names follow this repo's `StatType` members (lower-cased), because the database is the
# source of truth for game data and the DAG should not need a second dialect. The gcsim
# name is in the comment where the two differ.

# Base stats — a character's level/ascension curve output, plus the weapon's base ATK.
Q_BASE_HP = "base_hp"            # gcsim BaseHP
Q_BASE_ATK = "base_atk"          # gcsim BaseATK
Q_BASE_DEF = "base_def"          # gcsim BaseDEF

# Percentage and flat contributions — what artifacts, weapons and kits write to.
Q_HP_PCT = "hp_pct"              # gcsim HPP
Q_ATK_PCT = "atk_pct"            # gcsim ATKP
Q_DEF_PCT = "def_pct"            # gcsim DEFP
Q_FLAT_HP = "flat_hp"            # gcsim HP
Q_FLAT_ATK = "flat_atk"          # gcsim ATK
Q_FLAT_DEF = "flat_def"          # gcsim DEF

# Resolved totals — what the stat graph solves for.
Q_HP = "hp"
Q_ATK = "atk"
Q_DEF = "def"

# Stats with no base/percent split: a single additive pool.
Q_ELEMENTAL_MASTERY = "elemental_mastery"    # gcsim EM
Q_ENERGY_RECHARGE = "energy_recharge"        # gcsim ER
Q_CRIT_RATE = "crit_rate"                    # gcsim CR
Q_CRIT_DMG = "crit_dmg"                      # gcsim CD
Q_HEALING_BONUS = "healing_bonus"            # gcsim Heal
Q_INCOMING_HEALING_BONUS = "incoming_healing_bonus"
Q_SHIELD_STRENGTH = "shield_strength"

#: Generic DMG% — applies to every channel. gcsim `DmgP`; Genshin's own UI has no such
#: stat, but kits grant it (a "+40% DMG" buff), and the damage chain adds it to whichever
#: channel a hit uses. Kept separate from the per-channel bonuses so a buff cannot be
#: silently double-counted into both.
Q_DMG_BONUS = "dmg_bonus"

#: Per-channel DMG bonus, e.g. `pyro_dmg_bonus`. Built by `dmg_bonus_q`, never spelled out,
#: so adding a channel is one edit to `DAMAGE_CHANNELS`.
_DMG_BONUS_SUFFIX = "_dmg_bonus"

#: Enemy-side **resistance shred**, per channel. `def_reduction` and `def_ignore` are
#: distinct mechanics that the DEF term treats differently (F.5), so they are two names from
#: the start rather than one that later has to be split.
#:
#: **This pool is shred only — it is not where an enemy's base resistance lives.** The base
#: comes from the enemy profile (`services.damage_calculator.Enemy`), because the enemy is
#: fixed while the build varies, and the optimizer would otherwise have to re-register it
#: into every candidate. A build's contributions to this pool are negative (Deepwood's 4pc
#: is `-0.30`). Putting the base here as well double-counts it, which is exactly what the
#: PR #7 review found.
_RES_SUFFIX = "_res_shred"

#: The **wearer's own** elemental resistance — a defensive stat, and emphatically not the
#: enemy's. `FIGHT_PROP_FIRE_SUB_HURT` on an artifact or an ascension row means "this
#: character resists Pyro"; mapping it into the shred pool would make a Pyro-resistant
#: character deal *less* Pyro damage. Nothing reads these yet — there is no incoming-damage
#: model — and they exist so that the import path has somewhere correct to put them.
_SELF_RES_SUFFIX = "_self_res"
Q_DEF_REDUCTION = "def_reduction"
Q_DEF_IGNORE = "def_ignore"
Q_ENEMY_LEVEL = "enemy_level"
Q_CHARACTER_LEVEL = "character_level"

#: Talent multiplier for the hit being evaluated, as a fraction of the scaling stat.
Q_TALENT_MULTIPLIER = "talent_multiplier"

#: Amplifying-reaction multiplier (F.6). Registered as its own quantity so a damage number
#: can report it separately — A6's "a number must explain itself" applies to the reaction
#: term as much as to the crit term.
Q_AMPLIFYING_MULTIPLIER = "amplifying_multiplier"


def dmg_bonus_q(channel: str) -> str:
    """The DMG-bonus quantity for a damage channel: `pyro` → `pyro_dmg_bonus`."""
    _require_channel(channel)
    return f"{channel}{_DMG_BONUS_SUFFIX}"


def res_shred_q(channel: str) -> str:
    """The enemy resistance-**shred** quantity for a channel: `pyro` → `pyro_res_shred`."""
    _require_channel(channel)
    return f"{channel}{_RES_SUFFIX}"


def self_res_q(channel: str) -> str:
    """The **wearer's own** resistance quantity: `pyro` → `pyro_self_res`."""
    _require_channel(channel)
    return f"{channel}{_SELF_RES_SUFFIX}"


def _require_channel(channel: str) -> None:
    if channel not in DAMAGE_CHANNELS:
        msg = (
            f"{channel!r} is not a damage channel. The eight are {DAMAGE_CHANNELS}; a new "
            f"one is a change to that tuple, not a string built at a call site."
        )
        raise ValueError(msg)


#: Every quantity this vocabulary defines, for the tests that assert nothing was invented
#: at a call site. Built from the module's own names so it cannot drift from them.
ALL_QUANTITIES: tuple[str, ...] = (
    Q_BASE_HP, Q_BASE_ATK, Q_BASE_DEF,
    Q_HP_PCT, Q_ATK_PCT, Q_DEF_PCT,
    Q_FLAT_HP, Q_FLAT_ATK, Q_FLAT_DEF,
    Q_HP, Q_ATK, Q_DEF,
    Q_ELEMENTAL_MASTERY, Q_ENERGY_RECHARGE, Q_CRIT_RATE, Q_CRIT_DMG,
    Q_HEALING_BONUS, Q_INCOMING_HEALING_BONUS, Q_SHIELD_STRENGTH,
    Q_DMG_BONUS,
    *(dmg_bonus_q(channel) for channel in DAMAGE_CHANNELS),
    *(res_shred_q(channel) for channel in DAMAGE_CHANNELS),
    *(self_res_q(channel) for channel in DAMAGE_CHANNELS),
    Q_DEF_REDUCTION, Q_DEF_IGNORE, Q_ENEMY_LEVEL, Q_CHARACTER_LEVEL,
    Q_TALENT_MULTIPLIER, Q_AMPLIFYING_MULTIPLIER,
)


# ---- Sources --------------------------------------------------------------

#: Where a contribution came from. **Not a tag category** — see the note on `SCOPE`. These
#: are the labels `app.formula.genshin.explain` records alongside a registration, so an
#: explained damage figure can say which part of a build produced which number.
SRC_CHARACTER = "character"
SRC_WEAPON = "weapon"
SRC_ARTIFACT = "artifact"
SRC_ARTIFACT_SET = "artifact_set"
SRC_TALENT = "talent"
SRC_CONSTELLATION = "constellation"
SRC_ASCENSION_PASSIVE = "ascension_passive"
SRC_TEAM = "team"
SRC_ENEMY = "enemy"

ALL_SOURCES: tuple[str, ...] = (
    SRC_CHARACTER, SRC_WEAPON, SRC_ARTIFACT, SRC_ARTIFACT_SET, SRC_TALENT,
    SRC_CONSTELLATION, SRC_ASCENSION_PASSIVE, SRC_TEAM, SRC_ENEMY,
)


# ---- Tag constructors -----------------------------------------------------

def stat_tag(quantity: str) -> Tag:
    """The tag a contribution to `quantity` registers under, and that its node reads."""
    return Tag.of(**{Q: quantity})


def scoped_stat_tag(quantity: str, scope: str) -> Tag:
    """A contribution that only applies to one attack scope (`+40% Charged Attack DMG`)."""
    if scope not in SCOPES:
        msg = f"{scope!r} is not an attack scope. The seven are {SCOPES}."
        raise ValueError(msg)
    return Tag.of(**{Q: quantity, SCOPE: scope})

