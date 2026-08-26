# RESEARCH: can a gcsim-derived damage recipe be the optimizer's base?

**Owner question (2026-08-26):** measure the cost of the damage-recipe plan in detail, and say
whether gcsim can be the base of the optimizer.

**Answer: yes on cost — a full-rotation recipe costs 1.1×–2× a single-hit score, not 100×.
The blocker is not arithmetic. It is that gcsim's *browser* build cannot run multi-character
rotations at all**, which this investigation found while trying to measure a team recipe.

---

## 1. The cost, measured

`score()` in `src/app/sim/search.ts` does two separable things per combination: **aggregate the
candidate's stats** (≈7 `sum()` walks over ~8 stat pools) and then **one `computeDamage`**. A
recipe re-evaluates the second per hit and **shares the first**.

Measured in Node against the real kernel, largest committed search fixture plus synthesised
inventories:

| marginal cost of one extra hit (`computeDamage`) | **0.051 µs** |
|---|---|

| inventory | combinations | µs/combination | H=7 | H=50 | H=221 |
|---|---|---|---|---|---|
| 20 pieces | 576 | 6.363 | **1.05×** | 1.39× | 2.77× |
| 40 pieces | 10,368 | 3.729 | **1.08×** | 1.67× | 4.02× |
| 60 pieces | 45,360 | 2.675 | **1.11×** | 1.94× | 5.21× |
| 80 pieces | 107,811 | 2.599 | **1.12×** | 1.96× | 5.33× |

**The fixed cost is ~91× the marginal cost.** Stat aggregation dominates a combination, and a
recipe pays it once. Per-combination cost also *falls* at scale (6.4 → 2.6 µs), so recipes get
relatively cheaper on the searches that matter.

### How big is a recipe?

Measured from `source_damage_instances`, 30 iterations each:

| rotation | distinct sources | total hit instances |
|---|---|---|
| solo Ayaka, `while 1` gated, 90 s | **7** | 221 |
| solo Raiden Shogun, same shape | **13** | 252 |

**Distinct sources is the number that matters, not instances** — every instance of one source
under constant buffs computes the same damage, so the recipe multiplies rather than repeats.
That makes H ≈ 7–13 solo, and **1.05×–1.12× the current cost**.

Per-*instance* evaluation (H = 221–252) is only needed when buffs vary across the rotation —
Tier 2 territory — and even that is **2.8×–5.3×**, not the 100× the naive reading suggests.

**On cost, the proposal is not merely feasible. It is nearly free.**

---

## 2. The actual blocker: the browser build cannot swap characters

Trying to measure a four-character team recipe produced
`runtime error: index out of range [0] with length 0` from `flush()`. That message is a
symptom. The real one, from `simulate()`:

> `internal error: requested next char xiangling is not active and next action is not swap`

`pkg/simulation/run.go:155` raises it, under a comment that gives the game away:

```go
// IMPORTANT: evaluator should handle adding in implicit swaps if next char is not active
// we add a sanity check here just to guard against evaluator error
```

**The wasm entry point loses the parsed file, so the evaluator cannot insert those swaps.**
`cmd/wasm/main.go:initialize()` builds `file := ast.NewFile()`, parses into it, and then keeps
only `cfg`, `simcfg` and `gcsl` — **`file` is discarded**. `simulate()` then constructs
*another* empty `ast.NewFile()` for `NewEvaluator`. The native path
(`pkg/simulator/simulator.go:93`) keeps the populated file and hands it to every worker.

Confirmed by bisection: a two-character config runs fine when the rotation **only acts on the
active character** (13 sources, identical DPS to solo), and fails the moment it acts on the
second.

### What this caps

- **W.6's comparison page works for solo builds only.** Any team rotation fails.
- **`compile_rotation` emits no swap actions at all** — verified directly against the repo's
  own compiler for a two-character rotation. So every multi-character rotation this repo
  produces is a config the browser build refuses.
- It is **not** a limit on the recipe idea. It is a limit on *generating* recipes in the
  browser.

---

## 3. Why this argues *for* the recipe design rather than against it

A recipe is generated **once per rotation**, not per candidate. Nothing requires that
generation to happen in the browser — and the native binary, which does insert implicit swaps,
is already what `tests/crossval` uses as the oracle.

So the shape that falls out of these measurements is:

| stage | where | cost | frequency |
|---|---|---|---|
| generate the recipe | **server or offline, native gcsim** | ~0.24 s/run × iterations | once per rotation |
| evaluate it per candidate | browser kernel | **+0.051 µs per hit** | per combination |

That sidesteps the wasm defect entirely, keeps `RESEARCH_gcsim_embed.md` §6's ruling intact
(gcsim is still not in the inner loop), and gives the optimizer a **full-rotation** objective
instead of a single-hit one — which is a better question, not just a faster answer.

---

## 4. What still has to be solved, honestly

1. **Modifier semantics.** `DamageEvent.Damage` is a final number; the log carries modifier
   *names*, not amounts. A recipe cannot be rescaled, only recomputed — which needs
   `TASKS_passive_port.md`. **The recipe and the port are the same project from two ends.**
2. **The ER transition bands.** `RESEARCH_damage_recipe.md` measured burst count going
   2.00 → 2.75 → 4.00, and at +20 % ER the count is 2 *or* 3 by iteration. A recipe is valid
   only where `sd == 0` on burst instances; inside a band it must be regenerated or reported.
   `sim_runs.er_bucket` and `RESEARCH_er_bucketing.md` already encode this problem.
3. **Snapshot semantics.** Abilities that snapshot at cast use cast-time buffs. The per-hit log
   encodes this via its modifier list, but only in the *unaggregated* MessagePack, not in
   `flush()`.
4. **Crit.** gcsim rolls it; this repo computes it (a documented divergence). A recipe must use
   expected value, not the per-event `Crit` flag, or it imports Monte Carlo noise into a
   deterministic evaluator.

---

## 5. Recommendation

**Build it, in this order, and do not start with the recipe.**

1. **Tier 1 of the passive port first** (`TASKS_passive_port.md`, P.3/P.4). The recipe is
   worthless without modifier semantics, and Tier 1 alone fixes the optimizer's *wrong
   answers* — `Redhorn Stonethresher`, `Staff of Homa`, `Engulfing Lightning`.
2. **Then recipe generation server-side**, native gcsim, one per (rotation, team, ER bucket),
   cached in `sim_runs` — which already exists and is already keyed the right way.
3. **Then swap the optimizer's objective** from one hit to the recipe. On these numbers that
   costs ~10 % at H=13.

**Fix or route around the wasm swap defect before W.6's page is used with a team.** It is
upstream, at the pin, and this repo's compiler feeds it exactly the configs it rejects.
