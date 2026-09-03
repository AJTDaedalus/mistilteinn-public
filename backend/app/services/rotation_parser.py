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
#: `noelle attack:3;` or `noelle skill[hold=1];` — the shape this app emits, and the shape
#: every community config is written in.
_BARE = re.compile(
    r"^([a-z0-9]+)\s+([a-z_]+)(?:\[([^\]]*)\])?(?::([^\s;]+))?\s*;$",
)

#: The same action wrapped in the readiness gate this app emitted until 2026-09-01. Still read,
#: because a config exported before then is still a config someone may re-import, and because
#: hand-written community configs do use gates where the author wanted a conditional cast.
#: The readiness condition this model *does* understand, for telling a branch it cannot
#: express from a condition it cannot read. See `_why_refused`.
_READY_CONDITION = re.compile(r"\.[a-z0-9]+\.[a-z_]+\.ready\b")
#: The conditions a block may carry, and nothing else. `DESIGN_conditional_steps.md` states
#: why the list is short: a grammar that accepts what it cannot faithfully re-emit is how a
#: rotation silently becomes a different one, so anything outside this is refused by name.
_BLOCK_CONDITION = re.compile(
    r"^if\s+("
    r"\.[a-z0-9]+\.[a-z_]+\.ready"
    r"|\.[a-z0-9]+\.energy\s*(?:>=|<=|>|<|==)\s*\d+"
    r"|\.[a-z0-9]+\.status\.[a-z0-9_-]+"
    r")\s*\{$",
)
_CLOSE_BLOCK = re.compile(r"^\}$")
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

    body = _action_lines(lines)

    steps: list[dict[str, Any]] = []
    problems: list[str] = []
    for line, group, group_repeat, condition in body:
        step, problem = _statement(line, by_key)
        if step is not None:
            # Carried on **every** member, because the schema requires the members of a group
            # to agree and refuses a repeat count on a step with no group.
            step["group"] = group
            step["group_repeat"] = group_repeat
            step["group_condition"] = condition
            steps.append(step)
        else:
            problems.append(problem)

    if problems:
        # **Each distinct problem once, with a count.** Unrolling a counted loop copies every
        # line in it, so one unreadable block inside `for i < 6` was reported six times — the
        # owner's re-import was a wall of the same sentence, and a refusal list that repeats
        # itself is one nobody finishes reading. The count is kept because "six times" says
        # something "once" does not: it is inside the loop, not beside it.
        counted: dict[str, int] = {}
        for problem in problems:
            counted[problem] = counted.get(problem, 0) + 1
        problems = [
            line if times == 1 else f"{line} (repeated {times} times, once per cycle)"
            for line, times in counted.items()
        ]
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
            "this config has no action steps in it. A rotation with no steps is nothing to "
            "do — gcsim would accept the config and simulate a character standing still."
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


#: Statements that configure the simulation rather than act in it.
#:
#: Load-bearing for the opener: everything *else* outside the loop is treated as an action and
#: reported if it cannot be read, so a line this set does not recognise is never dropped in
#: silence. Testing the opposite way — "does it parse as an action?" — would swallow exactly
#: the lines a user needs told about.
_CONFIG_PREFIXES = ("options", "target", "active", "energy", "fn ", "let ")


def _is_config(line: str) -> bool:
    if line.startswith(_CONFIG_PREFIXES):
        return True
    # `<character> char lvl=…` / `<character> add weapon=…` — two words, then the keyword.
    _, _, rest = line.partition(" ")
    return rest.startswith(("char ", "add "))


#: `for let a=0; a<5; a=a+1 {` — the bound is the only part this model keeps.
_FOR_BOUND = re.compile(r"^for\s.*?<\s*(\d+)\s*;.*\{$")


def _with_blocks(
    lines: list[str], base_group: str, base_repeat: int,
) -> list[tuple[str, str, int, str]]:
    """Walk a run of lines, turning `if … { … }` into the group path each step is inside.

    **A block, not a per-step flag.** gcsim evaluates a guard once on entry and an action
    inside can change what it tested — `internal/characters/flins/skill.go:56` deletes the very
    status its block is guarded on — so a rotation that flattened the nest would run
    differently while looking like the one that was written.

    Only the conditions in `_BLOCK_CONDITION` open a block. Anything else is left in place for
    `_statement` to refuse **by name**, which is what makes an unimportable config say why
    rather than arrive missing a guard nobody can see.
    """
    out: list[tuple[str, str, int, str]] = []
    stack: list[str] = []
    conditions: list[str] = []
    unnamed = 0

    for line in lines:
        opened = _BLOCK_CONDITION.match(line)
        if opened:
            unnamed += 1
            stack.append(f"guard{unnamed}")
            conditions.append(opened.group(1))
            continue
        if _CLOSE_BLOCK.match(line) and stack:
            stack.pop()
            conditions.pop()
            continue
        group = "/".join([*( [base_group] if base_group else [] ), *stack])
        out.append((line, group, base_repeat, conditions[-1] if conditions else ""))
    return out


