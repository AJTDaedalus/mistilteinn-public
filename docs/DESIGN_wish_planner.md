# DESIGN — the wish planner

**Status:** **built**, 2026-09-22 — math, income store, API, page and the daily timer.
Driven in a browser, not merely tested. Open questions in §8 remain open.

**Status (original):** design, 2026-09-22. Implements `docs/RESEARCH_wish_planner.md`, which carries the
Fribbels review, the verified prototype and the income-source work. Read it first; nothing
here repeats its evidence.

## Branch policy

**`feat/wish-planner`, off `dev`. No direct commits to `dev`.** One branch, no parallel
tracks — the math, the income store and the page are one feature and the page is untestable
without the other two. Task 0 of `docs/TASKS_wish_planner.md` is the branch-setup gate.

The research doc's two commits are already on this branch; it was renamed from
`docs/wish-planner-feasibility` rather than merged, so the feature's evidence travels with it.

---

## 1. What it answers

Given primogems, Intertwined Fate, current pity, whether the next 5★ is guaranteed, and how
many 50/50s have been lost since the last win — **what is the chance of reaching C0, C1 … C6,
R1 … R5, and what does each cost on average?**

Deliberately the same shape as Fribbels' Warp Planner (owner: *"the goal would be to be very
similar so people are familiar"*), with one addition it has no equivalent of: **Capturing
Radiance**, exposed as a previous-losses input.

## 2. Non-goals

- **Not an optimizer.** It reports odds; it does not recommend who to pull.
- **No day-level proration.** Owner, 2026-09-22: *"other than welkin, income isn't predictable
  day to day, some things are time gated and many things are when the user does them."* Income
  is added in **whole patches**, ticked on or off. §5.
- **No starglitter, no acquaint fate.** Owner, 2026-09-22: *"just primogems + intertwined."*
- **No standard banner, no chronicled wish.** The question is the limited banners.

## 3. The math

`app/services/wishes/` — a pure function, no session, no ORM.

Fribbels' algorithm (`RESEARCH_wish_planner.md` §2), generalised to Capturing Radiance:

1. **First-passage PMF** — `pulls_to_next_five_star`, built from the banner's four pity
   parameters. Index *k* is *exactly k pulls*; index 0 is 0.0.
2. **Pity conditioning** — slice from the current pity, renormalise.
3. **Per-copy cost** — win at `w`, else convolve with a fresh cycle and take the guarantee.
4. **Convolve down the ladder**, read the CDF at the budget.

**Capturing Radiance** makes `w` depend on a counter that survives a copy, so the carried state
is a **4-vector of PMFs indexed by the counter (0–3)** rather than one PMF. Each milestone
mixes: win → counter 0; lose → counter+1, guaranteed. Exact, and ~14 ms with `numpy.convolve`.

**The off-by-one is the thing to protect.** A PMF whose index 0 means "one pull" makes `Σ k·p`
low by exactly one **per 5★ drawn** — 1.6 on one copy, 10.5 across seven. Invisible on a single
milestone, linear down the ladder. `tests/unit/test_wish_planner_math.py` pins the ladder, not
just the first row.

### Validation

`tests/unit/test_wish_planner_crossval.py` pins the exact output against numbers **measured
against gachasim's Monte Carlo** during the research pass (300k runs/cell, all |z| < 2):

| banner | copies | expected mean |
|---|---|---|
| character | 1 | 93.45 |
| character | 2 | 186.11 |
| character | 7 | 634.85 |
| weapon | 1 | 86.53 |
| weapon | 7 | 605.72 |

These are a **regression pin, not an oracle** — the oracle was gachasim, and re-deriving them
means re-running it. The test says so.

### Rates

`app/data/wishes/banner_rates.json`, hand-maintained, **every entry cites a source** — the same
rule and the same enforcement as `app/data/planner/curated_rates.json`. Values come from
gachasim's `configurations.py` and its `docs/RESEARCH_gacha_math_audit.md`, which carries the
source links. Carried forward with them:

- **`soft_pity_start` and `increase_rate` are jointly fitted** to the published consolidated
  rate and not separately identified. The centre is stable (< 0.02 pulls); the far tail is not
  (18–26). So the planner reports means and mid-range probabilities and **must not grow a
  "worst case" column** off the fitted curve. `published_worst_case` — 180 and 160 — is the
  figure for that.
- **Capturing Radiance is a community model**, `(0.50, 0.525, 0.75, 1.0)`, whose stationary win
  rate of 55.65 % reproduces HoYoverse's published 55 %.

## 4. State validation

Two rules the UI and the service both enforce, from `RESEARCH_wish_planner.md` §5:

1. **`guaranteed=true` with `losses=0` is unreachable** — arming the guarantee requires a lost
   50/50, and that same loss increments the counter. The service rejects it; the page cannot
   express it.
