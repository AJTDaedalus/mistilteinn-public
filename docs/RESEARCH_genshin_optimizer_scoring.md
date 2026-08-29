# RESEARCH — How Genshin Optimizer scores and ranks a single artifact

## What this is and how it was gathered

Written **2026-08-29**. The question asked was: what does Genshin Optimizer (GO) compute and
display for a single artifact's *future* value, what probability model backs it, what per-artifact
scores exist, what those scores are relative to, how it stays cheap over a large inventory, and
whether there is an explicit "should I level this?" affordance.

**Sources, in descending order of trust:**

1. **Actual source, read in full** from `raw.githubusercontent.com/frzyc/genshin-optimizer/master`
   (branch `master`, fetched 2026-08-29). Every file named in this document was read, not
   summarised from search results. The files:
   - `libs/gi/upopt/src/{consts,substatProbs,upOpt,upOpt.types,expandSubstat,expandRolls,deduplicate,upOptMemoize,index}.ts`
   - `libs/gi/upopt/src/markov-tree/{mathUtil,mvncdf,evaluation,makeObjective,markov.types}.ts`
   - `libs/gi/page-team/src/CharacterDisplay/Tabs/TabUpgradeOpt/{index.tsx,UpgradeOptChartCard.tsx,upOpt.ts,mathUtil.ts,formulaUtils.ts}`
   - `libs/gi/util/src/artifact/{artifact,artifactMeta,artifactSortUtil,rollProbabilityUtil,index}.ts`
   - `libs/gi/ui/src/components/artifact/ArtifactCard.tsx`, `libs/gi/ui/src/components/PercentBadge.tsx`
   - `libs/gi/localization/assets/locales/en/{page_character_optimize,page_character,artifact}.json` (the user-facing strings)
   - The repository file tree, via `api.github.com/repos/frzyc/genshin-optimizer/git/trees/master?recursive=1`
