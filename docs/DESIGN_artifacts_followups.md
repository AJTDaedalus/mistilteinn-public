# DESIGN — Artifacts follow-ups (after the upgrade estimator)

*Planner pass, 2026-10-25. Four pieces of work left open by `DESIGN_upgrade_estimator.md` and the
#344 audit. Owner, 2026-10-25: "develop robust implementation plans for all four, then begin on
#1." The tasks are in `docs/TASKS_artifacts_followups.md`.*

| part | what | state |
|---|---|---|
| **F1** | Merge the build-state setup repeated across four `ArtifactRankingService` methods, with one refusal rule | **in progress** |
| **F2** | One build/rotation picker across Optimize, Rank and Upgrade | planned; two owner rulings recommended below (OQ-F1, OQ-F2) |
| **F3** | Reshape (Dust) and Elixir as alternative columns on Upgrade (OQ-U4) | planned; **unblocked by computing a range, not by waiting for research** (§3.3) |
| **F4** | Strongbox crafts as a second output on Upgrade (`DESIGN_upgrade_estimator.md` §4.4) | planned; one owner ruling (OQ-F4) |

Recommended order: F1 → F4 → F2 → F3. F1 fixes a live inconsistency. F4 is the smallest feature
and the only one that turns an existing "never" into a number. F2 is UI-only. F3 is the largest
and the most model-dependent.

## Branch policy

- One branch per part, each off `dev`, each merged by its own PR:
  `refactor/ranking-setup` (F1), `feat/upgrade-strongbox` (F4), `feat/artifacts-shared-picker`
  (F2), `feat/upgrade-reshape-elixir` (F3).
- **No direct commits to `dev`.** A merge to `dev` deploys. Each PR needs
  `cd backend && python -m scripts.ci_local` green on the exact PR head (CLAUDE.md §Gate
  discipline rule 3); use `--clean` if a part changes dependencies (none is expected to).
- This planning doc and the TASKS file are committed on `refactor/ranking-setup`, because F1
  is the first branch to merge.
- Task 0 of each part in the TASKS file is the branch-setup gate.

---

## 1. F1 — one build-state setup, one refusal rule

### 1.1 What is there

`frontend/src/app/pages/artifacts/artifact-ranking.service.ts` has four places that build the
same state before scoring anything (line numbers at `bbb04af`):

| method | line | behind |
|---|---|---|
| `rank` | 293 | Rank tab's list |
| `outcomesFor` | 489 | one card's outcome distribution |
| `upgradeEstimate` | 599 | Upgrade tab |
| `diveContext` | 861 | Optimal build (`deepDive`) and the background sweep (`sweepBestBuilds`) |

Each does the same steps: load the inventory snapshot, check the draw model, read the worn
pieces, work out the worn 4-piece, call `calibrateAll` with `targetsFor(...)`, choose the recipe
the build is in today, build the five equipped stat pools, and evaluate the baseline.

### 1.2 The defect the duplication has produced

When the build's **own** 4-piece recipe is missing (gcsim failed on it, or `targetsFor` skipped
it because the catalogue has no entry for the set):

- `rank` and `upgradeEstimate` **refuse**. Rank's comment: falling back to `noFourPiece` "would
  understate every piece, and not uniformly."
- `outcomesFor` (`?? noFourPiece`, line 522) and `diveContext` (line 894) **fall back silently**.
  The outcome chart, Optimal build and the sweep then score a build that has lost its own set
  bonus, and nothing on screen says so.

Smaller differences, none user-visible today:

- `wornIds`: `rank` and `upgradeEstimate` take it from `worn.items`; `diveContext` takes it from
  the slot map's values. These are the same unless two worn pieces share a slot, which the
  equip endpoint prevents.
- The `noFourPiece` refusal has three different wordings, and `upgradeEstimate` does not check
  `noFourPiece` separately at all; it reaches it only through the worn-recipe check.
- Only `upgradeEstimate` passes `shouldCancel` to `calibrateAll`.

### 1.3 Design

One private method, `buildState(request, options)`, returning everything the four share:

```ts
interface BuildState {
  snapshot: InventorySnapshot;
  model: DrawModel;
  byId: Map<string, InventoryArtifact>;
  wornBySlot: Map<string, string>;
  wornIds: Set<string>;
  counts: Record<number, number>;       // setCountsOf(wornBySlot, byId)
  wornFour: number | null;
  calibration: CalibrationResult;
  recipes: { noFourPiece: Recipe; byFourPieceSet: Map<number, Recipe>; byPair: Map<string, Recipe> };
  current: Recipe;                       // the recipe the build is in today
  equipped: StatPool[];                  // SLOTS order; {} for an empty slot
  baseline: number;                      // evaluateRecipe(current, candidateStatsFrom(equipped))
}

private async buildState(
  request: RankingRequest,
  options?: {
    /** Runs on the snapshot before calibrating, so a cheap refusal never waits on gcsim. */
    check?: (snapshot: InventorySnapshot) => void;
    shouldCancel?: () => boolean;
  },
): Promise<BuildState>
```

**One refusal rule, Rank's**, applied in one place:

1. No draw model → refuse (Rank's wording).
2. `options.check(snapshot)` → caller-specific refusals: Upgrade's missing `fresh_drop` and
   5★ ladders; `outcomesFor`'s and `deepDive`'s "not in the inventory".
3. `noFourPiece` missing → refuse.
4. The build wears a 4-piece whose recipe is missing → refuse, naming the set id. **This is the
   behaviour change:** the outcome chart, Optimal build and the sweep now refuse here instead of
   understating.

`check` exists because the snapshot is fetched inside the helper (`OptimizeService.inventory()`
is a network call with no cache), and today `outcomesFor` and `upgradeEstimate` refuse before
calibrating. A refusal that waited six seconds for gcsim would be a regression.

`diveContext` stays as a thin wrapper that adds `all` (the searchable candidates) to the
`BuildState`. Its callers keep reading `current` and `before`; `before` becomes `baseline`.

`shouldCancel` is passed through **only where it is today** (Upgrade). Passing it from
`outcomesFor` would turn a quiet abort into a `CalibrationCancelled` the page does not catch.
That is a separate decision and stays out of a refactor.

**What does not change:** every number. Each method keeps its own scoring code, which is the
part that differs (Rank's swap recipes, the outcome walk, the fresh-drop estimate, the pinned
search). Only the setup moves.

### 1.4 Tests

There is no `artifact-ranking.service.spec.ts` today, and `upgrade.spec.ts` stubs the whole
service. A new spec with stubbed `OptimizeService`, `ArtifactsService` and
`RecipeOptimizeService` (synthetic recipes from `sim/upgrade-fixtures.ts`):

- **Characterisation, written before the refactor and unchanged after it:** for a fixed snapshot
  and a fixed worn set, `rank`'s rows and baseline, `outcomesFor`'s distribution, and
  `upgradeEstimate`'s rows equal values captured from the pre-refactor code; `deepDive`'s
  `before`/`after`/`gain` are pinned the same way. This is the before-and-after check, automated.
- **The refusal, all four:** a build wearing four pieces of a set whose recipe the stub does not
  return. All four methods must reject with the same message. Before the refactor this test
  fails for `outcomesFor`, `deepDive` and `sweepBestBuilds`. Committed red first, then turned
  green.
- **The cheap refusals still come first:** with `fresh_drop` missing (Upgrade) or an unknown
  artifact id (outcomes, dive), `calibrateAll` is never called.
- **Planted faults** (`scripts.inject`, or by hand if the target is ambiguous): drop step 4,
  restore the `?? noFourPiece` fallback in the wrapper, and evaluate the baseline under
  `noFourPiece`. Each must be caught by the spec.
- **Driven once in the browser** on the owner's Skirk build: Rank, an outcome card, Optimal build
  and Upgrade show the same figures before and after.

---

## 2. F2 — one picker for Optimize, Rank and Upgrade

### 2.1 What is there

| | Optimize (`pages/optimize/optimize.ts`) | Rank / Upgrade (`ArtifactsContextService`) |
|---|---|---|
| fields | team → rotation → build | rotation → build (team taken from the rotation) |
| rotation scope | rotations of the chosen team; all when "Any team" | all rotations |
| build scope | builds the team fields; **all builds when "Any team"** | builds the rotation's team fields; **none without a rotation** |
| survives a reload | **yes** — `remembered.ts`, `localStorage` under `mistilteinn:optimize:` | no |
| survives a tab switch | n/a | yes (root singleton) |
| account change | `recallAmong` drops ids not in the loaded list | `reset()` on `auth.token()` |
| side effects of choosing a build | `selectBuild` clears results, findings and hit list; restores per-character selections | none |

Optimize's **single-hit objective needs no rotation**. Whatever the shared picker becomes, it must
allow a build with no rotation, which the current context's `buildChoices` (empty without a
rotation) does not.

