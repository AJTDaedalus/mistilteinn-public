# DESIGN — the rotation language, and a builder that can edit it

**Status:** design, 2026-09-03. Nothing built. Supersedes nothing; **extends**
`DESIGN_rotation_builder.md` (the surface) and `DESIGN_conditional_steps.md` (guarded blocks),
and closes **OQ-C1** and **OQ-C3** if built.

Owner, 2026-09-03: *"I'm aiming for complete parity with gcsim in the language"*, and
*"We may need to redesign the builder to support this, as the 'meat' of the builder is quite
small where you pick moves, with the move list being the biggest element and having the least
important features."*

## Branch policy

`feat/rotation-language`, off `dev`. **No direct commits to `dev` or `main`** — every change
lands by PR after review, like everything else here. Task 0 of `TASKS_rotation_language.md` is
the branch-setup gate.

The feature is large enough to want sub-branches. Each phase below gets one, cut from
`feat/rotation-language` and merged back into it by PR; `feat/rotation-language` merges to
`dev` only when the whole thing is walkable. **The one exception is Phase 11** (the sweep
harness), which is independent and may go straight to `dev` — it is a measurement tool and
blocks nothing.

## Why, and how far

Measured 2026-09-03 over **500 configs from gcsim's own database**, of which **256 are
playable on the owner's roster** (`docs/LOG_rotation_language.md` will carry the run):

| | |
|---|---|
| import today | **33 / 256 — 13 %** |
| run today, via a verbatim action block | **256 / 256 — 100 %** |

The second row is the important one and it is why this design exists at all. `build_config`
already generates the character, weapon, stats and target lines and takes the **action block
verbatim**, so *running* an arbitrary gcsim rotation needs no model change: partitioning all
223 refused configs into build-lines and rotation-lines lost **0 lines**, and all 223 then ran.

So the gap is **authoring**, not simulation. This document is about closing it.

### The ceiling, measured

Adding constructs in rough cost order, and counting how many of the 256 become *editable*:

| add | editable | tier |
|---|---|---|
| *(today)* | 33 — 13 % | |
| carry unknown action params opaquely | 33 | 1 |
| `else` | 41 — 16 % | 1 |
| loop-index conditions | 86 — 34 % | 1 |
| `wait` / `delay` | 122 — 48 % | 1 |
| compound conditions (`&&`, `||`) | 124 | 2 |
| richer sim state (`nightsoul`, `shrapnel`, `mods`, `sets`) | 132 | 2 |
| user variables + `let` | 139 — 54 % | 2 |
| multiple loops | 149 | 3 |
| state-guarded `while` | 173 — 68 % | 3 |
| `swap` | 200 — 78 % | 1 |
| zero repeat, builtin calls | 215 — 84 % | 1 |
| **`fn`** | **256 — 100 %** | 3 |

**`fn` alone is 84 % → 100 %, and it cannot be cheated.** The obvious shortcut — inline a
user function as a macro — was measured and does not exist: of the 41 configs defining an
`fn`, **41 have control flow inside the function body and 30 take a parameter**. There is no
subset of "simple" functions to expand.

That is the whole argument for Tier 3. Stopping at Tier 1 is a defensible product (81 %
editable, 100 % importable) and is what `DESIGN_rotation_builder.md` implies. Going to 100 %
means **a rotation stops being a list and becomes a program**, and the builder has to become
something that can edit a program without feeling like one.

## The model: a tree, with an escape hatch

A rotation today is `list[RotationStep]` plus `group` (a path), `group_repeat` and
`group_condition`. That is already a tree flattened into a list with a path column, and it
does not survive the additions above — `else`, nested loops and `fn` all need real structure.

**A rotation becomes an ordered tree of nodes.**

| node | holds | notes |
|---|---|---|
| `action` | character, action, repeat, params, note | today's step, plus an opaque `params` map |
| `loop` | kind (`counted` / `guarded`), variable, bound, condition, body | `group_repeat` becomes `counted` |
| `branch` | a list of `(condition, body)` arms plus an optional `else` body | closes **OQ-C3** |
| `wait` | frames, or `delay` | today refused by name |
| `let` | name, expression | |
| `assign` | name, expression | `i = i + 1` outside a loop header |
| `call` | function name, argument expressions | |
| `fn` | name, parameters, body | the Tier 3 step |
| `swap` | character | gcsim's explicit swap |
| **`raw`** | **verbatim source text** | **the escape hatch — see below** |

