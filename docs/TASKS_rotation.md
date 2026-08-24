# TASKS — Rotation authoring

Worker tasks for `docs/DESIGN_rotation.md`. One task per PR-sized unit; each names what proves
it done. **Read the DESIGN first** — particularly §2's list of things the model deliberately
cannot express, because the temptation in every one of these tasks is to add a conditional.

**Verification:** CI's hosted-runner lanes are billing-blocked, so each task is verified with
`cd backend && python -m scripts.ci_local` (19 gates, read from the workflow files) and says
**"verified locally"** rather than "green". The self-hosted deploy runner is unaffected.

---

### [ ] R.0 — Branch setup **(gate)**
- **Do:** work on `feat/rotation` or per-task branches off `dev`; merge by PR.
- **Accept:** nothing reaches `dev` outside a PR.

### [ ] R.1 — The model and its schema **[decides OQ-R1, OQ-R2]**
- **Do:** `rotations` table — name, owner, team (ordered character ids), `steps` JSONB — plus
  the model, repository and migration. Steps validate on the way in: a known action, a
  `repeat` of at least 1, a character that is in the team.
- **Decide OQ-R1** (rotation belongs to a team or a build) and **OQ-R2** (a step naming a
  character the team no longer has), and record both in `DECISIONS.md` with the reasoning.
- **Accept:** a rotation round-trips; a step naming an unknown action is refused **naming the
  ten that exist**; a step naming a character outside the team is refused; owner scoping is
  covered in `test_owner_scoped_repositories.py` the way `SimRunRepository` is.

### [ ] R.2 — The compiler: rotation → gcsim action list
- **Do:** a pure function, no I/O. `active <first>;`, then `while 1 { … }`, then one
  readiness-gated statement per step, `repeat` as `:n`, **no swap actions** (§3.3).
- **Accept:** unit tests over the shape; the action vocabulary is derived from one place, not
  restated; a burst-first rotation emits its gate. **Injection: remove the gate and the
  deadlock test in R.3 must fail.**

### [ ] R.3 — The compiler is checked by gcsim, not by us **[gate]**
- **Do:** extend the `gcsim:verify-config` harness so compiled rotations are fed to real
  gcsim at the pin, and add a **cycle-count** assertion: read `statistics.character_actions`
  back and require the rotation to have run more than once over the configured duration.
- **Accept:** a rotation whose first step is a burst runs many cycles; the same rotation
  compiled **without** gates runs once and **fails the gate**. Both of the D.2 failure modes
  are regression-tested rather than described.
- **Why it is its own task:** acceptance by gcsim is not evidence of correctness. Both ER-sweep
  failures produced configs gcsim accepted happily.

### [ ] R.4 — The API
- **Do:** CRUD under `/api/v1/rotations`, owner-scoped, plus `POST /rotations/{id}/compile`
  returning the emitted config for inspection.
- **Accept:** every new route added to the 401 sweep **in the same commit** —
  `test_the_sweep_covers_every_owned_route` fails otherwise, which is the point; `openapi.json`
  regenerated; the contract test green.

### [ ] R.5 — The editor
- **Do:** a page to build a rotation: pick a team, add steps, reorder, set `repeat`, save.
  Uses `catalogue-list.ts`'s error discipline and the Mitya tokens.
- **Accept:** reachable from the shell nav — `app.routes.spec.ts` fails otherwise; a failed
  load is surfaced rather than rendered as "no results"; the compiled config is viewable, so a
  user can see what their rotation became.

### [ ] R.6 — Wire it to the run corpus
- **Do:** a saved rotation feeds `sim_context.context_key` and the D.1 corpus, so a rotation
  and a team together identify a cached run.
- **Accept:** two rotations differing by one step produce different context keys; the same
  rotation reordered produces a different key — `context_key` already treats rotation order as
  significant, and this proves the compiler agrees.

---

## Open questions

- **OQ-R1** — a rotation belongs to a team, or to a build. Decide in R.1.
- **OQ-R2** — a saved rotation naming a character the team no longer has. Decide in R.1.

## Not in this chunk

**Optimizing the rotation.** `DESIGN_client_optimizer.md` §3.5 warns it reopens the entire
client-side cost argument, which rests on the rotation being an input. Authoring is not
optimizing.

**Timing controls** (`wait`, `delay`) — see DESIGN §2. If a rotation genuinely needs them that
is a finding to bring back to the DESIGN, not a field to add ahead of evidence.
