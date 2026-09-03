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

## The shape this emitted until 2026-09-01, and why it was wrong

    options iteration=100 duration=90;
    active kamisatoayaka;
    while 1 {
        if .kamisatoayaka.burst.ready { kamisatoayaka burst; }
        if .kamisatoayaka.attack.ready { kamisatoayaka attack:3; }
    }

Three decisions in there, each defensible alone and jointly producing a simulation that
**could not measure Energy Recharge at all**:

- **`while 1`** repeated the user's cycle forever, so the rotation's own length stopped
  mattering and `duration` decided what was measured.
- **`duration=90`**, a constant nobody chose, truncated every rotation at ninety seconds.
- **A readiness gate on every step**, which turns *waiting* into *skipping*. gcsim only records
  `insufficient_energy` for an action it **attempted and failed**; a gated burst is never
  attempted, so the field read **0 for a team plainly starved** and the only visible symptom
  was a burst count nobody was looking at.

Owner, 2026-09-01: *"The optimizer should run through the rotation as defined to completion,
regardless of how short/long it is, and score ER appropriately."*

### The correction that followed, the same day

Dropping all three at once was too much. `duration` and `while 1` were right to go; **removing
every gate was not**, and the verification run that was meant to bless it died instead:

    runtime: out of memory: cannot allocate 155189248-byte block (2369191936 in use)
    fatal error: out of memory
        pkg/stats/status/status.go:56  avgUpdate
        pkg/simulation/run.go:187      actionReadyCheckPhase

**gcsim has no watchdog.** `actionReadyCheckPhase` answers `ErrActionNotReady` with
`advanceFrames(1, actionReadyCheckPhase)` — retry, forever, with nothing counting the retries.
`stopCheck()` ends a run on `noMoreActions`, on all targets dead, or on an exact
`F == Duration*60`; and `target hp=` turns damage mode **on implicitly**
(`pkg/gcs/parser/parseTarget.go:63`), where duration is never consulted at all. An unkillable
target, no duration and no gate therefore remove *every* termination condition together, and
the run grows a per-frame stats slice until the kernel takes it.

Bisecting the emitted 116 actions put it on action 92, `escoffier burst` — the fourth cycle,
where her `er=0.583` runs out. The identical config with her at `er=3.0` finishes in **0.03 s
using 32 MB**. That ratio is the diagnostic worth keeping: a healthy run of this size is
free, so a gcsim run consuming real memory is a hang, not a big simulation.

**This is the failure mode the optimizer exists to find**, which is what made it unshippable
rather than merely unlucky: the hang happens precisely when a character cannot fund a burst.

### What the measurements said

Same team, same rotation, native gcsim. Furina's artifact ER against team DPS, and how long she
spent unable to act:

| passes | DPS @ er=0.3 | DPS @ er=0.9 | ER is worth | Furina waited @ 0.3 |
|---|---|---|---|---|
| 1 | 274,719 | 274,662 | **0.0 %** | 0 s |
| 2 | 198,313 | 246,811 | **+24.5 %** | 15.9 s |
| 3 | 167,314 | 238,297 | **+42.4 %** | 37.2 s |
| 5 | 136,270 | 232,332 | **+70.5 %** | 87.7 s |

**One pass cannot see ER, and that is gcsim, not a bug here: every character starts at full
energy.** Measured directly — a single pass at er=0, er=0.3 and er=2.0 returns the same
duration, the same DPS and the same burst counts. The first cycle is always free, so a rotation
has to run past it before energy is a cost. There is no `start_energy` option to turn that off;
`pkg/gcs/parser/parseOptions.go` has no such case.

Against that, the gated 90-second window reported ER as worth **+2.6 %**. The optimizer was
never weighing ER wrongly. It was weighing it against a simulation in which nobody ever pays
for a second burst.

**Read that table as the *ungated* model, because it is one — the `waited` column only has
meaning where gcsim blocks.** It is not what this file now emits, and the difference is not
small. Measured on the owner's own 87-step rotation and gear (243 actions, five bursts each,
50 iterations), with bursts gated:

| artifact ER | 0.279 | 0.6 | 1.0 | 1.3 | 1.6 | 2.0 |
|---|---|---|---|---|---|---|
| team DPS | 267,508 | 267,211 | 266,676 | 267,329 | 287,085 | 307,850 |
| ER is worth | — | -0.1 % | -0.3 % | -0.1 % | **+7.3 %** | **+15.1 %** |

