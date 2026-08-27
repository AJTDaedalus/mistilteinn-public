# RESEARCH: the optimizer cannot see 4-piece set bonuses

**Question:** `DESIGN_gcsim_optimizer.md` §3.1 said a recipe is calibrated per artifact-set
combination, so conditional set bonuses stay inside it. **How many sets actually need that,
and what does the optimizer do about them today?**

**Answer: every 4-piece bonus in the game is conditional — 60 of 60 — and the kernel scores
every one as zero.** The 2-piece tier is usually a plain stat (51 of 60), so the split is
unusually clean, and it collapses the combinatorics from *"one calibration per set
combination"* to *"one per 4-piece state"*.

## 1. What the kernel is given today

`builds.py:_bonus_stats` turns a set tier into kernel quantities, and skips any prop it cannot
map:

> A prop the mapping refuses is **skipped rather than guessed** […] a conditional affix's props
> are all `FIGHT_PROP_NONE`, and inventing a quantity for one would add a bonus the game does
> not give.

That refusal is right. The consequence is that **a conditional tier reaches the kernel as an
empty stat dict** — it contributes nothing, and nothing says so.

## 2. How much of the catalogue that is

| | |
|---|---|
| affix tiers in the catalogue | **125** |
| tiers with **no** static prop (conditional) | **74** (59 %) |
| sets carrying a 2-piece and a 4-piece tier | **60** |
| **sets with a conditional 4-piece** | **60 / 60 — all of them** |
| sets with a **static** 4-piece | **0** |
| sets with a conditional 2-piece | 9 / 60 |
| single-piece sets with no 2pc or 4pc at all | 5 (the `Prayers` circlets) |

**Every 4-piece bonus in the game is conditional, and the kernel scores every one as zero.**
`Blizzard Strayer`, `Archaic Petra`, `Bloodstained Chivalry` and 57 others contribute exactly
**nothing** to a search's score.

### The five that are not in that 60 are not exceptions

`Prayers for Destiny`, `Prayers for Illumination`, `Prayers for Wisdom`,
`Prayers to Springtime` and `Prayers to the Firmament` have **no 2-piece or 4-piece tier at
all** — one 1-piece tier each, and its effect is *"Affected by \<element\> for 40 % less
time"*. A circlet-only status-duration set with no damage component.

So they are not five sets with a working 4-piece; they are five sets with **no multi-piece
bonus to model**. An earlier draft said *"60 of 65"*, which reads as though five sets were
fine. **None are.**

So the optimizer currently ranks four-piece sets as though their headline effect did not
exist. That is not a precision caveat; for a `Blizzard Strayer` cryo build it is most of the
reason to wear the set.

## 3. Why this makes the recipe approach cheaper than DESIGN assumed

`DESIGN_gcsim_optimizer.md` §3 keys calibration by *"artifact-set combination"*. Taken
literally that is one calibration per reachable set state — with S sets present, roughly
`S²/2 + 2S + 1` of them, because 2+2 splits multiply.

**The measurement removes the square term.** **51 of 60** two-piece bonuses are **plain static
stats**, which the kernel already models as stat pools and already gets right. Only the
**4-piece** tier needs to be inside a calibration.

A combination has **at most one** 4-piece set. So the states are:

| state | count |
|---|---|
| 4-piece of some set | **S** (sets with ≥4 pieces in the inventory) |
| no 4-piece at all | **1** |

**S + 1 calibrations**, not `S²/2`. At ~3.2 s each plus a probe, a user with a dozen viable
4-piece sets is **under two minutes**, once per (team, rotation, weapon, ER plateau).

## 4. What must be verified rather than assumed

- **That a 2-piece bonus really is kernel-representable.** 51 of 60 have static props, and
  *having a static prop* is not the same as *having no conditional part*. A tier could carry
  both. The check is the probe technique applied to sets: calibrate with and without, and see
  whether the difference is a plain stat delta.
- **That the 9 sets with a conditional 2-piece are handled.** They need the same treatment as
  a 4-piece, which makes their states `S₂ + 1` on top.
- **That the `Prayers` sets stay out of the calibration budget.** A 1-piece set has no tier a
  five-piece combination can gain or lose by rearranging, and its effect is status duration
  rather than damage. Counting them as sets would add five states that change nothing.
- **That a set's effect does not depend on the rotation in a way one calibration cannot
  hold.** `Blizzard Strayer`'s crit bonus applies against frozen opponents; if the rotation
  freezes for only part of its length, the calibration captures the *average over that
  rotation*, which is correct for that rotation and not transferable to another. That is
  already true of the whole recipe, and is why calibration is keyed by rotation.

## 4a. What "60 of 60" is, and is not

It is an **exact** count of tiers that reach the kernel as an empty stat dict — the condition
under which `_bonus_stats` produces one is precisely the condition counted here, and
`scripts/verify_seed.py` now anchors it so a patch adding a static 4-piece cannot pass
unnoticed.

It is **not** a count of rankings the optimizer gets wrong. Some conditional bonuses are
healing, energy or shield effects that would contribute nothing to a *damage* ranking even if
they were modelled. **The two numbers are different sizes and the second is the one that
matters.** `TASKS_recipe_surface.md` R.7 measures it, and this section should be corrected if
the answer is much smaller.

## 5. What this does not fix

**Nothing here helps the single-hit search.** It has no way to represent a conditional bonus,
which is why the props are skipped in the first place. The fix is available only to a search
scoring against a recipe — so this is an argument for `searchRecipe` reaching the page, not
just for it existing.
