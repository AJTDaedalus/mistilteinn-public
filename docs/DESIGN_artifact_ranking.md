# DESIGN: ranking one artifact

**Status: replanned 2026-09-05 against issue #291; nothing built yet.** The 2026-08-29 rulings
(`DECISIONS.md` §22) stand unchanged. Four further questions were answered on 2026-09-05 —
**§8** — and they widen the feature: the issue asks for a number this document did not plan for.
`docs/TASKS_artifact_ranking.md` is the task list. Owner request (2026-08-29): *"make a plan for implementing
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


---

# The 2026-09-05 replan — issue #291

Filed from Discord by `discord-triage` and read at
[#291](https://github.com/AJTDaedalus/mistilteinn/issues/291):

> *"Add an 'artifact ranker' alongside the optimizer, like Fribbles, that calculates and
> presents the probability an artifact, at max level, would be an upgrade for the selected
> team/rotation/build. Potential challenge: this should assume that you can move other
> artifacts, so the 'best build with this artifact leveled up' vs current for the % gain."*

## 8. Four rulings, and the one that widens the plan

| | ruling (owner, 2026-09-05) |
|---|---|
| **OQ-A5** | **Both engines.** A fast single-slot delta for every piece, *and* a pinned re-search for one piece on demand. |
| **OQ-A6** | **Through the distribution.** OQ-A4 is in this plan rather than a later one. |
| **OQ-A7** | **`/artifacts`**, with its own build picker, calibrating on demand and reusing the warm recipe cache. |
| **OQ-A8** | **Calibrate the other set on demand** when a candidate would complete a 4-piece the build does not wear. |

And a standing restatement, owner 2026-09-05: *"We should aim, like we did for optimize, to do
what Fribbels/GO do but with gcsim as the engine."* That is OQ-A1 unchanged, and §4's closing
sentence is the guard on it: the loop runs the **recipe** — gcsim's own published per-hit
decomposition, replayed closed-form — and gcsim itself runs only to calibrate. Anything that
reaches for gcsim *inside* the ranking loop has left the design.

### 8.1 OQ-A5 is the one this document did not plan for

Everything in §§1–7 scores a piece by **substituting it into its slot and leaving the other four
alone**. `frontend/src/app/sim/artifact-score.ts` already implements exactly that — `scoreArtifact`
and `scoreForSlot`, tested, and with **no caller**, carrying a header comment that says to delete
them if this feature stayed unbuilt. They are the fast half and they survive.

**The issue asks for something else.** *"Assume that you can move other artifacts"* is a
**re-optimization with the piece pinned**: the best five-piece build that contains this artifact,
against the best five-piece build that does not. The two differ by orders of magnitude:

| question | mechanism | cost |
|---|---|---|
| "what is this piece worth in its slot?" | one `evaluateRecipe` per candidate | **~12 µs** per piece — 28 ms for 2,370 |
| "what is the best build containing this piece?" | `searchRecipe` with that slot pinned | **~5 s** per piece (`COMBINATION_BUDGET_SECONDS`) |

Five orders of magnitude. A sortable inventory column can only be the first; the second can only
be a deliberate act on one piece. **So the feature is both**, and the relationship between them is
the design:

- the **column** triages — it is complete, sortable, and understates any piece that would only pay
  off if the rest of the build moved;
- the **deep dive** settles — it is the number #291 actually asks for, and it is spent one piece at
  a time, on a piece the column already made a case for.

**The column's understatement is directional and must be labelled as such.** A single-slot delta is
a *lower bound* on the pinned-re-search delta, because the re-search may keep the same four
neighbours — it never does worse. That is a fact worth printing next to the number rather than a
caveat to bury: *"at least +N%; ask for the full search to see if it is more."*

### 8.2 What Fribbels offers, and the half it does not

Both audits are committed and were read at the source pin — `docs/RESEARCH_fribbels_hsr.md`
(`futureScore.ts`, `estTbp.ts`, `scoreFormatting.ts`) and `docs/AUDIT_fribbels_handson.md` (driven
against the owner's own 1,712-relic HSR export, 27 grid columns, five score columns). Their five
per-relic columns — *Score · Avg Potential · Max Potential · Reroll Avg · Δ Reroll Avg* — map onto
§5's four numbers plus a delta, and `AUDIT_fribbels_handson.md` names **Δ Reroll Avg** as the one
that turns a sortable list into a decidable one.

**But every one of those five is a single-piece score against a weights vector.** Fribbels does not
re-run its optimizer per relic, and its own optimizer on that inventory quoted *"10:42:43 left"*.
So **the pinned re-search has no reference implementation in either tool** — it is this repo's
addition, and it is affordable here for a reason neither has: the recipe evaluator makes a whole
search closed-form after one calibration.

**That claim is no longer an inference.** A.1 drove Genshin Optimizer 10.38.1 against the owner's
own export, and its Artifact Upgrader prints the limitation itself, in an info panel above the
results:

> *"The Artifact Upgrader identifies artifacts with high potential to boost the Optimization
> Target's value, guiding you to artifacts worth leveling up. **As it only swaps one artifact at a
> time, for the best overall build across all artifacts, use the main artifact optimizer.**"*

GO has both tools and **no bridge between them** — a user who wants the best build containing a
piece must leave the ranker and set a search up by hand. `docs/AUDIT_go_handson.md` §1. The bridge
is the part worth building that neither reference has, and it is A.12.

The parts that *are* worth copying, and are: the five-number shape (§5), the letter grades
(`scoreFormatting.ts`, 5% steps), heat-shaded numeric cells, and the "who wants this piece" bucket
panel across the roster. `AUDIT_fribbels_parity.md` §2's outstanding row — *a per-piece score* — is
closed by the same work.

### 8.3 The distribution, and where its numbers come from

OQ-A6 puts `docs/RESEARCH_genshin_optimizer_scoring.md`'s model in scope. GO's method is a
**delta method** over a three-level lazily-expanded tree with **exact enumeration at the leaves**
and no Monte Carlo — §5's "apparent conflict" section is the argument that our objective satisfies
what that method assumes.

**Its inputs are not all in a committed primary source, and this was checked rather than assumed.**
Measured 2026-09-05 against the pinned AnimeGameData capture:

- `ReliquaryAffixExcelConfigData` (350 rows, at `5445617e33b2`) carries
  `id / propType / group_id / propValue / depotId` — **no weight field.**
- `ReliquaryMainPropExcelConfigData` (66 rows) carries `id / propDepotId / propType / affixName` —
  **no weight field.**
- `ReliquaryExcelConfigData` does have a `weight`, and it is an **item-drop weight on the artifact
  entry** (`weight: 1`), not a substat appearance weight. A plan that grabbed it because the key
  matched would be confidently wrong.

So the **substat appearance weights** (`hp/atk/def 6`, `hp_/atk_/def_/eleMas/enerRech_ 4`,
`critRate_/critDMG_ 3`) and the **main-stat probabilities** are, in GO too, quoted from
`libs/gi/upopt/src/consts.ts`, whose own comment cites the fandom *Artifact/Distribution* page.
They are a **named secondary source**, and this repo already has a precedent for shipping one
openly rather than pretending otherwise: `gcsim_config.ENERGY_DRIP`, five community configs, cited
in place.

**And the owner's export cannot be used to ground them.** That was the attractive alternative, and
it was tested before being written into a task. Restricted to flowers at +0 — the least-selected
cut available, 319 pieces, 1,061 lines — the observed line frequencies are:

| stat | published weight | observed |
|---|---:|---:|
| `eleMas` | 4 | 13.29% |
| `enerRech_` | 4 | 13.10% |
| `critDMG_` | 3 | 12.25% |
| `atk` | 6 | 11.97% |
| `critRate_` | 3 | 11.78% |
| `def` | 6 | 11.40% |
| `atk_` | 4 | 10.27% |
| `hp_` | 4 | 8.11% |
| `def_` | 4 | 7.82% |

Inclusion probability under a weighted draw without replacement is **monotone in weight** — it is
not proportional to it, which is why a naive percentage comparison would be the wrong test, but the
*ordering* is forced. Weight 3 above weight 6, and `hp_` and `def_` (weight 4) at the bottom,
violates that ordering. So either the inventory is still selected at +0 — a kept +0 is a kept piece
— or the published table is wrong. **Either way this corpus cannot be the source**, and A.9 exists
to say so in a test rather than leave the next reader to rediscover it.

### 8.4 OQ-A8 and the cost it admits

Calibrating a set on demand is ~3.2 s of gcsim per 4-piece state, cached client-side by
`recipe-cache.ts` under a key that already names the gcsim pin, build, rotation, set, ER, seed and
probe. So the honest shape is: **the column scores what is calibrated, and offers to calibrate what
is not** — a piece from an uncalibrated set shows *"needs calibration"* and a button, never a
number computed under the wrong recipe. §6's third refusal already demands this; OQ-A8 says the
button exists rather than the refusal being the end of it.

### 8.6 §6's three refusals, revisited by building them (A.6, 2026-09-05)

§6 names three things that must never be silent. Implementing them, **two dissolved and one
moved**, and that is worth recording rather than quietly not doing:

| §6 says | what building it found |
|---|---|
| a piece whose **rolls could not be decomposed** must report no score | Projecting *future* rolls needs the line count and the committed schedule, both exact, and **never the history**. `substat_rolls`' 85 / 11.5 / 3.5 exact / estimated / unknown split governs the roll bars on the inventory card and does not reach the projection at all. The refusal that genuinely applies is a rarity-and-level the schedule does not cover — `RankRefusal.noSchedule` — plus a rarity with no ladders. |
| a **wrong main stat** must not be a low number that looks comparable | True of a *weights* model, which cannot represent a main stat's contribution and so collapses the grade to 0%. **Not true here.** An ATK% goblet run through the real damage chain produces its real, correctly lower damage, and that number *is* comparable. So the main stat is reported as a separate fact for filtering, never folded into the score and never used to void it. This is the clearest case so far of the engine ruling buying something a weights table cannot. |
| a score derived against an **unmodelled passive** must carry that caveat | Names a caveat from a different subsystem: `unmodelled_passives` belongs to `weapon_comparison`, which runs the Chunk F single-hit chain. A recipe is calibrated by gcsim, which implements the kits, so it carries no unmodelled passives by construction. **The rule behind it is still right and the recipe has its own two** — `meta.unstable` and `meta.staleConversions` — and both already exist because dropping them went wrong once: they were returned beside the recipe rather than on it, a cached recipe came back with its instability forgotten, and the page then affirmatively called the ranking sound. They travel with every ranked row. |

**The grade needed a denominator §5 did not specify.** A percentage has to be a percentage *of*
something, and Fribbels' is "of an ideal relic" under its weights. Ours is the damage of a
**synthetic ideal piece with the same main stat** — four lines chosen to maximise damage,
enumerated rather than picked by substat weight, every roll at the top tier. Synthetic rather
than "the best piece you own", so an *S* means the same thing on a fresh account and a finished
one.

That arithmetic went wrong on the first attempt and a test caught it: the draft spent upgrade
rolls *creating* the four lines, when in Genshin the substats come with the artifact and all five
upgrades are free on top — one line can reach **six** rolls. It graded a real maxed piece at
**117 % of "ideal"**, which is the sort of number a normalisation with no ceiling test produces
quietly.

### 8.7 What driving the page found, and none of it failed a test (A.8, 2026-09-05)

`CLAUDE.md`'s standing entry is that a green suite here is *"good at formulas and blind to
wiring"*, and #240 is its worst case — a weapon picker, an integration test, unit tests on the
search loop, and two weapons returning **1,376,712.1** to the decimal because the client never
sent the id. This chunk reproduced the pattern three times in one afternoon, and **1,078
frontend tests passed before and after every one of them**:

| what a real run did | why nothing caught it |
|---|---|
| **`422 Unprocessable Entity`** from `POST /rotations/{id}/context-key`: *the build is not in the rotation's team.* The picker offered every build against every rotation — a 75 × N cross-product, most of which does not exist. | No test made that call. `/optimize` had already solved this with `buildsInTeam`, and the panel invented a second answer instead of reaching for the shared one. |
| **The baseline recipe never calibrated**, so `noFourPiece` came back `null` and nothing could be scored. `calibrateAll` was passed `targets: []`. | The baseline is **a target, not the absence of one** — `/optimize`'s own comment says *"it is not optional and never was: every combination that reaches no 4-piece is scored against it, so a search without it can rank nothing."* The service's refusal caught it correctly; it just had no caller until a browser ran one. |
| **Every build read `"Furina —"`**, a name followed by an em-dash and nothing. | All 84 builds in the local database have an **empty `name`**. `shared/team-scope.buildOptions` had already decided the label — character name, with `C2 · Mappa Mare · R5 · Lv90` as detail — and never uses `name`. |

The third is `FINDINGS_frontend_validation.md`'s lesson exactly: **a pattern nothing owned, so
every page decided separately.** The fix in all three cases was to use what `/optimize` already
uses rather than to write something new.

**The picker is now rotation-first**, because a rotation names a team and only that team's four
builds can be asked about. That is one control fewer than `/optimize`'s team-then-rotation-then-
build, and it makes the invalid combinations unrepresentable rather than merely rejected.

### 8.5 What is still not settled

Two things, recorded here rather than guessed at in a task:

- ~~**OQ-A9 — does the deep dive run against the whole inventory or a filtered pool?**~~
  **Answered 2026-09-05: a filtered pool, because the whole inventory does not terminate.** The
  uncapped pinned search did not finish in 300 s and the browser sat in it for seven minutes. The
  dive trims each slot to its best 24 pieces *for this build*, keeps the pinned piece regardless
  of where it ranks, and reports both numbers on screen — a best-of-this-pool is not a proof, and
  `searchRecipe`'s `isExact: true` is a claim about the pool it was handed.

  **`RESEARCH_pinned_search_cost.md`'s own first draft got this wrong**, by reasoning from a
  `budgetK` layer `searchRecipe` does not have. That is §7's mistake — inferring a cost from
  something adjacent — repeated inside the document written to avoid it. Driving the feature is
  what caught it.
- **OQ-A10 — what "% gain" is a percentage of.** #291 says *"vs current for the % gain"*.
  Against the build as currently equipped is the obvious reading and the one A.11 implements. It is
  written down because *against the best build without this piece* is a different and defensible
  number, and the two diverge exactly when the current build is not optimal — which for a piece
  someone is asking about is most of the time.