Duration is 101.1 s at every rung, set by the rotation. Base ER is 1.0
(`pkg/core/player/character/basestat.go:82`), so the step is at ~260 % total and she is at
128 %.

**The two models disagree about what ER is worth, and the disagreement is the open question.**
Waiting spreads one character's shortfall across the whole team, so it prices ER high;
skipping costs only the burst and its cast time, so it prices ER low. Waiting is arguably the
better model of a player and it is the one that cannot be run — see the correction above. So
what ships is the cheaper answer, and **the gated emitter will systematically under-value ER
against a rotation whose author would have waited.** Recorded here rather than settled,
because which of the two a build should be scored against is the owner's ruling, not this
file's.

## What it emits now

    active kamisatoayaka;
    kamisatoayaka burst;
    kamisatoayaka attack:3;

- **No loop wrapper of any kind.** `unroll` has already expanded whatever repeats the rotation
  *defines*, so the emitted list **is** the whole rotation. "A bare action list runs once" is
  no longer failure 1 — once is exactly the ask, and the length is the user's rather than ours.
- **No gates**, so gcsim waits for an action rather than skipping it. That is what a player
  does, and it is what makes `insufficient_energy` report real seconds — the number the owner
  asked for and that this could not previously produce. Failure 2 does not return with them:
  the deadlock was a property of `while 1`, and a finite list cannot deadlock, only take longer.
- **`gcsim_config` sets `target hp=` and emits no `duration`**, so the run ends when the
  actions do. In HP mode gcsim ignores `duration` entirely — measured: the same rotation
  reports 189.3 s whether the config says `duration=90`, `duration=3600` or nothing at all.
- **No swap actions.** `pkg/simulation/run.go:154`: *"the evaluator should handle adding in
  implicit swaps if next char is not active"*, with a sanity check that errors if one was
  missed. Emitting our own would double them.
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
    *,
    wait_for_energy: bool = False,
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
    lines = [f"active {keys[0]};", *_blocked(keys, steps, wait_for_energy)]
    return "\n".join(lines) + "\n"


def _blocked(
    keys: Sequence[str],
    steps: Sequence[Mapping[str, object]],
    wait_for_energy: bool = False,
) -> list[str]:
    """The statements, wrapped in the `if` blocks their groups are guarded by.

    **A block, not a condition per statement.** gcsim evaluates a guard once on entry, and an
    action inside can change what it tested — `internal/characters/flins/skill.go:56` deletes
    the very status its block is guarded on. Emitting `if A { x; }` then `if A && B { y; }`
    would re-test `A` after `x` cleared it, so the rotation would run differently while looking
    like the one that was written. `DESIGN_conditional_steps.md` argues it at length.

    Nesting comes from `group` being a path: `"flame/energy"` is a block inside a block. Blocks
    are compared as a prefix, so consecutive steps in the same one stay in it and a change
    closes exactly what it must.
    """
    lines: list[str] = []
    open_blocks: list[tuple[str, str]] = []
    conditions = _conditions_by_path(steps)

    for key, step in zip(keys, steps, strict=True):
        wanted = _guards(step, conditions)
        shared = 0
        while (
            shared < len(open_blocks)
            and shared < len(wanted)
            and open_blocks[shared] == wanted[shared]
        ):
            shared += 1
        while len(open_blocks) > shared:
            open_blocks.pop()
            lines.append("    " * len(open_blocks) + "}")
        for block in wanted[shared:]:
            lines.append("    " * len(open_blocks) + f"if {block[1]} {{")
            open_blocks.append(block)
        lines.append(
            "    " * len(open_blocks) + _statement(key, step, wait_for_energy),
        )

    while open_blocks:
        open_blocks.pop()
        lines.append("    " * len(open_blocks) + "}")
    return lines


