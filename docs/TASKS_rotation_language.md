# TASKS — the rotation language, and a builder that can edit it

**Status: not started, 2026-09-03.** Plan for `docs/DESIGN_rotation_language.md`. Read that
first; this file is the decomposition and does not restate the argument.

**Order matters between phases, not always within them.** Phases 1–3 are backend and
independent of the UI; Phase 4 is the migration gate; Phases 7–10 are the builder and need
1–5 landed. **Phase 11 is independent of everything** and can be done first if a measurement
is wanted early.

**Nothing is gated any more.** OQ-L1 and OQ-L2 were both answered by the owner on 2026-09-03
— *"We can expand beyond buttons where needed"*, and *"user defined functions almost need to
be written… they'll have to author them themselves"*. That **reordered the plan**: the source
view moved from a gated last phase to **Phase 7, core**, because it makes every rotation
editable the moment parse and emit exist. The GUI phases after it are progressive enhancement
over a surface that already works, not the only way in.

**The value curve is therefore no longer 13 % → 84 % → *gated***. It is:

| after | importable | editable |
|---|---|---|
| Phase 2 | **100 %** (`raw`) | 13 % |
| Phase 5 | 100 % | 13 % — runs and scores |
| **Phase 7** | 100 % | **100 %** — GUI where it fits, text where it does not |
| Phases 8–10 | 100 % | 100 %, with **~84 %** clickable rather than typed |

---

## Phase 0 — the gate

| # | task | acceptance |
|---|---|---|
| 0.1 | Cut `feat/rotation-language` from `dev`; confirm `git branch --show-current` | branch exists, nothing committed to `dev` |
| 0.2 | Create `docs/LOG_rotation_language.md` with the 2026-09-03 corpus numbers as its first entry | 33/256 import, 256/256 run, 0 lines lost, the `fn` census |

## Phase 1 — the node model, backend only

No parser, no UI. Just the shapes and their rules.

| # | task | acceptance |
|---|---|---|
| 1.1 | `app/schemas/rotation_nodes.py`: `ActionNode` carrying today's step fields plus `params: dict[str, str]` | round-trips through Pydantic; `params` defaults empty |
| 1.2 | `LoopNode` — `kind` (`counted`/`guarded`), `variable`, `bound`, `condition`, `body` | a counted loop with a non-integer bound is accepted and kept as an expression |
| 1.3 | `BranchNode` — `arms: list[(condition, body)]`, `otherwise: body \| None` | an `if/else if/else` chain is one node, not three |
| 1.4 | `WaitNode`, `SwapNode`, `LetNode`, `AssignNode`, `CallNode`, `FnNode` | each validates its own required fields |
| 1.5 | `RawNode` — `source: str`, plus a `reason` naming what was not understood | `reason` is required; a `raw` with no reason fails validation |
| 1.6 | The expression model: literal, identifier, state path, unary, binary | `.furina.energy >= 30` and `i > 0 && !x` both parse into it in a unit test |
| 1.7 | `RotationTree` root + a discriminated union over node kinds, published to OpenAPI | `npm run codegen` produces a usable TS union |
| 1.8 | Depth and size limits with named errors | a 200-deep tree is refused by name, not by recursion error |

## Phase 2 — tokenizer and parser

**Import must reach 100 % at the end of this phase**, because 2.2 makes `raw` the fallback.

| # | task | acceptance |
|---|---|---|
| 2.1 | Tokenizer over gcsim's grammar: identifiers, numbers, strings, operators, braces, `;`, both comment syntaxes | tokenizes all five vendored configs, CRLF and LF alike |
| 2.2 | Parser skeleton that produces **one `RawNode` for the whole action block** | every one of the five vendored configs "imports"; nothing is lost |
| 2.3 | Parse a flat action statement, with variant and repeat, into `ActionNode` | `razor skill[hold=1]:2;` → one node; unknown params land in `params` |
| 2.4 | Parse `for` (counted and variable-bound) into `LoopNode` | bound kept as an expression when not an integer |
| 2.5 | Parse `while` (guarded) into `LoopNode` | `while .clorinde.status.clorinde-night-watch {` parses |
| 2.6 | Parse `if` / `else if` / `else` into one `BranchNode` | closes OQ-C3 at the model level |
| 2.7 | Parse `wait(n)` / `delay(n)` / `swap` | |
| 2.8 | Parse `let`, assignment, and `call` | |
| 2.9 | Parse `fn` definitions, body included | the definition is structural even if authoring is later refused |
| 2.10 | **`raw` containment rule**: a production that cannot complete emits `raw` for its *whole* construct, never a partial tree | unit test: an unparseable `for` body makes the whole `for` raw |
| 2.11 | Every `raw` carries a human reason naming the construct | reasons are the refusal messages this repo already writes well |

