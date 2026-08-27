# RESEARCH: the optimizer cannot see 4-piece set bonuses

**Question:** `DESIGN_gcsim_optimizer.md` §3.1 said a recipe is calibrated per artifact-set
combination, so conditional set bonuses stay inside it. **How many sets actually need that,
and what does the optimizer do about them today?**

**Answer: 60 of 65 sets have a conditional 4-piece bonus, and the kernel scores every one of
them as zero.** The 2-piece tier is almost always a plain stat, so the split is unusually
clean — and it collapses the combinatorics from *"one calibration per set combination"* to
*"one per 4-piece state"*.

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
| sets with at least one conditional tier | **65 / 65** |
| **sets with a conditional 4-piece** | **60 / 65** |
| sets with a conditional 2-piece | 9 / 65 |
| sets where both tiers are conditional | 9 |

**Every set in the game has a tier the optimizer cannot see, and for 60 of them it is the
4-piece** — the tier that decides what a build *is*. `Blizzard Strayer`, `Archaic Petra`,
`Bloodstained Chivalry` and 57 others contribute exactly **zero** to a search's score.

So the optimizer currently ranks four-piece sets as though their headline effect did not
exist. That is not a precision caveat; for a `Blizzard Strayer` cryo build it is most of the
reason to wear the set.

## 3. Why this makes the recipe approach cheaper than DESIGN assumed

`DESIGN_gcsim_optimizer.md` §3 keys calibration by *"artifact-set combination"*. Taken
literally that is one calibration per reachable set state — with S sets present, roughly
`S²/2 + 2S + 1` of them, because 2+2 splits multiply.

**The measurement removes the square term.** 56 of 65 two-piece bonuses are **plain static
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

- **That a 2-piece bonus really is kernel-representable.** 56 of 65 have static props, and
  *having a static prop* is not the same as *having no conditional part*. A tier could carry
  both. The check is the probe technique applied to sets: calibrate with and without, and see
  whether the difference is a plain stat delta.
- **That the 9 sets with a conditional 2-piece are handled.** They need the same treatment as
  a 4-piece, which makes their states `S₂ + 1` on top.
- **That a set's effect does not depend on the rotation in a way one calibration cannot
  hold.** `Blizzard Strayer`'s crit bonus applies against frozen opponents; if the rotation
  freezes for only part of its length, the calibration captures the *average over that
  rotation*, which is correct for that rotation and not transferable to another. That is
  already true of the whole recipe, and is why calibration is keyed by rotation.

## 5. What this does not fix

**Nothing here helps the single-hit search.** It has no way to represent a conditional bonus,
which is why the props are skipped in the first place. The fix is available only to a search
scoring against a recipe — so this is an argument for `searchRecipe` reaching the page, not
just for it existing.
