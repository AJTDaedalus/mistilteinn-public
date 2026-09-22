# RESEARCH — a Genshin wish planner, after Fribbels' Warp Planner

**Status:** research, 2026-09-22. Nothing built. Commissioned by the owner: *"Fribbels has a
'warp planner' tab … can you review this and give me feasibility for doing the same, using
gachasim's math underlying the simulator, in mistilteinn for Genshin?"* and *"review fribbels
as well using a browser with screenshots. The goal would be to be very similar so people are
familiar. One thing that will differ is capturing radiance, which will need to be shown as well
and let users select previous losses as an input."*

**Verdict: feasible, and small.** The math is a pure function of about eight numbers, it is
exact rather than simulated, and it needs no database, no migration and no catalogue. A working
prototype was written and cross-validated during this pass (§4). The real work is not the
probability — it is the **resource layer**, which gachasim does not have at all (§6).

---

## 1. What Fribbels' Warp Planner actually is

Driven headless at `https://fribbels.github.io/hsr-optimizer#warp` on 2026-09-22.
**This is the first time anyone here has looked at the running application** —
`RESEARCH_fribbels_hsr.md` §7 flags that its whole description was inferred from component
names, and its one line on this tool (*"jade/pity budgeting for banners. Not an optimizer
feature at all"*) undersells it considerably.

It is a **fourth-ranked entry in the sidebar's TOOLS group**, above the entire OPTIMIZATION
group — not buried. One screen, no scrolling, no run button: every edit recomputes live.

### The input panel — three columns

| Settings | Character | Light Cone |
|---|---|---|
| **Jades** (currency) | **Pity counter** | **Pity counter** |
| **Passes** (tickets) | **Guaranteed** ✗/✓ | **Guaranteed** ✗/✓ |
| **Starlight** — refund tier | | |
| **Additional resources** — projected income | | |

`Guaranteed` is a two-segment ✗/✓ control, not a checkbox. Both of the pull-currency
boxes and both pity boxes are plain number inputs.

### The resource line

A single centred sentence sits between the inputs and the table, and it is the best idea on
the page:

```
24,000 💎 + 60 🎫 + 300 ✨ = 225 🎫
```

It shows the arithmetic rather than just the total — currency ÷ 160, plus tickets, plus the
starlight refund, equals the budget every row below is then measured against. The table
header reuses the number: *"Success chance with 225 🎫"*.

### The results table — `Simple` mode

Three columns: **Goal**, **Success chance with N**, **Average # required**.

The Goal cell has a **coloured bar behind the chip**, width proportional to the success
chance, running green → yellow-green → orange → red as the odds fall. Rows that are
unreachable on the current budget go dim. With 24,000 jade, 60 passes and 45 pity:

| Goal | Success | Average |
|---|---|---|
| E0 S0 | 100.0 % | 58 |
| E0 S1 | 98.2 % | 110 |
| E1 S1 | 64.1 % | 200 |
| E2 S1 | 20.2 % | 289 |
| E3 S1 | 3.4 % | 379 |
| E4 S1 | 0.4 % | 468 |
| E5 S1 … E6 S5 | 0.0 % | 558 … 908 |

The ladder is **cumulative and ordered by a strategy** — a `Strategy:` dropdown offering
`S1 first, E0 first, E1 first … E6 first`. Their guide gives the rule: after the primary goal
the order is always `E0 → S1 → E6 → S5`.

### `Multi Target` mode

The same budget spent across a **queue of banners**. Three add buttons — *Add character and
signature*, *Add character*, *Add light cone* — and each row is a card with the character's
splash art as its background, a **from → to** pair of eidolon ladders (`— E0 E1 … E6` ➡
`E0 E1 … E6`), a drag handle for reordering and an ✕. Each row then gets its own goal chip,
bar, success chance and average, **cumulative down the queue** (E0 at 100 % / 58, then S1 at
97.0 % / 123).

Banner pity and the guarantee apply **only to the first target of each type** in the queue;
everything after starts fresh. That is correct and worth copying.

### Other details

- **Starlight** offers `None`, `4 % refund (Low)`, `7.5 % refund (Average, default)`,
  `11 % refund (High)`, documented as the 4★ character/light-cone split — every 4★ a light
  cone, an even split, every 4★ a character.
- **Additional resources** is a multi-select of upcoming patch phases (F2P / Express /
  BP+Express), sourced in their guide to *"Nivskisl on Telegram"*.
- There is a **written guide** at `docs/guides/en/warp-planner.md` in their repository, and
  16 locale files for this tab alone.

---

## 2. How it computes — the finding that decides the architecture

Their guide states it outright:

> Results are computed using **exact probability math, not simulations**. Pull probabilities
> are derived directly from the pity formula and summed across all milestones to produce
> fully accurate results.

`src/lib/tabs/tabWarp/warpCalculatorController.ts` is **377 lines** and the algorithm is four
steps:

1. **A precomputed first-passage PMF** — `warpRates.ts` ships the distribution of "pulls until
   the next 5★" as a hardcoded 90-element array, generated by the pity curve in a comment.
2. **`pityAdjustedPmf(dist, pity, cap)`** — slice from the current pity and renormalise. That
   is conditioning on "no 5★ in the last *pity* pulls".
3. **`milestoneCostPmf`** — the cost of one copy:
   - guaranteed → just the start distribution;
   - otherwise → `rate · startDist + (1 − rate) · convolve(startDist, freshDist)`.

   Two branches is **exact**, because a lost 50/50 guarantees the next 5★.
4. **`convolveArrays`** across the milestone ladder, then read the CDF at the budget for the
   success chance and `Σ k·p` for the average.

No simulation, no sampling error, no job queue, no progress bar. Arrays of ≤ 90 elements and a
handful of discrete convolutions.

### Their pity curve is gachasim's pity curve

`warpRates.ts` generates its array from:

```js
const softStacks = Math.max(0, n - 72)     // n is 0-indexed
return 0.00600 + softStacks * 0.06
```

That is `base_rate 0.006`, ramp `+0.06`, first raised pull at 1-indexed pity **74** — which is
exactly `soft_pity_start: 74, increase_rate: 0.06` in `gachasim/configurations.py`. The two
projects fitted the same community curve independently.

They also use **gachasim's loss-pool model**, which gachasim's own docs present as a
hypothesis: their guide gives the character rate-up as `50% + (1/8 × 50%) = 56.25%` and the
light cone as `75% + (1/8 × 25%) = 78.125%`, which is `effective_featured_rate(0.5, 8)` and
`effective_featured_rate(0.75, 8)` to the digit. `docs/RESEARCH_hsr_loss_pool_hypothesis.md`
has independent corroboration it did not know it had.

**None of that loss-pool machinery applies to Genshin** — both Genshin banners carry
`loss_pool_size: None`, so the Genshin port is the *simpler* case.

---

## 3. Where gachasim and Fribbels differ, and why it does not matter here

gachasim distinguishes **fresh** accounts from **sequential** ones: on HSR a *fake win* — a
lost roll whose pool handed the promotional item over anyway — leaves the guarantee armed, so
a continuing account pays 87.95 per copy against a fresh account's 89.55. Fribbels implements
the fresh model only; its published table matches gachasim's fresh numbers (§4).

For Genshin the distinction collapses to **Capturing Radiance alone**, which is precisely the
thing the owner has asked to expose as an input.

---

## 4. Feasibility, demonstrated rather than argued

A prototype of the full algorithm — Fribbels' four steps, generalised to Capturing Radiance —
was written against `gachasim.configurations` and validated twice.

**Against gachasim's own Monte Carlo**, 300,000 runs per cell, seeded:

| banner | copies | Monte Carlo | exact | z |
|---|---|---|---|---|
| character | 1 | 93.532 ± 0.079 | 93.446 | −1.09 |
| character | 2 | 185.958 ± 0.110 | 186.113 | +1.41 |
| character | 7 | 635.185 ± 0.189 | 634.847 | −1.79 |
| weapon | 1 | 86.598 ± 0.068 | 86.532 | −0.97 |
| weapon | 2 | 172.958 ± 0.095 | 173.064 | +1.10 |
| weapon | 7 | 606.054 ± 0.178 | 605.723 | −1.86 |

CDF agreement is within 0.0015 at every budget checked. The copy-1 figure, 93.45, reproduces
gachasim's own README to the digit.

**Against Fribbels' published table** — reconfigured to their documented HSR rates, the
prototype reproduces their whole ladder to their rounding:

| goal | prototype | Fribbels |
|---|---|---|
| E0 S0 | 89.55 | 90 |
| E0 S1 | 154.6 | 155 |
| E1 S1 | 244.2 | 245 |
| E6 S5 | 952.3 | 953 |

**It agrees with the simulator it came from and with the tool being copied.** That is the
feasibility answer.

**One trap, found by running it.** The first version was wrong by exactly **one pull per 5★
drawn** — 1.59 on a single copy, 10.53 across seven — because a PMF whose index 0 means "one
pull" makes `Σ k·p` a mean that is one too low, every cycle. It is invisible on a single number
and accumulates linearly down the ladder. The fix is to define index *k* as *exactly k pulls*
and leave index 0 at zero. **A test on one milestone would not have caught it**; the ladder is
what exposes it.

**Cost:** 684 ms for a full C0→C6 ladder in naive pure Python, **14 ms** with `numpy.convolve`.
This is an interactive request, not a job.

---

## 5. Capturing Radiance — the one piece of new math

Fribbels carries **one** cumulative PMF and a **scalar** 50/50 rate. Capturing Radiance breaks
that: the win rate depends on a hidden counter that *survives a milestone*, because winning
through the guarantee does not reset it.

The generalisation is small. Carry a **vector of PMFs indexed by the radiance counter (0–3)**
instead of one, and let each milestone mix between them:

- entering at counter *r*, **win** with probability `w(r)` → exit at counter **0**;
- **lose** with probability `1 − w(r)` → exit at counter **r+1**, guaranteed.

Sum over *r* for the answer. `w = (0.50, 0.525, 0.75, 1.0)` — gachasim's
`CAPTURING_RADIANCE_WIN_RATES`, whose stationary win rate of 55.65 % reproduces HoYoverse's
published 55 %. Still exact, still four convolutions wide, still milliseconds.

### The input, and what it is worth

The honest question is **"how many 50/50s have you lost since you last *won* one?"** — losses
through a guarantee count, because winning by guarantee does not reset the counter. Offer
`0 / 1 / 2 / 3`.

Genshin character banner, 180 wishes of budget, pity 0:

| state | P(C0) | **P(C1)** | mean to C0 |
|---|---|---|---|
| not guaranteed, 0 losses | 1.0000 | **0.4908** | 93.45 |
| not guaranteed, 1 loss | 1.0000 | **0.5371** | 91.89 |
| not guaranteed, 2 losses | 1.0000 | **0.6409** | 77.87 |
| not guaranteed, 3 losses | 1.0000 | **0.7127** | 62.30 |
| guaranteed, 0 losses | — | **unreachable** | — |
| guaranteed, 1 loss | 1.0000 | 0.7271 | 62.30 |
| guaranteed, 2 losses | 1.0000 | 0.8563 | 62.30 |
| guaranteed, 3 losses | 1.0000 | 1.0000 | 62.30 |

**A 22-point swing on P(C1)** between a player with no banked losses and one with three. This
is not a decorative input.

**Two things fall out of the table that the UI has to respect.**

1. **`guaranteed = yes` with `0 losses` is an impossible state and must be refused.** Arming
   the guarantee *requires* a lost 50/50, and that same loss increments the counter. Every
   other combination of the two is reachable.
2. **At 3 losses the counter is already a guarantee** — `w(3) = 1.0` — so "not guaranteed,
   3 losses" and every guaranteed row share the same 62.30 mean. The page should say so rather
   than leave a player wondering why two different-looking states agree.

**And the reason the input is the whole feature.** `RESEARCH_gacha_math_audit.md` §"Capturing
Radiance is inert here" records that for a *single copy from a fresh account* the mechanic can
never fire — the first loss triggers the ordinary guarantee and the run ends. The table above
confirms it: the 0-loss row is 93.45, exactly the plain 50/50 answer. **Without the losses
input, Capturing Radiance is invisible for the most common question anyone will ask.** Exposing
it is what makes modelling it worth anything.

---

## 6. What is genuinely missing — the resource layer

**gachasim models pulls and nothing else.** It has no currency, no refund, no income: grep it
for `starlight|primogem|refund|income` and the only hits are `160-wish worst case`, which is
the guarantee chain, not the conversion rate. Everything left of the `=` in Fribbels' resource
line is **net-new and uncited**:

| piece | status |
|---|---|
| Primogems ÷ 160 → wishes | trivial, but **cite it** |
| Intertwined Fate, Genesis Crystals | trivial |
| **Masterless Starglitter refund** | **needs sourcing** — Genshin's starlight analogue, and its rates and the 4★-pity assumption are not in gachasim |
| **Projected income per patch phase** | **a standing maintenance burden** |

The middle two are where this repo's own failure mode lives. `CLAUDE.md` is explicit: *do not
write formulas from memory … fairy's hardest-won lesson was fabricated citations in curated
data*. A starglitter model invented from recollection is exactly that mistake, and it would sit
behind a number that looks authoritative.

The last row is worse in a quieter way. Fribbels sources projected income from a
community-maintained tracker updated every patch. That is the *"how many Teachings do I hold"*
shape from `CLAUDE.md` §planner-materials — **a number that goes stale within a patch and does
it invisibly**. If it ships, it needs the same treatment the curated resin rates got: a dated
file, a named source, and a test that fails when nothing has been refreshed.

**Recommendation: ship without "Additional resources" first.** Primogems + fates + pity +
guarantee + losses is the whole of the question people actually ask, and it is entirely
derivable from published rates plus one citation. Income projection can be a second pass, or
never.

---

## 7. Where it goes in mistilteinn

Nothing here touches the damage chain, the catalogue or the optimizer.

- **Backend** — `app/services/wishes/` and one `POST /api/v1/wishes/plan`. It is a pure
  function: no model, no migration, no seed. Python is the right home despite being a pure
  function, because the curve parameters come from gachasim, the citations live with them, and
  the validation gate is a crossval test against gachasim's Monte Carlo — all of which are
  Python. Pin `numpy.convolve`; at 14 ms the round trip is the slow part.
- **Frontend** — `/planner` already carries a `tab = signal<'plan' | 'materials'>` with a
  lazy-creation pattern for the second tab; a third `'wishes'` tab drops straight into it.
  **But Fribbels puts the Warp Planner in the sidebar's TOOLS group, above the optimizer, not
  inside a planner** — and the owner's stated goal is familiarity. A separate `/wishes` route
  is the closer match, at the cost of two things called "planner". **Owner's call (OQ-W1).**
- **Debounce the recompute.** Fribbels recalculates on every keystroke, which is right, but
  `CLAUDE.md` records this repo typing `9999` into a materials box and writing `9`, `99`,
  `999` — an input bound per-keystroke to a request is the same defect wearing a different
  hat. And `Number('') === 0`, so an emptied pity box must not read as pity 0 silently.
- **Prefill, later.** `builds.constellation_level` and `builds.refinement` already exist, and
  `builds.owned` is designed in `DESIGN_account_tracking.md` Track 1 but not built. Once it
  is, the "current" end of a Multi Target row can default from the roster. Not a dependency.

## 8. Genshin-specific shape

| HSR | Genshin | note |
|---|---|---|
| Jades / Passes | Primogems / Intertwined Fate | 160 : 1 |
| E0–E6 | **C0–C6** | 7 copies |
| S1–S5 | **R1–R5** | 5 copies |
| Light Cone | **Weapon** | |
| — | **Epitomized Path** | 1 Fate Point since 5.0 (was 2) |
| — | **Capturing Radiance** | §5 |
| Starlight | Masterless Starglitter | §6 |

The weapon banner needs no new machinery: `success_rates[0] = 0.375` is already
`0.75 (promotional) × 0.5 (which of the two)`, and any other 5★ grants the single Fate Point,
so the next is certain. That is the same two-branch shape as a 50/50, at a different rate.

**A caveat to carry onto the page.** gachasim's `configurations.py` warns that
`soft_pity_start` and `increase_rate` are *jointly* fitted to the published consolidated rate
and are not separately identified — roughly thirty pairs fit each weapon banner. The **centre**
is stable (the mean moves < 0.02 pulls) but the **far tail is not** (18–26 pulls). A planner
reports means and mid-range probabilities, so it sits in the stable part; it should not grow a
"worst case" column reading off the fitted curve. `published_worst_case` — 180 and 160 — is the
figure for that, and it is the one HoYoverse advertises.

---

## 9. Open questions

| | |
|---|---|
| **OQ-W1** | Its own `/wishes` route (matches Fribbels, two things named "planner") or a third tab on `/planner`? |
| **OQ-W2** | Ship "Additional resources" income projection at all? §6 argues not in a first pass. |
| **OQ-W3** | Is the Masterless Starglitter refund in scope for v1, given it needs sourcing that gachasim cannot supply? |
| **OQ-W4** | Multi Target in v1, or Simple only? Multi Target is most of the UI and none of the math. |
| **OQ-W5** | Genshin's wish history is exportable. Should pity / guarantee / losses eventually be *derived* rather than typed? That would make the losses counter exact instead of remembered. |

## Sources

- Fribbels Star Rail Optimizer, `#warp`, driven headless 2026-09-22. Screenshots were taken to
  a session scratchpad and are **not committed**; re-derive with Playwright against the live
  site.
- `fribbels/hsr-optimizer` — `docs/guides/en/warp-planner.md`,
  `src/lib/tabs/tabWarp/{warpCalculatorController,warpRates}.ts` (read at main, 2026-09-22).
- `/root/gachasim` — `simulator.py`, `configurations.py`,
  `docs/RESEARCH_gacha_math_audit.md`, `docs/RESEARCH_hsr_loss_pool_hypothesis.md`.
  **It is not a git repository** — no `.git`, no remote, last touched 2026-08-16. Anything this
  repo comes to depend on should be vendored with its citations, not referenced by path.