## Phase 3 — emitter, and the round-trip property

| # | task | acceptance |
|---|---|---|
| 3.1 | Emit each node kind | |
| 3.2 | `RawNode` emits **byte-identical** source | property test over every construct the parser declines |
| 3.3 | Property test: `parse(emit(t)) == t` for generated trees | hypothesis-style generation over the node union |
| 3.4 | Round-trip the five vendored configs, tree-equality | |
| 3.5 | Behavioural check **with the self-noise control first** | documented that gcsim has no seed flag; comparison is a noise band, never equality |
| 3.6 | Re-express `_unroll_parity` over the tree | same reduction, now on `LoopNode` + `BranchNode` |
| 3.7 | Re-express `_reduce_ready_branches` over the tree | |

## Phase 4 — storage and migration (the gate)

| # | task | acceptance |
|---|---|---|
| 4.1 | Alembic revision: `rotations.tree` JSONB, nullable, beside `steps` | generated **on the host**, not in the container |
| 4.2 | Lossless `steps` → tree conversion, `group`/`group_repeat`/`group_condition` → `LoopNode` | |
| 4.3 | **Migration equivalence gate**: every rotation in the database compiles to the *same gcsim text* before and after | a diff of one character fails the task |
| 4.4 | Backfill script with a dry-run mode reporting the diff count | refuses to write if any rotation's text changes |
| 4.5 | Read path prefers `tree`, falls back to `steps` | old rows keep working during rollout |
| 4.6 | Drop `steps` **only** after 4.3 passes on production data | separate task, separate PR, deliberately last |

## Phase 5 — API and compiler

| # | task | acceptance |
|---|---|---|
| 5.1 | `compile_rotation` reads a tree | emits what today's compiler emits for a flat rotation, byte-identical |
| 5.2 | Import endpoints return a tree | `/rotations/import` and `/import/link` share one path, as they do now |
| 5.3 | `rotation_signature` over the tree | stable under comment and whitespace edits; changes when meaning changes |
| 5.4 | Recipe cache `SCHEMA` bump | one deliberate miss on deploy, as with every prior bump |
| 5.5 | `wait_for_energy` rewrites gates **in the tree** | and reports partial application when a `raw` node contains a burst — **OQ-L3** |
| 5.6 | Contract test + `npm run codegen` | `tests/unit/test_openapi_contract_is_current.py` stays green |

## Phase 6 — validation and diagnostics

**Promoted, because a typed surface is only as friendly as its errors.** This lands *before*
the editor that needs it. The refusal messages this repo already writes are the model.

| # | task | acceptance |
|---|---|---|
| 6.1 | Call-graph validation: undefined function, arity mismatch, recursion | each refused **by name**, with the line |
| 6.2 | Scope checking for parameters and `let` | an out-of-scope identifier is named, never silently emitted |
| 6.3 | Unknown character key, unknown action, unknown state property | resolved against the team, as `_canonical` already does for aliases |
| 6.4 | Diagnostics carry a **position** (line, column, length) | the editor needs it to underline; refusals today carry only text |
| 6.5 | A diagnostic distinguishes *error* (will not compile) from *warning* (compiles, probably not meant) | `attack:0` is a warning; an undefined `fn` is an error |
| 6.6 | Diagnostics are returned by the API, not only raised | one endpoint, so the editor and the importer report identically |

## Phase 7 — the source view (core)

**This is the phase that makes everything editable**, and it is why the ordering changed.

| # | task | acceptance |
|---|---|---|
| 7.1 | Read-only source view rendering `emit(tree)` | useful alone: it is how a user checks what their clicks produced |
| 7.2 | Editable, parsed on change through the **same** parser as import | no second vocabulary; the tree stays the source of truth |
| 7.3 | Diagnostics from Phase 6 shown inline, underlined at their position | |
| 7.4 | Two-way sync: GUI edits re-render the text, text edits rebuild the tree | a conflict reports rather than silently picking a side |
| 7.5 | Unparseable text is held as a draft and never destroys the last good tree | the failure mode that would lose a user's work |
| 7.6 | `fn` authoring is text-only, and the view says so where a function appears | owner: *"they'll have to author them themselves"* |