### 2.2 Design

Grow `ArtifactsContextService` into the one picker, rather than teaching Optimize's 2,267-line
component to share its own:

- **Fields:** `teamId`, `rotationId`, `buildId`, plus Optimize's current scoping rules (§2.1, left
  column). Those rules are already the stricter, tested ones, and they reduce to the context's
  current behaviour when a rotation is chosen.
- **`buildChoices`:** the team's builds when a team or a rotation implies one; otherwise all
  builds. Labels stay `shared/team-scope.buildOptions`'s.
- **`readyFor(need: 'rotation' | 'build')`** replaces `ready`. Rank and Upgrade ask for
  `'rotation'`; Optimize's hit objective asks for `'build'`.
- **Memory (OQ-F1):** persist the three ids through `remembered.ts` under its existing keys, so
  Optimize users keep what they had. Every recalled id is checked against the loaded list
  (`recallAmong`) before it is used. The account-change reset also clears what was remembered.
- **Optimize's side effects stay in Optimize:** an `effect` on `context.buildId()` runs its
  existing `selectBuild` body. Optimize's own `buildId`, `teamId` and `rotationId` signals are
  deleted, not mirrored. Two copies of one choice is what this part removes.
- **One component, `shared/artifacts-context-bar`**, shown on Optimize, Rank and Upgrade, not on
  Inventory. Rank's and Upgrade's pickers and Optimize's three comboboxes are replaced by it.
  Upgrade's existing `[selected]`-per-option pattern is kept (memory: a `select [value]` binding
  runs before `@for`).

### 2.3 Owner rulings needed

| | question | recommendation |
|---|---|---|
| **OQ-F1** | Should all three tabs remember the choice across a reload, as Optimize does today? | **Yes.** You asked for it on Optimize, and a tab that forgets while its sibling remembers would read as a bug. |
| **OQ-F2** | Keep the team picker, or derive the team from the rotation as Rank does? | **Keep it, as a filter.** The hit objective has no rotation to derive a team from, and "Any team" is how Optimize reaches every build today. |

If the owner does not rule, the recommendations are the defaults, and the PR says so.

### 2.4 Tests

- The context's spec grows to cover: build choices with no rotation; team narrowing; recall
  validated against loaded lists; an account change clearing memory; a remembered id from
  another account ignored.
- `optimize.spec.ts` (2,420 lines) is the risk. Its picker tests are rewritten against the
  context, and **a choice made on Optimize must clear the previous build's result**, the defect
  `selectBuild`'s comments record. Pinned by a test that fails if the effect is removed.
- `remembered.spec.ts` keeps passing unchanged: the storage format does not change.
- Driven: choose on Optimize, switch to Rank and Upgrade, reload, sign out and in. Checked with a
  real typed selection, not only `fill()` (CLAUDE.md, planner materials entry).

---

## 3. F3 — Reshape and Elixir as alternative columns (OQ-U4)

### 3.1 What the player is choosing between

For a slot, Upgrade today answers "resin until a domain drop beats this piece by `θ`". Two other
routes exist, each priced in its own currency:

- **Reshape** (Dust of Enlightenment): re-allocates **the current piece's** enhancement rolls,
  with at least 2 on two chosen lines (Advanced ≥ 3, Decreed ≥ 4, from pity). The player keeps
  whichever is better, so a reshape can never make the piece worse. Dust cost 1/1/2/2/2 by slot.
  Research: `RESEARCH_artifact_drop_model.md` §5.7, and the follow-up's Item 2.
- **Definition** (Sanctifying Elixir): a new piece with chosen set, slot, main stat and two
  chosen lines, with at least 2 rolls shared between them. Elixir cost 1/1/2/4/3 by slot, and
  at most 2 per set per version. §5.2.

The columns: "**1 Reshape: P(≥θ better) = …**" and "**1 Elixir: P = …**, about N Elixirs on
average".

### 3.2 What is unsettled, and why it no longer blocks

**Floor or resample.** "At least 2 enhancements will be allocated" has two readings:

