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

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.enums import LEVELLED_TALENTS
from app.services import gcsim_keys

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.artifact import Artifact
    from app.models.build import Build, EnemyProfile
    from app.models.weapon import Weapon

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


@dataclass(frozen=True)
class SubstituteWeapon:
    """A candidate weapon to emit in place of the build's own (W.2).

    **Substituted at the source, not by rewriting emitted text.** A regex over a finished
    config is the direct route to the failure this whole task exists to prevent: a
    substitution that quietly does nothing produces a *flat ranking* — every candidate scoring
    the worn weapon's number — which reads as "these weapons are equivalent" rather than as a
    bug, and is a conclusion a user would believe.

    `level` defaults to the build's own weapon level at the call site rather than to 90, so a
    comparison is like-for-like: ranking a level-90 worn weapon against level-1 candidates
    measures levelling, not weapons.

    `refinement` defaults to **1**, matching `WeaponCandidate.passive_refinement` and for the
    same stated reason — a candidate the user does not own has no refinement to read, so 1 is
    an assumption and is named as one rather than inferred from the worn weapon's.
    """

    weapon: Weapon
    level: int
    refinement: int = 1


#: Five slots hold at most two 2-piece sets; a third would need six.
_MAX_TWO_PIECE_SETS = 2


@dataclass(frozen=True)
class Calibration:
    """What a recipe is calibrated against, replacing the build's own artifacts.

    `docs/DESIGN_recipe_surface.md` §3. A calibration equips **one 4-piece set and an Energy
    Recharge**, and nothing else — the candidate's own stats are what the search varies, and a
    stat baked in here would be counted twice.

    **`energy_recharge` is not zero, and that is the correction `RESEARCH_recipe_risks.md` §1
    records.** ER is an artifact stat, so a zero-ER calibration runs at the character's base ER
    and lands on a *different burst count* — measured at **2 against a real candidate's 3**.
    ER is structural: baked in here, and a candidate's own ER is compared against the recipe's
    minimum rather than added as a damage stat.

    **The 4-piece set is equipped because it cannot be modelled any other way.** All 60 sets
    with a 4-piece have a conditional one (`RESEARCH_conditional_sets.md`), and the kernel
    understates them by 15–25 % (R.2). Equipping it also applies the 2-piece, so a caller must
    not add that set's bonuses again — `docs/TASKS_recipe_surface.md` R.4a.
    """

    #: The gcsim key of the 4-piece set, or `None` to calibrate a combination that reaches no
    #: 4-piece at all. Not a display name — take it through `gcsim_keys.artifact_set_key`.
    set_key: str | None
    #: Artifact-borne Energy Recharge as a fraction: `0.30` is +30 %.
    energy_recharge: float
    #: Sets equipped at **two** pieces, for a 2+2 combination. At most two.
    #:
    #: **Why a 2-piece needs equipping at all**, when 51 of the 60 two-piece bonuses are static
    #: stat grants a caller can add itself: the other **nine** are not. Six are ability-scoped
    #: DMG bonuses — Noblesse Oblige's burst +20 %, Marechaussee Hunter's normal/charged
    #: +15 % — which a flat stat pool cannot express, because it cannot say *only on burst
    #: hits*. Owner ruling 1 (2026-08-28, `docs/DECISIONS.md`) is that those are calibrated
    #: rather than derived from `param_list`, so gcsim applies the real bonus.
    #:
    #: Mutually exclusive with `set_key`: a five-slot combination cannot hold a 4-piece and a
    #: 2+2 at once, and emitting both would describe a build that cannot exist.
    two_piece_set_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a combination no five slots can hold, rather than emitting it."""
        if self.set_key is not None and self.two_piece_set_keys:
            msg = "a calibration is either a 4-piece or a 2+2, never both"
            raise ValueError(msg)
        if len(self.two_piece_set_keys) > _MAX_TWO_PIECE_SETS:
            msg = f"at most two 2-piece sets fit in five slots; got {len(self.two_piece_set_keys)}"
            raise ValueError(msg)


#: A character declaration in an emitted config: `nahida char lvl=90/90 …;`
_CHAR_LINE = re.compile(r"^([a-z0-9]+) char lvl=", re.M)


def character_order(config: str) -> list[str]:
    """The gcsim keys a config declares, in the order it declares them.

    **Read off the emitted text rather than rebuilt from the build and its teammates.** The two
    would be one refactor away from disagreeing, and the consequence is quiet: gcsim's
    aggregate reports `character_actions` as a positional list, so a mismatched order would
    attribute one character's instability to another — a warning naming the wrong person, which
    is worse than no warning.

    Order matters because the emitter puts the build's own character first and teammates after
    (`_teammate_lines`), which is also the order gcsim indexes them in.
    """
    return _CHAR_LINE.findall(config)


#: The energy a team collects from particles and enemy hits that its own rotation does not
#: generate — emitted **only** for the waiting model, where a burst is ungated and gcsim holds
#: the whole simulation until it can be paid for.
#:
#: **Without it, waiting does not terminate.** gcsim has no watchdog:
#: `actionReadyCheckPhase` retries the frame forever and `stopCheck` never consults duration in
#: damage mode, so an unfundable burst blocks the run while a per-frame stats slice grows —
#: measured at **2.4 GB and `fatal error: out of memory`**. The drip bounds the wait, and the
#: *length* of that wait is the Energy Recharge penalty the waiting model exists to price.
#:
#: **Cited, not chosen.** Five configs use this exact line, four committed under
#: `references/gcsim_db/` and one the owner's own import; three of them call it *standard
#: Energy drops*:
#:
#:   - `clorinde-chevreuse-nicole-durin.txt:30`
#:   - `mavuika-escoffier-citlali-bennett.txt:33`
#:   - `arlecchino-citlali-escoffier-bennett.txt:34`
#:   - `neuvillette-furina-citlali-escoffier.txt:32`
#:   - `gcsim.app/db/bgHjR7MP7Fkn:36`
#:
#: It is still an **assumption**, and a ranking produced under it is a ranking against a stated
#: rate of incoming energy. Saying so is the difference between a citation and a claim.
ENERGY_DRIP = "energy every interval=480,720 amount=1;"


def build_config(
    build: Build,
    *,
    teammates: Sequence[Build] = (),
    calibration: Calibration | None = None,
    substitute_weapon: SubstituteWeapon | None = None,
    actions: Sequence[str] | None = None,
    action_block: str | None = None,
    enemy: EnemyProfile | None = None,
    iterations: int = 100,
    energy_drip: bool = False,
) -> str:
    """The gcsim config text for one build.

    Two ways to supply the rotation, and exactly one may be used:

    - **`action_block`** — a compiled block from `rotation_compiler`, emitted verbatim. This
      is the real path: it carries the rotation as the user defined it, already unrolled, and
      the run ends when those actions do rather than at a duration this file chose.
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
        # **No `swap_delay`.** It is omitted rather than set, and never set to 0: gcsim
        # queues the swap to land `Delays.Swap` frames later
        # (`pkg/core/player/exec.go:156`), so at **0 the swap never lands** before the next
        # action is requested and the run dies with *"requested next char X is not active and
        # next action is not swap"*. This emitter hardcoded `swap_delay=0`, so **every
        # multi-character rotation it produced was unrunnable** — natively and in the browser
        # alike. Solo rotations never swap, which is why it went unnoticed.
        #
        # Omitted rather than pinned to a number, because gcsim's default is gcsim's answer
        # (`pkg/gcs/parser/parser.go:55`, "default swap timer of 1") and a value restated here
        # is one this repo would have to defend as game data.
        # **No `duration`.** It is not omitted for tidiness: the target carries `hp=`, and in
        # HP mode gcsim ignores `duration` outright — measured on the owner's rotation, which
        # reports the same 189.3 s whether the config says `duration=90`, `duration=3600` or
        # nothing at all. Emitting it would be a line that looks like it decides something and
        # does not, which is how `duration=90` spent months deciding what every rotation
        # measured. `target_fields` carries the argument for HP mode itself.
        f"options iteration={iterations};",
        "",
        char_line,
    ]

    # The candidate wins when one is given, and it is emitted **even if the build has no
    # weapon of its own** — "compare these against nothing worn" is a coherent question, and
    # falling through to no weapon line would answer a different one.
    if substitute_weapon is not None:
        lines.append(
            f'{key} add weapon="{gcsim_keys.weapon_key(substitute_weapon.weapon.name)}" '
            f"lvl={substitute_weapon.level}/90 refine={substitute_weapon.refinement};"
        )
    elif build.weapon is not None:
        lines.append(
            f'{key} add weapon="{gcsim_keys.weapon_key(build.weapon.name)}" '
            f"lvl={build.weapon_level}/90 refine={build.refinement};"
        )

    # A calibration replaces the build's artifacts wholesale: one 4-piece set and an ER, and
    # no other stat. Falling through to the build's own pieces would bake its substats into
    # every recipe scored against it.
    if calibration is not None:
        lines.extend(_calibration_lines(key, calibration))
    else:
        lines.extend(_artifact_lines(key, build.artifacts))
    # **Everyone the rotation names has to be declared.** A multi-character action block over
    # a config declaring one character is not a config that fails — gcsim accepts it and
    # simulates *nobody*: `character_details` comes back `[]`, the log is empty, and every
    # damage figure is zero. `sample()` returns valid JSON throughout, so a caller checking
    # only that it parsed sees a clean result describing an empty simulation.
    #
    # That is what `/builds/{id}/calibrate` did. It validated that the build's character was
    # on the rotation's team, compiled the *team's* rotation, and then emitted one character
    # — so every recipe calibrated to zeros and `/optimize` ranked ten builds at 0 damage
    # while reporting `isExact`. See `AUDIT_fribbels_parity.md` §9a.
    #
    # Teammates carry **their own gear**, never the calibration: their buffs are what the
    # subject's damage is being measured inside, and a Furina at calibration stats is a
    # different Furina. This is also the whole of the owner's ruling that ranking asks "given
    # this character *in this team*" (`DECISIONS.md` §22).
    lines.extend(_teammate_lines(teammates, subject_key=key, subject_id=build.id))

    lines.append("")
    lines.append(_target(enemy))
    if energy_drip:
        lines.append(ENERGY_DRIP)
    lines.append("")
    if action_block is not None:
        # Verbatim: the block already names its own `active` character, which is the first
        # *step's* rather than this build's — a multi-character rotation may open on someone
        # else, and re-deriving it here would fight the compiler.
        lines.append(action_block.rstrip("\n"))
    else:
        lines.append(f"active {key};")
        lines.extend(f"{key} {action};" for action in actions or ())
    text = "\n".join(lines) + "\n"
    _refuse_undeclared_characters(text)
    return text