def _action_lines(lines: list[str]) -> list[tuple[str, str, int, str]]:
    """Every action line, as `(line, group, group_repeat, condition)`, in gcsim's own order.

    ## Three shapes, because real configs have three

    **A bare list** is a rotation that runs once. This used to be refused — *"gcsim runs a bare
    action list once, over a 90-second duration that is one burst"* — and that refusal was
    correct only while this repo *emitted* `while 1`. Since 2026-09-01 the compiler emits the
    rotation as defined and lets it end when its actions do, so a bare list is the normal shape
    and refusing it would refuse this app's own output.

    **An opener followed by a loop** is what the gcsim database is full of: statements that run
    once, then a bounded cycle. Both halves are kept — the opener ungrouped, the cycle as a
    group. Refusing it cost a real import: gcsim db `kDHmWKmfgqtF` has 19 opener statements,
    and this model could not hold them.

    **A `for` loop** carries its own repeat count, and `group_repeat` is exactly the field for
    it — the refusal said *"this model has no field for it"*, which stopped being true when
    groups landed. `while 1` is still read, and still cannot be counted: it is unbounded, so
    its body is taken as one pass, which is what this parser has always returned for it.
    """
    opens = [i for i, line in enumerate(lines) if line.startswith(("while", "for ", "for("))]

    if len(opens) > 1:
        # **Say which it is.** Both community configs that reach this branch have one
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

    if not opens:
        # No loop: every non-config line is the rotation, once through, in order. Unreadable
        # ones are kept so `parse_action_block` can name them rather than drop them.
        return _with_blocks([line for line in lines if line and not _is_config(line)], "", 1)

    start = opens[0]
    header = lines[start]
    if header == "while 1 {":
        repeat = 1
    else:
        match = _FOR_BOUND.match(header)
        if match is None:
            msg = (
                f"the loop is {header!r}, which this model cannot count. A `while 1 {{` runs "
                f"until the simulation stops and a `for let i=0; i<N; i=i+1 {{` runs N times; "
                f"a conditional loop runs a number of times only the simulation knows, and "
                f"there is no repeat count to store for it."
            )
            raise RotationParseError(msg)
        repeat = int(match.group(1))
        if repeat < 1:
            msg = (
                f"the loop runs {repeat} times, so its body never executes. A rotation whose "
                f"cycle never runs is not a rotation this app can hold."
            )
            raise RotationParseError(msg)

    closes = [i for i, line in enumerate(lines) if line == "}"]
    if not closes:
        msg = f"the {header!r} loop is never closed."
        raise RotationParseError(msg)

    # Anything after the closing brace is outside the rotation and is not silently ignored:
    # gcsim would run it, so a config carrying it does not mean what the imported steps say.
    tail = [line for line in lines[closes[-1] + 1 :] if line and not _is_config(line)]
    if tail:
        msg = (
            f"{len(tail)} statement(s) follow the loop and would run after it: "
            f"{'; '.join(repr(t) for t in tail)}. This model holds an opener and one cycle, "
            f"and has nowhere to put a third section."
        )
        raise RotationParseError(msg)

    # **The opener is kept, not dropped and not refused.** A *config* statement is not an
    # opener: `skirk char lvl=90`, `add weapon=`, `options`, `target`, `energy` and `active`
    # all legitimately precede the loop and carry no actions. The test is whether the line
    # reads as an action, asked with the same parser that reads the body — so the two can
    # never disagree about what an action is.
    opener = _with_blocks(
        [line for line in lines[:start] if line and not _is_config(line)], "", 1,
    )
    body = _with_blocks(
        [line for line in lines[start + 1 : closes[-1]] if line], "loop", repeat,
    )
    return opener + body


def _statement(line: str, by_key: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
    """One action, gated or bare, or the reason this line could not be read as one.

    **Bare is the normal form now.** The gate was refused as recently as 2026-08-31, on the
    argument that an ungated action inside `while 1` deadlocks — true, and it stopped being
    this app's problem when the compiler stopped emitting `while 1`. Refusing bare actions
    would now refuse this app's own output, and would go on refusing every config in the gcsim
    database, none of which gates.
    """
    match = _GATED.match(line)
    if match is None:
        bare = _BARE.match(line)
        if bare is None:
            return None, _why_not(line)
        key, action, param_text, repeat_text = bare.groups()
        gate_key, gate_action = key, action
    else:
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
        # **A `.ready` gate is refused for a different reason, and said so wrongly.** The
        # message below claims the condition guards on something this model does not
        # understand, which is a false statement about `if .sucrose.burst.ready {` — that is
        # exactly the form named as the only one allowed. What makes it unimportable is the
        # branch it opens, not the condition it tests, and a refusal that misidentifies its own
        # reason sends the reader to fix something that is not wrong. Reported from a real
        # community config, 2026-09-02.
        if _READY_CONDITION.search(line):
            return (
                f"{line!r} — the condition is a readiness gate this model understands, but it "
                f"opens a **branch**. A rotation here is a list of steps with no alternatives "
                f"in it, so there is nowhere for the `else` to go; keeping only one side would "
                f"be a rotation the author did not write."
            )
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
