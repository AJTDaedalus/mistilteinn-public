# RESEARCH: can a gcsim-derived damage recipe be the optimizer's base?

**Owner question (2026-08-26):** measure the cost of the damage-recipe plan in detail, and say
whether gcsim can be the base of the optimizer.

**Answer: yes — and it stays client-side.** A full-rotation recipe costs **1.1×–1.2×** a
single-hit score, not 100×. A real four-character team is **17 distinct sources ≈ 1.15×**.

The one apparent blocker — multi-character rotations failing — turned out to be **a one-line
bug in this repo's own config emitter** (`swap_delay=0`), not a limitation of gcsim or of the
browser. §2 records both the fix and the wrong root cause published before it.

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

## 2. CORRECTED — the blocker was ours, and it is one line

**An earlier version of this document said gcsim's browser build could not run
multi-character rotations, and blamed the wasm entry point for discarding its parsed
`ast.File`. That was wrong, and it was published in PR #97 before it was checked properly.**

The symptom was real:

> `internal error: requested next char xiangling is not active and next action is not swap`

**The native binary fails identically.** Built from the pin and run against the same config, it
produces the same error — which rules the wasm out immediately, and would have if the native
binary had been tried before the theory was written down.

**The cause is `swap_delay=0`, which this repo's own emitter hardcoded.** gcsim queues the
swap to land `Delays.Swap` frames later (`pkg/core/player/exec.go:151`), so at **0 the swap
never lands** before the next action is requested, and the sanity check at
`pkg/simulation/run.go:155` fires. gcsim's default is **1**
(`pkg/gcs/parser/parser.go:55`, *"default swap timer of 1"*).

| config | native | browser |
|---|---|---|
| `swap_delay=0` | **fails** | **fails** |
| `swap_delay=1` | runs | runs |
| omitted (default 1) | runs | runs |

`gcsim_config.build_config` emitted `options iteration=… duration=… swap_delay=0;`
unconditionally, so **every multi-character rotation this repo has ever produced was
unrunnable.** Solo rotations never swap, which is why nothing caught it — and why the sample
configs, the crossval fixtures and the W.6 page all looked healthy.

**Fixed by omitting the option**, rather than pinning a number: gcsim's default is gcsim's
answer, and a frame count restated here is one this repo would have to defend as game data.

With it removed, in the **browser build**:

| rotation | distinct sources | hit instances | DPS |
|---|---|---|---|
| solo Ayaka | 7 | 221 | — |
| solo Raiden | 13 | 252 | 2,303 |
| 2-char Raiden + Xiangling | 14 | 251 | 3,323 |
| **4-char Raiden National** | **17** | 233 | 9,532 |

**A real four-character team recipe is 17 distinct sources**, which on the table in §1 is
**≈1.15× the current per-combination cost.**

### Why this correction matters more than the error

The wrong version concluded *"generate recipes server-side, the browser cannot do it"*. That
would have moved the optimizer off the client to work around a bug in one line of our own
config emitter. **The whole design premise was nearly rewritten to accommodate a typo.**

## 3. The shape, entirely client-side

A recipe is generated **once per rotation**, not per candidate — so even at gcsim's full price
it is amortised across every combination in the search.

| stage | where | cost | frequency |
|---|---|---|---|
| generate the recipe | **browser**, gcsim wasm | ~4.9 s at 100 iterations | once per rotation / ER bucket |
| evaluate it per candidate | browser kernel | **+0.051 µs per hit** | per combination |

`RESEARCH_gcsim_embed.md` §6's ruling stands untouched: **gcsim never enters the inner loop.**
It sets the loop's question once, and the loop answers it 100,000 times at 1.15× the price of
today's single-hit objective — which is a *better question*, not merely a faster answer.

Caching belongs in `sim_runs`, which already exists and is already keyed by `context_key` +
`er_bucket` — the exact axis `RESEARCH_damage_recipe.md` showed a recipe is only valid along.

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