def _conditions_by_path(steps: Sequence[Mapping[str, object]]) -> dict[str, str]:
    """Which condition guards each block, gathered across every step in it.

    **A step carries only its innermost condition**, because that is the block it sits directly
    in — an outer block's condition arrives on the steps directly inside *it*. So the chain has
    to be assembled from the whole rotation rather than read off one step.

    Reading it off one step was the first draft, and it produced two *siblings* where the
    author wrote a nest: the outer block closed before the inner opened. That is the flattening
    `DESIGN_conditional_steps.md` refuses, arrived at by accident rather than by choice, and it
    is why this function exists.
    """
    found: dict[str, str] = {}
    for step in steps:
        path = str(step.get("group") or "")
        condition = str(step.get("group_condition") or "")
        if path and condition:
            found.setdefault(path, condition)
    return found


def _guards(
    step: Mapping[str, object], conditions: Mapping[str, str],
) -> list[tuple[str, str]]:
    """`(path, condition)` for every guarded block this step is inside, outermost first.

    A segment no step guards is a plain group — `group_repeat`'s concern, already expanded by
    `unroll` before this runs — and opens no block.
    """
    path = str(step.get("group") or "")
    if not path:
        return []
    chain: list[tuple[str, str]] = []
    prefix = ""
    for segment in [part for part in path.split("/") if part]:
        prefix = f"{prefix}/{segment}" if prefix else segment
        condition = conditions.get(prefix)
        if condition:
            chain.append((prefix, condition))
    return chain


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


#: The one action whose readiness the rotation cannot make true on its own. See
#: `_statement` for why exactly one action needs this.
_ENERGY_GATED_ACTION = "burst"


def _statement(
    key: str, step: Mapping[str, object], wait_for_energy: bool = False,
) -> str:
    """One action, with gcsim's own `:n` repetition and `[param=1]` variant.

    **The variant becomes a parameter here and nowhere else.** The model holds `skill_hold` as
    an action, because a hold-E is a different move to a tap-E and the owner's ruling is that
    this model stays parameterless (`DESIGN_rotation_builder_gui.md` §3). gcsim spells the same
    thing `skill[hold=1]` — the form a real community config uses,
    `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt:48`.

    **Gated on bursts and nothing else, since 2026-09-01.** The rule is about what a wait is
    *waiting for*:

    - A **cooldown** always expires. Waiting on it is free of risk and models what a player
      does, so every non-burst action is emitted bare and gcsim waits.
    - **Energy** may never arrive. A burst nobody can pay for blocks the whole simulation, so
      no later action runs, so no particles drop, so the energy never comes. gcsim has no
      watchdog for this — see the module docstring — and the run does not fail, it grows
      until the process is killed.

    Gating everything was the older mistake and turned every cooldown wait into a silent skip;
    gating nothing was the newer one and hung. The burst is the only action whose readiness
    condition the rotation itself cannot satisfy, so it is the only one that gets a gate.
    """
    action, param = gcsim_keys.split_variant(str(step["action"]))
    repeat = int(step.get("repeat", 1) or 1)
    call = action if param is None else f"{action}[{param}=1]"
    suffix = f":{repeat}" if repeat > 1 else ""
    statement = f"{key} {call}{suffix};"
    # **The gate is the whole difference between the two models.** Gated, gcsim skips a burst
    # nobody can pay for; ungated it *waits*, holding the entire simulation until the energy
    # arrives — which is what a person at a keyboard does, and what prices Energy Recharge some
    # 70 % higher on the owner's own team.
    #
    # Ungated only terminates because the waiting model also emits `ENERGY_DRIP`; without it
    # gcsim retries the frame forever and the run grows to 2.4 GB.
    # `DESIGN_waiting_for_energy.md` carries the argument and the drip's citations.
    if wait_for_energy or action != _ENERGY_GATED_ACTION:
        return statement
    # The gate names the base action, not the variant: a hold and a tap share one cooldown,
    # and `.burst_hold.ready` is a condition gcsim's parser does not know.
    return f"if .{key}.{action}.ready {{ {statement} }}"


def signature_digest(signature: Sequence[str]) -> str:
    """`rotation_signature`'s output, as the 64 characters `sim_runs` stores.

    **One definition, because two would be a silent mismatch.** The library computes this
    digest to ask "does the caller have a run for this rotation *as it stands*", and a
    submitter computes it to label the run. If those two ever hashed differently, every answer
    would be `None` — a library that quietly never sorts, with nothing to see in a log.
    """
    return sha256("\n".join(signature).encode()).hexdigest()