### `raw` is the robustness guarantee, and it is load-bearing

**Any construct the parser does not yet model becomes a `raw` node holding its exact source
text.** A `raw` node emits byte-identical text, is shown read-only in the builder, and blocks
nothing.

This single decision changes the character of the whole project:

- **Import is 100 % from the first phase**, before a single new node kind is implemented. The
  parser starts by producing one `raw` node per config and is refined toward structure
  afterwards, so no phase of this work ever regresses what a user can bring in.
- **A partly-understood rotation is still editable.** A config whose loop we model and whose
  `fn` we do not is a tree with an editable loop and one opaque block, not a refusal.
- **The refuse-don't-degrade rule is preserved and strengthened.** Today the choice is
  *refuse* or *silently change*; `raw` adds *carry exactly, and say so*. Nothing is
  reinterpreted — a `raw` node is never rewritten, and the builder marks it plainly.

The rule that keeps `raw` honest: **a `raw` node is opaque, never partial.** The parser may
not read half a construct and `raw` the rest; if a `for` header is understood but its body is
not, the whole `for` is `raw`. Anything else risks a tree that looks structured and emits
something the author did not write, which is exactly the failure
`DESIGN_conditional_steps.md` §"The decision this design exists to make" exists to prevent.

### Expressions

Conditions and bounds become a small expression tree — literals, identifiers, sim-state paths
(`.furina.energy`), comparison, `&&`, `||`, `!`, and arithmetic. **Parsed and re-emitted, never
evaluated by us**, with one deliberate exception: a condition that is a pure function of a
counted loop's index is *arithmetic*, and unrolling it is already this repo's precedent
(`_unroll_parity`). That exception stays confined to the converter and never reaches the
compiler.

## Parser and emitter

Today's importer is line-oriented regex (`rotation_converter` + `rotation_parser`). That is the
right shape for a subset and the wrong one for a language. Tier 3 needs:

- **A tokenizer** over gcsim's config grammar — identifiers, numbers, strings, operators,
  braces, comments, `;`.
- **A recursive-descent parser** producing the node tree, with `raw` on any production it
  cannot complete.
- **An emitter** producing gcsim text from the tree.

**The property that governs both:** `parse(emit(tree)) == tree`, and for an imported config,
`emit(parse(source))` runs in gcsim to the same DPS as `source` within gcsim's own run-to-run
noise. Note the second is a *noise-band* comparison, not equality — **gcsim has no seed flag**,
so two runs of an identical config differ. That was measured on 2026-09-03 and it briefly read
as a real difference before the control was added; the harness must always compare
original-against-itself first.

The existing regex importer is **kept, not deleted**, until the parser passes the same corpus:
`rotation_converter`'s two reductions (parity unrolling, ready-branch collapse) are rewrites
this design still wants, expressed over the tree instead of over lines.

## What Tier 3 keeps that a verbatim passthrough would lose

Worth stating, because passthrough is the cheap alternative and looks equivalent:

- **The waiting/skipping toggle keeps working.** It adds or removes `.ready` gates on bursts,
  which needs a tree to edit. On verbatim text it could not apply at all.
- **`rotation_signature` stays structural.** A cache key over a tree is stable under
  reformatting and comment edits; one over text is not, so a whitespace change would miss the
  recipe cache for no reason.
- **The rotation stays inspectable.** Burst counts, step counts, per-character action tallies
  and the timeline all read the tree.

## The builder, redesigned

### What is wrong now, measured rather than asserted

`editor.html` is 458 lines and `editor.scss` 465. The layout is
`grid-template-columns: minmax(0, 36rem) minmax(0, 1fr)` above 88rem: the **roster and action
picker are confined to a 36rem aside**, and the **step list takes the wider `1fr` column**.

The owner's reading is exactly right. The picker — the only part where a user makes a decision
— is the smaller column, and the list, which is a repetitive record of decisions already made,
is the larger. Adding loops, branches and functions to that list makes the imbalance worse, not
better.