#: `active noelle;` and `noelle burst;` — the two shapes that name a character in an action
#: block. Deliberately not a general parser: this is a guard over text *this module emits*.
#:
#: **The `[param=1]` group is not optional decoration.** The compiler emits `skill[hold=1]` for
#: a kit variant, and without this the guard matched nothing on those lines — so a config whose
#: only mention of a character was a hold would have passed a check written precisely to catch
#: a config that names somebody it never declared. gcsim accepts that and simulates *nobody*:
#: `character_details` comes back empty and the damage is zero, in valid JSON.
_NAMES_A_CHARACTER = re.compile(
    r"^(?:active\s+([a-z0-9]+)\s*;|(?:if\s+\.[a-z0-9]+\.[a-z_]+\.ready\s*\{\s*)?"
    r"([a-z0-9]+)\s+[a-z_]+(?:\[[^\]]*\])?(?::\d+)?\s*;)",
    re.M,
)


def _refuse_undeclared_characters(text: str) -> None:
    """Refuse a config whose rotation names somebody it never declared.

    **This is the guard the zero-damage bug needed and did not have.** gcsim does not reject
    such a config: it accepts it and simulates *nobody* — `character_details` comes back `[]`,
    the log is empty, every damage is zero — while `sample()` returns perfectly valid JSON. So
    a caller that checks only "did it parse" sees a clean result describing an empty
    simulation, and calibrates a recipe of zeros from it.

    That is not a hypothetical. `/builds/{id}/calibrate` emitted one character's stanza beside
    a four-character action block for months; `/optimize` then ranked ten builds at 0 damage
    and labelled them `isExact`. `AUDIT_fribbels_parity.md` §9a.

    Refusing here rather than checking the *result* is deliberate: a bad config is knowable
    from the text, at the moment it is written, without a simulator and without a browser.
    """
    declared = set(re.findall(r"^([a-z0-9]+) char ", text, re.M))
    named: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        match = _NAMES_A_CHARACTER.match(stripped)
        if match:
            named.add(match.group(1) or match.group(2))
    missing = sorted(named - declared)
    if missing:
        msg = (
            f"this config's rotation names {missing}, which it never declares. gcsim would "
            f"accept it and simulate nobody — an empty log and zero damage, returned as valid "
            f"JSON — so the failure would arrive as a confident zero rather than as an error."
        )
        raise GcsimConfigError(msg)