- **Floor** (GO's): allocate uniformly, then move any shortfall onto the chosen pair.
- **Resample**: redraw until the guarantee holds, which is conditioning on it.

Measured against the one large simulation found (a Miyoushe script, 10⁶ runs, mechanism not
stated; follow-up Item 2), for two valid lines on a 3-line piece:

| P(hits on the pair) | 2 | 3 | 4 |
|---|---|---|---|
| floor | 68.75% | 25.0% | 6.25% |
| script | 56.2% | 37.6% | 6.2% |
| resample | 54.5% | 36.4% | 9.1% |

For the upper tails, which are what an upgrade needs, the script lies **between** the two
readings: P(≥3) is 31.25 / 43.8 / 45.5, and P(≥4) is 6.25 / 6.23 / 9.1. The 6.23 is below the
floor by 0.02 points, inside the script's own sampling error (σ ≈ 0.024 points at 10⁶ runs). The resample distribution
stochastically dominates the floor one, because the floor puts all the missing mass on the
minimum and the resample spreads it over every allowed count.

**So compute both and show the range.** "1 Reshape: 18–24% chance" is honest under either
reading and under the script, and it needs no research to ship. If a measurement later settles
the mechanism, the range collapses to a point and nothing else changes.

**The caveat to test, not assume:** P(beat) is monotone in the pair's hit count only when the
chosen pair is worth more than the other lines. The column always chooses the pair that
maximises P(beat), which makes that likely, but it is not guaranteed. So the column reports
`min` and `max` of the two computed values, not "floor = lower bound". A spec pins that the
script's published rows fall inside the range, to within its sampling error, for the cases above.

**Initial values.** Reshape keeps each line's initial value (official wording "enhancements
reallocated"; GO's `dustReshape`; the Hupu and Icy Veins notes) and the 8-draw budget of a
3-line-origin piece. We do not store initial values, but `services/substat_rolls.resolve_artifact`
decomposes each line into roll tiers (85% of lines decompose uniquely). Because an initial value
and an upgrade roll are drawn from the same tier distribution, **given a line's multiset of
tiers, the initial is equally likely to be any of them**. The model averages over that choice.
A line with an ambiguous decomposition is averaged over its decompositions, weighted the way
`artifact_potential` already weights them. If that weighting does not exist, the line is
refused and the column says why.

**Elixir pieces' line count.** No source settles 20% or 34% 4-line (GO assumes 34%, uncited).
Bracket it the same way: compute both and widen the range.

### 3.3 Design

- **`sim/reshape.ts`:** `reshapeBeatProbability(piece, pair, guarantee, evaluate, threshold,
  mechanism)`. It enumerates the allocations of the piece's upgrade budget across its four lines
  under the chosen mechanism, tiers per roll from the 5★ ladder, and initial values per the
  exchangeability argument. Small: at most 5 upgrades, so ≤ 4⁵ tier tuples per allocation.
- **`sim/definition.ts`:** P(beat) for an Elixir piece with a given main stat and pair. It reuses
  `fresh-drop.ts`'s cells with the two lines forced present and the guarantee applied to the
  multinomial. The column takes the best main and pair: up to 5 mains × C(8,2) = 28 pairs, each
  an exact enumeration. **Measure before designing around it** (Task F3.2): if a worst slot
  exceeds the 12 ms yield budget's tolerance, it runs as generator steps like
  `slotBeatProbabilityAsync`.
- **Oracle:** extend `fresh-drop-sampler.ts`'s style with a literal reshape sampler (both
  mechanisms) and a literal definition sampler, sharing no code with the enumerations.
