# DESIGN: porting weapon passives from gcsim's Go

**Companion:** `docs/TASKS_passive_port.md`.
**Decision:** `docs/DECISIONS.md`, "Weapon passives are ported from gcsim's Go, not simulated
(2026-08-26)". **Evidence:** `docs/RESEARCH_gcsim_speed.md`.

## Branch policy

Per-task branches off `dev`, named `feat/<task>` or `fix/<task>`, merged to `dev` by PR after
review. **No direct commits to `dev` or `main`** — and note the specific way that went wrong
in W.6: **`gh pr merge --delete-branch` checks out the default branch**, so branch immediately
after a merge, before doing anything else. **Task P.0 is the branch-setup gate.**

---

## 1. Why porting, when a simulator already implements these

Because the simulator cannot be in the loop. `RESEARCH_gcsim_speed.md` measured the ceiling on
making gcsim faster at **~4×**, against the **~8,900×** gap to `SECONDS_PER_COMBINATION`. The
comparison page can afford gcsim; the artifact search never will.

And the gap is not cosmetic. **`Redhorn Stonethresher` makes DEF genuinely valuable and the
search will never once consider DEF.** The answer is wrong, not imprecise.

## 2. What a gcsim weapon passive actually is

Read at the pin, not assumed. `The Stringless`:

```go
char.AddAttackMod(character.AttackMod{
    Base: modifier.NewBase("stringless", -1),
    Amount: func(atk *info.AttackEvent, t info.Target) []float64 {
        switch atk.Info.AttackTag {
        case attacks.AttackTagElementalArt:
        case attacks.AttackTagElementalArtHold:
        case attacks.AttackTagElementalBurst:
        default:
            return nil
        }
        return m
    },
})
```

`Redhorn Stonethresher` — *"DEF is increased by 28 %. Normal and Charged Attack DMG is
increased by 40 % of DEF"*:

```go
defBoost := .21 + 0.07*float64(r)
val[attributes.DEFP] = defBoost
char.AddStatMod(...)                       // a permanent stat modifier

nacaBoost := .3 + .1*float64(r)
c.Events.Subscribe(event.OnEnemyHit, func(args ...any) {
    if atk.Info.AttackTag != attacks.AttackTagNormal &&
       atk.Info.AttackTag != attacks.AttackTagExtra { return }
    atk.Info.FlatDmg += char.TotalDef(false) * nacaBoost
})
```

**They decompose into a small set of primitives**, and refinement scaling is arithmetic on
`r` — `base + step*r` — which is data, not code.

## 3. The primitives map onto the chain that already exists

| gcsim | this repo |
|---|---|
| `AddStatMod` on any `attributes.*` | the stat aggregation `stat_calculator` already does |
| `AddAttackMod` gated by `AttackTag` | `Hit.base_damage_bonus`, gated by `Hit.scope` |
| `atk.Info.FlatDmg += …` | **`Hit.flat_damage`** |
| `char.TotalDef()` / `TotalAtk()` / max HP | computed stats, already available |
| scaling off a non-ATK stat | **`Hit.scaling_stat`** (ATK / HP / DEF / EM) |

**Every primitive Redhorn and Jade Cutter need already exists.** This is why the port is
tractable: `Hit` was built with `flat_damage` and `scaling_stat` for the talent chain, and
they are exactly what a stat-conversion passive needs.

## 4. Passives are data, not per-weapon code

**Standing architecture constraint (DESIGN §1 A6):** *characters are modelled as data a shared
evaluator reads, never per-character branches in the damage chain.* **The same rule binds
here.** 260 weapons must not become 260 branches — that is the structure the legibility goal
exists to forbid, and it is how gcsim itself ends up at 231 directories.

So a ported passive is a **record**: a list of effects, each with a condition and a
refinement-scaled amount, read by one evaluator. A new weapon is a new row, not a new code
path, and the evaluator is the only thing anyone has to be able to follow.

## 5. Tiers, by what the chain can express

**Tier 1 — static and stat-conversion.** No timeline, no target state. Scope-gated DMG
bonuses, permanent stat mods, flat damage from a stat. `The Stringless`, `Festering Desire`,
`"The Catch"`, `White Tassel`, `Rust`, `Redhorn Stonethresher`, `Primordial Jade Cutter`.
**Tier 1 contains every passive that changes which artifacts win**, which is why it is first.

**Tier 2 — rotation-evaluable.** Durations, cooldowns and stacks resolved against the
**authored, compiled action list**. Not Monte Carlo: the rotation is known, so a buff's uptime
over it is arithmetic. Larger, and it needs a decision about what "uptime" means for a hit
that lands mid-buff.