## Phase 8 — builder: the outline

| # | task | acceptance |
|---|---|---|
| 7.1 | Recursive outline component, one line per node, indentation for nesting | a 180-step imported rotation renders without a scroll jail |
| 7.2 | Collapse a block to one line with a count | |
| 7.3 | Selection model, single node, keyboard navigable | arrow keys move, Enter opens the inspector |
| 7.4 | Drag to reorder within and across blocks, refusing an invalid drop | dropping a node into its own descendant is refused |
| 7.5 | `raw` renders plainly marked and read-only | it must be obvious it is carried, not understood |

## Phase 9 — builder: the picker becomes primary

This is the layout inversion the owner asked for.

| # | task | acceptance |
|---|---|---|
| 8.1 | Flip the grid: picker takes `1fr`, outline the fixed column | `grid-template-columns: minmax(0, 1fr) minmax(0, 34rem)` |
| 8.2 | Roster as a character grid using `RosterCharacter.icon` / `element_icon` | already published; no new endpoint |
| 8.3 | Move tiles carrying talent art and the character's own ability name | `ability_names` is already published |
| 8.4 | Insertion point model — clicking a tile appends there, not always at the end | visible caret in the outline |
| 8.5 | Structure rail: `loop`, `if`, `else`, `wait`, `swap` | inserting with a selection **wraps** it |
| 8.6 | `npm run check:tokens`; no hand-written colours | CSS custom properties fail silently — that is why this is its own task |
| 8.7 | Screenshot pass at 1920×1200, 1440×900 and 1100×700 via `scripts/shoot.py` | a green suite has never caught a layout defect here |

## Phase 10 — builder: the inspector

| # | task | acceptance |
|---|---|---|
| 9.1 | Inspector panel bound to the selection | |
| 9.2 | Repeat, note, and opaque `params` shown read-only with an explanation | |
| 9.3 | Condition builder: subject / property / comparison / value, all dropdowns | no free text; **still "buttons only"** |
| 9.4 | Property list per character from what gcsim publishes | not a hand-written list — derived, like `authorable_actions()` |
| 9.5 | `&&` / `||` as additional rows | |
| 9.6 | Loop editor: counted bound, or a guard built by 9.3 | |

## Phase 11 — the sweep harness (independent)

| # | task | acceptance |
|---|---|---|
| 11.1 | `scripts/sweep_gcsim_db.py` — fetch, import, round-trip, report | polite: paged fetch, identifying User-Agent, ≥1 s delay |
| 11.2 | Synthetic construct suite, one config per node kind, **written here so it is ours to licence** | committed; CI runs it |
| 11.3 | CI gate over the synthetic suite plus the five vendored configs | the 500-config corpus stays uncommitted — no licence is stated for it |
| 11.4 | Record each sweep in `docs/LOG_rotation_language.md` | a percentage with a date, never a bare number |

---

## What each phase is worth

Cumulative, against the 256 configs measured on 2026-09-03:

| after | importable | editable | how |
|---|---|---|---|
| Phase 2 | **100 %** | 13 % | `raw` carries anything unmodelled, byte-exact |
| Phase 5 | 100 % | 13 % | it runs, scores, and survives the recipe cache |
| **Phase 7** | 100 % | **100 %** | GUI where it fits, source view where it does not |
| Phases 8–10 | 100 % | 100 % | **~84 % clickable** rather than typed |

**The shape the owner's ruling produced.** Under "buttons only" the last 16 % was gated on a
hard question and the GUI was the only way in. With text as a first-class surface, **editing is
complete at Phase 7** and everything after it is progressive enhancement — each GUI phase moves
work from the text surface to the clickable one without ever being the thing that decides
whether a rotation can be edited at all.

**Two natural stopping points**, both coherent:

- **After Phase 7** — complete parity. Everything imports, runs, scores and can be edited. The
  GUI is what it is today, plus an outline and a text view.
- **After Phase 10** — the same, with ~84 % of real rotations editable without typing a
  character. `fn` and free-form expressions stay text, by decision rather than by omission.
