# Crossval against gcsim

gcsim is this project's oracle for damage numbers and its **citation target** for every
game constant. This file pins the version those citations point at and records the rules
that make a comparison meaningful.

Read `docs/DECISIONS.md` first if you are wondering why the code does not look like gcsim's:
gcsim is the reference for *correctness and feature scope*, deliberately not for structure
(DESIGN §1 A6).

## The pin

| | |
|---|---|
| **Repository** | `github.com/genshinsim/gcsim` |
| **Commit** | `a36661d918772851378d48a38c267dd6efe49540` |
| **Dated** | 2026-08-29 |
| **Title** | `Fix max level of characters from Enka (#2726)` |
| **Pinned** | 2026-08-31 — re-pinned from `3647a07a` to pick up Ifa and Jahoda |

**A citation names a file, a line range, and this commit.** A citation that names only a
file is a citation to a moving target: gcsim refactors, and "see `pkg/core/attributes`" ages
into "see wherever that went". Re-pinning is a deliberate, reviewed step that re-checks the
citations it invalidates — the same rule the YuanShenResources snapshot follows.

## What has been cited so far

| Constant or rule | Source at the pin | Used by |
|---|---|---|
| stat vocabulary | `pkg/core/attributes/stats.go:12-40` | `formula/genshin/tags.py` |
| `MaxHP`/`TotalATK`/`TotalDEF` are **single-stage** | `pkg/core/attributes/stats.go:44-46` | `formula/genshin/stats.py` |
| element list | `pkg/core/attributes/element.go:13-27` | `formula/genshin/tags.py` |
| attack-tag (scope) list | `pkg/core/attacks/attack.go:5-20` | `formula/genshin/tags.py` |
| strike types | `pkg/core/attacks/attack.go:52-59` | `formula/genshin/tags.py` |
| character base stats: `base * GrowCurve[curve][level-1]` + the ascension row | `pkg/core/player/character/basestat.go:73-101` | `services/stat_calculator.py:add_character` |
| a character starts at **100% Energy Recharge** (`res[ER] += 1`) | `pkg/core/player/character/basestat.go:82` | `services/stat_calculator.py:BASE_ENERGY_RECHARGE` |
| base CRIT rate 5% / CRIT DMG 50% — **and the payloads' disagreement with it** | `pkg/core/player/character/basestat.go:82-84` | `models/character.py:base_crit_rate`, migration `55afb8679231` |
| weapon base stats: each published prop is `init_value * GrowCurve[its own curve][level-1]`, plus the ascension row | `pkg/core/player/character/basestat.go:102-126` | `services/stat_calculator.py:add_weapon` |
| the damage chain: `base x (1+dmgBonus) x def x res x crit x amp` | `pkg/enemy/damage.go:11-130` | `formula/genshin/damage.py:compute_damage` |
| DMG bonus is `elemental[channel] + generic`, each once | `pkg/enemy/damage.go:47` | `formula/genshin/stats.py:hit_dmg_bonus_node` |
| base is `mult * stat * (1 + baseDmgBonus) + flat`, flat **inside** the bonus | `pkg/enemy/damage.go:65-66` | `formula/genshin/damage.py:compute_damage` |
| a talent may scale off ATK, HP, DEF or EM | `pkg/enemy/damage.go:52-62` | `formula/genshin/damage.py:ScalingStat` |
| DEF term, with reduction and ignore multiplied **separately** | `pkg/enemy/damage.go:81-84` | `formula/genshin/damage.py:def_multiplier` |
| DEF reduction capped at 0.9; DEF ignore at 1.0 | `pkg/enemy/damage.go:76-80` | `formula/genshin/damage.py:MAX_DEF_REDUCTION` |
| RES term, three branches | `pkg/enemy/damage.go:89-93` | `formula/genshin/damage.py:res_multiplier` — **see the divergence below** |
| crit rate clamped to [0, 1] | `pkg/enemy/damage.go:66-71` | `formula/genshin/damage.py:crit_multiplier` |
| amplifying EM bonus `2.78*em/(1400+em)`, added to the reaction bonus inside the bracket | `pkg/enemy/damage.go:113-116` | `formula/genshin/damage.py:amplifying_multiplier` |
| melt multipliers: Pyro→Cryo 2.0, Cryo→Pyro 1.5 | `pkg/reactable/melt.go:23,30` | `formula/genshin/damage.py:_AMP_MULTIPLIERS` |
| vaporize multipliers: Hydro→Pyro 2.0, Pyro→Hydro 1.5 | `pkg/reactable/vaporize.go:26,33` | `formula/genshin/damage.py:_AMP_MULTIPLIERS` |