2. **At `losses=3` the counter is already a guarantee** (`w(3) = 1.0`). "Not guaranteed, 3
   losses" and every guaranteed row share a mean, and the page says why rather than letting it
   read as a bug.

Capturing Radiance applies to the **character banner only**. The weapon banner's Epitomized
Path is an ordinary two-branch guarantee at `0.375`.

## 5. Income

`RESEARCH_wish_planner.md` §10 has the sourcing, the three invariants and the hoyincome
finding. Design consequences only:

- **`wish_income`** — one row per (version, tier), tier in `f2p | welkin | welkin_bp`. Plus
  `is_estimate` and `fetched_at`.
- **`scripts/refresh_wish_income.py`** fetches and upserts. **Never called from `app/`.** It
  runs on a daily systemd timer — `deploy/wish-income/`, following `tools/discord-triage`'s
  precedent. A refusal is not an outage: the API keeps serving the rows it has and keeps
  reporting their `fetched_at`, so the page shows dated numbers rather than wrong ones.
- **`app/data/wishes/income_snapshot.json`** is committed, and is what a fresh clone and CI
  read. The doctrine is `app/data/yuanshen/snapshot/`'s: the app never depends on a live fetch.
- **Three invariants gate a refresh**, and a failure refuses the whole update rather than
  writing part of it: derived `f2p + welkin + bp` equals the sheet's `Total P2P`; per-patch
  `Total F2P` equals the `summary` tab; both subscriptions are flat across patches.
- **Refuse an implausible shrink**, `seed_db`'s `PRUNE REFUSED` rule.
- **`fetched_at` ships in the payload.** Stale projected income is the
  "how many Teachings do I hold" failure — it goes wrong invisibly.
- **`is_estimate` survives to the page.** The sheet publishes `7.1 est.`; a forecast shown as
  history is the same error as a mean shown as a certainty.

**Whole patches, ticked.** The sheet has no phase structure — I checked every per-patch tab and
column A carries only `Events / Other New Content / Web, Mail, Apologems / Repeating Content`.
Fribbels splits by half-patch; we cannot without inventing a split, and the owner's ruling says
the lumpiness is real rather than smoothable. So the control is a multi-select of **whole
patches at or after the current one**, at one of the three tiers. **This is a deliberate
divergence from Fribbels and the only one in the UI.**

## 6. Surface

- `POST /api/v1/wishes/plan` — the whole request in, the ladder out. No persistence, no
  caching: it is cheaper than the cache lookup would be.
- `GET /api/v1/wishes/income` — the tiers, per version, with `fetched_at` and `is_estimate`.

Both require a signed-in caller, matching the rest of `/api/v1`.

## 7. The page

`/wishes`, its own route — Fribbels puts the Warp Planner in the sidebar's TOOLS group above
the optimizer, not inside a planner, and familiarity is the stated goal (**OQ-W1, resolved
this way**; the cost is two things named "planner", which the nav labels disambiguate as
"Wish Planner" and "Levelling Planner").

Following Fribbels' layout: a three-column settings panel, the **resource line that shows its
arithmetic** (`24,000 💎 + 60 🎫 = 210 🎫`), and a goal table with a proportional bar behind
each chip. Differences: primogems/fates rather than jades/passes, C/R rather than E/S, whole
patches rather than half-patches, and a **Capturing Radiance control** beside Guaranteed.

### One banner at a time — a divergence this section originally failed to name

**Fribbels' Simple mode is not one banner.** It shows Character *and* Light Cone pity and
guarantee at once and builds a single interleaved ladder from one budget —
`E0 S0 → E0 S1 → E1 S1 → … → E6 S5` — which is what its `Strategy` dropdown reorders.

What shipped is a Character/Weapon **toggle** with two independent ladders, so it cannot
answer *"I have 298 wishes: can I get C1 and R1?"* — the question most people bring. The first
draft of this section listed four deliberate differences and treated this as a layout choice.
It is a capability difference and the largest one remaining. **OQ-W8.**

The math needs no change: the same convolution with two alternating first-passage PMFs, and
the banners' state is independent because Capturing Radiance is character-only. The work is
the milestone ordering and the UI.

Recompute is **debounced**, not per-keystroke: `CLAUDE.md` records this repo typing `9999` into
a materials box and writing 9, then 99, then 999. And `Number('') === 0`, so an emptied pity box
must not silently read as pity 0.

## 9. Planned — a real starglitter simulator

Owner, 2026-09-22: ship the flat refund first, *"and then once all of these are in draft a plan
for building a real refund simulator like zzz.163.moe"*. This is that draft. **Nothing below is
built.**

### Why a constant is not enough

The shipped tiers are a single number applied to the budget, and three things make that wrong
in ways that do not cancel:

