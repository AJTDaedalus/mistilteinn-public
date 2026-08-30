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

from hashlib import sha256
from typing import TYPE_CHECKING

from app.services import gcsim_keys

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.models.character import Character


#: How many steps a rotation may hold **after** its groups are expanded.
#:
#: `MAX_STEPS` (200) and `MAX_REPEAT` (20) are checked on the *authored* list, and `unroll`
#: runs afterwards — so 200 steps each in a group repeating 20 times is 4,000 gated statements,
#: each of which may itself carry `:20`. `MAX_REPEAT` exists "so a typo cannot compile to a
#: config that runs for an hour", and groups walked straight around it.
#:
#: Ten times the authored cap: generous enough that no rotation anyone writes meets it, and
#: bounded enough that a mistake is refused with a sentence rather than compiled.
MAX_UNROLLED_STEPS = 2000


class RotationCompileError(RuntimeError):
    """The rotation cannot be compiled, and the message says which step is at fault."""


def unroll(steps: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Expand every group into its repeated steps — the flat list everything downstream sees.

    `DECISIONS.md` §27. `DESIGN_rotation.md` §2 refused nesting because *"nesting buys
    terseness and costs a grammar"*, and the owner amended it once the cost turned out not to
    be paid: a group carries a repeat count and **nothing else**, and it is gone before the
    compiler runs. gcsim receives character-for-character what it received before groups
    existed.

    **This runs in front of both `compile_rotation` and `rotation_signature`.** Those two
    already share `_resolve` so that a signature and a config cannot disagree about who a step
    names; putting the unroll ahead of both extends the same guarantee to *how many* steps
    there are. The consequence is deliberate: a grouped rotation and its unrolled equal produce
    the same `context_key` and share one cached run, which is correct because the key describes
    what gcsim ran.

    A step with no group passes through untouched, so a rotation authored before groups existed
    unrolls to itself.
    """
    flat: list[Mapping[str, object]] = []
    index = 0
    while index < len(steps):
        group = steps[index].get("group")
        if not group:
            flat.append(steps[index])
            index += 1
            continue
        end = index
        while end < len(steps) and steps[end].get("group") == group:
            end += 1
        chunk = list(steps[index:end])
        # Read off the first member. The schema requires every member to agree, so this cannot
        # silently pick one of two answers — see `_groups_are_contiguous_and_agree`.
        repeat = int(chunk[0].get("group_repeat", 1) or 1)
        flat.extend(chunk * repeat)
        index = end
    return flat


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

    steps = unroll(steps)
    if len(steps) > MAX_UNROLLED_STEPS:
        msg = (
            f"this rotation unrolls to {len(steps)} steps, past the {MAX_UNROLLED_STEPS} a "
            f"config may hold. A group multiplies its chunk, so a long rotation of long groups "
            f"leaves the bound the authored list is checked against. Shorten it, or repeat a "
            f"group fewer times."
        )
        raise RotationCompileError(msg)
    keys = _resolve(steps, characters)

    # **No swap actions are emitted, and none are needed.** gcsim's parser desugars
    # `xiangling burst;` into `execute_action(...)`, which inserts an implicit swap when the
    # named character is not active (`pkg/gcs/eval/sysfunc.go:472`).
    #
    # That implicit swap is silently defeated by `swap_delay=0`, which `gcsim_config` used to
    # emit unconditionally — gcsim queues the swap to land `Delays.Swap` frames later, so at
    # zero it never lands and the run dies with *"requested next char X is not active and next
    # action is not swap"*. **Every multi-character rotation this repo produced was
    # unrunnable**, natively and in the browser alike, and solo rotations never swap so nothing
    # caught it. See `docs/RESEARCH_recipe_cost.md` §2.

    # `active` is the **first step's** character, not the team's first slot. Otherwise the
    # rotation opens with an implicit swap gcsim has to pay for, before the user's first
    # intended action — a cost they did not write and cannot see.
    lines = [f"active {keys[0]};", "while 1 {"]
    for key, step in zip(keys, steps, strict=True):
        lines.append(f"    {_statement(key, step)}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def rotation_signature(
    steps: Sequence[Mapping[str, object]],
    characters: Mapping[str, Character],
) -> list[str]:
    """The rotation as `sim_context.context_key` sees it — one string per step, in order.

    R.6. A cached gcsim run is reusable only if it simulated the same rotation, so the key
    has to change when the rotation does. It does, because this is derived from the same
    steps and the same `_resolve` the compiler uses: **a signature and a config cannot
    disagree about who a step names.** Two functions reading the steps separately would
    eventually differ, and the failure would be a confident cached number computed for a
    different rotation — the exact thing `context_key` exists to prevent.

    Order is preserved, because `context_key` hashes `rotation` as a sequence and reordering
    a rotation makes it a different rotation. `repeat` is in the string for the same reason:
    `attack:3` is not `attack`.
    """
    steps = unroll(steps)
    keys = _resolve(steps, characters)
    return [
        f"{key} {step['action']}:{int(step.get('repeat', 1) or 1)}"
        for key, step in zip(keys, steps, strict=True)
    ]


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
    """One gated action, with gcsim's own `:n` repetition and `[param=1]` variant.

    **The variant becomes a parameter here and nowhere else.** The model holds `skill_hold` as
    an action, because a hold-E is a different move to a tap-E and the owner's ruling is that
    this model stays parameterless (`DESIGN_rotation_builder_gui.md` §3). gcsim spells the same
    thing `skill[hold=1]` — the form a real community config uses,
    `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt:48`.

    **The gate names the base action, not the variant.** `.chev.skill.ready` is the condition
    gcsim carries; there is no `.skill_hold.ready`, because a hold and a tap share one cooldown.
    Gating on the variant would emit a condition gcsim's parser does not know.
    """
    action, param = gcsim_keys.split_variant(str(step["action"]))
    repeat = int(step.get("repeat", 1) or 1)
    call = action if param is None else f"{action}[{param}=1]"
    suffix = f":{repeat}" if repeat > 1 else ""
    return f"if .{key}.{action}.ready {{ {key} {call}{suffix}; }}"


def signature_digest(signature: Sequence[str]) -> str:
    """`rotation_signature`'s output, as the 64 characters `sim_runs` stores.

    **One definition, because two would be a silent mismatch.** The library computes this
    digest to ask "does the caller have a run for this rotation *as it stands*", and a
    submitter computes it to label the run. If those two ever hashed differently, every answer
    would be `None` — a library that quietly never sorts, with nothing to see in a log.
    """
    return sha256("\n".join(signature).encode()).hexdigest()
