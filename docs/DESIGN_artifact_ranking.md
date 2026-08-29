# DESIGN: ranking one artifact

**Status: open questions answered 2026-08-29 (`DECISIONS.md` §22); nothing built.** Owner request (2026-08-29): *"make a plan for implementing
artifact ranking like they do for relics. It's similar to optimization, but has more to do with
[artifact] potential for a rotation than picking the best set of 5 artifacts, and applies to
lower level artifacts too (like the probability a lvl 0 artifact will be an upgrade if
levelled)."*

**Branch policy.** Work happens on `feat/artifact-ranking`, never on `dev` or `main`; `dev` is
updated only by PR. Task 0 of the TASKS file is the branch-setup gate.

Prior reading, both written 2026-08-29: `docs/RESEARCH_fribbels_hsr.md` (how Fribbels does it,
with its source cited) and `docs/AUDIT_fribbels_parity.md` §5 (why we cannot answer this today).

---

## 1. The two questions, and why they are different

A player holding a new drop asks one of two things, and they need different machinery:

1. **"Is this any good?"** — a score for the piece *as it stands*. Cheap; a weighted sum.
2. **"Is this +0 worth levelling?"** — the piece's **potential**, given rolls it has not had
   yet. This is the one the owner named, it is the harder half, and it is where a tool either
   earns trust or quietly makes things up.

Both are **per character**. A CRIT DMG circlet is a prize for Ayaka and litter for Zhongli, so
any score that is not asked on behalf of somebody is a score about nothing.

## 2. What we already have

More than I expected, and it is worth being precise, because the plan below is mostly *joining
existing pieces* rather than building new ones.

| piece | where | what it gives |
|---|---|---|
| roll decomposition | `app/services/substat_rolls.py` | how many rolls each substat has had, and each roll's **tier** (0–3). 85.0% exact, 11.5% estimated, 3.5% unknown on the owner's real export |
| the upgrade schedule | `app/data/snapshot.py:artifact_upgrade_levels` | 5★ gains a roll at +4/+8/+12/+16/+20; a 3★ caps at +12 and gets three |
| initial substat counts | `substat_rolls._INITIAL_SUBSTATS` | 5★ starts with 3 or 4 lines, 4★ with 2 or 3 |
| roll tier values | `substat_rolls._tiers_for` | the four values a roll of each substat can take, per rarity |
| a real damage chain | Chunk F, `/explain` | **the thing Fribbels does not have** — see §4 |

So the inputs to a potential model exist and are already crossvalidated. What is missing is the
**weights**, and that is the whole design question.

## 3. Remaining rolls — the arithmetic, in Genshin's terms

Fribbels computes (`futureScore.ts`, read at the pin):

    remainingRolls = ceil((maxEnhance − enhance) / 3) − (4 − substats.length)

HSR relics gain a roll every three levels. **Genshin's are every four**, and the schedule is
already a committed snapshot rather than arithmetic, so the port is:

    upgrades_left = |{ L in artifact_upgrade_levels(rarity) : L > level }|
    new_line      = 1 if len(substats) < 4 else 0      # a 3-line piece spends one upgrade
    remaining     = upgrades_left                       # the new line is itself one of them

A +0 five-star with three substats has **five** upgrades ahead, one of which creates the fourth
line. With four substats it has five that all land on existing lines. That difference is most of
why a three-liner is a lottery ticket and a four-liner is a known quantity — and it falls out of
the schedule rather than needing a special case.

## 4. Where the weights come from — the decision this document exists to make

Fribbels uses **per-character substat weights**: numbers, set by the user or taken from a
community preset, saying how much a roll of CRIT DMG is worth against a roll of ATK%.

**We should not copy that, and we are unusually well placed not to.**

Curating 150 characters' weight tables from community guides is *exactly* the fabricated-citation
failure `CLAUDE.md` names as fairy's worst, and `TASKS_weapon_passives.md` already rejected the
same shape for weapon passives — deriving 237 conditions from refinement prose — in favour of
letting gcsim answer.

### OQ-A1, answered — and this section's own proposal was overruled

