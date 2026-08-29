# DESIGN: ranking one artifact

**Status: proposed, nothing built.** Owner request (2026-08-29): *"make a plan for implementing
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

We have a damage chain that can explain itself. So:

> **A substat's weight is the measured derivative of the build's own damage with respect to
> that substat.**

Add one roll of CRIT DMG to the build, re-run the chain, take the difference. That is a finite
difference on a function we already have, it is *specific to this character with this weapon at
this constellation against this enemy*, and it is **derived, not asserted**. A weight that is
wrong is then a bug in the damage chain — which is crossvalidated to 1.3e-8 — rather than a
citation nobody can check.

It also composes with `/explain`: the same machinery that says *why the winner won* can say
*why this substat is worth more than that one on this build*, in the same units.

**Cost, honestly.** One evaluation per substat type, per build — six or seven — and the result
is a vector reusable for every artifact in the inventory. `docs/RESEARCH_recipe_cost.md`'s 7.84 s
figure is for a **gcsim rotation**, not for the Chunk F chain; the chain is the cheap path and
this is why it should be the one used. **This needs measuring in Task 1 before anything is built
on it** — if a chain evaluation turns out to be milliseconds, the weight vector can be computed
on demand; if not, it is cached per build and invalidated with `context_key`.

**Diminishing returns are real and are not modelled by a single derivative.** CRIT Rate above
100% is worth nothing, and the derivative at the current stat is not the average over five more
rolls. Task 3 addresses this by evaluating at the *midpoint* of the projected gain rather than at
the current value, which is the cheapest honest correction; a full curve is a later refinement
and should not gate the first version.

## 5. What to report — four numbers, and none of them a single grade

Following Fribbels' shape, which is the right shape:

| number | meaning |
|---|---|
| **current** | the piece as it stands |
| **average** | deterministic expected value of the remaining rolls |
| **best** | every remaining roll on the highest-weighted substat, at the top tier |
| **worst** | every remaining roll on the lowest-weighted substat, at the bottom tier |

*Average* follows Fribbels in being a **deterministic expected value**, not a simulation:
remaining rolls spread evenly across the eligible substats at the mid tier. Fribbels runs no
Monte Carlo here and neither should we — a distribution implies a precision the substat pool
does not support, and the honest spread is already carried by `best` and `worst`.

**The owner asked for "the probability a lvl 0 artifact will be an upgrade if levelled", which
is a fifth number and a genuinely different computation.** It needs the substat draw
distribution — which lines can appear, without replacement, weighted by the pool — and a
threshold to beat. It is the most valuable number here and the most likely to be wrong. **Task 5,
separately, and only after 1–4 are landed and checked.** Fribbels puts its probability model in
one place (its time-to-beat estimate) rather than sprinkling it, and that separation is worth
copying.

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
1. **Measure a Chunk F evaluation.** Everything downstream depends on whether a weight vector
   costs milliseconds or seconds. No code until this number exists.
2. **`remaining_rolls`** — pure, from the committed schedule. Small and fully testable offline.
3. **The weight vector** — finite differences over the damage chain, evaluated at the midpoint.
4. **current / average / best / worst**, with the three refusals of §6.
5. **`GET /artifacts/{id}/score?build_id=`**, then the inventory column and sort — which is also
   the fix for `AUDIT_fribbels_parity.md` §2, so the two land together.
6. **Upgrade probability**, separately, or not at all.

## Open questions for the owner

- **OQ-A1** Derived weights (§4) or user-editable ones? This document argues derived, and
  recommends *showing* the derived vector so a user can see the tool's reasoning — but not
  offering an override in the first version, because an override is a second source of truth.
- **OQ-A2** Score against a **build** (its real weapon and constellation) or against a
  **character** at some assumed baseline? Build is more honest and means an unbuilt character
  cannot be scored for.
- **OQ-A3** Grades (F→AEON) as well as numbers? Fribbels has them and they compress well, but
  a letter invites comparison across characters where none is meaningful.
- **OQ-A4** Is §5's probability number wanted enough to justify a substat-pool distribution
  model, which is the single largest new thing in this plan?
