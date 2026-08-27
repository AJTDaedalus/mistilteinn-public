# RESEARCH: gcsim publishes the whole damage calculation, per hit

**Question:** to reuse a gcsim rotation as an optimizer objective, a "damage recipe" must be
**recomputable** under different artifacts. `RESEARCH_damage_recipe.md` concluded that the
aggregated result gives structure but not decomposition — `DamageEvent.Damage` is a final
number and the log carries modifier *names*, not amounts — so recomputation would need ported
modifier semantics.

**That conclusion was based on the wrong entry point.** gcsim's wasm exports **`sample(cfg,
seed)`**, which returns the full per-frame log as JSON, and it publishes **every term of the
damage formula for every hit**.

## 1. What `sample()` returns

One call, one seed, ~3.2 s, ~1.3 MB of JSON for a 90-second solo rotation. 3,128 log entries:

| event | count | contents |
|---|---|---|
| `hitlag` | 1,475 | |
| `icd` | 423 | |
| `snapshot` | 246 | per ability: `mult`, `final_stats` (the complete stat vector), element, icd tag, and every active modifier with **its amounts** |
| **`calc`** | **245** | **the entire damage computation, term by term** |
| `damage` | 245 | ability, attack tag, element, amp, crit, damage, `source_frame`, active modifiers |
| `action` | 157 | |

A `calc` entry carries `talent`, `total_scaling`, `base_atk`/`base_hp`/`base_def`,
`atk_per`/`flat_atk`/`hp_per`/`def_per`, `bonus_dmg`, `ele_per`, `cr`, `cd`, `def_mod`,
`res_mod`, `flat_dmg`, `em`/`em_bonus`/`react_mult`/`react_bonus`/`amp_mult_total`,
`use_hp`/`use_def`/`use_em`, `damage_grp_mult`, `ignore_def`, and the intermediate results
`base_dmg`, `pre_crit_dmg`, `dmg_if_crit`, `avg_crit_dmg`, `damage`.

**`talent` is the ability multiplier.** `use_hp`/`use_def`/`use_em` say which stat it scales
off. Both were things this repo planned to derive; gcsim states them.

## 2. The decomposition is exact — checked, not assumed

Recomposing each relation from its published parts, across **all 245 hits** of a committed
sample:

| relation | worst relative error |
|---|---|
| `base_dmg = talent × total_scaling + flat_dmg` | **0.000e+00** |
| `total_scaling = base_atk × (1 + atk_per) + flat_atk` | **0.000e+00** |
| `pre_crit_dmg = base_dmg × (1 + bonus_dmg) × def_mod × res_mod` | **0.000e+00** |
| `avg_crit_dmg = pre_crit_dmg × (1 + cr × cd)` | 1.986e-16 |

**Zero hits fail any relation at 1e-12.** The single non-zero figure is one float rounding.

Two traps found by getting them wrong first:

- **`bonus_dmg` already includes `ele_per`.** The element bonus is published separately as a
  *component*, not an addend. Adding it double-counts and breaks 73 of 245 hits.
- **`damage_grp_mult` is not part of the pre-crit relation.** The 24 `Normal 4` entries with
  `damage: 0` are queued-but-not-landed hits, and including that factor makes them look like
  formula errors.

## 3. What this changes

**A recipe needs neither talent tables nor ported passives to capture what a passive did.**
`bonus_dmg`, `cr`, `cd`, `flat_dmg` and `total_scaling` already contain every weapon, artifact
and character effect gcsim applied. The calibration run captures the *effect*, not the
implementation — so `TASKS_passive_port.md`'s premise, that 237 passives must be transcribed
before a rotation can be scored, does not hold.

**But it captures the effect at the calibration's stats.** A passive whose amount is a
*function of the candidate's own stats* goes stale the moment artifacts change:

| weapon | conversion |
|---|---|
| `Staff of Homa` | ATK from **max HP** |
| `Engulfing Lightning` | ATK from **ER** |
| `Redhorn Stonethresher` | flat damage from **DEF** |
| `Primordial Jade Cutter` | ATK from **max HP** |

**Those are the stat-conversion passives — precisely the ones that change which artifacts
win**, and precisely what the port was for. So the port survives with a **much narrower
target**: not "44 Tier 1 + 14 Tier 1c", but "those whose amount depends on candidate stats".

## 4. Cost

| step | cost | frequency |
|---|---|---|
| `sample(cfg, seed)` | **~3.2 s** | once per calibration |
| 100-iteration aggregate (for instance counts and stability) | ~4.9 s | once per calibration |
| evaluating one recipe hit in the kernel | **0.051 µs** | per hit per combination |

At H=17 (a four-character team, measured) a full-rotation objective is **≈1.15×** the current
per-combination cost. `RESEARCH_recipe_cost.md` §1 has the curve.

## 5. Limits this does not remove

- **One seed.** `sample()` runs a single iteration, so its instance counts carry that seed's
  timing jitter and its `crit` flags are rolls. Use `avg_crit_dmg`, never `is_crit`, and take
  instance counts from the aggregate — where `sd` also says whether the rotation is stable.
- **ER transition bands.** `RESEARCH_damage_recipe.md`: burst count is a step, and a recipe is
  only valid where `sd == 0` on burst instances.
- **Set bonuses and weapon passives are baked into the calibration.** Changing either
  invalidates the recipe, which is why calibration is keyed by them — the owner predicted this
  before any of it was measured.