This document first proposed finite differences over the **Chunk F single-hit chain**: add one
roll of CRIT DMG, re-run the chain, take the difference. Measured rather than asserted, which
was the right instinct. The owner's ruling goes further, and asks the better question:

> *"Calculated via our gcsim-like optimizer. It should be the engine beneath ranking too. 'How
> much potential does this artifact have given this character in this team with this rotation?'
> With the same efficiency tweaks we did for optimize."*

**A single-hit derivative cannot see a team buff or a rotation's shape**, and those are most of
what decides whether Energy Recharge or CRIT DMG is worth more on a given piece. A Furina in the
party changes the answer; so does whether the rotation gets the burst off. Scoring against one
hit would produce a confident number for a question nobody asked — the failure this repo names
most often.

**And the performance shape already exists.** `sim/recipe-eval.ts` calibrates a recipe *once per
4-piece state*, after which evaluating one candidate's stats is cheap. That is exactly the
amortisation ranking needs: the expensive part is paid per *search*, not per artifact, so a whole
inventory can be scored off one calibration. `RESEARCH_recipe_cost.md`'s **7.84 s** is the cost of
a calibration, not of an evaluation, and conflating the two is what made the first draft reach for
the cheaper, wronger engine.

So **ranking is not a new engine.** It is the optimizer's evaluator asked a different question:
instead of *"which five pieces score highest"*, *"what does this one piece score, and what could
it score once levelled"*.

**What still needs measuring in Task 1** is not "is the chain fast enough" but *how many
evaluations a full inventory costs at one calibration*, and whether the result is cached per
`context_key` or recomputed. That is a number, and nothing gets built on an assumed one.

**Diminishing returns fall out of this for free**, which the derivative approach could not manage:
evaluating the recipe at the piece's *projected* stats already accounts for CRIT Rate passing
100%, because the evaluator is the real damage function rather than a local slope.

## 5. What to report — four numbers, and none of them a single grade

Following Fribbels' shape, which is the right shape:

| number | meaning |
|---|---|
| **current** | the piece as it stands |
| **average** | expected value of the remaining rolls |
| **best** | every remaining roll on the highest-weighted substat, at the top tier |
| **worst** | every remaining roll on the lowest-weighted substat, at the bottom tier |

*Average* starts as Fribbels' deterministic expected value — remaining rolls spread evenly
across the eligible substats at the mid tier — because it is cheap and is enough to sort a list
by. **It is superseded by the distribution once that lands** (OQ-A4 below), at which point the
average becomes that distribution's mean rather than a separate rule, and the two cannot
disagree.

### OQ-A4, answered — a distribution, following Genshin Optimizer

**Fribbels' deterministic average is not enough.** The owner's ruling:

> *"Check Genshin Optimizer… It shows a distribution per artifact. That's a little better,
> yeah."*

So the fifth number is a **distribution over outcomes**, not a point estimate — which is a
genuinely different computation from the four above. It needs the substat draw model: which
lines can appear, drawn without replacement, weighted by the pool, across the remaining
upgrades. `docs/RESEARCH_genshin_optimizer_scoring.md` is the audit of how GO does it.

**Still last, and still separately.** It remains the largest new piece and the one with no
crossvalidation oracle behind it — everything else in this plan is the optimizer's evaluator,
which is checked against gcsim. GO keeps its probability model in one place rather than
sprinkling it, and that separation is worth copying whatever the model turns out to be.

### The apparent conflict between A1 and A4, and why there isn't one

The audit of GO ends with a warning: its method — a **delta method** at the coarse tree levels
(symbolic Jacobian, `f_cov = df·cov·dfᵀ`) and **exact enumeration** at the leaves, with no Monte
Carlo anywhere — needs an objective that is *differentiable and microsecond-cheap*. And it
observes that **gcsim is neither**.

That is true of gcsim and **not true of what A1 actually names.** A "recipe" in this repo is not
gcsim. `sim/recipe.ts` is a **transcription** of gcsim's own published per-hit decomposition —
`talent`, `total_scaling`, `bonus_dmg`, `cr`, `cd`, `def_mod`, `res_mod` — recomposed and
verified exact to **0.000e+00** across all 245 hits of a committed sample. gcsim runs once, to
calibrate; the loop then replays closed-form arithmetic at a measured **0.051 µs per hit**.

