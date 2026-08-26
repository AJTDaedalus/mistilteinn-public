# DESIGN: weapon passives, via gcsim as a second tier

**Companion:** `docs/TASKS_weapon_passives.md`.
**Decision this implements:** `docs/DECISIONS.md`, "Weapon passives go to gcsim as a second
tier (2026-08-26)". **Escalation it closes:** `docs/LOG_mistilteinn.md`, "ESCALATION — weapon
passives have no home".

## Branch policy

Per-task branches off `dev`, named `feat/<task>` or `fix/<task>`, merged to `dev` by PR after
review. **No direct commits to `dev` or `main`.** W.1 gates everything; W.2–W.4 gate W.5; W.6
needs W.5's output. **Task W.0 of `docs/TASKS_weapon_passives.md` is the branch-setup gate.**

---

## 1. What the gap is, measured

`weapon_comparison` scores candidates on base ATK and the substat. It reports every candidate
that has a passive as `unmodelled_passives`, and the module's own docstring is blunt about
why: **it is not a warning about precision — the ordering itself can be wrong.** A stat-stick
outranks the weapon whose passive is the entire reason anyone equips it, with a
precise-looking number attached.

N.5 measured it against the seeded catalogue:

| | |
|---|---|
| weapons | **260** |
| carrying a refinement passive | **242** (93 %) |
| expressible in the Chunk F chain today | **5** (2 %) |

The five — `The Stringless`, `Festering Desire`, `"The Catch"`, `White Tassel`, `Rust` — are
all scope-gated DMG bonus plus crit rate, and `/compare-weapons` already knows the scope.
Everything else needs machinery the chain does not have, and **nine of them ask questions
`KernelTarget` cannot express at all**: it is `level`, `resistance`, `def_reduction`,
`def_ignore`, so *"opponents affected by Hydro"*, *"against Slimes"* and *"weak spots"* are
unaskable rather than unimplemented.

## 2. Why gcsim, and why this is not §6 being overturned

`RESEARCH_gcsim_embed.md` §6 ruled gcsim out of the **optimizer's inner loop**: ~430× a
damage-chain combination, over a 9,000-combination artifact search. Its actual conclusion was
that gcsim is *a second tier above the chain, not a replacement for it*. **This applies that
conclusion; it does not reopen it.** Weapon comparison is one evaluation per candidate, at
most 59.

The alternative — deriving 237 conditions from English refinement prose — is the
fabricated-citation failure fairy actually suffered, and the BRIEF's citation rule is not
satisfied by a careful reading of a tooltip.

## 3. What already exists, and the one piece that does not

Almost all of it is built. This is a wiring chunk, not a from-scratch one.

| piece | state |
|---|---|
| gcsim browser build, pinned + provenanced | **built** — `frontend/gcsim/`, gitignored, `scripts/build-gcsim-wasm.sh` |
| a CI gate proving the wasm runs and matches a known total | **built** — `scripts/verify-gcsim-wasm.mjs` |
| rotation → gcsim config compiler | **built** — `compile_rotation`, sharing `_resolve` with `rotation_signature` |
| a run corpus with retrieval and measured error | **built** — `sim_runs`, `sim_retrieval` |
| `unmodelled_passives`, so the gap is already reported | **built** — `weapon_comparison` |
| **a browser-side gcsim runner the app calls** | **missing** |

The missing piece is small and has a working reference: `verify-gcsim-wasm.mjs` already drives
the full API — `validateConfig` → `initializeAggregator` → `initializeWorker` →
`aggregate(simulate())` → `flush`. **It is 66 lines and CI runs it every build.**

**Read it before writing the runner.** Two of its details are non-obvious and both cost time
during planning: `validateConfig` returns the *parsed config* on success and signals failure
by embedding `"error"` in the returned string, so a truthiness check inverts it; and
`iteration=N` in the config does **not** make `simulate()` run N times — `simulate()` is one
iteration and the caller loops, so a benchmark that varies `iteration=` measures nothing.

## 4. The cost, measured rather than inferred

Against the committed browser build at the pin, `frontend/gcsim/emitted/ayaka.txt` — a
90-second rotation:

| iterations | wall | per iteration | dps.sd | standard error |
|---|---|---|---|---|
| 1 | 515 ms | 515 ms | — | — |
| 10 | 1.53 s | 153 ms | 96.1 | 4.3 % |
| 50 | 4.39 s | 88 ms | 80.0 | 1.6 % |
| 100 | **7.84 s** | 78 ms | 86.9 | **1.2 %** |

Two consequences, and both shape the design more than the feature does.

**Single-threaded, 59 candidates is ~7.7 minutes.** The escalation's "~14 s" came from §6's
**native, all-cores** 0.238 s/run, and inferring a browser cost from it was a 33× miss. So
**the comparison is a job with progress, never a request that blocks** — and W.4 exists
because how much of that parallelism is recoverable in Web Workers is an open question, not a
known.

**Two weapons closer than ~3 % are not separable at 100 iterations.** A ranking that presents
them as ordered is exactly the "confident answer to a question nobody asked" this repo keeps
legislating against — the same argument as `isExact` on the optimizer and the measured error
on `sim_retrieval`. **The ranking ships with its separability or it does not ship.**

## 5. Shape

1. **`frontend/src/app/sim/gcsim.ts`** — loads the wasm lazily (41 MB; ~7 MB gzipped) and
   exposes `run(config, iterations, onProgress)`. Lazy because no other page should pay for
   it, and the optimizer explicitly must not: §6's ruling is that the search does not touch
   gcsim.
2. **Config per candidate.** The build's saved rotation compiles today; a comparison
   substitutes the candidate weapon into the compiled config. **The substitution is the risk
   in this chunk** — a config that silently keeps the worn weapon produces a flat ranking that
   looks like "these weapons are all equivalent" rather than like a bug. W.3 exists for that
   alone.
3. **Ranking with separability.** Rank by dps mean; report sd and iteration count; mark pairs
   whose intervals overlap as **not separated** rather than ordering them.
4. **Caching in `sim_runs`.** The corpus is keyed by `context_key` + `er_bucket` + `gcsim_pin`
   and already exists. A candidate's run is cacheable on the same terms.

## 6. Open questions

- **OQ-W1 — how many iterations?** 100 gives 1.2 % SE at 7.84 s. 50 gives 1.6 % at 4.39 s.
  The answer depends on the gaps between real weapons, which W.5 can measure and no amount of
  reasoning can. **Do not pick this from a table; measure the ranking's stability.**
- **OQ-W2 — Web Workers?** gcsim's native speed is parallel; the browser build in one thread
  is not. Whether N workers each holding a wasm instance is memory-viable at 41 MB is
  unmeasured. **W.4 measures it; it does not assume it.**
- **OQ-W3 — which rotation does a comparison use?** A build has artifacts and a weapon; the
  rotation is a separate saved entity. If a build has no rotation there is nothing to
  simulate, and the endpoint must say so rather than invent a default — a fabricated rotation
  would make the ranking an answer about a rotation the user never wrote.
- **OQ-W4 — does the existing `/compare-weapons` stay?** It answers the cheap question in
  milliseconds and is honest about its limits. **Recommendation: keep it**, and let the gcsim
  tier be a second, explicit request. Deleting a fast honest answer because a slow better one
  exists is a downgrade for anyone who wanted the fast one.
