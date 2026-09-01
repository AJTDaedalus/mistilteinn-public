# DESIGN: Calculate, at gcsim's level of detail

**Owner brief.** *"The calculate page still doesn't have gcsim-level details on the full
rotation... we need teamwide stats too... per character it's less per hit and more about
distribution... a full rotation list where you can click for details on exactly how it was
calculated."* And: *"use Mitya-themed design elements to make it our own while presenting the
data clearly and using best scientific data practices."*

## Branch policy

`feat/calculate-parity`, sub-branches per chunk. **No direct commits to `dev` or `main`**;
`dev` moves only by reviewed PR. Task 0 of the TASKS file is the branch-setup gate.

## 1. The architecture changes, and that is the point

Calculate currently **calibrates a recipe per character** and evaluates it at their gear. That
is the optimizer's machinery: it exists so a search can score thousands of candidates without
running gcsim thousands of times.

**Calculate is not a search.** It is one team, one rotation, one answer. It can run the thing.

`POST /rotations/{id}/preview` with `runnable: true` already returns a config carrying *every*
character's real gear — `_runnable_config` says so: *"every character's gear is emitted either
way"*. Running that through the browser wasm and reading gcsim's own statistics gives:

- **true parity** — the same fields the gcsim results page prints, because they are the same
  object;
- **no residual** — the 1.3 % gap against gcsim disappears, because there is no approximation
  left to be off by;
- **less code** — no `mine` filter, no per-character calibration, no 4-piece target resolution,
  and no teammate/optimized-character asymmetry in the energy warning;
- **less waiting** — one run of ~8 s against four calibrations of ~6 s.

**The recipe path stays exactly where it earns its keep**: the optimizer, which must score a
corpus. Nothing here changes it.

### What this admits about tonight's fixes

The `mine` filter and the per-character 4-piece calibration were **correct for the design as it
stood**, and they took Calculate from 3.7x wrong to within 1.3 %. This replaces the design
rather than the fixes. That is worth stating plainly rather than quietly deleting them.

## 2. What to show — from gcsim's own results sheet

Extracted from the owner's shared `references/gcsim_results.html`:

| section | source field | have it? |
|---|---|---|
| DPS, EPS, RPS, HPS, SHP, Duration — each with min/max/sd/p25/p50/p75 | `statistics.{dps,eps,rps,hps,shp,duration}` | direct |
| DPS distribution over iterations | `damage_buckets` | direct |
| Damage over time / cumulative contribution | `cumu_damage`, `cumu_damage_contrib` | direct |
| Character DPS distribution | `character_dps` | direct |
| Element DPS distribution | `dps_by_element` | direct |
| Source DPS / damage instances | `source_dps`, `source_damage_instances` | direct |
| Actions per character | `character_actions` | direct |
| Field time | `field_time` | direct |
| Total energy per source | `total_source_energy` | direct |
| Energy at end | `end_stats.ending_energy` | direct |
| Reactions per source | `source_reactions` | direct |
| Target aura uptime | `target_aura_uptime` | direct |
| Failed actions, incl. insufficient energy | `failed_actions` | direct — already shipped as the red warning |
| Target information | the config we sent | direct |

**Every one is already in the object.** The work is presentation, not derivation — which is why
this is the right trade.

## 3. Scientific presentation, as the brief asks

1. **Never a point estimate alone.** gcsim reports mean, sd, min, max and quartiles; a mean
   printed by itself invites a precision the run does not have. Every headline figure carries
   its **sd** and the **iteration count** that produced it.
2. **Significant figures follow the spread.** A DPS of 172,543 ± 3,039 is five digits of
   precision claimed on four digits of knowledge. Round the estimate to the uncertainty.
3. **Units, always.** Seconds on delays, `%` on shares, `DPS` spelled on the headline.
4. **Bars start at zero.** A truncated axis exaggerates a difference; on a share chart it
   invents one.
5. **Measured, derived and modelled are labelled differently.** gcsim's own numbers, our
   arithmetic on them, and anything the model cannot see are three kinds of claim.
6. **n is on the page.** "100 iterations" is part of the number, not a footnote.
7. **What is not modelled is written down**, in the same place, rather than implied by absence.

## 4. Mitya, without going overboard

The palette is already sampled and `check:tokens` keeps it honest. The rules here:

- **Two accents, kept apart** — brass is identity and action, mint/azure is data and state.
  A damage number and a button are different kinds of thing, and the palette already says so.
- **Gold rules separate; they do not decorate.** The ability table established this.
- **Art where a row names a character**, never as ornament — `shared/icon` exists.
- **Emblems for elements**, not colour alone (#131): a shape carries meaning colour cannot.
- **No portrait.** Owner ruling: his colours and his ornament are the brand, he is not.

## 5. The rotation list the owner asked for

*"A full rotation list where you can click for details on exactly how it was calculated."*

The steps in order, each expandable to: which character, which ability, the hits it produced,
their element and damage, and — the point — **the multipliers that made the number**, in order,
with their source. `/builds/{id}/explain` already answers exactly that question for one hit and
is the shape to reuse.

## 6. Open questions

- **OQ-C1** — how many iterations? 100 is ~8 s and gives a usable sd; gcsim's page uses 1000.
  A slider, or a fixed number with the count shown?
- **OQ-C2** — does the rotation list show every hit, or group by step? A 90-second rotation is
  hundreds of hits and about 30 steps.