So the objective A1 selects is:

- **closed-form**, not a simulation;
- **deterministic** — crit is computed rather than rolled, a divergence taken deliberately in
  `CROSSVAL_gcsim.md` precisely so no Monte Carlo noise enters a deterministic evaluator;
- **microsecond-cheap**, comfortably inside what GO's method assumes;
- **smooth except for one clamp** — `effectiveCritRate` is `min(max(cr, 0), 1)`, so the function
  is piecewise-smooth in exactly the way a crit-rate cap makes GO's own objective
  piecewise-smooth. Not a new problem, and it has a known kink location rather than an unknown
  one.

**The two rulings therefore compose**, and this is the enabling fact for the whole plan: the
engine A1 chose is the differentiable cheap objective A4's method requires. Anything that later
reaches for *gcsim itself* inside the ranking loop has left the design.

## 6. What must never be silent

Three failure modes, each with a required behaviour:

- **A piece whose rolls could not be decomposed.** 3.5% of the owner's export. It must report
  *no score*, not a score computed from a guess. `SubstatAnalysis` already carries this
  distinction and a ranking that dropped it would be the `isExact` flag thrown away at the last
  step.
- **A wrong main stat.** Fribbels collapses the grade rather than docking it, which is right: an
  ATK% goblet for a Hydro DPS is not a slightly worse Hydro DMG goblet. Report it as a separate
  fact, not as a low number that looks comparable to a high one.
- **A weight vector computed against an unmodelled passive.** `weapon_comparison` already
  reports `unmodelled_passives`; a score derived from the same chain inherits the same caveat
  and must carry it forward rather than presenting a clean number.

## 7. Suggested task order

0. Branch setup.
1. ~~**Measure what a full inventory costs off one calibration.**~~ **Done — and the answer
   removes a whole layer from this plan.**

   Measured against the shipped `evaluateRecipe`, warmed, five runs, 2,370 candidates:

   | recipe size | whole inventory | per piece | per hit |
   |---|---:|---:|---:|
   | 50 hits | 5.8 ms | 2.43 µs | 0.049 µs |
   | 245 hits | **28.1 ms** | 11.85 µs | 0.048 µs |

   245 hits is the size of a real decomposed rotation (`RESEARCH_gcsim_calibration.md` §2), and
   **0.048 µs/hit independently reproduces the 0.051 µs/hit** that `sim/recipe.ts` documents —
   so this is the same evaluator at the same cost, not a stub.

   **So scoring an entire inventory costs about 28 ms**, and the four potential figures about
   112 ms. There is nothing here to cache and no `context_key` invalidation to design: it is
   cheaper to recompute than to store. That was the open question and it is closed.
2. **`remaining_rolls`** — pure, from the committed schedule. Small and fully testable offline.
3. **Score one piece through the recipe evaluator**, at its current stats. The smallest thing
   that proves the engine choice.
4. **current / average / best / worst**, with the three refusals of §6, plus grades (OQ-A3).
5. **`GET /artifacts/{id}/score?build_id=`**, then the inventory column and sort — which is also
   the fix for `AUDIT_fribbels_parity.md` §2, so the two land together.
6. **The distribution** (OQ-A4), last, with its own verification.

## Answered (2026-08-29, `DECISIONS.md` §22)

| | ruling |
|---|---|
| **OQ-A1** | The **rotation engine**, not a weights table and not the single-hit chain. "Given this character, in this team, with this rotation." |
| **OQ-A2** | Score against a **build** — its real weapon, constellation and talents |
| **OQ-A3** | **Numbers and grades.** The caveat that an "A" is per-character belongs in how they are labelled, not in refusing to have them |
| **OQ-A4** | A **distribution**, following Genshin Optimizer rather than Fribbels' point estimate |

Nothing is blocked on a decision. What remains unknown is a **measurement** — Task 1 — not a
choice.