def _teammate_lines(
    teammates: Sequence[Build], *, subject_key: str, subject_id: object,
) -> list[str]:
    """Every teammate's own stanza — character, weapon and their real artifacts.

    Split out so `build_config` stays inside its branch budget, and because this is one idea:
    *the rest of the party, as they actually are*.
    """
    out: list[str] = []
    for mate in teammates:
        if mate.character is None or mate.id == subject_id:
            continue
        mate_key = gcsim_keys.character_key(
            mate.character.nanoka_id, mate.character.name, mate.character.element,
        )
        if mate_key == subject_key:
            continue
        out.append("")
        out.append(
            f"{mate_key} char lvl={mate.character_level}/90 "
            f"cons={mate.constellation_level} talent={_talents(mate)};",
        )
        if mate.weapon is not None:
            out.append(
                f'{mate_key} add weapon="{gcsim_keys.weapon_key(mate.weapon.name)}" '
                f"lvl={mate.weapon_level}/90 refine={mate.refinement};",
            )
        out.extend(_artifact_lines(mate_key, mate.artifacts))
    return out


def _talents(build: Build) -> str:
    """Three levels, in the attack/skill/burst order gcsim expects.

    The order and membership come from `LEVELLED_TALENTS`, which the build schema validates
    against — so a key the schema accepts is a key this renders, and vice versa. They were
    two lists until T.1, and the `get(name, 1)` below is why that mattered: an accepted key
    this did not list was stored and ignored, and a misspelled one rendered as level 1.
    """
    levels = build.talent_levels or {}
    return ",".join(str(levels.get(str(talent), 1)) for talent in LEVELLED_TALENTS)


