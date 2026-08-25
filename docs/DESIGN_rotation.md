# DESIGN — Rotation authoring

**Status:** Planner output, 2026-08-24. Owner ruling recorded in `DECISIONS.md`:

> *"Rotations should be built by users, gcsim uses a convoluted rotation syntax, something
> more like fairy would be a big improvement."*

**Reads first:** `BRIEF_mistilteinn.md`, `DESIGN_client_optimizer.md` §3.5, and the Chunk I
entry in `TASKS_mistilteinn.md` — which records that gcsim already implements the *simulation*
this chunk was once going to build, so what remains is authoring.

---

## Branch policy

Work happens on **`feat/rotation`** and sub-branches off it, merged to `dev` by PR. **No direct
commits to `dev` or `main`.** Task R.0 in `TASKS_rotation.md` is the branch-setup gate.

Per-task branches off `dev` are also acceptable and are what the client-optimizer chunk
actually did — see A.0's disposition there for why an umbrella branch was the wrong shape for
independently-shippable work. The rule that matters is the PR, not the topology.

---

## 1. The problem is authoring, not simulating

gcsim runs the rotation. Chunk S established that and C.6 acted on it. What gcsim does *not*
do is give a user a way to express one without learning a scripting language.

**This is not a matter of taste, and I have the scars.** Building the ER sweep for D.2 — a
config of one character doing three things — cost two wrong answers, both of which produced
**plausible JSON with exactly one burst in it**:

1. **A bare action list runs once.** `duration=90` with a flat list gave 1 burst, 1 skill and
   3 attacks over ninety seconds. Nothing errored. The DPS figure was simply the wrong
   question answered correctly.
2. **`while 1 { … }` deadlocks on an ungated action.** gcsim *waits* for an action that is not
   ready, so a `burst` at the top of the loop waits for energy it can no longer generate,
   because generating it requires the actions after the burst. Still exactly one of
   everything.

A user comparing two artifacts should not have to know either of those. Both are mechanical
consequences of the action's *type*, which means **a compiler can handle them and a human
should not have to.**

## 2. The model: an ordered list, like fairy's

fairy's combo is `name + team + sequence`, where a sequence is a flat list of steps, each
naming who does what plus per-step parameters (`app/schemas/build.py:ComboStepInput` in that
repo). No control flow. That shape is what "more like fairy" means, and it ports directly.

A **rotation** is:

```
Rotation
  name          "Ayaka melt opener"
  team          [character, …]        the ordered party; index 0 starts on field
  steps         [Step, …]
```

A **step** is:

```
Step
  character     which party member acts       (a swap is implied — see §3.3)
  action        one of gcsim's 13             (§3.1)
  repeat        1..n, for `attack:3`          (§3.2)
  note          free text, the user's own label
```

That is the whole authoring surface. **No conditionals, no loops, no expressions**, because
every one of those is a thing the compiler can derive or the user does not need — and every
one is a way to write a rotation that deadlocks.

### What the model deliberately cannot express

- **"Burst if you have energy, else skill."** A branch. The compiler already gates every
  action on readiness (§3.4), so the common case is covered; a genuine either/or is a
  different rotation and should be authored as one.
- **"Repeat this section 3 times."** Nesting. Write the steps three times; the list is short
  and a UI can duplicate a selection. Nesting buys terseness and costs a grammar.
- **Timing, delays, `wait`.** gcsim has `wait` and `delay` actions, and they are how a human
  hand-tunes a config. Exposing them invites the user back into frame counting, which is the
  thing being removed. If a rotation needs them, that is a finding to bring back here, not a
  field to add pre-emptively.

**This is a v1 that refuses to be a language.** The moment it grows a conditional it has
become gcsim's syntax with different punctuation, and the owner's complaint applies to it too.

## 3. The compiler

`rotation → gcsim action list`. One direction only; gcsim's config is a build artifact, not a
format we read back.

### 3.1 The action vocabulary is gcsim's, cited

Read from `pkg/core/action/action.go` at the pin, not from memory:

```
skill  burst  attack  charge  high_plunge  low_plunge  aim  dash  jump  swap  walk  wait  delay
```

The model exposes a subset. `swap` is excluded because it is implicit (§3.3); `wait`/`delay`
because §2 excludes timing. The remaining ten are offered, and **the list lives in one place
derived from that file**, so a re-pin that adds an action is a diff rather than a silent gap.

### 3.2 `repeat` compiles to gcsim's `:n`

`attack ×3` becomes `attack:3`. This is gcsim's own repetition syntax and needs no
interpretation.

### 3.3 Swaps are gcsim's job, verified

`pkg/simulation/run.go:154` carries the comment *"the evaluator should handle adding in
implicit swaps if next char is not active"*, with a sanity check that errors if one was
missed. So naming a different character's action swaps to them.

