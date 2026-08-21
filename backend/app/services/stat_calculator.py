"""Turn a build into registered stat contributions.

This is the bridge between the data Chunks D and E committed and the DAG F.2 built: each
part of a build — the character, the weapon, each artifact, the enemy — declares what it
contributes, and the graph adds them up. Nothing here computes a total; that is
`app.formula.genshin.stats`' job, and there is exactly one of it.

**Every function here takes plain values, never ORM rows.** Services do not import
SQLAlchemy (backend/CLAUDE.md), and keeping the boundary at dataclasses also means the
optimizer can evaluate a candidate build without one existing in the database — which is
what a search over millions of artifact combinations needs.

## The formula, cited

Character base stats, from gcsim `pkg/core/player/character/basestat.go:73-101` at the pin
in `docs/CROSSVAL_gcsim.md`:

    lvl = clamp(level - 1, 0, 99)
    BaseHP  = base_hp  * GrowCurve[hp_curve][lvl]
    BaseATK = base_atk * GrowCurve[atk_curve][lvl]
    BaseDEF = base_def * GrowCurve[def_curve][lvl]
    EM = published elemental mastery
    ER += 1 ; CD += 0.5 ; CR += 0.05
    + the ascension row's AddProps

Weapons, from the same file at lines 102-126: each published `weapon_prop` is
`init_value * GrowCurve[its own curve][lvl]`, plus the ascension row's props. Note that
**a weapon's substat grows on a curve too** — it is not the flat number the index shows.

## Two things the payloads settled that a reader would otherwise guess

* **Ascension row `i` is phase `i + 1`.** nanoka publishes six rows with no phase label.
  Project Amber publishes the same numbers keyed by `promoteLevel`, and its `promoteLevel: 6`
  entry is nanoka's `ascension[5]` — identical values, independently sourced. Phase 0 adds
  nothing.
* **A character's DEF can grow on an HP curve.** Ayaka's `prop_grow_curves` names
  `GROW_CURVE_HP_S5` for `FIGHT_PROP_BASE_DEFENSE`, and Amber says the same. Reading the
  curve name from the payload rather than deriving it from the stat is not defensive
  programming; it is the only thing that gets this right.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.data.snapshot import artifact_main_stat_value, growth_curve
from app.formula.genshin import tags
from app.formula.genshin.explain import ContributionLog

if TYPE_CHECKING:
    from app.pando.calculator import NodeRegistry

#: Character and weapon levels are published 1..90; the curve tables cover 1..100 and 1..90.
MAX_CHARACTER_LEVEL = 90
MAX_WEAPON_LEVEL = 90

#: Ascension phases. Six published rows, phase 0 meaning "not yet ascended".
MAX_ASCENSION_PHASE = 6

#: A character starts at 100% Energy Recharge. gcsim `basestat.go:82` (`res[ER] += 1`); the
#: nanoka payload has no field for it, which is why this is the one base value that comes
#: from the oracle rather than from the database.
BASE_ENERGY_RECHARGE = 1.0

#: The payload's own keys for the three base stats inside an ascension row. Lower-case here
#: and upper-case everywhere else — `stat_type_for` is case-insensitive for exactly this
#: reason (C.2), and this module goes through it rather than re-lowering strings itself.
_BASE_PROPS = {
    "fight_prop_base_hp": tags.Q_BASE_HP,
    "fight_prop_base_attack": tags.Q_BASE_ATK,
    "fight_prop_base_defense": tags.Q_BASE_DEF,
}


class StatInputError(ValueError):
    """A build description is out of range or names something the data does not have."""


@dataclass(frozen=True, slots=True)
class CharacterStats:
    """What the character contributes, as the payload publishes it.

    `prop_curves` maps a `FIGHT_PROP_BASE_*` key to its `GROW_CURVE_*` name — read from
    `stats_modifier.prop_grow_curves`, never inferred from the stat.
    """

    name: str
    base_hp: float
    base_atk: float
    base_def: float
    prop_curves: dict[str, str]
    #: `stats_modifier.ascension`, verbatim: six rows of `{prop_key: value}`.
    ascension_rows: list[dict[str, float]]
    #: The payload's published values, **not defaults**. gcsim hardcodes `CR += 0.05` and
    #: `CD += 0.5`; the payloads disagree in both directions — Lauma publishes 200 base EM,
    #: Nefer 100, and the two unreleased Traveler bodies publish `crit_rate: 0`. Defaulting
    #: to zero here means a caller that forgets to pass them gets a visibly wrong build
    #: rather than a plausibly wrong one.
    elemental_mastery: float = 0.0
    crit_rate: float = 0.0
    crit_dmg: float = 0.0


@dataclass(frozen=True, slots=True)
class WeaponStats:
    """What the weapon contributes.

    `props` is `weapon_prop` verbatim: `[{prop_type, init_value, type}, …]`, where `type` is
    the growth curve. Both the base ATK and the substat live in it, and both grow.
    """

    name: str
    props: list[dict[str, object]]
    #: `ascension`, verbatim: `{"1": {"fight_prop_base_attack": 31.1}, …}`.
    ascension: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArtifactStats:
    """One equipped artifact: its main stat, and its substats as rolled."""

    slot: str
    rarity: int
    level: int
    main_stat: str
    #: `[{"stat": "FIGHT_PROP_...", "value": 0.0525}, …]` — the shape `Artifact.substats`
    #: stores. Values are as rolled; this module does not re-derive them from roll counts.
    substats: list[dict[str, object]] = field(default_factory=list)


def _check_range(name: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        msg = f"{name} {value} is outside {low}..{high}"
        raise StatInputError(msg)


def add_character(
    log: ContributionLog, character: CharacterStats, level: int, ascension_phase: int,
) -> None:
    """Register everything a character contributes at `level` and `ascension_phase`."""
    _check_range("character level", level, 1, MAX_CHARACTER_LEVEL)
    _check_range("ascension phase", ascension_phase, 0, MAX_ASCENSION_PHASE)

    for prop_key, quantity in _BASE_PROPS.items():
        base = {
            tags.Q_BASE_HP: character.base_hp,
            tags.Q_BASE_ATK: character.base_atk,
            tags.Q_BASE_DEF: character.base_def,
        }[quantity]
        curve = _curve_name(character, prop_key)
        log.add(
            quantity,
            base * growth_curve("avatar", curve, level),
            tags.SRC_CHARACTER,
            f"{character.name} level {level} ({curve})",
        )

    log.add(
        tags.Q_ELEMENTAL_MASTERY, character.elemental_mastery, tags.SRC_CHARACTER, "base",
    )
    log.add(tags.Q_ENERGY_RECHARGE, BASE_ENERGY_RECHARGE, tags.SRC_CHARACTER, "base 100%")
    log.add(tags.Q_CRIT_RATE, character.crit_rate, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_CRIT_DMG, character.crit_dmg, tags.SRC_CHARACTER, "base")

    _add_ascension_row(
        log,
        _ascension_row(character.ascension_rows, ascension_phase),
        tags.SRC_CHARACTER,
        f"ascension phase {ascension_phase}",
    )


def _curve_name(character: CharacterStats, prop_key: str) -> str:
    """The growth curve for one base prop, from the payload.

    Raises rather than falling back to a curve named after the stat: Ayaka's DEF grows on
    `GROW_CURVE_HP_S5`, so "the DEF curve" is not a thing that can be assumed.
    """
    curve = character.prop_curves.get(prop_key.upper())
    if curve is None:
        msg = (
            f"{character.name} publishes no growth curve for {prop_key}; "
            f"it has {sorted(character.prop_curves)}"
        )
        raise StatInputError(msg)
    return curve


def _ascension_row(rows: list[dict[str, float]], phase: int) -> dict[str, float]:
    """The published row for an ascension phase, or nothing at phase 0.

    **Row `i` is phase `i + 1`** — see the module docstring for the cross-source check that
    settled it. Off by one here is a silent ~9% error in every stat at max level.
    """
    if phase == 0:
        return {}
    if phase > len(rows):
        msg = f"ascension phase {phase} but only {len(rows)} rows are published"
        raise StatInputError(msg)
    return rows[phase - 1]


def _add_ascension_row(
    log: ContributionLog, row: dict[str, float], source: str, note: str,
) -> None:
    """Register an ascension row's props, base stats and bonus stat alike."""
    for prop_key, value in row.items():
        quantity = _BASE_PROPS.get(prop_key.lower()) or _quantity_for_prop(prop_key)
        log.add(quantity, value, source, note)


