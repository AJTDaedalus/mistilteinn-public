# DESIGN — the upgrade estimator: "how much resin until I beat this piece?"

**Status: draft, 2026-10-24. Feasibility and plan only; nothing built.** Owner request:
*"come up with a draft 'upgrade estimator' that calculates the distribution of how much resin it
will cost to get an upgrade for each piece of an artifact set on a character. Like the optimizer,
but theoretically 'how long would it take to get a better artifact than this?' for each slot."*
The goal is feasibility and an implementation plan, not code. `docs/TASKS_upgrade_estimator.md`
is the task list. **§9.1 records the owner's 2026-10-24 rulings**; OQ-U4 and OQ-U6 remain open.

**Evidence:** `docs/RESEARCH_artifact_drop_model.md` (2026-10-24) has every public source this
document relies on: drop rates, line counts, weights, tiers, the newer acquisition routes, and the
two community methods. Nothing below repeats its citations. Where a number here comes from there,
the section number is given as R§n.

**Branch policy.** Work happens on `feat/upgrade-estimator`, off `dev`. **No direct commits to
`dev`**: `dev` is updated only by PR, and a merge deploys. One branch, no parallel tracks. Task 0
of the TASKS file is the branch-setup gate. This draft and its research are on
`docs/upgrade-estimator`, which Task 0 renames rather than merges, so the evidence travels with
the feature. That is the precedent `DESIGN_wish_planner.md` set.

---

## 1. Verdict: feasible, and mostly assembly

**Yes, it is feasible. About two thirds of it is already built and tested.** The estimator asks
the artifact ranker's question with the probability model pointed at a piece that does not exist
yet:

| needed | exists? | where |
|---|---|---|
| the damage of a build with a given piece in one slot | **yes**, ~12 µs per evaluation | `sim/artifact-score.ts:scoreForSlot` over `sim/recipe-eval.ts` |
| the substat draw (weights, without replacement, excluding the main stat) | **yes** | `artifact_draw_model.json`, `sim/artifact-projection.ts:eligibleNewLines`, `sim/artifact-distribution.ts:lineOutcomes` |
| main-stat probabilities per slot | **yes**, already shipped, same secondary source | `artifact_draw_model.json:main_stat_probabilities` |
| roll-count splits and tier-sum distributions | **yes**, exact | `sim/artifact-distribution.ts:rollSplits`, `tierSums`, `rollTotals` |
| a Gaussian fast pass with covariance | **yes**, for an existing piece | `sim/artifact-estimate.ts` |
| exact enumeration that yields and cancels | **yes**, for an existing piece | `sim/artifact-outcome.ts:outcomeDistributionAsync` |
| "the damage to beat" | **yes**, `OutcomeDistribution.reference` (the owner's 2026-09-06 correction) | `sim/artifact-outcome.ts` |
| **a fresh-drop prior** (set → slot → main → 3 or 4 lines → substats → rolls) | **no** | new, §3 |
| **drop counts per run and the 80/20 line split** | **no** | new data, R§1.2, R§4.1 |
| **domain → its two sets** | **no**, but derivable from the pinned AnimeGameData the planner already reads | new snapshot field, §6 |
| **probability per drop → resin distribution** | **no**, but closed form | new, §4 |

**No new engine is involved and gcsim never enters the loop.** It is the ranker's evaluator
(OQ-A1, `DECISIONS.md` §22) asked a different question. §4 of `DESIGN_artifact_ranking.md` is
the guard: anything that calls gcsim *inside* the estimate has left the design.

**The one genuinely hard part is the tail.** A good piece's beat-probability per drop is often
10⁻³ to 10⁻⁵. Those are exactly the pieces people ask about, and they are where the cheap
Gaussian is least trustworthy. §5 is about that, and Task 1 is a measurement, not a build.

## 2. The question, stated precisely

For a build `B` with a calibrated recipe, and one of its five slots `s`:

> How many resin until a **freshly dropped 5★**, levelled to **+20** and placed in `s` with the
> other four pieces unchanged, gives `damage > reference · (1 + θ)`?

Every word in that sentence was a choice:

- **"fresh drop"**: a domain drop by default. §7 covers the other sources.
- **"+20"**: the piece's outcome once fully levelled. This matches issue #291's ranker number
  ("the probability that, if fully levelled, that artifact provides an upgrade").
- **"other four unchanged"**: a single-slot substitution. This makes the estimate a **lower
  bound on the true upgrade chance**, for the same reason the ranker's column is
  (`DESIGN_artifact_ranking.md` §8.1). A re-search could move the other four, and it never does
  worse. The resin figure is therefore an **upper bound**, and the page must say so.
- **"reference"**: the build's damage today, with the current piece as it stands. A +12 piece
  is compared as a +12. That is OQ-U3.
- **θ = 1%** (owner, 2026-10-24): a minimum meaningful gain. At θ = 0, a drop that adds 0.01%
  counts as "better", and for a weak slot the answer becomes "one run" for a reason nobody
  cares about. Editable, defaulting to 1%.
- **the set constraint**: §3.1.

**The output is a distribution over resin**, per slot, plus one "any slot" line per domain (§4.3).
It is not a point estimate. That follows OQ-A4 and the wish planner's population-not-sample
argument (`DESIGN_wish_planner.md` §9.7), and here it costs nothing extra (§4).

## 3. The fresh-drop prior

Per R§§1–4, one domain 5★ is generated as:

```
set   ~ ½ / ½ over the domain's two sets                 R§1.3
slot  ~ uniform 1/5                                       R§2
main  ~ main_stat_probabilities[slot]                     R§3 (already shipped)
lines ~ 3 w.p. 0.80, 4 w.p. 0.20   (domain)               R§4.1
subs  ~ weighted draw without replacement, excl. main     R§4.2
rolls ~ each line 1 initial roll; then 5 upgrades;
        a 3-liner's first upgrade adds the 4th line (drawn by the same rule),
        the rest pick a line uniformly                    R§4.3
tier  ~ uniform {0.7, 0.8, 0.9, 1.0} × max, every roll    R§4.4
```

**One simplification falls out of this and halves the state space.** A 3-liner's fourth line is
drawn by the same weighted-without-replacement rule as the first three. So the **set of four
substats has the same distribution whether the piece started with 3 lines or 4**. The line count
changes only the roll budget:

- **4-line:** each line gets `1 + Multinomial(5, ¼)` rolls, 9 in total.
- **3-line:** the three originals get `1 + Multinomial(4, ¼)` each; the added line gets its 1
  roll plus its share of the same 4. That is `1 + Multinomial(4, ¼)` for every line, 8 rolls in
  total.

So the prior is a **mixture over (main stat, unordered 4-subset)**, weighted exactly by
`substatProb` (GO's recursion, already ported as `lineOutcomes`). Each cell then has two
roll-budget variants, weighted 0.8 and 0.2. That is at most `C(10,4) = 210` subsets per main
stat (126 when the main is itself a substat type), and `rollSplits` already enumerates
`Multinomial(n, ¼)`.

**GO has this function and does not use it.** `freshArtifact(sets, p3sub, rarity)` in
`libs/gi/upopt/src/upOpt.ts` builds exactly this mixture, and R§7 found no caller in the current
UI. It is a **reference implementation to crossvalidate against** (Task 3), the same role
`substatProb` played for A.13. It is not code to port wholesale. The repo's port is already the
leaf machinery.

### 3.1 Which sets count, without recalibrating

A replacement is **admissible** for slot `s` if putting a piece of set `X` there keeps every set
bonus the build currently activates. Computed generically from the build's set counts, that
means:

- **a slot inside a 4-piece**: only that set;
- **a slot inside a 2-piece** (2+2+1, 2+2): only that set;
- **the off-piece** (4+1, 2+2+1): **any set**. In every common layout an off-piece cannot
  complete a new bonus without breaking one.

The useful consequence: **an admissible replacement never changes the active set bonuses, so the
recipe already calibrated for the build is the right one**, and no on-demand calibration (OQ-A8)
is needed. A replacement that would *switch* the build to a different 4-piece is a re-search,
not a slot upgrade, and is out of scope (§8).

An all-different "rainbow" build is the exception: there, a piece could *create* a 2-piece. v1
treats every set as admissible and ignores the new bonus, which keeps it a lower bound. This is
written down so it is not mistaken for exactness.

## 4. Probability per drop → resin, in closed form

### 4.1 Per drop

For slot `s` and domain `D`:

```
q(s, D) = Σ_{X ∈ sets(D), admissible(s, X)} ½ · ⅕ · Σ_main P(main | slot)
                                                · P(beat | s, main)
```

`P(beat | s, main)` does not depend on `X`, because the recipe is unchanged (§3.1). So it is
computed **once per (slot, main stat)** and reused across every domain. That matters for §4.3.

### 4.2 Per run, then resin

A run yields `N₅` 5★ pieces, each independent. R§1.2 gives a mean of 1.065 (measured 1.07,
n = 14,088) and a guarantee of at least one. **The shape beyond the mean is unverified**
(R§8). v1 takes `N₅ = 1 + Bernoulli(0.065)`, the only shape consistent with both the guarantee
and the mean that adds nothing, and labels it as an assumption. Then:

```
r(s, D) = 1 − E[(1 − q)^N₅] = 1 − (1 − q)(1 − 0.065·q)
runs    ~ Geometric(r)                  (support 1, 2, …)
resin   = 20 · runs                     R§1.1: every claim option is 20 per reward set since Luna I
```

**Every quantile is a formula, not a simulation.** `runs_p = ⌈ln(1 − p) / ln(1 − r)⌉`. The
histogram is the geometric PMF. The mean is `20 / r`. **The Luna I change matters here:** the
"condensed = 40 resin for 2 drops" rule that much community arithmetic still uses is out of date
(R§1.1), and per reward set the cost is now flat.

**What to report, per slot:** median, mean, the P25–P75 band and P90 in resin. The same in
**days of resin regeneration**, which is how a player thinks about it. The daily figure is a
curated constant to cite in Task 2, not a number to write from memory. Also report the per-drop
`q`, because "1 in 2,300 drops" is a sentence a reader can check against their own experience,
and a resin number alone is not.

**`q = 0` is a real answer and must say so.** A +20 piece no fresh drop can beat (for example a
near-perfect CRIT circlet) has an infinite expected cost. Rendering that as "∞" or a huge
number would be wrong. It is *"no drop of this kind can beat this piece"*, and branch-and-bound
(§5) proves it exactly rather than estimating it.

### 4.3 The view a player acts on: "farm this domain"

A player does not farm a slot; they farm a domain, and every drop lands somewhere. So beside the
per-slot table, report per domain:

```
q_any(D) = Σ_s q(s, D)       slots are mutually exclusive per drop, so the sum is exact
```

pushed through the same geometric. **"Resin until any of your five pieces improves"**, ranked
across domains. Because `P(beat | s, main)` is shared (§4.1), ranking every domain in the game
costs only the per-slot work plus a table lookup.

### 4.4 Later: Strongbox recycling — **deferred** (owner, 2026-10-24)

*Not in v1: standard domain runs only. Kept because the owner wants it later, framed as "how
many Strongbox crafts would it take", which is a different output from a blended rate.*


Unwanted 5★ pieces go into the Strongbox at 3:1 for a chosen set, with better line odds (66/34,
R§5.1). Under a policy that recycles **every** non-upgrade, each domain 5★ yields on average
`1 + ⅓ + ⅑ + … = 1.5` pieces, the extras from a chosen set. To first order, the per-drop success
becomes:

```
q_eff ≈ q_domain + ½ · q_box(chosen set)
```

where `q_box` uses the 34% 4-line split and the set of the player's choice. This is an
**approximation**: it treats a 3-for-1 renewal process as a smooth rate, and that is accurate
when `q` is small, which is the case the feature exists for. It is a toggle and off by default.
The page must say which it is showing. Strongbox slot and main-stat tables are unverified (R§5.1)
and assumed to match domains, as GO assumes.

## 5. Computing P(beat | slot, main): the one hard part

### 5.1 Cost, reasoned (measuring it is Task 1)

Per (slot, main stat): ≤ 210 subsets × 2 budgets × roll splits (35 or 56) × tier sums per line
(`3n + 1` distinct values for a line rolled `n` times). Fully exact, that is on the order of
10⁷ evaluations, or **minutes** at ~12 µs each. That is too slow for a page, so not as such.

### 5.2 Three reductions, each exact

1. **Branch and bound per cell.** For each (subset, budget, split), evaluate the cell's **best
   case** (every roll at the top tier) and **worst case**. If best ≤ threshold, the cell
   contributes 0. If worst > threshold, it contributes its full weight. Only straddling cells
   are enumerated. For a strong piece, nearly every subset without the stats that matter dies
   here, and that is how `q = 0` is *proved* (§4.2). This relies on **damage being monotone
   non-decreasing in every substat**. That is expected of the recipe, but **not verified**,
   least of all for ER through the energy ladder, which the client optimizer buckets in 5% steps
   (`RESEARCH_er_bucketing.md`). Task 1 tests monotonicity before anything relies on it. If ER is
   stepwise, bounding still holds, because a step function is still monotone. If anything is
   *non*-monotone, that stat is enumerated and never bounded.
2. **Dead-stat collapse.** A line whose stat has zero partial derivative in this recipe (flat
   DEF on an ATK scaler) affects only *how many* rolls the live lines get, never the damage. Its
   tier sum need not be enumerated. Live stats are usually two to four.
3. **Monotone frontier counting.** Within a straddling cell, the live stats' tier sums form a
   small grid on which damage is monotone. `P(f > t)` needs evaluations only along the
   **frontier**, by staircase walk, not over the full grid: about `O(m^(d−1))` instead of
   `O(m^d)`. With `d ≤ 4` and `m ≤ 19`, that turns thousands of evaluations per split into
   hundreds.

**The fast pass is the existing Gaussian, per cell.** `artifact-estimate.ts`'s delta method with
the multinomial covariance gives a whole-slot estimate in about 2,000 evaluations (~25 ms) and
sorts the slots while the exact pass runs. GO draws both and labels them *Estimated* and
*Exact*. Here too, the Gaussian must never be shown as the tail answer: a Gaussian's tail at
10⁻⁴ is a statement about the normal distribution, not about artifacts.

### 5.3 The oracle: a literal Monte Carlo, in tests only

There is no external oracle. GO's `freshArtifact` covers the prior, not this damage function,
and KQM's formula assumes every piece starts with 4 lines (R§7). So the verification is **a
second, deliberately naive implementation**: a sampler that *generates artifacts the way the game
does* (draw main, draw lines one at a time, roll, upgrade), scores them with the same evaluator,
and counts. It shares no code with the enumeration beyond the evaluator and the data file. The
exact `q` must fall inside the sampler's binomial confidence interval on fixtures chosen so that
`q` is large enough to sample (≥ 10⁻²). **It never runs on the page**: a Monte Carlo cannot
see 10⁻⁵, which is why the exact pass exists.

`scripts.inject` then plants a fault in each reduction (an off-by-one in a split, a wrong prune
direction, a dropped dead stat) and confirms the sampler test catches it. That follows the repo's
rule that a check must be shown it can fail
([[checks-that-can-only-return-one-answer]]).

### 5.4 Where it runs

In the browser, where the recipe and its calibration cache already live (`recipe-cache.ts`). If
Task 1 measures more than ~200 ms of main-thread time per slot, it moves to a **Web Worker**
rather than another round of yielding. `outcome.ts` already records that yielding between
branches has a floor (223 ms worst case), and five slots times many mains is more branches.

## 6. Data that has to land

| datum | source | form |
|---|---|---|
| 5★ per run, AR 45+ = 1.065; 4-line share 0.20 domain, 0.34 boss/Strongbox/Abyss | R§1.2, R§4.1: community tables plus GDGT measurement | extend `app/data/external/artifact_draw_model.json`, with a citation per entry and the `N₅` shape marked as assumed |
| resin per reward set = 20 | R§1.1 | the planner already prices domains at 20 (`planner_economy.json`); **read it, do not restate it** |
| domain → its two artifact sets | `DungeonExcelConfigData` + `RewardPreviewExcelConfigData` at the pinned AnimeGameData commit: the same tables `build_snapshot.py` already reads for talent domains | new derived field in the yuanshen snapshot; **refuse** on a domain whose preview names other than two 5★ sets |
| which sets the Strongbox offers | R§5.1: grows by patch, not in our data | v1: all sets, labelled. OQ-U5 |

**One trap is already known from the planner:** a reward preview publishes *which* items, and
for domains it published only part of *how many*. That is how talent books first priced at 4.6×
too pessimistic (`CLAUDE.md`, the two-roll model). So the snapshot takes **set membership only**
from the preview, and drop *counts* come from R§1.2, never from the preview's numbers.

## 7. Sources other than domains

| route | in v1? | why |
|---|---|---|
| domain | **yes** | the question |
| Strongbox recycling | **later**, §4.4 (owner: "may be nice later to know how many strongbox runs it would take") | its own output, not a toggle on the resin number |
| Stygian Onslaught outbreak (+1 5★ per 120 resin, 10 days a version) | **no** (owner, 2026-10-24) | time-boxed. Folding it into an average would misprice the rest of the version |
| Sanctifying Elixir (Definition) | **no**, OQ-U4 | not resin. It is a per-version budget, 2 per set per version, at a cost by slot. It is a **different question**: "how many Elixirs", not "how much resin". GO already models it (`elixirDefinition`) |
| Dust of Enlightenment (Reshape) | **no**, OQ-U4 | upgrades **the current piece**, not a new one, and is often the cheaper path. The guarantee's mechanism is unverified (floor or resample, R§5.7), and that changes the numbers |
| weekly/normal bosses, Abyss | no | sets are fixed or rotating, and runs are better spent elsewhere. They matter as Strongbox fodder, which §4.4 already abstracts |

**Elixir and Reshape belong in this feature eventually**, as a second column: *"or: 1 Reshape
(2 Dust) gives P = …"*. That is the comparison a player actually faces, and GO is the only tool
that offers it. It comes after the resin estimate, not inside it, and only once the reshape
mechanism is settled, because the wrong reading of a guarantee is a confident wrong number.

## 8. Non-goals

- **Not a re-search.** Moving the other four pieces is the ranker's pinned deep dive (A.12).
  This is the single-slot lower bound, labelled as one.
- **Not a farming optimizer.** It ranks domains for *this build*. It does not plan resin across
  a roster. That is a natural follow-up, since `q_any` sums across builds the same way it sums
  across slots, but only if the owner wants it.
- **Not the levelling cost.** A 5★ to +20 is 270,475 EXP, about 16–19 runs of fodder (R§6). The
  resin figure assumes you can level whatever drops and **says so**. An optimal-stopping policy
  (level to +4, look, decide) is real and is the GO-style extension, OQ-U2.
- **No 4★ pieces.** A 4★ cannot beat a 5★ in any slot worth asking about. Stated rather than
  computed.

## 9. Open questions for the owner

| | question | recommendation |
|---|---|---|
| **OQ-U1** | Minimum meaningful gain θ: "better" by any amount, or by at least *x*% damage? | **Default 1%, editable.** At 0 the answer for an already-good piece is dominated by trivial wins |
| **OQ-U2** | Include levelling cost (EXP fodder in resin terms) or not? | **Not in v1, said on the page.** It needs a stopping policy, which is its own design |
| **OQ-U3** | Compare against the current piece as it stands, or against its own expected +20? | **As it stands.** The other is the ranker's question, already on `/artifacts` |
| **OQ-U4** | Elixir and Reshape as alternative columns: in this feature, later, or never? | **Later, Reshape first**, after the guarantee mechanism is settled |
| **OQ-U5** | Strongbox: offer the toggle with "all sets available", or wait for a curated set list? | **Offer it, labelled.** The difference is a few sets per patch |
| **OQ-U6** | Where it lives: a column/panel on the build (per slot), a panel on `/optimize` beside the result, or a new page with the domain ranking? | **A panel on the build view**: slots as rows, a domain ranking under it. It needs a build plus a calibrated recipe, which those pages already have |
| **OQ-U7** | When the current piece is the off-piece, should the domain ranking prefer the domain the player is already farming for another slot? | **No special case.** `q_any` already credits a domain for every slot it feeds |

### 9.1 Answered, owner 2026-10-24

| | ruling |
|---|---|
| **OQ-U1** | **θ = 1%** — *"a meaningful barrier"* |
| **OQ-U2** | **No levelling cost.** *"This isn't about leveling cost but resin spent on artifact domain runs."* |
| **OQ-U5** | **Standard artifact domains only** — no Strongbox, no Stygian Onslaught in v1. Strongbox later, as "how many Strongbox crafts". |
| **OQ-U6** | **One `/artifacts` page with tabs** — Inventory · Optimize · Rank · Upgrade. §11. |

## 10. Risks

- **The secondary sources are the whole prior.** Every probability rests on community tables
  (R§0), and the owner's export already disagrees with the weight *ordering*
  (`RESEARCH_substat_draw_weights.md`), most plausibly through selection. The estimator inherits
  that caveat. It must ride on the page, not only in this doc.
- **Sensitivity to the tail.** A resin figure for `q ≈ 10⁻⁴` moves a lot with small changes in
  the weights. Task 6 runs a **sensitivity check** (perturb each weight ±1, report the spread),
  so the page can say how firm the number is rather than printing four significant figures of
  confidence it does not have.
- **Recipe staleness.** A recipe carries `meta.unstable` / `staleConversions`
  (`DESIGN_artifact_ranking.md` §8.6), and the estimate must carry them forward on every row,
  as the ranking does.

---

## 11. OQ-U6: one `/artifacts` page, a tab per question

**Owner, 2026-10-24:** the parent is **Artifacts**, not Optimize — *"make 'Search' 'Optimize'.
That's what everyone thinks when they hear optimize"* — with an **Inventory** tab for the raw
pieces. So:

| tab | route | question | lives today |
|---|---|---|---|
| **Inventory** | `/artifacts/inventory` | what do I own? import, filter, equip | `/inventory` |
| **Optimize** | `/artifacts/optimize` | which five pieces (and weapon) maximise this rotation? | `/optimize` |
| **Rank** | `/artifacts/rank` | what is each piece worth to this build, now and levelled? | Rank panel on `/inventory` (OQ-A7) |
| **Upgrade** | `/artifacts/upgrade` | how much domain resin until each slot improves by 1%? | new |

**Child routes, not in-page tabs**, so a tab is linkable and the back button works. **One context
bar** (build · rotation · recipe state with its `unstable`/`stale` flags) shared by Optimize,
Rank and Upgrade, and hidden on Inventory, which needs none. The calibration is paid once;
`recipe-cache.ts` already makes that true, the UI just stops asking twice.

**Redirects, not deletions:** `/inventory` → `/artifacts/inventory`, `/optimize` →
`/artifacts/optimize`, and bare `/artifacts` → `/artifacts/inventory`. `/artifacts` is today
itself a redirect *to* `/inventory` (`app.routes.ts`), so this reverses that pointer rather than
inventing a path. The `/` and `**` fallbacks follow.

**OQ-A7 mostly dissolves.** It put Rank on `/inventory` so scores sat beside the pieces; with
Inventory and Rank as sibling tabs that adjacency survives, and Rank gets the room the panel was
squeezed into.

**The "Optimal build" button is not a tab.** It is built (`TASKS_artifact_ranking.md` A.12, on
each ranked card) and it is what issue #291 literally asked for: *"assume that you can move
other artifacts"* — the best five-piece build that contains this piece, levelled, against the
build as equipped, naming which neighbours moved. It answers "this piece scores low in its slot,
but would it be great if I rebuilt around it?", which the single-slot score structurally
understates. It is an action on one piece, so it stays a button on Rank's cards. Whether it
earns its place is a usage question; it is not part of this restructure.

**Out:** `/calculate` (evaluates a team's rotation, does not search) and `/planner`
(materials). Weapons stay inside Optimize, where #237 put them.

**Its own refactor, first.** A small `TASKS_artifacts_tabs.md`: shell + context bar + move
Inventory, Optimize and Rank, **no behaviour change**, driven before and after with
`scripts/shoot.py`. This feature's Phase 3 then lands as the Upgrade tab; Phases 1–2 are
unaffected.

*Planner draft. OQ-U4 open (later, recommended). OQ-U6 shaped by the owner, §11.*
