# DESIGN — the rotation builder as a timeline

**Status:** Planner draft, 2026-08-30. Supersedes nothing; extends
`docs/DESIGN_rotation_builder.md`, whose five surface items shipped in #181 and #184.

**Reads first:** `docs/RESEARCH_rotation_builder_gui.md` (the measurements every decision here
rests on), then `docs/DESIGN_rotation.md` §2 and §3.

**Branch policy.** Work happens on **`feat/rotation-builder-gui`**, never on `dev` or `main`;
`dev` is updated only by PR after review. Task T.0 of the TASKS file is the branch-setup gate.
Sub-branches off it are acceptable for independently-shippable pieces, as the client-optimizer
chunk did — the rule that matters is the PR, not the topology.

## Owner rulings folded in (2026-08-30)

| | |
|---|---|
| **Variants** | Per-character action vocabulary. A hold-E is its own action with its own name, not a parameter. |
| **Reach** | Kit variants only. `collision` / `travel` / `weakspot` keep gcsim's defaults. |
| **Variant buttons** | One button carrying a `t`/`h` badge, clicked to flip. |
| **Hierarchy** | **timeline → rotation list → click for detail of moves.** Three levels, not two. |
| **The other seven actions** | Words, no drawn glyphs. |
| **Selection & reuse** | Drag-select a chunk, Ctrl+C / Ctrl+V. |
| **Loops** | **In.** A group repeats a chunk; the compiler unrolls it. `DESIGN_rotation.md` §2 amended first — `DECISIONS.md` §27. |
| **Running a sample** | A button the author presses. Never automatic. |
| **A stale run** | The measured timeline drops to the authored one the instant `steps()` changes. |

---

## 1. The finding that reshapes this: a *real* timeline costs one second

`RESEARCH_rotation_builder_gui.md` §4.1 refused a time axis, on the grounds that it is frame
counting and that the `.ready` gates make a step's length unknowable. **The first half of that
was right about the wrong thing and the second half is exactly backwards.**

The committed wasm build already exports `sample(cfg, seed)` — `cmd/wasm/main.go:45`, in the
same binary the optimizer loads. It returns one fully-logged run. Driven against the real
four-character config in `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt`:

```
sample() ms: 2277 | team: ["clorinde","chevreuse","nicole","durin"]
action events: 163       explicit swap actions: 15
derived on-field intervals: 16
  f   1- 117  nicole     (2 actions)
  f 160- 245  chevreuse  (4 actions)
  f 280- 345  durin      (4 actions)
  f 459- 924  clorinde   (28 actions)
  f1068-1184  nicole     (3 actions)
  ...
```

That is a frame-accurate, colour-codable record of **who was on field when**, for a real team,
in 2.3 s. `RESEARCH_calibration_cost.md` already measured `sample()` at 808–939 ms on smaller
configs and — separately, over CDP — found **no browser penalty** (842 ms browser against
839 ms Node). So this is affordable where the user is, not only on this box.

**Two corrections it forces on the research doc:**

1. **A time axis is not necessarily frame counting.** Frame counting is the *user* reasoning in
   frames to hand-tune a config, which is what `DESIGN_rotation.md` §2 removed. Being *shown*
   what the simulator did is the opposite: it is the machine doing the counting and reporting.
2. **The gates are the reason to show it, not the reason not to.** A step that is skipped
   because its gate was closed is invisible in the step list and *visible* on a simulated
   timeline. That is precisely the failure `DESIGN_rotation.md` §1 describes — a config that
   runs once in ninety seconds and reports a plausible number.

**Caveat, stated because it will otherwise be discovered later:** `sample()` does **not** return
`stats.Result`. It returns `{config, initial_character, character_details, target_details, seed,
logs}` — 3,124 entries for a 90-second solo rotation, of which 157 carry `event: "action"` with
`frame`, `char_index` and `logs.action`. There is no `active_characters` array to read; the
intervals above are **derived** from `char_index` transitions. That derivation is ours to own
and to test.

### 1.1 It also answers OQ-B3, and shrinks it

`DESIGN_rotation_builder.md` §5 left open whether an author should get a "does this rotation
work?" button, on the grounds that it costs a gcsim run while the user waits. **That estimate
was for an aggregate.** A sample is one iteration, and 2.3 s is a spinner, not a job. The
question is no longer whether to afford it — it is whether the timeline *is* the answer, which
it is: three Clorinde cycles in the trace above is the burst-count-and-stability check, drawn.

---

## 2. The three levels

The owner's hierarchy, with what each level owns:

```
┌─ 1. TIMELINE ───────────────────────────────────────────────────────┐
│  who is on field, across the cycle.  Two states:                    │
│  · authored  — ordinal, instant, derived from steps()               │
│  · simulated — frames, ~2 s, derived from one sample() run          │
│  Selection lives here.  Drag-select a range.  Ctrl+C / Ctrl+V.      │
├─ 2. ROTATION LIST ──────────────────────────────────────────────────┤
│  the steps, in order, one row each.  Reorder, duplicate, delete.    │
│  Scrolls with, and highlights from, the timeline's selection.       │
├─ 3. MOVE DETAIL ────────────────────────────────────────────────────┤
│  one step: action (incl. variant), repeat, note — and, once a       │
│  sample has run, what this step actually did.                       │
└─────────────────────────────────────────────────────────────────────┘
```

