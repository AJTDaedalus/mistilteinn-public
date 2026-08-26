# RESEARCH: can gcsim "boil down" a rotation into a reusable damage recipe?

**Owner proposal (2026-08-26):** run gcsim once to learn *what hits when*, build equations from
that, and reuse the recipe to score artifact candidates cheaply — regenerating it per
weapon/artifact-set combination, with an "is ER enough to ult on time?" cutoff per character.

**Answer: the idea holds, gcsim already publishes the recipe, and the ER limitation is real,
measured, and — better than a cutoff — self-diagnosing.** The catch is a different one: the
recipe gives *structure*, not a decomposition of damage, so it does not remove the need to
know what each modifier does.

## 1. gcsim already publishes a recipe

`flush()` returns, among others, **`source_damage_instances`** — per named ability, how many
instances landed, with min/max/mean/sd across iterations — plus `source_dps`,
`total_source_energy`, `source_reactions` and `target_aura_uptime`.

For a solo Ayaka `while 1` rotation at 90 s that is **7 sources**. A four-character team is
larger but nothing like a per-frame trace.

**The per-hit log exists too but not here.** `stats.Result` carries `DamageEvent`
(frame, action id, source, element, reaction modifier, crit, modifier *names*, mitigation,
damage) and `EnergyEvent` (frame, gained, wasted, current) — but the **aggregator collapses
them**. They are in the MessagePack blob `simulate()` returns, before `aggregate()`. Reaching
them means decoding msgpack against `pkg/stats/result_gen.go`, not reading `flush()`.

## 2. The ER limitation, measured

Same rotation, ER varied by adding an `er=` stat. 40 iterations each.

| source | as emitted | +20 % ER | +200 % ER |
|---|---|---|---|
| **Soumetsu (Bloom)** — the burst | **2.00** (sd 0) | **2.75** (min 2, max 3) | **4.00** (sd 0) |
| Soumetsu (Cutting) | 38.33 | 53.37 | 84.20 |
| Normal 0 | 32.92 | 32.85 | 29.13 |
| Hyouka | 9.00 | 9.00 | 8.95 |

**ER does not merely add bursts — it displaces normal attacks.** Normal 0 falls from 32.9 to
29.1 because time spent bursting is time not spent attacking. The whole recipe moves, so an ER
cutoff that only asked "does the burst fire?" would miss that the rest of the rotation changed
around it.

### The recipe says when it is invalid, which beats a cutoff

At +20 % ER the burst count is **2 or 3 depending on the iteration** — `sd > 0`. That is a
transition band, and **no single recipe is valid inside it**.

**That is detectable from the recipe itself.** `sd == 0` on the burst instance count means the
rotation is structurally deterministic and reusable; `sd > 0` means the build sits on a
transition and the recipe must be regenerated or reported as unusable. **The recipe carries
whether it can be trusted** — the same discipline as `isExact` on the optimizer, the measured
error on `sim_retrieval`, and W.5's separability.

### This repo already found the same thing from the other side

`docs/RESEARCH_er_bucketing.md`: *"burst count is a step, not a slope"*, and **bucket 120 is
13.3 % wide in DPS — 5.9× the Monte Carlo standard error** — because it straddles the
transition, while buckets away from it sit at the noise floor. `sim_runs` is keyed by
`er_bucket` for exactly this reason. **The owner's proposal generalises machinery this repo
already built**, and the existing measurement is the hazard quantified.

Note also that doc's Result 3: bucket 145 is flagged real at 3.4× the standard error while
burst count is **flat at 3.00**. So ER is the biggest sequence-mover but **not the only one**,
and a recipe keyed on ER alone would be assuming it is.

## 3. Even a "stable" recipe has a few percent of structural jitter

At sd 0 on bursts, `Normal 0` still ranges 32–33 and `Normal 3` 72–75 — roughly **3 %**. Small
against the 13.3 % transition band, and not zero. A recipe should carry the observed spread of
each count rather than the mean alone, for the same reason W.5 carries separability.

## 4. The catch: a recipe is structure, not a decomposition

`DamageEvent.Damage` is the **final number**. There is no multiplier, no snapshot stats, no
per-modifier amount — only modifier **names**. So an event cannot be *rescaled* for different
artifacts; it has to be **recomputed**.

Recomputing needs, per hit: the talent multiplier (this repo has it — M.4, crossvalidated),
the element and reaction (published), and **what every active modifier does** (not published —
only its name).

**So the recipe and the passive port are complementary, not alternatives:**

| | gives | missing without the other |
|---|---|---|
| **passive port** (`TASKS_passive_port.md`) | what each modifier does | which hits land, and how many |
| **damage recipe** | which hits land, and how many | how to recompute one under new stats |

And they compose best exactly where the port starts: **Tier 1 passives are permanent and
tag-gated**, so their contribution is constant across the rotation. Recipe × Tier 1 port is
*exact*, with no uptime assumption. Tier 2's timed and stacking effects are the ones that need
the per-frame trace out of the msgpack.

## 5. Cost, unmeasured

Scoring a combination today is one hit (`SECONDS_PER_COMBINATION` = 5.5e-4 s). A recipe means
~7 sources solo, more for a team. **It is not 7× the cost** — the expensive part, aggregating a
candidate's stats, is shared across every hit in that candidate — but the multiplier is not 1
either, and it is not measured. **That measurement decides whether this is an optimizer feature
or a second tier**, and it should be taken before anything is built.

## 6. A mistake worth recording

The first run of this experiment reported **"ER changes nothing"** across a 3× ER sweep.

The config was `emitted/ayaka.txt`, which is a **bare action list** — `build_config`'s own
docstring says a config built that way *"runs its actions once"*. One burst, no second burst to
gate, so energy could not matter. The sweep was correct and the question was wrong.

It was caught by checking that the `er=` injection was not a silent no-op — the regex *had*
applied. Had that check gone the other way and been believed, the headline would have been
"the ER limitation is not real", which is a confident, plausible, wrong answer to the exact
question the owner raised.