### The principle

**Space follows decisions, not records.** The surface where a user chooses gets the room; the
record of what they chose gets density.

### The layout

Three regions, replacing the current two:

```
┌────────────────────────────────┬───────────────────────┐
│  PICKER  (primary, ~1fr)       │  OUTLINE  (~34rem)    │
│                                │                       │
│  roster as a grid of           │  the rotation as a    │
│  characters; the selected      │  dense indented       │
│  character's moves as large    │  outline, one line    │
│  tiles with art and name       │  per node             │
│                                │                       │
│  ── structure rail ──          │  drag to reorder      │
│  loop · if · else · wait ·     │  click to select      │
│  swap · function               │                       │
├────────────────────────────────┴───────────────────────┤
│  INSPECTOR — the selected node only                     │
│  repeat · condition · bound · params · note             │
└─────────────────────────────────────────────────────────┘
```

- **Picker (primary).** Characters as a grid, the active character's moves as tiles big enough
  to carry the talent art and the character's own name for the move — both of which
  `RosterCharacter` already publishes (`ability_names`, `icon`). Clicking a tile appends to the
  current insertion point. This is the "meat" and it gets the space.
- **Structure rail.** Control flow is inserted the same way a move is: by clicking. `loop`,
  `if`, `else`, `wait`, `swap`, `function`. Inserting a block wraps the current selection when
  there is one — "wrap these four steps in a loop" is the actual verb.
- **Outline.** One line per node, indentation for nesting, a repeat badge, the note inline. A
  block collapses to a single line with a count. It is a *record*, so it is dense.
- **Inspector.** Everything about the selected node in one place. This is where a condition is
  built, a loop bound set, an opaque param shown. Nothing about a node is edited in the outline
  row itself, which is what keeps the row one line.

### Editing a condition without typing

The condition editor is three controls, not a text field:

`[ subject ▾ ] [ property ▾ ] [ comparison ▾ ] [ value ]`

— subject from the team's roster, property from what gcsim publishes for that character
(`energy`, `status.*`, `nightsoul.points`, `<action>.ready`), comparison from the operators the
property allows. `&&` / `||` add another row. **This is still "buttons only"** in the sense
OQ-B2 meant: nothing is typed that could drift from a clickable vocabulary.

### The source view — and the owner's ruling that makes it core

A `fn` body, or an expression outside the vocabulary above, cannot be built from dropdowns
without inventing a visual programming language. So the builder gains a **source view**: the
rotation as gcsim text, editable, parsed through the same parser as an import, two-way synced
with the tree.

**Owner, 2026-09-03, overturning OQ-B2 for this feature:**

> *"We can expand beyond buttons where needed, don't consider this a hard and fast rule. The
> priority is feature parity with the user being able to build a similar rotation in the tool
> if they desire, some of these things are too complicated for that."*

That is the decision, and it **changes the plan's shape rather than just unblocking a phase**.

Under "buttons only", the GUI was the only way in, so anything the GUI could not build was
uneditable — and the project's value curve ran 13 % → 84 % → 100 %, with the last leg gated on
a hard question. With text as a first-class surface the curve inverts: **the source view makes
every rotation editable as soon as the parser and emitter exist**, and the GUI phases become
progressive enhancement over a surface that already works.

So the source view moves from "Phase 10, gated" to **Phase 7, core**, and the ordering priority
becomes:

1. **Parity first** — import, run, score, edit *something*. (Phases 1–5, 7)
2. **Then make the common path clickable.** (Phases 8–10)

The three narrowings from the previous draft still hold and are worth keeping as design
constraints rather than as an argument for permission:

1. It is not a second way to do what buttons do; it is the only way to do what they cannot.
2. It is **not a second vocabulary** — text goes through the *same* parser as an import, so the
   tree stays the single source of truth and nothing typed escapes the rules an import obeys.
3. Its diagnostics are the user-friendliness story. This repo already writes refusal messages
   better than most things it does; a typed surface is only as friendly as its errors, so
   **validation and diagnostics get their own phase and land before the editor does**.

**OQ-B2 is not repealed generally.** It answered a *quick-add line for actions* — a second,
typed way to do exactly what the move buttons already do — and that remains closed. What is
now allowed is a surface for what buttons cannot express. `DECISIONS.md` §32 records the
distinction.