**One selection signal, three renderers.** The recurring failure in this repo is two
representations that can disagree (`DESIGN_rotation.md` §4 says so about the compiler, and
#184 found every `<select>` showing option zero). So: `steps()` and `selection()` are the only
state; the timeline, the list and the detail pane are all pure functions of them.

### 2.1 The authored timeline and the simulated timeline are the same component

They differ in one input: tile **width**. Authored, every tile is equal width and the x-axis is
ordinal. Simulated, tile width and position come from the frame intervals, and steps that never
fired render as gaps.

Keeping them one component with a `scale` input rather than two components is the whole point:
a user pressing "run" should watch their rotation *become* the real one, and the two views being
literally the same tiles is what makes the difference legible. It is also what stops the
simulated view drifting into a second, prettier, wrong renderer.

### 2.2 What the simulated timeline may not do

- **It may not become the editor.** Editing a frame position is hand-tuning, which is the thing
  removed. Selection carries across; nothing else does.
- **It may not be shown stale.** The moment `steps()` changes, the simulated overlay is of a
  different rotation and must be dropped, exactly as `previewError` refuses to leave a stale
  config beside an edit that broke it (#184).
- **It may not imply precision it does not have.** One sample is one seed. gcsim rolls crit and
  gcsim's own `sample` viewer is a debugging tool, not a statistic. The label says *one run*.

---

## 3. Per-character action vocabulary

### 3.1 The shape

`RosterCharacter.abilities` today is `{action: display name}`. It becomes a list of **offerable
actions** per character:

```
RosterCharacter.actions: [
  { key: "skill",       name: "All Schemes to Know",  variant: null  },
  { key: "skill_hold",  name: "All Schemes to Know",  variant: "hold" },
  { key: "burst",       name: "Illusory Heart",       variant: null  },
  ...
]
```

- The **step still stores one string**. `character · action · repeat · note` is unchanged, which
  is the owner's parameterless requirement met exactly.
- `variant` drives the `t`/`h` badge and nothing else. It is presentation.
- The **compiler** owns `skill_hold → skill[hold=1]`. That table is the only place the
  parameter exists, and it is derived from gcsim's source the way `authorable_actions()` already
  derives the ten.

### 3.2 Where the per-character list comes from

50 of gcsim's 106 characters read a kit-variant param — 33 a hold **skill**, 19 a hold **aimed
shot**, plus `short_hold` (4), `recast`, `hold_ticks`, `short`, `final`, `buffered`
(`RESEARCH_rotation_builder_gui.md` §2). The other 56 keep exactly the ten actions they have now.

This must be **generated from gcsim's source at the pin**, alongside the existing key snapshot,
never hand-kept. A hand-written table would drift in the direction that matters most — offering
a hold to a character gcsim will ignore it for, which is a silently wrong rotation rather than a
refused one. `gcsim_keys` already carries this discipline and its docstrings already explain it.

**The property to preserve, stated as a test:** *the picker offers exactly what the validator
accepts* (`RotationOptions`' own docstring). Per-character offers make that easier to break and
so it gets its own test, per character, not one global assertion.

### 3.3 The badge is not the only channel

`ElementChip`'s rule — colour, and by extension a corner glyph, is never the only channel — is
load-bearing here, because a tap-E and a hold-E are *different moves* distinguished by one
character. So: the badge on the button, and the word **Hold** in the move detail pane and in
the step row. Three levels means there is somewhere for the word to live without crowding the
button, which is the reason the owner's compact choice works.

---

## 4. Range selection, copy and paste

`DESIGN_rotation.md` §2 refused nesting with a promise: *"Write the steps three times; the list
is short and **a UI can duplicate a selection**."* Nothing has ever kept that promise. This
does, and it is therefore not a new capability — it is the one §2 already committed to.

- **Select** — click a tile; shift-click extends; drag across the timeline selects a range.
  Keyboard: arrows move, shift-arrows extend. `selection()` is a start/end index pair.
- **Copy** — Ctrl+C serialises the selected steps.
- **Paste** — Ctrl+V splices them in at the selection point.

**Two clipboards, and the distinction matters.** An internal signal is enough to paste within
one rotation. Writing the same payload to `navigator.clipboard` as JSON is what makes it paste
into *another* rotation, which is the case the owner will actually hit. Reading it back must
validate against the target team — a copied step naming a character the destination team does
not have is the stale reference `DESIGN_rotation.md` OQ-R2 already ruled on: keep it, flag it,
never silently drop it.

**Buttons too, not only chords.** Ctrl+C/Ctrl+V are invisible and unavailable on a phone. The
same three actions get visible controls, for the reason the reorder arrows stayed in #184.

---

## 5. Loops

**In, and `DESIGN_rotation.md` §2 was amended before anything was built on it** (owner,
2026-08-30; `DECISIONS.md` §27). §2 refused nesting because *"nesting buys terseness and costs
a grammar"*, and the cost turns out not to be paid: a group carries a repeat count, the
compiler emits its steps `n` times into the flat `while 1 { … }` body it already emits, and
gcsim receives character-for-character what it receives today.

The owner's own framing of why both exist: **a group says *this chunk repeats*; copy/paste says
*this fragment is reusable somewhere else*.** They are not two ways to say one thing, which is
what the "build copy/paste first and see" recommendation had assumed.

### 5.1 The shape

- A step gains `group_id`; a group carries `repeat`. Nothing else. **No condition, and no group
  inside a group** — both are part of the ruling, not implementation detail.
- **Unrolling happens in front of both `rotation_signature` and `compile_rotation`.** Those two
  already share `_resolve` so that *a signature and a config cannot disagree about who a step
  names*; a single `unroll(steps)` ahead of both extends that guarantee rather than adding a
  second place the two can differ.

### 5.2 The cache-key question, settled

A grouped rotation and its unrolled equal **hash the same** and share one cached run. That is
not a convenience: `context_key` describes *what gcsim ran*, and the two compile to identical
configs. Two keys for one config would mean a rotation missing a cache entry computed from
itself.

### 5.3 What the timeline does with a group

The authored timeline draws the group once with a `×n` bracket — that is the terseness being
bought. The **measured** timeline has no groups at all: `sample()` reports what happened, and
what happened is `n` passes. So a group is an authoring construct that disappears the moment
the rotation becomes real, which is the honest rendering and needs no extra decision.

## 6. Task outline

Ordered so each lands independently and nothing is blocked on an unanswered question.

| | task | gate |
|---|---|---|
| **T.0** | Branch setup | — |
| **T.1** | Vendor the 256 skill/burst sprites (`download_icons.py`) | `--check` clean; the committed-art test still asks git |
| **T.2** | Publish `talents.icon` on `/rotations/options`; contract regen | contract test |
| **T.3** | Generate the per-character action vocabulary from gcsim at the pin; compiler renders variants | per-character picker/validator agreement; a compiled `skill_hold` accepted by real gcsim |
| **T.4** | The authored timeline, as a component over `steps()` + `selection()` | tiles match steps 1:1; swaps drawn at run boundaries |
| **T.5** | The rotation list and the move-detail pane, rendered from the same two signals | selection round-trips across all three |
| **T.6** | Drag an ability button onto the timeline to insert at a position, **plus** a keyboard insert | both paths produce identical steps |
| **T.7** | Range select, copy, paste — chords and buttons, internal and system clipboard | a cross-rotation paste against a mismatched team flags rather than drops |
| **T.7b** | Groups: `group_id` + `repeat`, `unroll()` in front of signature and compiler, the ×n bracket | a grouped rotation and its unrolled equal produce the **same** `context_key` and the **same** config |
| **T.8** | `sample()` in a worker; the simulated overlay on the same component | the derived intervals reproduce the trace in §1 for the committed config |
| **T.9** | Look at it in a browser | §7 |

T.1–T.2 are pure gain and unblocked. T.3 is the owner's ruling made real. T.4–T.6 are the
builder. T.7 is §2's kept promise and T.7b is §2's amendment built. T.8 is the timeline
becoming true, and closes OQ-B3.

---

## 7. The check that is not automated

Every finding in `CLAUDE.md`'s "found by building, not by reading" paragraph was visible on
screen and invisible to a green suite. A timeline of coloured tiles is exactly the artefact that
renders plausibly while being wrong about which character is which — and #184 already found
every step's `<select>` showing option zero, in this same editor, with 418 tests passing.

So T.9 is a task, not a courtesy: open a rotation with at least three characters and a hold-E,
and read the tiles against the gcsim config sitting beside them. The config is the oracle; it
has been there since #184 and it is what makes the timeline checkable at a glance.

---

## 8. Open questions — all four answered 2026-08-30

| | |
|---|---|
| ~~**OQ-T1**~~ | **The measured timeline drops to the authored one the instant `steps()` changes.** Nothing on screen is ever untrue; the same rule the gcsim preview has followed since #184. The cost is accepted: comparing before and after means running twice. |
| ~~**OQ-T2**~~ | **A button the author presses.** Never automatic on a pause. The 2.3 s is spent deliberately. §7's browser check is where "an author who never presses it" gets tested against. |
| ~~**OQ-T3**~~ | **Both loops and copy/paste** — see §5. |
| ~~**OQ-T4**~~ | **`DESIGN_rotation.md` §2 amended first**, with `DECISIONS.md` §27 recording why the reasoning moved. Not read around. |

**Nothing here is blocked on the owner.** The next step is `docs/TASKS_rotation_builder_gui.md`
— T.0 through T.9, atomic, with the acceptance criteria the gate column names.
