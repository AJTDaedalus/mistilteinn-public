# DESIGN: artifacts — the inventory, and what a piece is worth

**Companion:** `docs/TASKS_artifacts.md`
**Tier:** Planner (Opus). Implementation is Worker.
**Follows:** `docs/TASKS_teams_builds.md` (complete). **Precedes:** the optimizer surface,
which needs an inventory to search.

## Branch policy

Per-task branches off `dev`, named `feat/<task>` or `fix/<task>`, merged to `dev` by PR after
review. **No direct commits to `dev` or `main`.** No parallel tracks: A.1 (equipping) gates
A.4 (the build's artifact panel), and A.5 (scoring) gates A.6 (showing it). Task 0 of
`docs/TASKS_artifacts.md` is the branch-setup gate.

---

## 1. Why this chunk exists

The teams-and-builds chunk made the app usable: a user can build a character, assemble a
party, author a rotation and compile it. They still cannot see a single piece of gear.

That matters more than an ordinary missing page, because **artifacts are what the product is
about**. `src/app/sim/` holds a working browser optimizer — a CPU kernel, a WGSL GPU kernel
and a search, all tested against the Python oracle — and **nothing imports it**. It is the
"a library no page calls" shape `app.routes.spec.ts` was written to catch, one level below
routes: the guard checks that every *route* is linked, and this is a module with no route at
all.

The engine cannot be reached because there is nothing for it to search.

**Owner decisions, 2026-08-24:** artifacts arrive by **GOOD import only** — no manual entry —
and **G.9's scoring belongs in the inventory**, next to the piece it describes.

## 2. What the backend already has

More than expected, and better built than the frontend gap suggests.

| | |
|---|---|
| `GET /artifacts` | paginated, filterable by `slot`, `set_id`, `equipped` |
| `GET /artifacts/inventory` | an ETag'd snapshot for the browser kernel — and it **already reports `truncated`**, which the catalogue pages did not until #66 |
| `POST /artifacts/import/good` | `mode` required, per-artifact rejections, a 409 that deletes nothing |
| `GET`/`DELETE /artifacts/{id}` | one piece |

The import endpoint has real discipline in it and **the UI must not flatten any of it**:

- **`mode` has no default** — `replace` and `append` are different intentions, and GOOD
  carries no stable per-artifact id to merge on. A UI that picked one for the user would be
  choosing whether to delete their inventory.
- **A malformed artifact does not fail the file.** It lands in `rejected` with a reason, and
  the rest imports, because someone with 800 artifacts and two odd ones wants the 798. A UI
  that shows only "imported 798" has thrown away the only record of the two.
- **A `replace` that resolved nothing is a 409 and deletes nothing.** The refusal is about
  the state it would leave behind, not about the request. Shown verbatim.

### 2.1 The gap: nothing equips

`Artifact.build_id` exists on the model and in `ArtifactRead`, and **no endpoint sets it**.
So a user could import 800 artifacts and attach none of them to a build. `uq_artifacts_build_slot`
already enforces one piece per slot per build, so the rule exists; the route does not.

This is A.1, and it gates both the build page's artifact panel and — later — the optimizer,
which has to be able to write its chosen five somewhere.

## 3. Approach

### 3.1 Equipping is a write on the artifact, not on the build (A.1)

`PATCH /artifacts/{id}` with `build_id`. The alternative — five slots on the build — is the
shape the model already rejected: *"a piece is equipped by at most one build, unequipping must
not delete it, and the alternative is five nullable FKs plus a constraint that they are
distinct."*

Refusals, in the discipline T.1 established:

- a build that is not the caller's → the same "no build of yours" answer the team check gives,
  because confirming it exists would disclose that it does;
- a slot already filled on that build → **422 naming the piece that holds it**, not a silent
  swap. Swapping is a reasonable thing to want and a terrible thing to do without being asked:
  the displaced piece is still equipped somewhere in the user's head.

### 3.2 The inventory page (A.2, A.3)

A list of every piece, filtered by slot and set, with the import form. Reuses `allPages`
(#66) and `catalogueList`'s error discipline. The import result is rendered in full: inserted,
deleted, and **every rejection with its reason**.

### 3.3 Scoring lives beside the piece (A.5, A.6)

G.9, unblocked since `artifact_roll_schedule.json` was derived, and now with a consumer.

**A score is a claim, and this repo's rule is that a number must be able to explain itself.**
So the API returns the parts, not just a figure: how many upgrades remain, which substats
could roll, and what the piece would be worth if they all landed on the ones a build cares
about. A single number with no derivation is the "confident number computed for something
else" failure with better presentation.

**Open question OQ-A1 — what is "worth"?** Upgrade *potential* is knowable from the schedule
alone: a +0 five-star has five rolls left, a +20 has none. Upgrade *value* needs weights —
which substats matter — and those come from a build. Answered in §6.

### 3.4 The build's artifact panel (A.4)

Five slots on the build editor, each showing the equipped piece or offering the inventory
filtered to that slot. This is where equipping is actually used, and where the optimizer will
later write its result.

## 4. Testing strategy

| task | what proves it |
|---|---|
| A.1 | equipping, unequipping, a filled slot refused by name, a stranger's build refused; each CAUGHT under `scripts.inject` |
| A.2 | a failed load surfaced, not rendered as "no artifacts"; every rejection shown; `mode` never defaulted |
| A.3 | filters are the server's, and `total` matches what the filter returned |
| A.5 | the schedule drives the count — a 4-star and a 5-star at the same level differ; a maxed piece scores zero potential |
| A.6 | the parts are shown, and a score with no build shows potential rather than a fabricated value |

Standing rules apply: a skipped check blocks, the agent runs the harness, and a surviving
mutation means the test is wrong until proven otherwise — which was true all three times it
happened in the last chunk.

## 5. Non-goals

- **No manual artifact entry** (owner decision). GOOD is what the ecosystem exports and
  hand-typed substats are the most error-prone data in the app.
- **No editing of imported pieces.** Re-import instead; `mode` exists for exactly that.
- **No optimizer UI.** Next chunk. This one exists to give it something to search.
- **No artifact art.** `frontend/public/icons/` was stripped in the fork and nothing has
  replaced it.

## 6. Open questions

- **OQ-A1 — what does an artifact score mean without a build?** *Answered: potential, not
  value.* With no build there are no weights, and inventing them would produce a ranking that
  looks authoritative and answers nobody's question. So the inventory shows **rolls remaining
  and which substats can still grow**, which is knowable from the schedule alone; a
  build-relative score arrives with the optimizer, where the weights come from.
- **OQ-A2 — does equipping swap or refuse?** *Answered: refuse, naming the holder.* Silently
  displacing a piece is an edit the user did not ask for, and the displaced piece is still
  equipped in their head.
- **OQ-A3 — does the inventory page show equipped pieces?** *Answered: yes, marked.* Hiding
  them makes the inventory disagree with `total` and hides why a slot cannot be filled. The
  `equipped` filter already exists on `GET /artifacts` for the cases where it matters.
