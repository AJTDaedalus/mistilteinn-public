"""Compile a user-authored rotation into a gcsim action list.

`DESIGN_rotation.md` §3. One direction only: gcsim's config is a build artifact, not a format
this repo reads back.

## What the compiler is for

gcsim's syntax is not hard because it is unfamiliar. It is hard because two of its behaviours
are **silent**, and I met both while building D.2's ER sweep — a config of one character doing
three things:

1. **A bare action list runs once.** `duration=90` with a flat list produced one burst, one
   skill and three attacks over ninety seconds. Nothing errored; the DPS figure was simply an
   answer to a question nobody asked.
2. **`while 1 { … }` deadlocks on an ungated action.** gcsim *waits* for an action that is not
   ready, so a `burst` at the top of the loop waits for energy it can no longer generate —
   because generating it needs the actions that come after the burst. Still one of everything.

Both are mechanical consequences of the action's *type*. That is exactly what a compiler can
carry and a user should not have to, and it is the whole of the owner's ruling that gcsim's
syntax is the wrong authoring surface.

## What it emits, and why each part

    active kamisatoayaka;
    while 1 {
        if .kamisatoayaka.burst.ready { kamisatoayaka burst; }
        if .kamisatoayaka.attack.ready { kamisatoayaka attack:3; }
    }

- **`while 1`** because a rotation is a *cycle*. The user writes one pass, not ninety seconds
  of actions, and without the loop it runs once (failure 1).
- **A readiness gate on every step.** `.<char>.<action>.ready` is a first-class condition —
  `pkg/conditional/character.go:134` calls `char.ActionReady(act, nil)`, which accounts for
  **cooldown and burst energy together**. So the user never types an energy threshold, never
  learns a burst cost, and cannot write failure 2.
- **No swap actions.** `pkg/simulation/run.go:154`: *"the evaluator should handle adding in
  implicit swaps if next char is not active"*, with a sanity check that errors if one was
  missed. Emitting our own would double them.

**Every step is gated, including `attack`.** An attack is essentially always ready, so its gate
is noise in generated text nobody reads. Gating selectively would mean a table of "which
actions can stall", maintained by hand against gcsim's behaviour — and a wrong entry there
reintroduces the deadlock silently. A redundant `if` is the cheaper mistake.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services import gcsim_keys

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.models.character import Character


class RotationCompileError(RuntimeError):
    """The rotation cannot be compiled, and the message says which step is at fault."""


def compile_rotation(
    steps: Sequence[Mapping[str, object]],
    characters: Mapping[str, Character],
) -> str:
    """The gcsim action-list block for `steps`.

    `characters` maps a step's `character` (a nanoka id) to the catalogue row, which is what
    `gcsim_keys.character_key` needs. The caller supplies it because resolving a team's
    characters is a database question and this stays a pure function — testable without a
    session, and reusable by anything that already holds the rows.
    """
    if not steps:
        msg = (
            "a rotation with no steps compiles to nothing to do. gcsim would accept the "
            "config and simulate a character standing still, which is a plausible number "
            "for a question nobody asked."
        )
        raise RotationCompileError(msg)

    keys = _resolve(steps, characters)

    # `active` is the **first step's** character, not the team's first slot. Otherwise the
    # rotation opens with an implicit swap gcsim has to pay for, before the user's first
    # intended action — a cost they did not write and cannot see.
    lines = [f"active {keys[0]};", "while 1 {"]
    for key, step in zip(keys, steps, strict=True):
        lines.append(f"    {_statement(key, step)}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _resolve(
    steps: Sequence[Mapping[str, object]],
    characters: Mapping[str, Character],
) -> list[str]:
    """A gcsim key per step, or a refusal naming every step that cannot be placed.

    **Every** unresolvable step, not the first. A user who removed two characters from a team
    should learn that once, not be sent round the loop twice — and the same reasoning the GOOD
    importer uses when it reports each rejected artifact rather than stopping at one.
    """
    resolved: list[str] = []
    missing: list[str] = []
    for index, step in enumerate(steps):
        nanoka_id = str(step.get("character", ""))
        character = characters.get(nanoka_id)
        if character is None:
            missing.append(f"step {index + 1} ({step.get('action', '?')}, {nanoka_id})")
            continue
        resolved.append(
            gcsim_keys.character_key(
                character.nanoka_id, character.name, character.element,
            ),
        )
    if missing:
        msg = (
            f"this rotation names characters its team does not have: {'; '.join(missing)}. "
            f"The steps are kept as authored — remove them, or put the character back on the "
            f"team. Dropping them here would delete your work to make a compile succeed."
        )
        raise RotationCompileError(msg)
    return resolved


def _statement(key: str, step: Mapping[str, object]) -> str:
    """One gated action, with gcsim's own `:n` repetition."""
    action = str(step["action"])
    repeat = int(step.get("repeat", 1) or 1)
    call = f"{key} {action}:{repeat};" if repeat > 1 else f"{key} {action};"
    return f"if .{key}.{action}.ready {{ {call} }}"