Extend this table in the same commit that adds the citation. A constant whose row is missing
here is a constant nobody can re-check.

## Known divergences from the oracle

Deliberate, tested, and listed here because **F.8's tolerance argument has to know about
them** — a crossval mismatch that lands on one of these is not a formula error on this side.

### 1. ~~The RES curve is continuous at exactly 0.75~~ — **resolved upstream 2026-08-31**

**gcsim fixed this, and this project no longer diverges.** `Fix Res Mod at 75% effective
res (#2717)` landed between the old pin and this one, and `pkg/enemy/damage.go` now reads:

```go
if res >= 0 && res < 0.75 {
    resmod = 1 - res
} else if res >= 0.75 {
    resmod = 1 / (4*res + 1)
}
```

`>=`, which is what this project has always used. The two implementations now agree at every
resistance, including exactly 0.75.

The entry is kept rather than deleted because F.8's tolerance argument was written knowing
about it, and because the reasoning still holds as a record: a resistance of exactly 0.75 used
to match neither branch and fall through to the negative-RES default, giving `1 - 0.75/2 =
0.625` where both neighbouring branches give `0.25` — a 2.5x discontinuity at a single point.
It read as a `>` that should have been a `>=`, and upstream agreed.
`test_the_curve_is_continuous_at_exactly_three_quarters` still pins our side; it is now a
check that we match gcsim rather than one that we deliberately do not.

### 2. Growth curves are float32 in the dump and decimal in gcsim

`GROW_CURVE_HP_S5` at level 90 is **`8.73900032043457`** in the YuanShenResources dump —
exactly the float32 representation of `8.739` — while gcsim's data pipeline stores the
decimal `8.739`. One is the value the game's binary holds; the other is the value a designer
typed.

This project keeps the datamined value. Rounding it to look tidier would be inventing a
number, and the whole snapshot exists so that values are read rather than chosen.

The two differ by **3.7e-8 relative**, which propagates to ≤2.5e-8 on any stat and on any
damage figure. That is the entire reason the tolerance below is not zero.

### 3. Crit is computed, not rolled

gcsim simulates and rolls against crit rate (`damage.go:101`). A calculator reports
`non_crit`, `crit` and `expected = 1 + clamp(rate) * dmg` — an optimizer has to score on the
expectation, and a build whose score depended on a random draw would not be reproducible.
Compare a crossval fixture against the matching field, not against whichever number gcsim
happened to roll.

## Tolerance

**`1e-7` relative**, set in F.8 at `backend/tests/crossval/test_gcsim_crossval.py`.

### Why it is not zero

**The measured agreement is 1.33e-8 relative, not zero** — `108.53040079774516` here against
gcsim's `108.53039935232651`. Exactly one understood difference separates the two sides on
the `ayaka_normal_1` case, and it is not arithmetic: the float32-vs-decimal growth curve
above, worth ≤2.5e-8 relative.

(A hand check during F.8 appeared to show an exact match and was reported as one. It had
substituted gcsim's own base ATK for this repo's, so it compared gcsim against itself for
that term. Any "exact match" claim about a curve-scaled quantity should be treated as a
measurement error until it survives the end-to-end harness.)
Everything else agrees exactly — **crit rate and crit DMG, which no curve touches, match bit
for bit**, and that is the check that the residual really is curve provenance rather than
something structural.

### Why it is small enough to mean something

`1e-7` is **five orders of magnitude** tighter than any formula error could be. The smallest
single mistake available — a dropped 10% resistance, the wrong ascension row, a missing
substat — moves the answer by *percent*, not by parts per ten-million.