2. **GitHub issue [#430](https://github.com/frzyc/genshin-optimizer/issues/430)** "Artifact Upgrade
   Probability (tooflesswulf)", fetched via WebFetch. It names a
   `GenshinOptimizer_UpgradePriority_TechnicalReport.pdf`. **I could not retrieve that PDF** — the
   attachment URL was not exposed in the fetched page and a web search did not surface a mirror. So
   the *author's own* justification of the method is not part of this document; everything below is
   read off the shipped code.

**Nothing here is from memory of how Genshin works.** Where a constant appears below it is quoted
from a named file. Where I am inferring behaviour rather than reading it, the sentence says so.

Two honest caveats up front:

- I did **not** run GO or view its UI. Statements about what the user *sees* are read off the JSX in
  `UpgradeOptChartCard.tsx` and the English locale strings, which is strong evidence but is not the
  same as having looked at the page.
- GO is under active development and the module I document (`libs/gi/upopt`, a three-level "Markov
  tree") is clearly newer than the 2022 issue that started it. Older write-ups of GO's upgrade
  optimizer that you may find describe a different implementation.

---

## 1. The distribution

**It is a real probability distribution over the objective's value after the artifact is fully
levelled, rendered as a binned density curve. It is not a percentile, not an expected value with
error bars, and there is no Monte Carlo anywhere in the code I read.**

### The UI element

The tab is **"Artifact Upgrader"** (`page_character.json`: `tabs.upopt`), implemented at
`libs/gi/page-team/src/CharacterDisplay/Tabs/TabUpgradeOpt/index.tsx`. Each candidate renders as an
`UpgradeOptChartCard` (same directory), whose right-hand half is `UpgradeOptChartCardGraph` — a
recharts `ComposedChart` with:

- x-axis `incLabel` = **"Relative Increase to Target"**, formatted as a signed percentage;
- y-axis `probLabel` = **"Probability"**;
- an `Area` series named either **"Estimated Distribution"** or **"Exact Distribution"** (plus
  `" Constrained"` when the user has set constraint targets) — locale keys
  `upOptChart.estimatedDist` / `upOptChart.exactDist` / `upOptChart.const`;
- a red dashed `ReferenceLine` at the **current** target value and a green dashed one at
  current + average increase;
- two headline numbers above the chart: **`Prob. upgrade (est.): X%`** and
  **`Average increase (est.): +Y%`** (`upOptChart.prob`, `upOptChart.average`; the `(est.)` suffix
  disappears once the exact pass finishes).

The histogram is built by `UpOptCalculatorV2.histogram()` in `TabUpgradeOpt/upOpt.ts` with
`nbins = 50` (declared in `UpgradeOptChartCard.tsx`).

### What the two headline numbers mean

In the `UpOptCalculatorV2` constructor (`TabUpgradeOpt/upOpt.ts`):

```ts
thresholds[0] = evalFn(baseBuild as ArtifactBuildData[] & { length: 5 })[0]
```

i.e. **threshold 0 is set to the objective's value on the build as it stands right now**. So:

- `p` = **P[objective after upgrade > objective now]** — "Prob. upgrade".
- `upAvg` = **E[objective − current | objective > current]**, an increase *conditional on the
  upgrade being an improvement*, displayed as a percentage of the current value. It is not an
  unconditional expectation.

`gaussianPE` in `libs/gi/upopt/src/markov-tree/mvncdf.ts` computes exactly that pair for one
Gaussian, and `accumulateEvaluations` in `libs/gi/upopt/src/upOpt.ts` aggregates over the tree as
`p = Σ pᵢ·probᵢ` and `upAvg = Σ pᵢ·probᵢ·upAvgᵢ / p` — a probability-weighted conditional mean.

### How the distribution is computed: a three-level lazily-expanded tree

`libs/gi/upopt/src/upOpt.types.ts` defines three node types, and the whole design turns on them:

| level | node type | what is still random inside the node |
|---|---|---|
| `substat` | `SubstatLevelNode` | *which* substat each future roll lands on, *and* each roll's value tier |
| `rolls` | `RollsLevelNode` | only each roll's value tier (the roll counts per substat are now fixed) |
| `values` | `ValuesLevelNode` | nothing — the node is a single deterministic outcome |

Every node carries a `GaussianNode { base, subs, mu, cov }`: a mean vector and covariance matrix
over the substat totals. `evaluateGaussian` (`markov-tree/evaluation.ts`) pushes that Gaussian
through the damage formula by the **delta method** — it asks the objective for the value *and* its
Jacobian w.r.t. each substat at the mean, then computes `f_cov = df · cov · dfᵀ` — and reads
`P[X > threshold]` and `E[X − x | X > x]` off the resulting Gaussian.

So:

- **At `substat` and `rolls` level the distribution is a Gaussian mixture** — one Gaussian per tree
  node, weight `p`. This is the **"Estimated Distribution"**. It is an approximation on two counts:
  the delta-method linearisation of the damage formula, and the Gaussian assumption on the substat
  totals.
- **At `values` level the tree is fully enumerated and every leaf is a point mass** (a values node
  has `subs: []`, so `f_cov` computes to 0 and `histogram()`'s `sig < 1e-3` branch drops the whole
  leaf weight into one bin). This is the **"Exact Distribution"** — an exact enumeration of every
  reachable outcome with its exact probability, binned into 50 bins. *Inference, clearly marked:* the
  code does not describe it as exact enumeration in a comment, but `expandSubstatLevel` +
  `expandRollsLevel` between them enumerate every roll-count assignment and every per-substat roll-sum
  with exact combinatorial weights, and the label the UI prints is literally `Exact Distribution`.

`histogram()` integrates the mixture over each bin with the error function rather than sampling:

```ts
const P = erf((mu - a) / sig) - erf((mu - b) / sig)
est += (p * P) / 2
```

Two series come out: `est` (unconstrained) and `estCons` (weighted by `constr_prob`, the probability
that the user's *other* constraint targets are simultaneously met). When constraints are set the
chart draws both, grey behind orange.

### The exact pass is opt-in-by-viewing and runs in the background

`UpgradeOptChartCardGraph` fires `upOptCalc.calcExactAsync(...)` in a `useEffect` for the candidate
currently on screen, showing a `CircularProgress` while it runs. `expandRollsLevelAsync`
(`TabUpgradeOpt/upOpt.ts`) chunks the expansion and evaluation, yielding to the browser every
`uiYieldBudgetMs = 12`, and takes a `shouldCancel` callback so paging away aborts it. Calls are
serialised through a promise queue so candidates refine one at a time. **This is the pattern worth
copying**: the cheap approximation ships immediately for every candidate; the exact answer is
computed only for what the user is looking at, cancellably.

---

## 2. The probability model

### Which substat a future roll lands on

**Two different mechanisms, correctly distinguished**, matching the game:

**(a) Choosing which substats the artifact *has*** — weighted draw *without replacement* from the
pool, excluding the main stat and any substat already present. The weights, from
`libs/gi/upopt/src/consts.ts`, whose own comment cites
`https://genshin-impact.fandom.com/wiki/Artifact/Distribution`:

```ts
export const substatWeights = {
  hp: 6, atk: 6, def: 6,
  hp_: 4, atk_: 4, def_: 4, eleMas: 4, enerRech_: 4,
  critRate_: 3, critDMG_: 3,
}
```

`substatProb` in `libs/gi/upopt/src/substatProbs.ts` computes the probability that a given set is a
subset of the final substats by **recursing over draw orders and renormalising the denominator after
each draw** — that is drawing without replacement done exactly, not an independent-weights
approximation. It memoises on `JSON.stringify({chosen, options, remaining})`. `crawlSubstats`
enumerates all `C(pool, 4 − |prefix|)` completions and returns `{p, subs}` pairs.

**(b) Choosing which existing substat each *upgrade* roll enhances** — **uniform over the 4
substats**, independent per roll. `rollCountProb` in `markov-tree/mathUtil.ts`:

```ts
const p = (factorial(N) / factNs) * 4 ** -N
```

a plain multinomial with p = 1/4 each. `crawlUpgrades(n)` enumerates all `C(n+3, 3)` ways to split
`n` rolls across 4 bins. (`rollCountProb` throws above 12 total rolls — its factorials are exact
integers only that far.)

Note GO does **not** mix these up: filler slots (a 3-substat artifact gaining its 4th) are drawn
with the weighted-without-replacement rule; the +4/+8/… enhancement rolls are uniform.

### Main-stat probabilities

Also in `consts.ts`, per slot, likewise cited to the fandom Distribution page:

- flower `hp: 1`; plume `atk: 1`
- sands: `hp_`, `atk_`, `def_` = 80/300 each; `eleMas`, `enerRech_` = 30/300 each
- goblet: `hp_` 77/400, `atk_` 77/400, `def_` 76/400, `eleMas` 10/400, and each of the 8
  `*_dmg_` (physical + 7 elements) 20/400
- circlet: `hp_`, `atk_`, `def_` = 22/100 each; `critRate_`, `critDMG_`, `heal_` = 10/100 each;
  `eleMas` 4/100

### Roll quality tiers

`getUniformSubstatValues` in `libs/gi/upopt/src/expandSubstat.ts`:

```ts
return [0.7, 0.8, 0.9, 1].map((x) => x * getSubstatValue(key, rarity, 'max', false))
```

Four tiers at 70/80/90/100% of the max value, **uniform** (`subMuVar` takes an unweighted mean and
variance over exactly those four). At the `values` level, `expandRollsLevel`
(`libs/gi/upopt/src/expandRolls.ts`) enumerates the *sum* of `n` tiers directly using quadrinomial
coefficients — the coefficient of xᵏ in (1+x+x²+x³)ⁿ, OEIS A008287, built by
`quadrinomial()` in `markov-tree/mathUtil.ts`:

```ts
p: 4 ** -rolls * quadrinomial(rolls, v - 7 * rolls)
stat: { [key]: (v * getSubstatValue(key, rarity, 'max', false)) / 10 }
```

with `v` ranging over `7·rolls … 10·rolls`. That is exact for the sum and collapses 4ⁿ orderings
into 3n+1 distinct totals — a cheap and exact win.

### The 3-vs-4 initial substat split

Handled in three different places, and the numbers differ by source:

- **Levelling an artifact you own** (`levelUpArtifact` in `libs/gi/upopt/src/upOpt.ts`): no
  probability is needed. If it already has 4 substats, nothing to guess. If it has 3, GO **sums over
  which the 4th will be** via `crawlSubstats(subkeys, subsToConsider, false)`, deducting one roll
  from `rollsLeft` for the one that creates it. If a GOOD import supplied `unactivatedSubstats` (a
  scanner-known 4th line), that is used directly instead of summed over.
- **A hypothetical fresh drop** (`freshArtifact`, same file): takes `p3sub` as a **caller-supplied
  parameter** — no constant is baked in. **I found no caller for `freshArtifact` in the code I read**
  (`UpOptCalculatorV2` uses only `levelUpArtifact`, `dustReshape` and
  `elixirDefinitionMemoSimplified`), so I cannot say what value the UI passes, or whether this entry
  point is currently reachable at all.
- **Sanctifying-Elixir "Define" candidates**: `UpOptCalculatorV2.fromDefineInfo` passes
  **`prob_4line: 0.34`**, hardcoded, **with no citation in the source**. Flagging it as such — it is
  a bare constant in the file, and I have not verified it against any primary source.

### Rolls remaining

`getRollsRemaining` (`libs/gi/util/src/artifact/artifact.ts`) is
`Math.ceil((artMaxLevel[rarity] - level) / 4)` — so a 5★ at +0 has 5 upgrade rolls left, which is the
+4/+8/+12/+16/+20 schedule.

### Known approximations in the probability model, named by the code itself

- **`mvnPE_bad`** (`markov-tree/mvncdf.ts`) — the name is the authors'. Its docstring says:
  *"this implementation ignores the cov off-diagonals (assumes all components are independent)."*
  It multiplies the marginal constraint probabilities. So when a user sets several constraint targets
  at once, `constr_prob` treats them as independent even though they share substats.
- **`erf`** is the Abramowitz & Stegun 7.1.26 rational approximation (max deviation ~1.5e-7), copied
  from picomath, duplicated in `markov-tree/mathUtil.ts` and `TabUpgradeOpt/mathUtil.ts`.
- `gaussianPE` switches to a 7th-order asymptotic expansion for `z ≥ 5` so the conditional mean stays
  continuous and numerically sane in the far tail.
- The delta method linearises the damage formula at the mean. For a highly non-linear objective
  (reaction/crit thresholds, `threshold` nodes) the Gaussian estimate can be off — which is precisely
  why the exact pass exists.

---

## 3. "Is this artifact good?" — the per-artifact scores in the UI

GO has **two entirely separate scoring systems**, and it is important not to conflate them.

### (a) Roll Value / substat efficiency — character-agnostic

Computed by `getArtifactEfficiency` in `libs/gi/util/src/artifact/artifact.ts` and
`getArtifactMeta` in `artifactMeta.ts`. Per substat, `efficiency = accurateValue / getSubstatValue(key)`
where the denominator is the **5★ max single roll** for that substat — so one perfect roll = 1.0
(100%), and the measure is comparable across rarities by construction (the comment says "Relative to
max star, so comparison between different * makes sense").

Displayed on `ArtifactCard.tsx` as two rows, with locale strings from `artifact.json`:

- **"Current Roll Value"** (`editor.curSubEff`) — *"Every 4 artifact upgrades, you get a substat
  roll. Roll Value calculates how high the substat rolled as a percentage."*
- **"Max. Roll Value"** (`editor.maxSubEff`) — *"the RV if the remaining upgrades rolled their
  maximum values."* `getArtifactEfficiency` computes this by adding `maxSubstatRollEfficiency[rarity]`
  for each remaining roll, but only into slots the user's substat filter actually cares about.

Both render through `PercentBadge` (`libs/gi/ui/src/components/PercentBadge.tsx`) with `max = 9`,
so the number is a sum over up to ~9 rolls and prints as e.g. `350%`. The badge **colour** is
`roll${clamp(floor((value / max) * 10) - 4, 1, 6)}` — a six-step colour ramp, so RV below 40% of the
9-roll ceiling is the bottom colour and it steps up from there.

Two numbers are shown side by side when they differ: the RV **restricted to the user's selected
substats** (`effFilter`) and the RV over **all** substats.

Per substat, `ArtifactCard.tsx` additionally shows the efficiency as a right-aligned percentage whose
**opacity** is `clamp01(0.5 + (efficiency / 5) * 0.5)`, and one `SmolProgress` bar per individual
roll, coloured `roll1..roll6` by **which of the four value tiers that roll landed on**.

On the Artifacts page these are sort and filter keys (`artifactSortUtil.ts`): sort by `efficiency`
or `mefficiency`, and filter on an `rvLow`/`rvHigh` range from 0 to 900 with a `useMaxRV` toggle.

**RV is not a damage model.** It is "how well did the dice roll, restricted to the substats I ticked".
The only user input is a *set* of substats — there are no weights, and no character.

### (b) The Artifact Upgrader's two numbers — build-specific

Per candidate: **`Prob. upgrade: X%`**, **`Average increase: +Y%`**, and the distribution chart of §1.
Candidates are **sorted by expected gain** — `compare()` in `TabUpgradeOpt/upOpt.ts`:

```ts
const scoreA = a.result.p * a.result.upAvg
```

`p × upAvg` is exactly E[max(increase, 0)] — the unconditional expected improvement. When every
candidate scores ~0 it falls back to comparing the mean objective value. Candidates with
`result.p <= 1e-6` are dropped entirely before sorting.

### (c) A third, unused-looking exact calculator

`libs/gi/util/src/artifact/rollProbabilityUtil.ts` exports `probability(artifact, target)` —
*"Probability that `artifact` will have at least `target` stats at max level"* — a fully closed-form
computation over filler rolls and upgrade rolls with its own weight table and precomputed
`pFillerSeq` / `pNExtra` / `cnr` tables. It is exported from the package index, but **its test file is
`rollProbabilityUtil.test.ts_` — renamed with a trailing underscore, i.e. disabled — and I found no
caller in the files I read.** I could not do a repo-wide grep without cloning, so I cannot assert it
is dead code; I can only say I did not find it used. It is worth reading anyway: it is an
independent, exact, substat-target-threshold formulation, quite different from the Markov tree.

---

## 4. What the score is relative to — the answer that matters for us

**The Artifact Upgrader scores against a full build and a user-chosen damage formula, evaluated by
GO's own calculation engine. It does not use curated substat weights.**

The evidence, all from `TabUpgradeOpt/index.tsx`:

```ts
const teamDataLocal = teamData && getTeamData(database, teamId, teamCharId, 0, [])
const workerData = uiDataForTeam(teamDataLocal.teamData, ...)
Object.assign(workerData, mergeData([workerData, dynamicData]))
const optimizationTargetNode = objPathValue(workerData.display ?? {}, optimizationTarget)
const valueFilter: { value: NumNode; minimum: number }[] = ...
const nodes = optimize([optimizationTargetNode, ...valueFilter.map((x) => x.value)], workerData, ...)
return new UpOptCalculatorV2(nodes, [-Infinity, ...valueFilter.map((x) => x.minimum)],
                             equippedArts, artifactsToConsider, reshapeConfig, defineConfig)
```

So the objective is:

- **a team-level data context** (`getTeamData` / `uiDataForTeam` — team buffs and conditionals are in
  scope, not just the solo character);
- **the other four equipped artifacts** (`equippedArts` from the loadout) plus the loadout's weapon —
  `toStats()` in `libs/gi/upopt/src/upOpt.ts` explicitly sums the other four slots into `base`, so the
  candidate is scored *as a swap into this specific build*;
- **a formula node the user picks** — `OptimizationTargetSelector`, plus `CustomMultiTargetButton`
  for user-authored composite targets. So the "score" is a damage (or healing, or whatever node)
  number produced by GO's formula engine, not a heuristic;
- **optional constraint targets** — `valueFilter` supplies thresholds 1..n (e.g. "keep ER ≥ 180%"),
  and the chart's `estCons` series and `constr_prob` are about jointly satisfying them.

`makeObjective` (`libs/gi/upopt/src/markov-tree/makeObjective.ts`) then compiles that node **plus its
symbolic Jacobian w.r.t. every substat** (`ddx`, `zero_deriv`, `optimize`, `precompute` from
`@genshin-optimizer/gi/wr`) into one callable, so each tree node costs a single evaluation returning
both value and gradient.

**This is the same shape as the decision our owner has made** — "how much potential does this artifact
have given this character in this team with this rotation", computed by the engine rather than by
curated weights. The differences to be aware of when porting the idea:

1. GO's objective is **differentiable and cheap** — a compiled expression tree it can take symbolic
   derivatives of. That is what makes the delta method available at all. A gcsim-backed rotation
   engine gives us neither a gradient nor a sub-millisecond evaluation. If we want GO's *estimated*
   tier, we need either finite-difference gradients (N+1 engine calls per node) or a different
   approximation; if we want only the *exact* tier, we need one engine call per enumerated leaf,
   which is far too many. **This is the load-bearing difference and it should be designed for
   explicitly, not discovered later.**
2. GO scores **one swap at a time**, and says so in the UI: *"As it only swaps one artifact at a time,
   for the best overall build across all artifacts, use the main artifact optimizer"*
   (`upOptInfo`), plus a separate warning when the build has empty slots (`upOptEmptyBuild`).
3. Set bonuses are handled by pruning: `removeSetKeys` in `TabUpgradeOpt/formulaUtils.ts` replaces
   `threshold(setKey, n, pass, fail)` nodes with `pass` or `fail` whenever a ±1 change in that set's
   count cannot flip them, and leaves the node alone when it can. A related known-issue thread exists
   ([#1186](https://github.com/frzyc/genshin-optimizer/issues/1186), "Upgrade Optimizer *Artifact Set
   Assumptions*") which I did **not** read — flagging it as a lead, not as evidence.

RV (§3a), by contrast, is relative to nothing but the user's ticked substat set.

---

## 5. Performance over a large inventory

GO's answer is **progressive refinement over a cost hierarchy**, not caching of final scores. Ranked
by how much I'd want to copy each:

1. **Three-tier evaluation, cheapest first, refined only where it matters.** Every candidate is first
   evaluated at `substat` level — that is *one* Gaussian, so **one objective evaluation per
   candidate**, regardless of how many outcomes the artifact actually has. Then:
   `this.candidates.sort(compare); this.calcSlowToIndex(5)`. `calcSlowToIndex(ix, lookahead = 5)`
   expands only candidates up to `ix + lookahead` to `rolls` level, re-sorts, and **repeats until the
   top of the list is stable** (the `do…while` loop breaks only when no candidate in the window is
   still at `substat` level). Paging calls `calcSlowToIndex(page × 5)`. The `values`-level exact
   expansion happens only for the card the user is currently looking at.
2. **Prune the search space by the objective's own derivatives.** `makeObjective` computes
   `zeroDeriv` — the substats no target formula depends on — and `deduplicate`
   (`libs/gi/upopt/src/deduplicate.ts`) *deletes those dimensions from every node* before evaluation,
   then merges nodes that have become identical, summing their probabilities. For a typical crit-DMG
   objective this collapses a large fraction of the tree. It also drops zero-roll substats at the
   `rolls` level.
3. **Memoise the combinatorics, which are build-independent.** `substatProbCache`
   (`substatProbs.ts`), `rollCountPCache` and `rollMuVarCache` (`markov-tree/mathUtil.ts`),
   `substatMuVarCache` (`expandSubstat.ts`) — all module-level `Record`s keyed on the structural
   inputs. And `upOptMemoize.ts` caches *whole deduplicated node lists* for Elixir "define"
   candidates keyed on `(mainStatKey, affixes, 3|4 lines)`, since only the `base` stats differ
   between builds; `rebase()` clones just the wrapper and shares the `mu`/`cov` arrays.
4. **Compile the objective once.** `optimize()` + `precompute()` turn the formula and its Jacobian
   into a single closure evaluated per node, rather than walking an expression tree each time.
5. **Filter aggressively before doing any work.** `index.tsx` restricts to 5★, to the user's level
   range, to allowed main stats per slot, to set-exclusion rules; then `UpOptCalculatorV2` drops any
   candidate with `p <= 1e-6`.
6. **Cooperative scheduling instead of workers, for the expensive tier.** `expandRollsLevelAsync`
   yields to the event loop every 12 ms and honours a cancel callback; a promise queue serialises the
   exact passes. (The main optimizer *does* use workers — `libs/gi/solver` — but the upgrade
   optimizer does not, in the code I read.)
7. `histogram()` caches its own output keyed on `{left, right, bins}`.

One honest wrinkle: `expandRollsLevelAsync` **skips deduplication** — `const deduped = expanded` with
the comment `// TODO: make dedup work w/ async yield so it doesn't hang UI`. So the exact pass is
doing more work than it strictly needs to.

**What I could not determine:** any measured timing. There are no benchmarks in the files I read, and
I did not run GO. Claims about it "handling several thousand artifacts cheaply" should be treated as
design intent read off the code, not as a measured result.

---

## 6. The upgrade decision — is there an explicit "should I level this?"

**Yes. The entire "Artifact Upgrader" tab is that affordance**, and its own copy says so
(`page_character_optimize.json`):

> *"The Artifact Upgrader identifies artifacts with high potential to boost the Optimization Target's
> value, guiding you to artifacts worth leveling up. As it only swaps one artifact at a time, for the
> best overall build across all artifacts, use the main artifact optimizer."*

What it actually tells the user, per candidate:

- a ranked position (ordered by `p × upAvg`, expected improvement),
- `Prob. upgrade: X%`,
- `Average increase: +Y%`,
- the full distribution chart, with the current value marked,
- and an **Equip** button (`EquipButton` in `UpgradeOptChartCard.tsx`) opening an `EquipBuildModal`.

It does **not** say "yes, level this" in words, and it does not model resin/fodder cost, so it is a
ranking-and-evidence affordance rather than a recommendation. There is no cost side to the
cost/benefit.

Three candidate *kinds* are ranked in the same list, which is a nice generalisation of "should I level
this":

- **`levelUp`** — level an owned artifact to +20. Gated on `art.rarity === 5` (`canLevelUp`).
- **`reshape`** — Dust of Enlightenment. `canReshape` requires 5★, level 20, and known `initialValue`
  on every substat (i.e. an Irminsul import; the locale tooltip says so). Each eligible artifact is
  scored **once per substat pair — 6 candidates per artifact**.
- **`definition`** — Sanctifying Elixir. Hypothetical artifacts with no backing DB row; rendered via a
  synthetic `cachedArtifact` with `hideSubstatValues`.

The reshape and define paths reuse the *same* machinery through `SubstatLevelNode.reshape`
(`{affixes, mintotal}`), which warps the roll-count distribution: `rollCountProb` takes the reshape
constraint and returns 0 for configurations that violate the guarantee, or a corrected
`p_total_equal_min × p_rolls` when the guaranteed total is exactly met. Worth noting as a design
point: **the "guaranteed N rolls into these stats" mechanic is expressible as a reweighting of the
same roll-count distribution**, so it did not need a second model.

Elsewhere in the app there is no per-artifact "level this" prompt that I found — the Artifacts page
offers RV-based sorting and filtering (§3a) and that is all.

---

## Summary for our design

- **Copy the shape**: a probability distribution over the *objective*, not over stats; headline
  numbers `P[improvement]` and `E[gain | improvement]`; rank by their product.
- **Copy the laziness**: cheap approximation for all candidates → a middle tier for the top of the
  list → exact only for what is on screen, cancellable, chunked.
- **Copy the pruning**: drop substats the objective does not depend on *before* enumerating, and merge
  the nodes that become identical.
- **Do not assume we can copy the delta method.** GO can differentiate its objective symbolically and
  evaluate it in microseconds. A gcsim-backed rotation engine can do neither. Deciding what plays the
  role of GO's cheap tier is the first real design question, and `docs/RESEARCH_recipe_cost.md`'s
  measured 7.84 s per browser sim is the number that constrains it.
- **Uncited constant to not propagate**: `prob_4line: 0.34`. If we need a 3-vs-4-line probability,
  derive it from a source we commit, per this repo's citation rule.
