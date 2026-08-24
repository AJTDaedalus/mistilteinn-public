"""Emit a gcsim config from a stored build.

gcsim's config is a small text format: options, one block per character, a target, and an
action list. This turns a `Build` into that text so the browser can hand it to the simulator
(DESIGN_client_optimizer §1).

## What this deliberately does not decide

**The action list.** gcsim needs a rotation to simulate, and this repo has no rotation model
— that is the BRIEF's *"rotation corpus (community action-list DB → default rotations per
team archetype)"*, and it is Chunk D's problem. The caller supplies one. Emitting a guessed
rotation would produce a number that looks like a simulation of this build and is a
simulation of something else.

## Refuse, do not approximate

Every key goes through `gcsim_keys`, which refuses anything gcsim does not implement at the
pin. That refusal propagates: a build containing one unsimulatable piece cannot be simulated,
and saying so is the only honest answer. Substituting a similar set would return a
confident, wrong number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services import gcsim_keys

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.artifact import Artifact
    from app.models.build import Build, EnemyProfile

#: gcsim's stat names for the artifact main/substats this repo stores. Its config vocabulary,
#: not this repo's — `pkg/core/attributes/stats.go` at the pin, the same file
#: `formula/genshin/tags.py` already cites for the stat vocabulary.
_STAT_KEYS: dict[str, str] = {
    "FIGHT_PROP_HP": "hp",
    "FIGHT_PROP_HP_PERCENT": "hp%",
    "FIGHT_PROP_ATTACK": "atk",
    "FIGHT_PROP_ATTACK_PERCENT": "atk%",
    "FIGHT_PROP_DEFENSE": "def",
    "FIGHT_PROP_DEFENSE_PERCENT": "def%",
    "FIGHT_PROP_ELEMENT_MASTERY": "em",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "er",
    "FIGHT_PROP_CRITICAL": "cr",
    "FIGHT_PROP_CRITICAL_HURT": "cd",
    "FIGHT_PROP_HEAL_ADD": "heal",
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "phys%",
    "FIGHT_PROP_WIND_ADD_HURT": "anemo%",
    "FIGHT_PROP_ICE_ADD_HURT": "cryo%",
    "FIGHT_PROP_GRASS_ADD_HURT": "dendro%",
    "FIGHT_PROP_ELEC_ADD_HURT": "electro%",
    "FIGHT_PROP_ROCK_ADD_HURT": "geo%",
    "FIGHT_PROP_WATER_ADD_HURT": "hydro%",
    "FIGHT_PROP_FIRE_ADD_HURT": "pyro%",
}


class GcsimConfigError(ValueError):
    """This build cannot be expressed as a gcsim config."""


def build_config(
    build: Build,
    *,
    actions: Sequence[str] | None = None,
    action_block: str | None = None,
    enemy: EnemyProfile | None = None,
    iterations: int = 100,
    duration: int = 90,
) -> str:
    """The gcsim config text for one build.

    Two ways to supply the rotation, and exactly one may be used:

    - **`action_block`** — a compiled block from `rotation_compiler`, emitted verbatim. This
      is the real path: it carries the `while 1` loop and the readiness gates, without which
      the rotation runs once or deadlocks.
    - **`actions`** — a flat list of bare action names for the build's own character, emitted
      one per line with no loop and no gates. It predates the rotation model and survives for
      the B.3 sample configs, whose whole job is to prove the *character and gear* lines are
      well-formed. **A config built this way runs its actions once**, which is correct for a
      fixture and wrong for a simulation anybody reads a number off.
    """
    if (actions is None) == (action_block is None):
        msg = (
            "supply exactly one of `actions` or `action_block`. Both would mean two "
            "rotations in one config and a silent choice about which wins; neither means "
            "a config that simulates a character standing still."
        )
        raise GcsimConfigError(msg)
    if build.character is None:
        msg = f"build {build.id} has no character; there is nothing to simulate"
        raise GcsimConfigError(msg)
    if actions is not None and not actions:
        msg = (
            "a gcsim config needs an action list. A guessed rotation would simulate "
            "something other than what was asked for."
        )
        raise GcsimConfigError(msg)
    if action_block is not None and not action_block.strip():
        msg = "the compiled action block is empty; there is nothing to simulate"
        raise GcsimConfigError(msg)

    key = gcsim_keys.character_key(
        build.character.nanoka_id, build.character.name, build.character.element,
    )
    char_line = (
        f"{key} char lvl={build.character_level}/90 "
        f"cons={build.constellation_level} talent={_talents(build)};"
    )
    lines = [
        f"options iteration={iterations} duration={duration} swap_delay=0;",
        "",
        char_line,
    ]

    if build.weapon is not None:
        weapon_line = (
            f'{key} add weapon="{gcsim_keys.weapon_key(build.weapon.name)}" '
            f"lvl={build.weapon_level}/90 refine={build.refinement};"
        )
        lines.append(weapon_line)

    lines.extend(_artifact_lines(key, build.artifacts))
    lines.append("")
    lines.append(_target(enemy))
    lines.append("")
    if action_block is not None:
        # Verbatim: the block already names its own `active` character, which is the first
        # *step's* rather than this build's — a multi-character rotation may open on someone
        # else, and re-deriving it here would fight the compiler.
        lines.append(action_block.rstrip("\n"))
    else:
        lines.append(f"active {key};")
        lines.extend(f"{key} {action};" for action in actions or ())
    return "\n".join(lines) + "\n"


def _talents(build: Build) -> str:
    """Three levels, in the attack/skill/burst order gcsim expects."""
    levels = build.talent_levels or {}
    return ",".join(
        str(levels.get(name, 1))
        for name in ("normal_attack", "elemental_skill", "elemental_burst")
    )


def _artifact_lines(key: str, artifacts: Sequence[Artifact]) -> list[str]:
    """Set counts, then the summed stats.

    gcsim takes an artifact build as *set counts plus a stat total*, not as five pieces —
    it does not model individual artifacts, which is precisely why the optimizer is this
    project's job and not gcsim's.
    """
    if not artifacts:
        return []

    counts: dict[str, int] = {}
    stats: dict[str, float] = {}
    for artifact in artifacts:
        if artifact.artifact_set is not None:
            set_key = gcsim_keys.artifact_set_key(artifact.artifact_set.name)
            counts[set_key] = counts.get(set_key, 0) + 1
        _accumulate(stats, artifact.main_stat_type, artifact.main_stat_value)
        for substat in artifact.substats or []:
            _accumulate(stats, substat.get("stat"), float(substat.get("value", 0.0)))

    lines = [f'{key} add set="{s}" count={c};' for s, c in sorted(counts.items())]
    if stats:
        totals = " ".join(f"{name}={value:g}" for name, value in sorted(stats.items()))
        lines.append(f"{key} add stats {totals};")
    return lines


def _accumulate(stats: dict[str, float], prop: object, value: float) -> None:
    """Sum one stat into the total, refusing a prop gcsim has no name for."""
    if prop is None or not value:
        return
    name = _STAT_KEYS.get(str(prop).upper())
    if name is None:
        msg = (
            f"gcsim has no stat name for {prop!r}. Dropping it would understate the build "
            f"by however much it was worth, silently."
        )
        raise GcsimConfigError(msg)
    stats[name] = stats.get(name, 0.0) + value


def _target(enemy: EnemyProfile | None) -> str:
    """The target line.

    A profile's resistances are per channel and gcsim takes one `resist=`, so a profile with
    uneven resistances cannot be expressed and is refused rather than averaged — an average
    is a number for an enemy that does not exist.
    """
    if enemy is None:
        return "target lvl=90 resist=0.1 pos=0,1;"

    resistances = {
        enemy.physical_res, enemy.anemo_res, enemy.cryo_res, enemy.dendro_res,
        enemy.electro_res, enemy.geo_res, enemy.hydro_res, enemy.pyro_res,
    }
    if len(resistances) > 1:
        msg = (
            f"enemy profile {enemy.name!r} has uneven resistances {sorted(resistances)}, and "
            f"a gcsim target takes one `resist=`. Averaging them would simulate an enemy "
            f"that does not exist; pick a channel-specific target instead."
        )
        raise GcsimConfigError(msg)
    return f"target lvl={enemy.level} resist={resistances.pop():g} pos=0,1;"