def add_weapon(
    log: ContributionLog, weapon: WeaponStats, level: int, ascension_phase: int,
) -> None:
    """Register a weapon's base ATK, its substat, and its ascension bonuses.

    The substat grows on its own curve — `weapon_prop[1].type` — which is why this loops
    over the published props instead of special-casing base ATK.
    """
    _check_range("weapon level", level, 1, MAX_WEAPON_LEVEL)
    _check_range("ascension phase", ascension_phase, 0, MAX_ASCENSION_PHASE)

    for prop in weapon.props:
        prop_type = str(prop.get("prop_type", ""))
        quantity = _quantity_for_prop(prop_type, allow_absent=True)
        if quantity is None:
            continue
        curve = str(prop.get("type", ""))
        value = float(prop.get("init_value", 0.0)) * growth_curve("weapon", curve, level)
        log.add(quantity, value, tags.SRC_WEAPON, f"{weapon.name} level {level} ({curve})")

    if ascension_phase:
        _add_ascension_row(
            log,
            weapon.ascension.get(str(ascension_phase), {}),
            tags.SRC_WEAPON,
            f"{weapon.name} ascension phase {ascension_phase}",
        )


def add_artifact(log: ContributionLog, artifact: ArtifactStats) -> None:
    """Register one artifact's main stat and substats."""
    _check_range("artifact level", artifact.level, 0, 20)
    _check_range("artifact rarity", artifact.rarity, 1, 5)

    # Quantity first, value second: an unknown prop should report "no DAG quantity, add it
    # here", not "not a main stat at rarity 5", which reads as a data problem when it is a
    # vocabulary one.
    main_quantity = _quantity_for_prop(artifact.main_stat)
    main_value = artifact_main_stat_value(artifact.rarity, artifact.level, artifact.main_stat)
    log.add(
        main_quantity,
        main_value,
        tags.SRC_ARTIFACT,
        f"{artifact.slot} main stat +{artifact.level}",
    )
    for substat in artifact.substats:
        stat = str(substat.get("stat", ""))
        log.add(
            _quantity_for_prop(stat),
            float(substat.get("value", 0.0)),
            tags.SRC_ARTIFACT,
            f"{artifact.slot} substat",
        )


