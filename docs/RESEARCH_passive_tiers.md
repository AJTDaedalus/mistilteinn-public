# RESEARCH: tiering gcsim's weapon passives by implementation (P.1)

**Question:** N.5 tiered weapon passives with a regex over English refinement prose and said so
— an explicit proxy. What do the *implementations* say?

**Answer: far more is reachable than the prose survey suggested — 58 weapons rather than 5 —
and the reason is that English describes as "conditional" what gcsim implements as a stateless
gate on attack tag**, which this repo's chain already expresses as `Hit.scope`.

Read at the pin (`docs/CROSSVAL_gcsim.md`), over `internal/weapons/**`: **231 weapons with a
`NewWeapon`.**

## The tiers

| tier | count | what it needs |
|---|---|---|
| **1 — static + stat-conversion** | **44** | permanent stat mods, tag-gated DMG bonuses, flat damage from a stat. Nothing new. |
| **1c — static, gated on character state** | **14** | the above, plus a condition the chain cannot evaluate: current HP ratio, energy, shields. **Portable behind a stated assumption.** |
| 2 — rotation-evaluable | 93 | durations, stacks, cooldowns. Resolvable against the compiled action list; not in this chunk. |
| 3 — target state | 34 | aura, enemy type, weak spots. `KernelTarget` cannot express these. **Out of scope.** |
| 0 — no damage primitive | 46 | healing, particles, movement. Genuinely inert for the damage chain. |

## Why this differs from N.5 by 10×, and why both were right

N.5 said **5** passives were "expressible in the chain as it stands". That was **expressible
with no new code**, and it was accurate. This says **58 need no new chain primitive** — the
difference is an evaluator, not a new damage model.

The deeper reason the prose survey undercounted: a refinement text reading *"increases
Elemental Skill DMG by 16 %"* looks conditional in English, and gcsim implements it as a
**permanent** `AddAttackMod` whose `Amount` returns `nil` unless the attack tag matches. That
is a `switch` on tag, not a timeline — and `Hit.scope` is the same gate. **Prose cannot
distinguish "conditional on when" from "conditional on which hit"; the implementation states
it in one argument.**

The signal that does most of the work is `modifier.NewBase(name, -1)`. **`-1` is permanent; a
positive expiry is a timed buff.** One argument separates tier 1 from tier 2.

## What tier 1c costs, concretely

`Staff of Homa` — `internal/weapons/spear/homa/homa.go`:

```go
mHP[attributes.HPP] = 0.15 + float64(r)*0.05        // permanent
atkp := 0.006 + float64(r)*0.002
lowhp := 0.008 + float64(r)*0.002
per := atkp
if char.CurrentHPRatio() <= 0.5 { per += lowhp }    // character state
mATK[attributes.ATK] = per * maxhp                  // HP → ATK conversion
```

The HP% and the base HP→ATK conversion are unconditional. **Only the below-50 % bonus needs an
assumption**, and gcsim's own default is that it does not apply. So 1c is portable with the
conditional part defaulting off and **named**, rather than silently assumed either way.

**1c contains `Staff of Homa` and `Engulfing Lightning`** — two of the most-equipped weapons in
the game, both **stat-conversion** passives that change which artifacts win. Leaving them out
would gut the point of the port.

## Limits of this survey, stated

- **It is a regex over Go.** A better proxy than a regex over English, and still a proxy.
  **Every weapon must be read before it is ported** — that is P.3's job, and P.4 is what makes
  the reading provable.
- **Directory names collide across weapon types.** `prototype` appears in both tier 1 and
  tier 1c because `sword/prototype` and `catalyst/prototype` are different weapons. The
  per-row data keys on the full path; only the summary lists collapse.
- **Tier 2's 93 is the biggest bucket and is not junk.** It is where the stacking and timed
  buffs live, and the compiled-rotation argument in `DESIGN_passive_port.md` §5 says it is
  reachable. It is simply not first.

## What this changes for the plan

**Tier 1 + 1c is 58 of 231 — 25 %** — and it is the quarter that contains the
stat-conversion passives, which are the only ones that change *which artifacts win*. The rest
mostly scale a build uniformly and leave the artifact ranking intact.

So the first deliverable is worth more than its share suggests: **the optimizer stops being
wrong for `Redhorn Stonethresher`, `Staff of Homa`, `Engulfing Lightning` and
`Primordial Jade Cutter`** rather than merely becoming more precise.
