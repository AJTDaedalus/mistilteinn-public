"""Read a gcsim action block back into rotation steps.

The inverse of `rotation_compiler`, over the subset that compiler emits.
`docs/DESIGN_rotation_library.md` §1.

## Why this exists, against what the compiler says

`rotation_compiler`'s docstring reads *"One direction only: gcsim's config is a build
artifact, not a format this repo reads back."* That was correct while the only configs in
play were ones this app had emitted seconds earlier — reading them back would have been a
round trip with no source. The owner asked for import (2026-08-29), which supplies the source
and reverses the decision deliberately rather than by drift.

## The subset, and why it is the whole feature

**gcsim's language is much larger than ten actions.** A community config can carry conditional
expressions (`if .noelle.energy > 40`), loops other than `while 1`, `wait` for buff alignment,
per-character options and status guards. A mistilteinn rotation is a list of
`(character, action, repeat, note)` and nothing else.

So an arbitrary config **cannot** round-trip, and the design question is not how to parse
gcsim but what happens to the parts that do not fit. This module's answer is: **nothing fits
partially.** Every line is understood or the import is refused, naming every line at fault.

Skipping the parts it could not express would be the worse failure and the quiet one. A
rotation whose `if .energy > 40` guard was dropped bursts every cycle instead of when the
energy is there — it looks like the author's rotation, carries their name on it, and
simulates to a number they never published. The user has no way to see the difference. That
is the same shape as `weapon_comparison.unmodelled_passives` and the substat `isExact` flag,
in a place with even less chance of being noticed.

## Keys are matched forward, never reversed

`gcsim_keys.character_key` maps `(nanoka_id, name, element)` onto a key. Inverting that by
rule — stripping an element suffix, un-normalising a name — would be a second implementation
of the mapping, free to drift from the real one, and the drift would land on Travelers, whose
keys are *structured* rather than normalised.

Instead the roster's keys are computed with the same function and matched. A key that no
roster character produces is refused by name. That cannot disagree with the compiler, because
it is the compiler's own function.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.services import gcsim_keys

if TYPE_CHECKING:
    from collections.abc import Iterable


class RotationParseError(ValueError):
    """The config cannot be read as a rotation, and the message says which lines are at fault."""


#: `active <key>;` — the compiler emits the *first step's* character, not a team slot.
_ACTIVE = re.compile(r"^active\s+([a-z0-9]+)\s*;$")

#: `if .<key>.<action>.ready { <key> <action>[param=1][:n]; }` — the only statement shape
#: emitted.
#:
#: **The parameter group is here because the compiler emits one.** A kit variant is an action
#: in this model and `skill[hold=1]` in gcsim's syntax, so without it a config *this repo
#: produced* could not be read back by *this repo's* importer — and the refusal blamed the
#: condition, which was not what was wrong. Real community configs use the same form:
#: `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt:48`.
_GATED = re.compile(
    r"^if\s+\.([a-z0-9]+)\.([a-z_]+)\.ready\s*\{\s*"
    r"([a-z0-9]+)\s+([a-z_]+)(?:\[([^\]]*)\])?(?::([^\s;]+))?\s*;\s*\}$",
)

#: `hold=1`, and nothing cleverer. gcsim accepts arbitrary integers and several parameters at
#: once; this model expresses exactly one boolean variant per action, so anything else is
#: refused by name rather than approximated.
_PARAM = re.compile(r"^([a-z_0-9]+)=1$")


def parse_action_block(config: str, characters: Iterable[Any]) -> list[dict[str, Any]]:
    """The rotation steps `config`'s action block describes.

    `characters` is the roster a step may name — catalogue rows, or anything carrying
    `nanoka_id`, `name` and `element`. The caller supplies it for the same reason
    `compile_rotation` takes a mapping: resolving a team is a database question, and this
    stays a pure function.

    Raises `RotationParseError` naming **every** line it could not read, rather than the first.
    A user fixing an import should learn what is wrong with it once.
    """
    by_key = _roster_keys(characters)
    lines = [line.strip() for line in config.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]

    body = _loop_body(lines, by_key)

    steps: list[dict[str, Any]] = []
    problems: list[str] = []
    for line in body:
        step, problem = _statement(line, by_key)
        if step is not None:
            steps.append(step)
        else:
            problems.append(problem)

    if problems:
        msg = (
            "this config uses gcsim features a rotation cannot express, so it was not "
            "imported:\n  - " + "\n  - ".join(problems) + "\n"
            "A rotation is a list of character/action/repeat steps. Importing it without "
            "these lines would produce something that looks like the author's rotation and "
            "simulates to a different number."
        )
        raise RotationParseError(msg)

    if not steps:
        msg = (
            "the loop has no steps in it. A rotation with no steps is nothing to do — gcsim "
            "would accept the config and simulate a character standing still."
        )
        raise RotationParseError(msg)
    return steps


def _roster_keys(characters: Iterable[Any]) -> dict[str, str]:
    """Map each roster character's gcsim key to its nanoka id, computed **forward**.

    Forward, with the compiler's own function — never by inverting a key.

    A character gcsim has no key for is simply absent, and a step naming it is then refused
    like any other unknown key — which is the right answer twice over: gcsim could not have
    simulated it either.
    """
    keys: dict[str, str] = {}
    for character in characters:
        try:
            key = gcsim_keys.character_key(
                character.nanoka_id, character.name, character.element,
            )
        except gcsim_keys.GcsimKeyError:
            continue
        keys[key] = character.nanoka_id
    return keys


def _canonical(key: str, by_key: dict[str, str]) -> str:
    """`arle` → `arlecchino`, when the roster has them under the canonical spelling.

    gcsim accepts 60 short names for characters and this repo emits none of them, so an alias
    only ever arrives from **somebody else's config** — which is exactly the case import
    exists for. Resolved against the roster rather than blindly: an alias for a character who
    is not on the team is still a refusal, and should still say so by the name the config used.
    """
    if key in by_key:
        return key
    alias = gcsim_keys.character_alias(key)
    return alias if alias is not None and alias in by_key else key


def _loop_body(lines: list[str], by_key: dict[str, str]) -> list[str]:
    """The statements inside `while 1 { … }`, refusing every other shape.

    **A bare action list is refused, and that is the point.** gcsim runs one without a loop
    exactly once, so a ninety-second config produces a single burst — a plausible number for a
    question nobody asked. It is the first of the two silent behaviours the compiler was
    written to prevent, and importing one would let it in through the back door.
    """
    opens = [i for i, line in enumerate(lines) if line.startswith("while")]
    if not opens:
        # **Say which it is.** A `for` loop is a loop, and reporting "no loop" for a config
        # that plainly has one sends the reader looking for a bug in their file. Measured
        # against a real community config (`skirk_team.txt`), which uses
        # `for let i=0; i<1; i=i+1 { … }` and got told it had no loop at all.
        if any(line.startswith(("for ", "for(")) for line in lines):
            msg = (
                "the loop is a `for`, not `while 1`. A bounded loop runs a rotation a fixed "
                "number of times, which is a property of the *simulation* — how long to run "
                "for — rather than of the rotation itself, and this model has no field for "
                "it. The steps inside are very likely importable once the loop is `while 1`."
            )
            raise RotationParseError(msg)
        msg = (
            "no loop at all. A rotation is a cycle, and gcsim runs a bare action list "
            "**once** — over a 90-second duration that is one burst, reported without "
            "complaint. If this config is meant to run its actions a single time it is not a "
            "rotation this app can hold."
        )
        raise RotationParseError(msg)
    if len(opens) > 1:
        # **Say which it is, again.** Both community configs that reach this branch have one
        # top-level cycle and one `while` *inside a user-defined function* — a helper that
        # waits for a cooldown, not a second rotation. Reporting "2 loops. Which of these is
        # it?" sends a reader looking for an ambiguity their file does not have.
        #
        # Measured, not assumed: of the four configs under `references/gcsim_db/`, the two
        # that refuse here are exactly the two carrying an `fn`.
        if any(line.startswith("fn ") for line in lines):
            msg = (
                "the config defines its own functions, and one of them loops. A named "
                "sequence with a body of its own is a *different rotation*, not a different "
                "spelling of one — this model holds an ordered list of "
                "`(character, action, repeat)` and has nowhere to put a helper that waits on "
                "a cooldown or branches on Nightsoul points. Inline what the function does, "
                "or author the rotation here."
            )
            raise RotationParseError(msg)
        msg = (
            f"{len(opens)} loops. A rotation is one cycle; which of these is it, and what "
            f"decides when the others run? That is a question this model has no field for."
        )
        raise RotationParseError(msg)

    start = opens[0]
    if lines[start] != "while 1 {":
        msg = (
            f"the loop is {lines[start]!r}, not `while 1 {{`. A bounded or conditional loop "
            f"repeats a rotation a number of times, which is a property of the simulation "
            f"rather than of the rotation, and this model does not carry it."
        )
        raise RotationParseError(msg)

    # **Anything before the loop is guarded the same way as anything after it.** The tail
    # check below has been here since the start; the head had none, and an opener — the
    # statements a config runs once before its cycle — was dropped without a word. Measured on
    # a real community config (gcsim db `kDHmWKmfgqtF`): 19 statements silently discarded,
    # including the on-field character's burst, leaving 32 steps that looked like a clean
    # import of a 51-statement rotation. That is precisely the failure the tail comment names,
    # and it was on the side nobody had written a check for.
    #
    # A *config* statement is not an opener: `skirk char lvl=90`, `add weapon=`, `options`,
    # `target`, `energy` and `active` all legitimately precede the loop and carry no actions.
    # The test is whether the line reads as an action, asked with the same parser that reads
    # the body — so the two can never disagree about what an action is.
    head = [line for line in lines[:start] if line]
    opener = [line for line in head if _statement(line, by_key)[0] is not None]
    if opener:
        msg = (
            f"{len(opener)} statement(s) run before the loop and would be dropped: "
            f"{'; '.join(repr(o) for o in opener)}. That is an opener — actions a rotation "
            f"performs once before its cycle — and this model holds a single repeating list, "
            f"so importing it would silently discard them. The loop itself is importable "
            f"without them."
        )
        raise RotationParseError(msg)

    # Anything after the closing brace is outside the rotation and is not silently ignored:
    # gcsim would run it, so a config carrying it does not mean what the imported steps say.
    closes = [i for i, line in enumerate(lines) if line == "}"]
    if not closes:
        msg = "the `while 1 {` loop is never closed."
        raise RotationParseError(msg)
    tail = [line for line in lines[closes[-1] + 1 :] if line]
    if tail:
        msg = (
            f"{len(tail)} statement(s) follow the loop and would run after it: "
            f"{'; '.join(repr(t) for t in tail)}. A rotation is the loop and nothing else."
        )
        raise RotationParseError(msg)
    return [line for line in lines[start + 1 : closes[-1]] if line]


def _statement(line: str, by_key: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
    """One gated action, or the reason this line could not be read as one."""
    match = _GATED.match(line)
    if match is None:
        return None, _why_not(line)

    gate_key, gate_action, key, action, param_text, repeat_text = match.groups()
    # Both sides, and **before** they are compared: a config writing `if .arle.skill.ready
    # { arle skill; }` must still be checked for the gate matching its own action.
    gate_key = _canonical(gate_key, by_key)
    key = _canonical(key, by_key)

    # `if .noelle.skill.ready { noelle burst; }` is legal gcsim and is not what the compiler
    # emits. Reading it as a burst step discards the condition; reading it as a skill step
    # discards the action. Neither is recoverable, so neither is guessed at.
    if (gate_key, gate_action) != (key, action):
        return None, (
            f"{line!r} — the gate gates `.{gate_key}.{gate_action}` but the action is "
            f"`{key} {action}`. A step carries one condition, on itself."
        )

    unnameable = _unnameable(line, key, action, by_key)
    if unnameable is not None:
        return None, unnameable

    if param_text is not None:
        action, problem = _variant(line, action, param_text)
        if action is None:
            return None, problem

    repeat, problem = _repeat(line, repeat_text)
    if repeat is None:
        return None, problem

    return {"character": by_key[key], "action": action, "repeat": repeat, "note": ""}, ""


def _unnameable(line: str, key: str, action: str, by_key: dict[str, str]) -> str | None:
    """Why this line names something a step cannot, or `None` if it names nothing wrong."""
    if key not in by_key:
        return (
            f"{line!r} — no character on this team is gcsim's {key!r}. Add them to the team, "
            f"or import this rotation against the team it was written for."
        )
    if action not in gcsim_keys.authorable_actions():
        return (
            f"{line!r} — {action!r} is not an action a rotation step can name. The ten are "
            f"{list(gcsim_keys.authorable_actions())}."
        )
    return None


def _repeat(line: str, repeat_text: str | None) -> tuple[int | None, str]:
    """The `:n` repetition gcsim writes, or the reason it is not a count."""
    if repeat_text is None:
        return 1, ""
    if not repeat_text.isdigit() or int(repeat_text) < 1:
        return None, (
            f"{line!r} — {repeat_text!r} is not a repeat count. `attack:0` is not an attack, "
            f"and reading it as one would import a step this config does not have."
        )
    return int(repeat_text), ""


def _variant(line: str, action: str, param_text: str) -> tuple[str | None, str]:
    """The action a `[param=1]` group names, or the reason it names none.

    **Refused rather than dropped.** gcsim *ignores* a parameter a character does not declare —
    measured: `xingqiu skill[hold=1]` and `xingqiu skill` produce byte-identical damage — so
    importing `skill[glide_cancel=1]` as a plain `skill` would produce a rotation that looks
    like the author's and simulates to a different number. That is the exact failure this
    parser exists to make impossible.
    """
    parsed = _PARAM.match(param_text.strip())
    if parsed is None or parsed.group(1) not in gcsim_keys.VARIANT_PARAMS:
        return None, (
            f"{line!r} — `[{param_text}]` is not a kit variant this model can hold. It "
            f"expresses one of {sorted(gcsim_keys.VARIANT_PARAMS)} as its own action, and "
            f"importing this without the parameter would be a different rotation that looks "
            f"like the author's."
        )
    variant = gcsim_keys.variant_action(action, parsed.group(1))
    if variant not in gcsim_keys.all_offerable_actions():
        return None, (
            f"{line!r} — no character declares `{parsed.group(1)}` on `{action}` at this gcsim "
            f"pin, so there is no such move to import."
        )
    return variant, ""


def _why_not(line: str) -> str:
    """Name the gcsim feature this line uses, rather than reporting a parse position.

    A user importing someone else's rotation did not write this line and cannot be expected to
    diff it against a grammar. What they can act on is *which feature* is missing here.
    """
    first = line.split(None, 1)[0].rstrip(";") if line.split() else line
    if first in {"wait", "delay"}:
        return (
            f"{line!r} — `{first}` aligns a rotation in time, and this model has no timing "
            f"field. A rotation missing its waits is a different rotation."
        )
    if line.startswith("if"):
        return (
            f"{line!r} — the only condition a step can carry is `.<char>.<action>.ready`. "
            f"This one guards on something else, and dropping it would change what the "
            f"rotation does while leaving something that looks like it."
        )
    if _ACTIVE.match(line):
        return (
            f"{line!r} — `active` inside the loop is an explicit swap. gcsim inserts swaps "
            f"itself when the next character is not the active one, so this model has no "
            f"step for one."
        )
    if re.match(r"^[a-z0-9]+\s+[a-z_]+(:\S+)?\s*;$", line):
        return (
            f"{line!r} — an action with no readiness gate. Inside `while 1` gcsim *waits* for "
            f"an action that is not ready, so an ungated burst waits for energy it can no "
            f"longer generate. The compiler gates every step to make this unwritable."
        )
    return f"{line!r} — not a statement this model can express."
