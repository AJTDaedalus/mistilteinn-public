# TASKS: weapon passives, via gcsim as a second tier

**Companion:** `docs/DESIGN_weapon_passives.md` — read §3 (what already exists) and §4 (the
measured cost) before starting. **Decision:** `docs/DECISIONS.md`, 2026-08-26.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to
`docs/LOG_mistilteinn.md`, **stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

> **Status: all seven tasks done.** W.0–W.5 merged as PR #92. **W.6 was pushed straight to
> `dev` as 49ab563 with no PR** — a standing-rule violation, kept by owner decision because
> the content had passed every gate and reverting a shared branch costs more than it buys.
> Recorded rather than tidied away: a plan file that quietly renumbers a mistake into a PR
> that never existed is a worse artefact than one that says what happened.
>
> **`rg "TODO\(chunk-"` now counts zero**, from nine at the start of `TASKS_loose_ends.md`.
> The two that survived that sweep were these, and they are retired because the work they
> named exists — not re-pointed, and not deleted while still open.
>
> **OQ-W1 (iteration count) and OQ-W2 (a worker pool) are deliberately still open.** Both
> need measurements over real weapon runs and a real browser, and the page ships serial with
> a user-set count rather than guessing them.

**Standing rules**

- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- **Run each gate standalone and check its exit code.** Not chained behind `&&`, not piped
  through `tail`.
- Lint with **CI's own argument list** — copy the `run:` line out of
  `.github/workflows/test.yml`; `test_documented_lint_command_matches_ci.py` keeps
  `backend/CLAUDE.md` honest about it.
- Every new authed route joins the 401 sweep in the same commit; any API change regenerates
  `frontend/openapi.json` and leaves the contract test green.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise.**
- **Do not write a passive's condition from a reading of its refinement text.** That is the
  fabrication this whole chunk exists to avoid — gcsim is the authority, which is the point of
  routing to it.

---

### [x] W.0 — Branch setup **(gate)**
- **Do:** branch `feat/gcsim-weapon-tier` off `dev`.
- **Accept:** `git branch --show-current` is not `dev` or `main`.

### [x] W.1 — The browser gcsim runner — **done**
- **Do:** `frontend/src/app/sim/gcsim.ts` — lazy-load the wasm, expose
  `run(config, iterations, onProgress)`.
- **Read first:** `frontend/scripts/verify-gcsim-wasm.mjs`. It drives the whole API in 66
  lines and CI runs it every build.
- **Two traps it already encodes**, both of which cost time during planning:
  `validateConfig` returns the **parsed config** on success and signals failure by embedding
  `"error"` in the returned string, so a truthiness check inverts it; and `iteration=N` does
  **not** make `simulate()` run N times — `simulate()` is one iteration and the caller loops.
- **Accept:** a spec runs the committed `ayaka_normal_1_nocrit.txt` fixture and matches
  `108.53039935232651`, the same anchor the CI gate uses.
- **The gitignored wasm is already handled** — do not re-solve it. The frontend lane runs
  `npm run gcsim:build` (test.yml:219) *before* `npm test` (test.yml:297), so a spec that
  needs the wasm has it. **Locally it may be absent**, and the spec must then fail loudly or
  be skipped with a reason `ci_local` can see — *a skipped check BLOCKS; it is never a pass.*

### [x] W.2 — Substituting a candidate weapon into a compiled config — **done**
- **Do:** given a compiled rotation config and a candidate weapon, produce the config with
  that weapon in place of the worn one.
- **Accept:** round-trip tests — the emitted config names the candidate, at the candidate's
  refinement, and **nothing else in the config changed**.
- **Why it is its own task:** a substitution that silently keeps the worn weapon produces a
  **flat ranking that reads as "these weapons are equivalent"** rather than as a bug. This is
  the single most dangerous failure in the chunk.

### [x] W.3 — Prove the substitution is not silently a no-op — **done**
- **Do:** a test that two different candidates produce two different configs **and two
  different DPS**, and a mutation that makes the substitution a no-op.
- **Accept:** `python -m scripts.inject` reports the no-op mutation **caught**. A test that
  passes when substitution does nothing is worse than no test — it certifies the failure mode.

### [x] W.4 — Measure parallelism **[Planner] — measurement, not a feature** — **done**
- **Do:** measure whether N Web Workers, each holding a wasm instance, is memory-viable and
  how much of the 7.84 s/run it recovers. **OQ-W2.**
- **Accept:** numbers in `docs/LOG_mistilteinn.md`, and a recommendation. **Do not build the
  worker pool if the measurement does not support it** — single-threaded with honest progress
  beats a pool that thrashes.

### [x] W.5 — Rank with separability — **done** (OQ-W1 still open: needs real weapons)
- **Do:** rank candidates by dps mean; carry sd and iteration count; mark pairs whose
  intervals overlap as **not separated** rather than ordering them.
- **Accept:** a test with two candidates inside one standard error asserts they come back
  **marked not-separated, not ordered**.
- **Then answer OQ-W1** — pick the iteration count from the measured stability of the ranking
  over real weapons, not from the table in DESIGN §4.

### [x] W.6 — Wire it to the page, and retire the markers — **done**
- **Do:** the comparison page offers the gcsim tier as an explicit second request with
  progress. Keep the existing `/compare-weapons` (OQ-W4) — it answers the cheap question
  honestly in milliseconds.
- **Accept:** `unmodelled_passives` is still reported by the fast tier; the gcsim tier does not
  report it, because it does not have that gap. **The two `TODO(chunk-H)` markers are
  re-pointed at this chunk or deleted**, and `rg "TODO\(chunk-"` is stated in the PR either
  way.
- **If a build has no rotation, say so** (OQ-W3). There is nothing to simulate, and inventing
  a default would make the ranking an answer about a rotation the user never wrote.

---

## Open questions

Carried from `DESIGN_weapon_passives.md` §6, all live: **OQ-W1** iteration count (W.5),
**OQ-W2** Web Workers — *answered in W.4:
a persistent pool capped at **4** (3.02×; six workers is **slower** than four), never sized
from core count, degrading to serial. Measured in Node, so the ~1 GB/worker RSS is the number
W.6 must re-check in a browser* — **OQ-W3** which rotation (W.6), **OQ-W4** keep the fast tier
(recommendation: yes).

## Not in this chunk

- **The five passives expressible in the Chunk F chain today.** Tempting and cheap, and
  deliberately excluded: this chunk's whole argument is that gcsim is the authority on
  passives. Adding a second, hand-derived implementation of five of them — in the chunk that
  exists because hand-derivation is the failure mode — would be the wrong lesson learned.
- **The optimizer.** §6's ruling stands: the artifact search does not touch gcsim.
