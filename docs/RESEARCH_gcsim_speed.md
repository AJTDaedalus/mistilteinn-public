# RESEARCH: how much faster can gcsim be made to run?

**Question:** the gcsim tier costs ~4.9 s per config at 100 iterations, so a 59-candidate
weapon comparison is minutes. Can the simulator itself be made materially faster?

**Answer: about 4×, and that is a ceiling rather than a starting point.** 86 % of the time is
the frame-by-frame combat simulation, which is what gcsim *is*. Everything a fork could attack
is in the other 14 %.

All numbers measured against the committed browser build at the pin (`frontend/gcsim/`,
`docs/CROSSVAL_gcsim.md`), driving `emitted/ayaka.txt` — a 90-second single-character
rotation — from Node. Warm, after discarding 8–20 JIT iterations.

## 1. Where the time goes

| component | per iteration | share |
|---|---|---|
| fixed setup — `simcfg.Copy`, `gcsl.Copy`, `NewCore`, `NewEvaluator`, `simulation.New` | 5.4 ms | **11 %** |
| MessagePack marshal → `CopyBytesToJS` → `CopyBytesToGo` → unmarshal | 1.6 ms | **2.6 %** |
| the simulation loop | ~43 ms | **~86 %** |
| **total** | **48.7 ms** | |

Fixed setup is read off `duration=1s`, which costs **5.40 ms/iter** — a one-second fight is
essentially all setup. The simulation share is then ~0.48 ms per simulated second, or roughly
**8 µs per frame** at gcsim's 60 fps.

### The serialization round-trip is not the bottleneck, and that was a surprise

`simulate()` marshals the result, allocates a JS `Uint8Array` and copies into it; `aggregate()`
copies straight back into Go and unmarshals. In *our* usage both run in the same instance, so
it is a round trip to nowhere — the serialization exists because upstream runs `simulate()` in
Web Workers and `aggregate()` on the main thread.

It looked like the obvious win. **It is 2.6 %.** Measured before being acted on, which is the
only reason a fork was not written for it.

## 2. Duration scaling

| duration | ms/iter | µs per simulated second | result payload |
|---|---|---|---|
| 1 s | 5.40 | — | — |
| 2 s | 7.10 | — | — |
| 5 s | 13.33 | — | — |
| 10 s | 12.46 | — | — |
| 15 s | 26.7 | 1779 | 28 KB |
| 30 s | 30.0 | 999 | 52 KB |
| 60 s | 41.3 | 689 | 100 KB |
| 90 s | 45.5–48.7 | 506 | 147 KB |
| 180 s | 88.9 | 494 | 289 KB |

Near-linear above ~30 s, dominated by fixed cost below ~10 s. The short-duration rows are
noisy — 40 Monte Carlo runs each, and what happens in a 5-second fight varies a lot.

**The payload is cleanly linear at ~1.6 KB per simulated second.** That is per-event detail —
damage, reactions, energy, shields, positions, swaps — collected during the run and discarded
by this repo, which reads `stats.dps.mean` and `stats.total_damage.mean` and nothing else.

## 3. The levers, and what each is worth

| lever | measured | notes |
|---|---|---|
| **Web Worker pool** | **3.02×** at 4 workers | W.4. Six workers is *slower* than four. ~1 GB RSS each, measured in Node. |
| fewer iterations | linear | Standard error falls as 1/√n; this trades wall time for separability. |
| shorter duration | near-linear above ~30 s | Changes what is being simulated, so it is not free. |
| **strip the stats collectors** | **unmeasured** | The one lever inside the 86 %. Collectors register globally via blank import, so it needs a fork. Plausibly 10–30 %, and that is a guess, flagged as one. |
| batch iterations inside Go | ≤ 2.6 % | Removes the round trip. Not worth a fork on its own. |
| amortise per-iteration setup | ≤ 11 % | Fresh state per iteration is the point of Monte Carlo; only the config/program copies look reclaimable. |

**Stacked ceiling: ~4×.** A 59-candidate comparison goes 289 s → ~72 s.

## 4. Why that ceiling decides something bigger

`SECONDS_PER_COMBINATION` is **5.5e-4 s**. A gcsim config at 100 iterations is **4.87 s** —
about **8,900×**. `RESEARCH_gcsim_embed.md` §6 ruled gcsim out of the optimizer's inner loop on
exactly this basis, and **a 4× improvement does not change that ruling**; it would need four
orders of magnitude.

So the speed question and the correctness question come apart:

- **For the weapon comparison page**, 4× is worth having. It is already a job with progress,
  and 72 s is a better job than 289 s.
- **For the optimizer**, no amount of making gcsim faster helps. The artifact search will still
  be running the Chunk F chain, which does not model weapon passives — and unlike
  `/compare-weapons`, the search does not currently say so.

## 5. What the optimizer's gap actually is

`rg` finds `weapon_refinements` read by **exactly one module**, `weapon_comparison.py`, and
only to *report* the gap. Nothing in `app/formula/` touches it.

The impact splits, and the split matters:

- **Passives that scale uniformly do not change which artifacts win.** `The Stringless`'s
  +24 % Skill/Burst DMG multiplies every candidate build equally.
- **Passives that change stat weights do.** `Redhorn Stonethresher` — *"DEF is increased by
  28 %. Normal and Charged Attack DMG is increased by 40 % of DEF"* — makes DEF genuinely
  valuable, and **the search will never once consider DEF**. `Primordial Jade Cutter` does the
  same for HP. The optimizer returns a confident five-piece answer that is wrong for those
  weapons, with nothing on screen suggesting doubt.

## 6. The option this reopens

The N.5 escalation rejected a conditional modifier model on **fabrication risk**: deriving 237
conditions from English refinement prose is the failure fairy actually suffered.

**Reading gcsim's Go source is not that.** It is a primary source, it is pinned, and
`tests/crossval` can prove a ported passive matches gcsim numerically rather than taking the
port on trust. The citation rule objects to inventing mechanics from tooltips, not to porting
an authoritative implementation.

And the timeline problem is smaller here than in general, because **this repo already has an
authored, compiled rotation**. Uptime for a duration or a cooldown can be evaluated against a
known action list; you do not need Monte Carlo to know when a burst happens in a rotation the
user wrote.

**This is a strategy question, not a decomposition one** — it reopens what the N.5 escalation
settled — so it goes to the owner rather than being decided here.
