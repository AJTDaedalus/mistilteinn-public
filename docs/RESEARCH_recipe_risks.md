# RESEARCH: three things that would have shipped wrong

**Question:** before implementing `TASKS_recipe_surface.md`, what in the design is wrong?

**Answer: three things, all measured, all of which would have produced confidently wrong
numbers rather than obvious failures.** Two invalidate `DESIGN_gcsim_optimizer.md` §3.1's
"calibrate at zero artifact stats" as written.

---

## 1. A zero-stat calibration lands on a plateau no real candidate occupies

`DESIGN_gcsim_optimizer.md` §3.1: *"calibrate with the sets equipped but with zero artifact
stats"*. **Energy Recharge is an artifact stat**, so a zero-stat calibration runs at the
character's **base ER**, and `RESEARCH_calibration_cache.md` already measured that burst count
is a **step function** of ER.

Same rotation, same seed:

| calibration | hits | **burst instances** |
|---|---|---|
| zero artifact stats (base ER) | 221 | **2** |
| a plausible candidate, `er=0.45` | 239 | **3** |
| a heavy ER candidate, `er=1.0` | 239 | **3** |

**The recipe would describe a rotation with one fewer burst than the build being scored** —
and the burst is the largest hit. Not a rounding error: a different rotation.

### Why G.5's gate cannot see it

Both fixtures — `rotation_gated` and `rotation_gated_nostats` — sit at **base ER**. Neither
carries an ER substat, so the prediction was exact *within one plateau* and the plateau problem
was invisible. **Third time in this work that a fixture with nothing to find could not fail.**

### The fix

Calibrate at an ER **representative of the plateau being scored**, not at zero. ER is then
**structural, not additive**: it is baked into the calibration and a candidate's own ER is used
to *check which plateau it is on*, never added as a damage stat.

---

## 2. Calibrating with a set double-counts its 2-piece bonus

A calibration must include the 4-piece set, because 60 of 60 four-piece bonuses are conditional
and only gcsim can apply them. Equipping the set also applies its **2-piece**:

| calibration | `cryo%` in `final_stats` |
|---|---|
| with `Blizzard Strayer` | **0.27** |
| without | **0.12** |

The difference is exactly **0.15** — the 2-piece's +15 % Cryo DMG, **baked into the recipe**.

`searchRecipe`'s `score()` then builds its stat pools from the candidate's pieces **plus every
matching `SetBonus.stats` tier**. So the 2-piece would be applied **twice**.

### The fix

**A recipe calibrated with set X carries X's 2-piece and 4-piece; the kernel must add neither.**
It still adds the 2-piece of any *other* set in the combination — a 2+2 split has a second set
whose static bonus is not in the calibration. That is a rule the search has to apply per
combination, not a global switch, and `DESIGN_recipe_surface.md` §2's "2-piece bonuses stay
kernel stat pools" is true only of the sets the calibration does **not** hold.

---

## 3. One recipe cannot score a whole inventory

ER comes from artifacts, so **candidates within a single search span plateaus**. Sweeping the
artifact-borne ER a real inventory can produce:

| artifact ER | burst count |
|---|---|
| +0 % to +10 % | **2** |
| +20 % to +90 % | **3** |

Two plateaus, and the boundary is **low** — an ER sands alone clears it. So ER-poor and ER-rich
candidates genuinely have **different rotations**, and scoring both against one recipe
overstates whichever side it was not calibrated for.

### The fix, and what it costs

Calibrate per **(4-piece set × ER plateau)**, and let the search select by the candidate's own
total ER.

That multiplies the budget: `(S + 1) × P`. With `S ≈ 12` and `P = 2` that is ~26 calibrations,
~3 minutes — still a one-time job, but **three times** `DESIGN_recipe_surface.md` §2's estimate.

It also adds a step the plan does not have: **boundary discovery**. The plateau edges are a
property of the rotation and must be found by sweeping ER before any recipe is calibrated —
about ten `sample()` runs, ~30 s. `stabilityFrom` detects that a build is *on* a transition; it
does not say *where* the transitions are.

---

## 4. What this does not change

**The cost of *evaluating* a recipe.** That is still ~0.02 µs per hit and ~1.05× a single-hit
score. Every one of these is a **calibration-time** problem — more calibrations, and each one
carrying stats it previously did not. The inner loop is untouched.

**The direction.** Nothing here argues against the approach; all three are fixable with
measurements already in hand. But two of them were in the *design*, not the code, and both
would have produced numbers that looked entirely reasonable.