**The compiler emits no swap actions.** It emits `active <first character>;` and then names
whoever acts. Emitting swaps ourselves would double them against gcsim's implicit ones.

### 3.4 The gates are the whole point

Every step compiles to a readiness-gated statement:

```
if .kamisatoayaka.burst.ready { kamisatoayaka burst; }
```

`.<char>.<action>.ready` is a first-class condition — `pkg/conditional/character.go:134`,
which calls `char.ActionReady(act, nil)` and therefore accounts for **cooldown and burst
energy together**. The user never types an energy threshold, never learns a burst cost, and
cannot write the deadlock.

Two consequences worth stating:

- **A gated rotation skips rather than stalls.** If the burst is not up this cycle, the
  rotation goes on to the skill. That is what a player does, and it is what the ungated form
  fails to do.
- **Gating everything is not free.** `attack` is essentially always ready, so its gate is
  noise in the emitted config. The compiler gates every action anyway, because "which actions
  can stall" is a judgement that would live in a table someone has to maintain against
  gcsim's behaviour, and a wrong entry there reintroduces the deadlock silently. A redundant
  gate costs a line of generated text nobody reads.

### 3.5 The loop

The step list is a **cycle**, so it compiles inside `while 1 { … }` and repeats for the
configured duration. That matches how a rotation is meant: a user writes one cycle, not
ninety seconds of actions.

`duration` stays an option on the run, not on the rotation.

## 4. Verification: the compiler is checked by gcsim, not by us

A compiler is a place two representations can disagree, and this repo's recurring failure is a
second implementation nobody exercises. So:

1. **Every emitted config is fed to real gcsim at the pin and must be accepted.** The harness
   exists — `npm run gcsim:verify-config` already does exactly this for the sample configs
   `scripts/gcsim/emit_sample_configs.py` writes.
2. **A compiled rotation must actually execute its steps.** Acceptance is not enough: the ER
   sweep's two failures both produced configs gcsim *accepted*. So the check reads
   `statistics.character_actions` back and asserts the rotation's actions appear at roughly
   the cycle count the duration implies. **A rotation that runs once in ninety seconds fails.**
3. **The deadlock is a regression test.** Compile a rotation whose first step is a burst,
   assert the emitted config contains the gate, and assert the run shows more than one cycle.
   That failure is not hypothetical; it is what §1 describes.

## 5. Where this sits relative to the client optimizer

`DESIGN_client_optimizer.md` §3.5 rests on team and rotation being **inputs**. This chunk
supplies the rotation half of that input and does not disturb the assumption.

**It stops short of optimizing the rotation**, and that boundary is load-bearing: §3.5 warns
that making the rotation an output multiplies the search by the space of action lists, against
a gcsim run costing ~4,700× one damage-chain combination under WASI. Authoring is not
optimizing, and this design does not open that door.

**Closed by owner decision, 2026-08-25: rotations are not optimized.** The door stays shut,
and not only for the cost reason — a user writes a rotation deliberately, and one arrived at
by search is not a rotation they would recognise as theirs. The design pass that was queued to
decide whether the cost was affordable is cancelled: the question is settled on other grounds,
so measuring it would answer something nobody is asking.

## 6. Deployment work folded in

Per the owner, the deploy remainder rides along here rather than as its own chunk. **K is
otherwise complete and live**; what is left is small:

- **`ALLOWED_ORIGINS` is not needed and should not be added.** Verified: the prod SPA builds
  with `apiBaseUrl: ''` and calls the API same-origin through nginx, so CORS never fires.
  fairy sets one; copying that would have been cargo-cult.
- **The rotation surface must reach prod like everything else** — the auto-deploy is proven
  end to end (a merge to `dev` deployed `46f5622` with both jobs green), so this is a matter
  of not breaking it rather than of building it.
- **CI's hosted-runner lanes remain billing-blocked.** The self-hosted deploy runner is not
  metered and works; `scripts/ci_local.py` covers the rest. This chunk is verified the same
  way the last several were, and says so in each PR.

## 7. Open questions

- **OQ-R1 — does a rotation belong to a team, or to a build?** fairy attached combos to a
  team. Here `sim_context.context_key` already hashes `team` and `rotation` together, so the
  pairing exists at the cache layer regardless. Decide in R.1, where the schema lands.
- **OQ-R2 — what happens to a rotation when a character leaves the team?** A saved rotation
  naming a character the team no longer has is a stale reference, and the choice is between
  refusing to save the team, dropping the steps, or keeping them inert and flagged. The last
  matches how this repo treats every other unresolvable reference. Decide in R.1.

---
**Planner output complete. Hand to Worker at `docs/TASKS_rotation.md` Task R.0.**