def build_log(registry: NodeRegistry) -> ContributionLog:
    """A fresh log over `registry`. Sugar, so callers do not import two modules for one line."""
    return ContributionLog(registry=registry)


#: `FIGHT_PROP_*` → DAG quantity. The bridge C.2's `StatType` and F.1's vocabulary meet at;
#: `tests/unit/test_genshin_tag_vocabulary.py` is what keeps the two lists from drifting.
_PROP_QUANTITIES: dict[str, str] = {
    "FIGHT_PROP_HP": tags.Q_FLAT_HP,
    "FIGHT_PROP_HP_PERCENT": tags.Q_HP_PCT,
    "FIGHT_PROP_ATTACK": tags.Q_FLAT_ATK,
    "FIGHT_PROP_ATTACK_PERCENT": tags.Q_ATK_PCT,
    "FIGHT_PROP_DEFENSE": tags.Q_FLAT_DEF,
    "FIGHT_PROP_DEFENSE_PERCENT": tags.Q_DEF_PCT,
    "FIGHT_PROP_BASE_HP": tags.Q_BASE_HP,
    "FIGHT_PROP_BASE_ATTACK": tags.Q_BASE_ATK,
    "FIGHT_PROP_BASE_DEFENSE": tags.Q_BASE_DEF,
    "FIGHT_PROP_ELEMENT_MASTERY": tags.Q_ELEMENTAL_MASTERY,
    "FIGHT_PROP_CHARGE_EFFICIENCY": tags.Q_ENERGY_RECHARGE,
    "FIGHT_PROP_CRITICAL": tags.Q_CRIT_RATE,
    "FIGHT_PROP_CRITICAL_HURT": tags.Q_CRIT_DMG,
    "FIGHT_PROP_HEAL_ADD": tags.Q_HEALING_BONUS,
    "FIGHT_PROP_HEALED_ADD": tags.Q_INCOMING_HEALING_BONUS,
    "FIGHT_PROP_SHIELD_COST_MINUS_RATIO": tags.Q_SHIELD_STRENGTH,
    **{
        f"FIGHT_PROP_{internal}_ADD_HURT": tags.dmg_bonus_q(channel)
        for internal, channel in (
            ("WIND", "anemo"), ("ICE", "cryo"), ("GRASS", "dendro"), ("ELEC", "electro"),
            ("ROCK", "geo"), ("WATER", "hydro"), ("FIRE", "pyro"), ("PHYSICAL", "physical"),
        )
    },
    **{
        f"FIGHT_PROP_{internal}_SUB_HURT": tags.res_q(channel)
        for internal, channel in (
            ("WIND", "anemo"), ("ICE", "cryo"), ("GRASS", "dendro"), ("ELEC", "electro"),
            ("ROCK", "geo"), ("WATER", "hydro"), ("FIRE", "pyro"), ("PHYSICAL", "physical"),
        )
    },
}

#: The two ways the source spells "no stat here" (C.2). Neither is an error.
_ABSENT_PROPS = frozenset({"", "FIGHT_PROP_NONE"})


def _quantity_for_prop(prop: str, *, allow_absent: bool = False) -> str | None:
    """Map a `FIGHT_PROP_*` key to a DAG quantity.

    Raises on an unknown prop rather than skipping it. A weapon whose substat this build
    does not know would otherwise be imported as having no substat — the exact failure D.4's
    review round fixed one layer up, and it would be no less quiet here.
    """
    upper = prop.upper()
    if upper in _ABSENT_PROPS:
        if allow_absent:
            return None
        msg = f"{prop!r} is the absent-stat marker, which is not a quantity"
        raise StatInputError(msg)
    quantity = _PROP_QUANTITIES.get(upper)
    if quantity is None:
        msg = (
            f"{prop!r} has no DAG quantity. Add it to _PROP_QUANTITIES and to "
            f"app/formula/genshin/tags.py; importing it as nothing would be a silently "
            f"weaker build."
        )
        raise StatInputError(msg)
    return quantity