**Tier 3 — target state. Out of scope and staying there.** Aura, enemy type, weak spots.
`KernelTarget` is level, resistance, DEF reduction, DEF ignore, so these are **unaskable
questions rather than unported ones**, and growing it is a separate decision.

## 6. The port is proved, not trusted

**This is the whole reason the option is legitimate.** N.5 rejected a modifier model on
fabrication risk; reading Go removes the *derivation* risk but not the *transcription* risk —
a typo in `.21 + 0.07*r` is exactly as wrong as an invented coefficient and looks exactly as
plausible.

So **every ported passive gets a crossval case**: a committed gcsim run for a build wearing
that weapon, recomputed by this chain, matched inside the argued tolerance. A passive with no
crossval case is not ported, it is claimed. `tests/crossval` and `docs/CROSSVAL_gcsim.md`
already hold the machinery and the tolerance argument.

## 6a. The record shape (P.2), and OQ-P1 settled

**A passive is a list of effects.** Three kinds cover every Tier 1/1c weapon read so far:

| kind | means | chain term |
|---|---|---|
| `stat` | add to a stat, optionally as a fraction of another stat | stat aggregation |
| `damage_bonus` | a DMG bonus, gated on attack tags | `Hit.base_damage_bonus` |
| `flat_damage` | flat damage, as a fraction of a stat, gated on attack tags | `Hit.flat_damage` |

Every amount is `base + step × refinement`, which is how gcsim writes them
(`0.18 + float64(r)*0.06`), so refinement scaling is two numbers rather than a function.

Worked against the three weapons that between them use every kind:

```
The Stringless          effects: [ {damage_bonus, base .18, step .06, scopes [skill, burst]} ]
Redhorn Stonethresher   effects: [ {stat DEFP,     base .21, step .07},
                                   {flat_damage of DEF, base .3, step .1, scopes [normal, charged]} ]
Staff of Homa           effects: [ {stat HPP,      base .15, step .05},
                                   {stat ATK of HP, base .006, step .002},
                                   {stat ATK of HP, base .008, step .002, requires hp_below_50} ]
```

**No weapon-specific code path in any of them**, which is the constraint DESIGN §1 A6 imposes.

**`requires` is how Tier 1c is carried.** A condition the chain cannot evaluate is **named and
defaults to off** — gcsim's own default for Homa's low-HP bonus is that it does not apply. Off
and named beats either silently-on (overstates every Homa build) or silently-dropped (the
current bug, one weapon over).

### OQ-P1 — answered: committed JSON under `app/data/gcsim_passives/`, citing source paths

Matching the `app/data/yuanshen/snapshot/` precedent: committed data with a documented
derivation. The difference is that **this derivation is a human reading Go, so it cannot be
regenerated by a script** — which makes the citation load-bearing rather than decorative.

So every record carries the **gcsim source path** as a field. It does **not** restate the pin:
`frontend/gcsim/PROVENANCE.md` sets that convention — *"the single pin in
`docs/CROSSVAL_gcsim.md` — never restated here"* — and 58 copies of a commit hash is 58 places
to forget.

**The payoff is that citations become checkable.** A test asserts every `source` names a file
that exists in the gcsim tree at the pin, so a path that rots, or one that was never real,
fails rather than reading as provenance. That is the difference between a citation and a
claim, and it is the failure mode this repo was forked with.

## 7. Open questions

- ~~**OQ-P1 — where do the records live?**~~ **Answered in §6a:** committed JSON under
  `app/data/gcsim_passives/`, each record citing its gcsim source path — and **not** the pin,
  which lives in one place. A test checks every cited path exists at the pin, so provenance is
  verified rather than asserted.
- **OQ-P2 — what happens to a weapon with no record?** It must not silently score as though
  it had no passive, which is the current behaviour and the bug. **Leaning: the existing
  `unmodelled_passives` reporting, extended to the optimizer** — so an unported weapon is
  named rather than quietly assumed inert.
- **OQ-P3 — does the optimizer report Tier 2/3 gaps per weapon?** A build wearing a Tier 3
  weapon has a genuinely unanswerable search. Refusing is one option; reporting loudly is
  another.
- ~~**OQ-P4 — how many weapons is Tier 1, exactly?**~~ **Answered in
  `docs/RESEARCH_passive_tiers.md`: 44, plus 14 more behind a stated assumption (tier 1c).**
  N.5 said 5, and both are right — N.5 meant *with no new code*, this means *with no new chain
  primitive*. The survey also added tier **1c**, which the plan did not anticipate and which
  holds `Staff of Homa` and `Engulfing Lightning`.