That is not an assertion:
`test_the_tolerance_cannot_hide_a_formula_error` drops the enemy's resistance and checks the
result lands **outside** the tolerance, by more than 10%. A passing run is the healthy state.
If that test ever **fails**, the tolerance has been widened past the point of meaning
anything.

### What this tolerance does not cover

The case it was argued for is deliberately minimal: one hit, no rotation, no crit averaging,
no artifacts, and a weapon with no passive. **A case that adds a rotation or averages over
crit RNG will need a looser, separately argued number — add it with its own tolerance and
its own paragraph. Do not widen this one to accommodate a different kind of case**, which is
how a tolerance stops being evidence and becomes a knob.

## The rule that is pre-paid

`CROSSVAL_REQUIRE_DB=1` makes a skipped crossval level a **hard failure** from the first
commit of the harness (F.7), not a retrofit.

fairy's crossval suite was green-by-absence on CI for months — the DB it needed was not
there, the levels skipped, and the summary said green — and it shipped a stale golden
fixture on the strength of it. That is the single most expensive bug in this project's
lineage, and it is the reason this paragraph exists before the harness does.


---

# The f32 tolerance, for the browser kernel

**C.2, argued before the kernel was written** — DESIGN_client_optimizer §6 requires that
order, because a tolerance chosen after the fact is a tolerance chosen to make the kernel
pass.

WGSL has **no f64**. The kernel runs in `f32`, and the chain above matches gcsim to
**1.3e-8** in float64 with a `1e-7` tolerance. An f32 kernel cannot reach that, so it needs
its own number — derived, not guessed.

## The tolerance

**`1e-6` relative**, against the Python chain's answer.

## What it was derived from

Both halves are measured, over the 2,000 cases in `tests/fixtures/kernel/cases.json`.

### 1. How far f32 actually drifts

The chain reimplemented in `float32` and compared to the committed f64 answers:

| | relative divergence |
|---|---|
| median | 6.78e-08 |
| p95 | 1.91e-07 |
| p99.9 | 3.15e-07 |
| **max** | **3.51e-07** |

f32's machine epsilon is 1.19e-07, and the chain is a sequence of five to seven
multiplications, so a worst case of ~3× epsilon is what the arithmetic predicts and what was
observed. **`1e-6` is ~2.8× the measured maximum** — enough headroom for cases the sweep did
not reach, without being loose.

This also settles the question the other way: an f32 kernel held to the f64 chain's `1e-7`
would fail on roughly **5% of cases** for reasons that are not bugs.

### 2. That it cannot hide a formula error

The property `test_the_tolerance_cannot_hide_a_formula_error` asserts for the f64 chain,
re-established for this one. Three mistakes a reimplementation plausibly makes, measured as
relative divergence on the cases where each applies:

| plausible bug | smallest divergence | margin over `1e-6` |
|---|---|---|
| crit-rate clamp forgotten | 2.06e-04 | **206×** |
| DEF reduction and ignore combined additively | 2.27e-04 | **226×** |
| RES boundary read as gcsim's `>` | 1.50e+00 | **1,500,000×** |

The smallest is **206× the tolerance**. There is no plausible formula error that fits inside
`1e-6`, and the two-and-a-half orders of magnitude between "worst floating-point noise" and
"smallest real bug" is what makes a single number safe to use for both.

## What this tolerance is *not*

It is **not** a claim that the kernel matches gcsim to 1e-6. It matches **this repo's Python
chain**, which matches gcsim to 1.3e-8. The kernel's total distance from the oracle is the
sum, and `1e-6` dominates it — so **the kernel is the least accurate link**, by design and by
about two orders of magnitude.

That is acceptable because of what the number is used for: ranking artifact combinations
whose damage differs by fractions of a percent, not reproducing a specific in-game figure. A
1e-6 relative error cannot reorder two builds that differ by more than 1e-6 relative, and two
builds closer than that are indistinguishable in play.

**If the kernel is ever used to display an absolute damage figure rather than to rank**, this
argument does not carry, and the figure should come from the simulator rather than the
kernel.