- **Page:** two columns, collapsed by default behind a "Show alternatives" toggle so the main
  table stays readable at phone width. Reshape shows the three pity tiers as one cell ("2+: a–b%
  · 3+: … · 4+: …"). Each range carries a footnote naming the two readings.
- **Not in scope:** reshaping a piece other than the worn one, and planning a sequence of
  reshapes with pity carry-over. Per-version supply (Dust ~3.5–6.5, Elixir ~3.8–4.8) is shown
  as context text, not computed into anything.

### 3.4 Owner rulings needed

| | question | recommendation |
|---|---|---|
| **OQ-F3** | Show a range under both readings, or pick GO's floor and label it assumed? | **The range.** A single assumed number is the confident wrong number the original DESIGN refused. |
| **OQ-U4 (narrowed)** | Reshape first, then Elixir, as two PRs? | **Yes.** Reshape needs no new drop model; Elixir needs the forced-line enumeration. |

---

## 4. F4 — Strongbox crafts

### 4.1 Mechanics (`RESEARCH_artifact_drop_model.md` §5.1)

Three 5★ artifacts make one Strongbox craft: a random piece from a **set you choose**, with
**34% 4-line** against a domain's 20%. Slot and main-stat odds are unverified and assumed to match
domains, as GO assumes. **Gladiator's Finale and Wanderer's Troupe are in the Strongbox**, so a
slot that Upgrade now reports as "never" (`sets_without_domain_five_star.boss_only`) gets a
finite answer. That is the strongest reason to build this.

### 4.2 Design: two figures, both labelled

1. **"Strongbox crafts until an upgrade"**, the owner's framing ("how many strongbox runs it
   would take"). Per craft, `q_box = σ_box · ⅕ · Σ P(main) · P(beat | main)` with the 34/66
   line split. `σ_box` is **1**, because you choose the set: an off-piece or spare can take the
   best-scoring set, which v1 approximates as "a set that keeps the bonus", the same thing the
   domain estimate assumes. Quantiles are geometric, as in `resin-to-upgrade.ts`, in crafts.
   The page also shows the feedstock: **3 five-stars per craft, ≈ 3 / 1.065 claims ≈ 56 resin
   of domain drops**, labelled "if every input came from domain runs".
2. **"With recycling"** (`DESIGN_upgrade_estimator.md` §4.4): a toggle, off by default, that
   folds the Strongbox into the resin figure. If every non-upgrade is recycled, each domain 5★
   yields 1 + ⅓ + ⅑ + … = 1.5 pieces, the extra half from the chosen set, so
   `q_eff ≈ q_domain + ½ · q_box`. That approximation is accurate for small q, which is the case
   the feature exists for. The page says which figure it shows.

**Line count is nearly free to change, with one trap.** In `upgrade-estimate.ts` the share enters
only through `liveCountTable`, which weights each question (main stat plus live roll counts).
The expensive part, `cache.answers`, is keyed by the question and is share-independent, so a
34/66 pass reuses every answer the domain pass computed. **But `cache.cellQuestions` stores
`factor`, which already includes the share.** Sharing one `BeatCache` between a 0.20 pass and a
0.34 pass would silently give the Strongbox figure the domain's split. Task F4.2 either keys
`cellQuestions` by share or splits it off, and a spec runs both passes on one cache and checks
each against its own uncached result.

### 4.3 Data

`app/data/external/artifact_draw_model.json` gains a `strongbox` block, validated by
`domain_drop_model()`'s sibling, with a source on every entry:

- `four_line_share: 0.34` (KQM Artifacts Guide table; wiki).
- `pieces_per_craft: 3` (wiki `Artifact_Strongbox`).
- `slot_and_main_stat: "assumed equal to domain"` (ASSUMED, GO `freshArtifact`).
- `offered_sets`: see OQ-F4.

`FreshDropInputs` gains the matching optional `strongbox` field. The OpenAPI diff must be purely
additive (memory: a duplicate Pydantic name renames both).

### 4.4 Owner ruling needed

| | question | recommendation |
|---|---|---|
| **OQ-F4** (was OQ-U5) | Which sets does the Strongbox offer? Curate a list per patch, or allow all sets with a label? | **Allow all, labelled "assumes your set is offered"**, plus a short curated **exclusion** list for sets known to be absent (the newest domain sets, which join about a year after release). An exclusion list goes stale towards "allowed", which is the safer direction for an estimate that is labelled. |

### 4.5 Tests

- The closed form against the literal sampler with `fourLineShare: 0.34` (the sampler already
  takes the share as a parameter).
- `setFactor`'s Strongbox sibling: 1 for every slot, including domainless sets.
- A slot wearing Gladiator's Finale: domain "never", Strongbox finite.
- The recycling toggle: `q_eff` within 1% of a literal renewal-process simulation for q ≤ 0.05;
  outside that, the page labels the approximation.
- Data validation refuses a `strongbox` block missing a source.

---

## 5. Open questions summary

| id | part | question | default if unanswered |
|---|---|---|---|
| OQ-F1 | F2 | Remember the picker across reloads on all tabs? | yes |
| OQ-F2 | F2 | Keep the team picker as a filter? | yes |
| OQ-F3 | F3 | Range under both reshape readings, or GO's floor? | range |
| OQ-U4 | F3 | Reshape first, Elixir second? | yes |
| OQ-F4 | F4 | Strongbox sets: all with label plus exclusions, or a curated list? | all, labelled, with exclusions |