### "Build a similar rotation if they desire"

The owner's phrasing sets the bar, and it is lower than "author anything in the GUI":

- Every rotation **imports, runs and scores**. Not negotiable, and delivered by Phase 5.
- Every rotation is **editable** — through the GUI where the construct is reasonable, through
  the source view where it is not. Delivered by Phase 7.
- A user who wants to **build something similar from scratch** can do so for the constructs a
  GUI can honestly represent: actions, repeats, loops, branches, waits, swaps, conditions.
  That is Phases 8–10, and it covers ~84 % of real configs.
- `fn` and free-form expressions are **too complicated for a GUI, by the owner's own reading**,
  and are authored as text. No visual programming language will be built for them.

  Owner, confirming the same day: *"user defined functions almost need to be written, and if a
  user wants that level of complexity they'll have to author them themselves."* So a `fn` is
  **parsed into a real node, emitted faithfully, validated, and edited as text** — structural
  everywhere it needs to be, and never rendered as a form. The measurement behind that:
  of the 41 corpus configs defining a function, **41 have control flow in the body and 30 take
  a parameter**, so there is no "simple function" case a GUI could have covered anyway.

### Progressive disclosure

A rotation with no control flow must look exactly as simple as it does today. The structure
rail is present but quiet; the outline of a flat rotation is a flat list; the inspector shows
repeat and note and nothing else. Complexity appears only in rotations that contain it.

## Testing

- **Round-trip property, over the corpus.** `parse(emit(parse(source))) == parse(source)` for
  every config. This is the main gate and it is a property test, not a fixture.
- **Behavioural equality, noise-controlled.** `emit(parse(source))` runs in gcsim to `source`'s
  DPS, compared against a same-config self-noise measurement first. No seed exists; skipping
  the control produces false differences, as it did on 2026-09-03.
- **`raw` fidelity.** A `raw` node emits byte-identical text. Property-tested over every
  construct the parser declines.
- **Migration equivalence.** Every existing rotation in the database compiles to the *same
  gcsim text* before and after the tree migration. This is the gate on Phase 4 and it is
  non-negotiable: a user's saved rotation may not change meaning.
- **The licence problem, and what CI actually runs.** gcsim's database states **no licence**
  for submitted configs (`references/gcsim_db/PROVENANCE.md`), so the 500-config corpus is
  **not committed**. CI runs against (a) the five configs already vendored with full
  provenance, and (b) a **synthetic suite written here**, one config per construct, which is
  ours to licence. The full sweep is `scripts/sweep_gcsim_db.py`, run on demand like
  `scripts.ci_local`, and its result is recorded in the log rather than gating a merge.

## Risks

| risk | mitigation |
|---|---|
| A hand-written parser diverges from gcsim's real grammar | `raw` on anything unrecognised; the sweep measures divergence rather than assuming none |
| The migration changes a saved rotation's meaning | Phase 4's gate compiles every existing rotation before and after and diffs the text |
| The builder becomes an IDE and loses the audience | Progressive disclosure: a flat rotation looks exactly as simple as it does today, and the source view is a surface a user opens rather than one they land in |
| Scope: this is the largest single change since the fork | Phased, each phase shippable; `raw` means import works from Phase 2 and the source view means editing works from Phase 7 |
| gcsim re-pin changes the grammar | The tokenizer is pinned and tested against the vendored configs; a re-pin runs the sweep |

## Open questions

| | |
|---|---|
| ~~**OQ-L1**~~ | **Answered 2026-09-03 — yes, and it is core rather than gated.** *"We can expand beyond buttons where needed."* The source view moves to Phase 7 and the value curve inverts: everything becomes editable as soon as parse and emit exist. |
| ~~**OQ-L2**~~ | **Answered 2026-09-03 — `fn` is importable, editable and authorable *as text*, and no GUI will be built for it.** *"Some of these things are too complicated for that."* Phase 6 therefore becomes validation and diagnostics, which a typed surface needs, rather than a decision. |
| **OQ-L4** | Does the library publish trees or text? A published rotation someone else imports must not depend on our node vocabulary staying still. |