def _calibration_lines(key: str, calibration: Calibration) -> list[str]:
    """The set and ER a calibration equips, and nothing else.

    Deliberately **not** built from `_artifact_lines`: that derives set counts and stat totals
    from the same loop over equipped pieces, and a calibration has neither. Sharing it would
    mean threading "ignore the stats but keep the sets" through a function whose whole shape is
    that they come together.
    """
    lines: list[str] = []
    if calibration.set_key is not None:
        lines.append(f'{key} add set="{calibration.set_key}" count=4;')
    lines.extend(
        f'{key} add set="{set_key}" count=2;' for set_key in calibration.two_piece_set_keys
    )
    # Emitted even at zero, because "the calibration states its ER" is the property that makes
    # a recipe's minimum meaningful — an absent line reads as "unspecified", not "none".
    lines.append(f"{key} add stats er={calibration.energy_recharge:g};")
    return lines


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


#: Target HP, set so gcsim never kills it — which is how a run is told to end when the
#: **actions** end rather than at a duration.
#:
#: gcsim has two stopping rules. Without `hp` it runs for `duration` and pads with idle time
#: once the action list is exhausted, so a 20-second rotation was reported as a 90-second one
#: and its DPS divided by ninety. With `hp` it runs until the target dies **or the actions run
#: out**, and `duration` is ignored outright — measured on the owner's rotation, which reports
#: the same 189.3 s whether the config says `duration=90`, `duration=3600` or nothing.
#:
#: So this number's job is to never be reached. It is the same value the gcsim database's own
#: configs use (`references/gcsim_db/skirk-furina-citlali-escoffier.txt`), which is the
#: strongest argument available that it is the community's idiom rather than this repo's
#: invention. Owner ruling, 2026-09-01: *"The optimizer should run through the rotation as
#: defined to completion, regardless of how short/long it is."*
_UNKILLABLE = 999999999

def target_fields(enemy: EnemyProfile | None) -> dict[str, object]:
    """What gcsim is being pointed at, as fields.

    Shared with `sim_context.context_key` (R.6) so a cache key and the config it was cached
    from cannot describe different enemies. Rendering the line and hashing the target from
    two separate readings of the profile would drift, and the drift would surface as a
    cached number for the wrong target — which is what the key is for.

    A profile's resistances are per channel and gcsim takes one `resist=`, so a profile with
    uneven resistances cannot be expressed and is refused rather than averaged — an average
    is a number for an enemy that does not exist.
    """
    if enemy is None:
        # The default target, in one place. Two literals would be one literal and a copy.
        return {"lvl": 90, "resist": 0.1, "pos": "0,1", "hp": _UNKILLABLE}

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
    return {
        "lvl": enemy.level, "resist": resistances.pop(), "pos": "0,1", "hp": _UNKILLABLE,
    }


def _target(enemy: EnemyProfile | None) -> str:
    """The target line, rendered from `target_fields`.

    Every field the dict carries is rendered, `hp` included — the two must not diverge, because
    `sim_context.context_key` hashes this same dict and a key that omitted `hp` would serve a
    cached run from the duration-capped era for a config that is no longer duration-capped.
    """
    fields = target_fields(enemy)
    return (
        f"target lvl={fields['lvl']} resist={fields['resist']:g} "
        f"pos={fields['pos']} hp={fields['hp']};"
    )