1. **The 10-pull figure is the guarantee, not the rate.** At the published 5.1% base rate the
   consolidated 4★ rate is **13.057%** — one every 7.66 pulls, not 10. Every tier therefore
   understates the refund by **1.34×**: `average` should be 10.1%, not 7.53%. Deliberate, and
   Fribbels calls it "worst-case timing" too, but it is an error of a third.
2. **Which tier applies is not a preference, it is a fact about the account.** `low` and `high`
   differ by 2.7× and the difference is entirely *"are your 4★ characters already C6"*. A page
   asking the user to guess that is asking them something the database already knows.
3. **The answer changes while you pull.** A 4★ character three constellations short pays 2
   starglitter until C6 and 5 after. A long campaign crosses that line, so the true refund rate
   **rises as the campaign runs** — which no constant can express.

### What it would model

A Monte Carlo over the 4★ stream, run alongside the exact 5★ convolution rather than replacing
it. Per pull:

| | |
|---|---|
| **4★ arrival** | its own pity: 5.1% base, guaranteed at 10. Independent of the 5★ counter. |
| **Featured or not** | a 4★ is one of the banner's three featured characters half the time, else from the standard pool. |
| **Character or weapon** | the standard 4★ pool holds both, so this is **not** a coin flip and needs the pool composition per patch. |
| **Which one** | uniform within the chosen pool. |
| **What it pays** | new character → a constellation and 2 starglitter; already C6 → 5; any weapon → 2. |
| **Roster state** | mutates as the run proceeds, which is the whole reason this is a simulation. |

**5★ contributions would be included**, which the constant ignores entirely: a 5★ weapon pays
10 starglitter, a duplicate 5★ character 10 before C6 and 25 after.

### The thing only this repo can do

**We know the roster.** `/api/v1/roster` already records tri-state ownership per character with
its source, and `builds.constellation_level` records how far along each one is. So the
simulator can derive the actual 4★ pool and the actual C6 count instead of asking. Fribbels
cannot: it has no roster, which is precisely why its equivalent is a three-way guess in a
dropdown. **This is the feature's strongest differentiator and it needs no new data.**

Gaps to close first, each needing a source before anything is built:

- The **standard 4★ pool composition** per patch — how many characters against how many
  weapons. The catalogue has the characters; whether it marks pool membership is unchecked.
- Whether the **three featured 4★** are drawn uniformly, and the soft-pity shape of the 4★
  counter, which is published only as a consolidated rate.
- **Stardust is not in scope**: 3★ weapons pay Masterless Stardust, which buys Acquaint Fate,
  which buys the standard banner. Out by the same ruling that excluded Acquaint.

### Shape

`scripts/` first, not `app/`: run it offline over a grid of (roster shape, campaign length) and
see whether the answer is a smooth function of two or three account facts. **If it is, the
product is a better-calibrated constant plus a roster-derived tier, and no simulator ships at
all** — which would be the good outcome. Only if the answer genuinely depends on the path does
a per-request simulation earn its place, and then it is a job with progress rather than a
request that blocks, at the cost `RESEARCH_wish_planner.md` §4 measures for browser runs.

**Do not put a sampler on the request path to replace a closed form that is already exact.**
The 5★ ladder stays exact; only the refund would be sampled, and only if it must be.

---

## 8. Open questions

| | |
|---|---|
| ~~**OQ-W8**~~ | ~~A combined ladder from one budget, with strategy ordering.~~ **Built 2026-09-22**, and generalised past Fribbels: *Custom plan* takes an ordered list of goals across several characters, which its Simple mode cannot express. |
| ~~**OQ-W4**~~ | ~~Multi Target.~~ **Built 2026-09-22** as *Custom plan*. |
| **OQ-W9** | Fribbels syncs pity, guarantee and currency **live** from the reliquary-archiver scanner. Genshin's analogue is the wish history export — same idea as OQ-W5. **Owner, 2026-09-22: low priority, not needed yet.** |
| ~~**OQ-W10**~~ | ~~Per-phase income rather than per-patch.~~ **Shelved 2026-09-22**, owner's instruction, after checking: the workbook has no phase structure in any of its 54 patch tabs or its three other tabs, and no equivalent of the Telegram source Fribbels uses for HSR publishes Genshin income per phase. It stays a known under-resolution that rounds in the player's favour. |
| **OQ-W11** | The refund tiers understate by **1.34×** because they price a 4★ every 10 pulls rather than every 7.66. Fix by calibration, or by the simulator in §9? |
| **OQ-W5** | Genshin's wish history is exportable. Derive pity / guarantee / losses rather than asking? Would make the losses counter exact instead of remembered. |
| **OQ-W7** | Does the character banner's two concurrent 5★ split the 50/50 further? gachasim models one promotional character per banner; Genshin runs two. Needs checking before the rate is trusted for a specific character. |
