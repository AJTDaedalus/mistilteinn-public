# DESIGN: the rotation builder

**Status: OQ-B1 and OQ-B2 answered by the owner 2026-08-29 — "the surface only", and no
quick-add line. B.1, B.2, B.3 and B.6 built in #181; B.4 and B.5 in #184. B.7 is closed.
OQ-B3 and OQ-B4 remain.** Owner request
(`BACKLOG_frontend.md` §5): *"I want a very extensive and easy to use rotation builder, it's
one of our key distinctions from gcsim."*

Read `docs/DESIGN_rotation.md` first. It decided what a rotation **is**, and this document is
constrained by it rather than free to revisit it.

**Branch policy.** Work happens on `feat/rotation-builder`, never on `dev` or `main`; `dev` is
updated only by PR after review. Task 0 of the TASKS file is the branch-setup gate.

---

## 1. The constraint that shapes everything: "extensive" cannot mean "more expressive"

`DESIGN_rotation.md` §2 is unambiguous:

> **This is a v1 that refuses to be a language.** The moment it grows a conditional it has
> become gcsim's syntax with different punctuation, and the owner's complaint applies to it too.

It names three things the model deliberately cannot express — branches, nesting, and
`wait`/`delay` — and gives a reason for each. So **every proposal here is about the authoring
*surface*, not the grammar.** A builder that grows "repeat this section ×3" has not become more
capable; it has reopened a decision, and reopening it is the owner's to do, not this document's.

That is the single most useful thing a design pass can establish, because "extensive" naturally
reads as "can express more" and here it must mean "costs less to say".

**If the owner does want more expressive power, that is a different document** — an amendment
to `DESIGN_rotation.md` §2 with the grammar question reopened, not a builder feature. §6 lists
what would have to be answered first.

---

## 2. What the builder costs today, counted

The editor (`pages/rotations`) offers: a name, a team picker, the roster shown once, and a list
of steps. Each step is a character `<select>`, an action `<select>`, a `repeat` number, two
reorder arrows and a delete.

`addStep()` appends a step defaulting to **the first roster member and the first action** —
`normal_attack` for whoever happens to be in slot one.

So authoring the owner's real Hyperbloom cycle — **8 steps, 11 actions** — costs roughly:

| per step | interactions |
|---|---:|
| "Add step" | 1 |
| change the character off the default | 2 (open, pick) |
| change the action off `normal_attack` | 2 |
| set `repeat` where it is not 1 | 2 |
| **total** | **5–7** |

**Around 45 interactions for eight steps**, plus reordering at one position per click if the
order came out wrong. gcsim's equivalent is four lines of typing.

**That is the number to beat, and it is worth stating rather than asserting the UI is bad.**
The current builder is correct, refuses what it should, and shows what it compiles to. It is
*slow*, and slowness is the specific thing to fix.

---

## 3. What only this app can do, and gcsim cannot

Three assets exist and none is used by the builder. They are where the "key distinction" the
owner wants actually lives.

### 3.1 The characters have names for their abilities, and the builder says `skill`

`Character.talents` carries the real names — Nahida's `elemental_skill` is **"All Schemes to
Know"**, her burst is **"Illusory Heart"**. Verified against the seeded database, not from
memory.

A gcsim config says `nahida skill`. A builder that says *"Nahida — All Schemes to Know"* is
naming the thing the player knows, and it costs one field on `/rotations/options`, which
already publishes the roster. **This is the cheapest distinction available and it is pure
gain**: nothing is hidden, since the action's key still governs what compiles.

### 3.2 The roster is already on screen, and is not clickable

The editor shows every team member as art plus an element chip, then asks the user to pick one
from a `<select>` underneath. **Click a face, then click an action** replaces five interactions
with two, and uses a control that is already rendered.

### 3.3 The app knows what the rotation becomes, behind a button

`POST /{id}/compile` returns the gcsim action list and the editor shows it on demand. Live
would make the gates visible as they are written — and the gates are what
`DESIGN_rotation.md` §3.4 calls "the whole point", because they are what stops the two silent
failures that cost the ER sweep two wrong answers.

**A caveat that has to survive into the implementation:** `compile` reads the **stored**
rotation, and the editor already disables the button while `dirty()`. A live preview must
therefore compile client-side or send unsaved steps — and a preview that silently showed the
saved version while the user edited would be worse than no preview.

---

## 4. Proposals, each with what it costs

Ordered by ratio of what it saves to what it risks. **None of them changes the model.**

| # | proposal | saves | cost / risk |
|---|---|---|---|
| B.1 | Ability names from `Character.talents` | recognition, not clicks | one field on `/rotations/options`; a character with no seeded talents falls back to the key |
| B.2 | Click a face → click an action, appends a step | ~3 interactions per step | a second way to add a step alongside the selects; both must stay in sync |
| B.3 | Duplicate a step, and insert **at** a position | the "write it three times" §2 already promises | none of substance |
| B.4 | Drag to reorder | n clicks → one drag | drag-and-drop needs a keyboard equivalent, so the arrows stay |
| B.5 | Live compile preview | sight of the gates while authoring | must compile the *unsaved* steps — see §3.3 |
| B.6 | Show and edit `note` per step | a field the model has carried since R.4 and no UI has ever shown | none |
| ~~B.7~~ | ~~Quick-add line~~ | — | **Closed by the owner (OQ-B2): "No — buttons only."** One way in, and no chance of a typed vocabulary drifting from the clickable one. |

### B.7 deserves its own paragraph, because it is the one that could go wrong

The owner's complaint that started this whole chunk was *"gcsim uses a convoluted rotation
syntax"*. A quick-add line is a syntax. The defence is that it would be an **accelerator over
the same ten actions**, parsing exactly what the buttons produce and nothing else — no
conditionals, no waits, no nesting — and that `rotation_parser` already exists and already
refuses everything outside that vocabulary.

**But the defence is only as good as the refusal.** If the line ever accepts something the
buttons cannot express, the builder has two vocabularies and the smaller one is a lie. This is
an owner call (§6, OQ-B2), not a judgement to make in an implementation.

---

## 5. The check that is worth more than all of them, and what it collides with

**"Does this rotation actually work?"** — a button that runs the rotation once and reports
whether the burst count is what the author expects and whether it is *stable across iterations*.

`sim/recipe-energy.ts` already computes exactly this shape of answer, and its docstring says
why it matters: a build that cannot burst when the rotation says to burst **is not performing
that rotation**. Today that is discovered during a search, long after authoring.

It is also, precisely, a `sim_run`: one gcsim aggregate for one context.

**Which collides with `DECISIONS.md` §25 — the run corpus has no producer.** That open question
asks who runs gcsim and submits the result. This feature answers it: *the author does, when they
ask whether their rotation works*, and the run is worth caching because it is exactly what the
corpus stores.

**One feature closing two open questions is a reason to look hard at it, not a reason to assume
it is right.** It costs a gcsim run (~3 s, measured in `DESIGN_client_optimizer.md`) at a moment
the user is waiting, and it makes the builder depend on the wasm bundle. Recorded here so the
two decisions are made together rather than twice.

---

## 6. Open questions for the owner

| | question |
|---|---|
| **OQ-B1** | Does "extensive" mean the surface (§4), or does the owner want the model to express more — sections, repeats, conditionals? The second reopens `DESIGN_rotation.md` §2 and is a different document. |
| **OQ-B2** | Is the quick-add line (B.7) wanted? It is the fastest single change and the only one that reintroduces a syntax, however small. |
| **OQ-B3** | Should "does this work?" (§5) be built, given it costs a gcsim run at authoring time — and should its result feed the run corpus, answering `DECISIONS.md` §25? |
| **OQ-B4** | Is the rotation *library* now part of the builder's job — "start from someone else's and edit it" — or does copying remain a separate action? #177 made copies possible; nothing makes them a starting point. |

**All five surface items are built.** B.1, B.2, B.3 and B.6 in #181; B.4 and B.5 in #184.

B.4 uses native HTML5 drag rather than a new dependency, and **the arrows stay** — a drag has
no keyboard equivalent, and this list has to be reorderable both ways. `reorder` is the general
move and `move` is its ±1 case; a test pins that they agree, because a swap and a splice
coincide only for ±1 and that coincidence is worth holding.

B.5 honours §3.3 by **compiling on the server**: `POST /rotations/preview` takes unsaved steps
and answers with the same `compile_rotation` a save would use. The alternative was a second
compiler in TypeScript, and the readiness gates it would have to reimplement are exactly what
stop gcsim's two silent failures.

### What building B.5 found

**Every step's dropdowns were showing the first option, whatever the step held.** `[value]` on
a `<select>` is assigned in the same change-detection pass that renders its `@for` options, so
the assignment lands before the option exists and the browser falls back to index 0.

The compiled config was correct the whole time — which is why nothing failed and no test
noticed. It was visible the moment the preview sat beside the editor: step 2 read *"Bennett ·
Chihayaburu"* next to a config that said `kaedeharakazuha skill`. `[selected]` on the option
fixes it, and it is a bug that predates this chunk — `addStep()` always used the first roster
member, so before the quick-add every step genuinely was the first character.

### One thing building B.1 found

**gcsim's actions and the catalogue's talent types are two vocabularies that look like one.**
gcsim writes `skill`; the catalogue stores `TalentType.ELEMENTAL_SKILL`. The first
implementation keyed abilities by talent type, so every lookup missed and every button showed
its own key — a feature that was live, green, and doing nothing.

**No test caught it, because the unit fixture had been written with the same wrong
assumption.** It was caught by opening the page. `gcsim_keys.ability_names` now owns the
correspondence so no client performs it, and
`test_abilities_are_keyed_by_gcsims_action_not_by_talent_type` pins it with that story in its
docstring.

---

## 7. Not proposed, and why

- **Frame or second counts in the editor.** `DESIGN_rotation.md` §2 removes timing on purpose,
  and the rotations list already says *"8 steps · 11 actions"* rather than hits and seconds
  because those need a run. Showing a duration while authoring would put the user back into
  frame counting, which is the thing being removed.
- **Suggesting a rotation.** Rotations are authored, never optimized (owner, 2026-08-25). A
  builder that offered "here's a good rotation for this team" would be that decision reversed
  through the side door.
- **Importing arbitrary gcsim configs into the editor.** Two of four real configs import today
  and two are refused for naming user-defined functions (`LOG_rotation_library.md`, L.10). That
  is the converter's problem and it is answered; the builder should not grow a second, laxer
  path to the same model.
