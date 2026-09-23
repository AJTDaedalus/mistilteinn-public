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

## 9. Planned — the starglitter refund, computed exactly

Owner, 2026-09-22: ship the flat refund first, *"and then draft a plan for building a real
refund simulator like zzz.163.moe"*, then — *"source the rates for each of the 3 on banner 4
stars. We should source their current constellations from the user's account, but let them
tweak it if they want (bold if it's sourced, regular italics if it's user edited). There's
also a chance of non-banner 4\*s, model that too. We should use the user's account for those
too to see what kind of refund it is, but don't give them those to edit because it's too much.
Ideally we'd also have a banner selector where you can pick from the last 8 or so banners, and
then a 'custom' builder where you pick the limited and the 4\*s."*

**Nothing below is built.** Everything it needs is sourced.

### 9.1 The 4★ stream, published in full

`https://genshin-impact.fandom.com/wiki/Character_Event_Wish` (read 2026-09-22) specifies it
completely, citing the same 9.45M-wish estimation that backs this repo's 5★ curves:

| | |
|---|---|
| **Base rate** | 5.1% |
| **Soft pity** | **56.1% at 9 wishes** since the last 4★ — a real ramp, not flat-then-guarantee |
| **Hard pity** | 100% at 10 |
| **Consolidated** | 13% official, **13.057%** community |
| **Featured rule** | *"Every time a player obtains a 4★ item, there is a 50% chance it will be one of the featured 4★ characters"*, and if it is not, **the next 4★ is guaranteed featured** |

So the 4★ stream is **the same two-branch 50/50-with-guarantee shape as the 5★**, at its own
rates, and the exact machinery in `planner.py` already models that shape. The three featured
characters are then drawn from that featured half — **16.67% of all 4★s each**, which is the
rate the owner asked for.

**One subtlety the same page publishes and a naive model would miss.** The 5★ and 4★ rolls are
independent per wish; a 5★ satisfies the *"4★ or above"* guarantee for that wish, but **does
not reset the 4★ counter**, which carries to the next wish instead.

### 9.2 The non-featured half is a roll, not a pool — and the pool sizes are a trap

**An earlier draft of this section was wrong, and the owner caught it.** It read the
`{{Wish Pool}}` sizes — 45 non-featured characters against 18 weapons — and concluded a
non-featured 4★ is a character 71.4% of the time. That assumes the game draws uniformly from
the combined pool. It does not.

`Wish/Expanded Wish Probabilities` publishes the real structure, which is the one the owner
described: **character-versus-weapon is rolled first, and only then is an item drawn from that
side's pool.** On the character banner:

| | share of all 4★ | |
|---|---|---|
| featured (always characters) | **66.67 %** | |
| non-featured **characters** | **5 %** | 15% of the non-featured third |
| non-featured **weapons** | **28.33 %** | 85% of it |

So it is the *opposite* of what pool size implies: a non-featured 4★ is a **weapon 85% of the
time**, not a character 71% of the time. The wiki names the reason — the mechanic keeps
characters and weapons balanced whichever banner you pull, so the character banner hands you
weapons and the weapon banner hands you characters.

**Pool size does not set the odds**, and a simulator that draws uniformly over 63 items would
be wrong by 5.7× on the non-featured character rate.

#### Settled, with primary sources and the owner's own pulls

The owner reconsidered — *"it may pull from the entire 4★ pool, character and weapon"* — and
then asked the right question: *"why are the pools different? And why is the probability so
weird? We need more reliable data sources."* Both are now answered.

**Why the pools differ: they do not.** Each banner simply removes its *own* featured items.
Character banner 45 = 48 standard 4★ characters − its 3 featured; weapon banner 16 = 18
always-available 4★ weapons + 3 currently featured-only − its 5 featured. Diffing the two
lists shows exactly the featured items moving across and nothing else, bar one wiki lag
(Jahoda). There is no second pool and no mechanic here.

**A primary source exists**, and it is HoYoverse's own regulatory rate disclosure, published
as static JSON: `https://webstatic.mihoyo.com/hk4e/gacha_info/cn_gf01/<gacha_id>/en-us.json`,
indexed by `.../gacha/list.json`. **Every 5★ rate this repo ships is confirmed by it**:

| | official | ships here |
|---|---|---|
| character 5★ base / consolidated / featured | 0.600 % / 1.600 % / 50 % | same |
| weapon 5★ base / consolidated / featured | 0.700 % / 1.850 % / 75 % | same (×½ for which of two) |
| character 4★ base / consolidated / featured | 5.100 % / 13.000 % / 50 % | 13.057 % community |
| **weapon 4★ base / consolidated** | **6.000 % / 14.500 %** | **not modelled — see OQ-W15** |

Only the soft-pity *ramp* is unpublished; everything else is now primary rather than a
community fit read through gachasim. The public index is frozen at 2023 banners, which is
enough to pin constants and not enough to track current ones.

**But the disclosure is silent on the non-featured split.** It publishes one flat 4★ list with
an `is_up` flag and one featured probability. No per-item probabilities, nothing about
character-versus-weapon. So the 15/85 has no primary backing, and an earlier version of this
section calling a two-banner comparison "decisive" was overclaiming: that argument is only
valid *if* the wiki's two splits are real measurements, which is what could not be checked.

**So it was measured.** The owner supplied a wish-history authkey link, and **1,416 character
banner pulls** settle it:

| | measured | |
|---|---|---|
| 4★ rate | **12.99 %** | against the official 13.000 % — the data and the parse are sound |
| 4★ weapons, share of all 4★ | **27.2 % ± 3.3** | |
| ⟶ wiki's rolled model predicts | 28.3 % | **z = −0.35, consistent** |
| ⟶ uniform over the combined pool predicts | 9.5 – 12.8 % | **z = +4.4 to +5.4, rejected** |

And a structural test with no free parameters. A 4★ *weapon* on the character banner is
always non-featured, and the published rule says a non-featured 4★ guarantees the next one is
featured — so **two 4★ weapons in a row must be impossible**. Across 183 adjacent pairs:
**zero**, where independence predicts 13.5. The featured guarantee is confirmed outright.

Backing the split out of the same data — every weapon here is non-featured, and the
non-featured third is fixed at 33.33 % by the published rule — gives **81.5 % weapons /
18.5 % characters ± 9.8**, against the wiki's 85 / 15. Consistent, and now independently
sourced.

**The owner's first instinct was right and the uniform reading was wrong.** Character-versus-
weapon is rolled first; only then is an item drawn from that side's pool. Pool size does not
set the odds.

### 9.3 What the numbers actually come out at

**A first copy pays nothing.** The wiki's quantity table lists *duplicates* only, so a 4★
character you do not own yet returns a constellation and no starglitter. Weapons always pay 2.
That makes the axis two-dimensional — how many 4★ characters you own, and how many are C6 —
and is the sharpest argument that no constant is right for long.

Priced at the consolidated 13.057%, with 71.67% of 4★s being characters:

| account | starglitter per 4★ | refund, compounded |
|---|---|---|
| still collecting — ~60% owned, none C6 | 1.43 | **3.9 %** |
| owns them all, none at C6 | 2.00 | 5.5 % |
| owns them all, half at C6 | 3.07 | **8.7 %** |
| owns them all, all at C6 | 4.15 | **12.2 %** |

The three bold rows are what ships as `low` / `average` / `high`. **The previous values —
4.2 / 7.5 / 11.1 % — were wrong twice over**: they priced a 4★ every 10 pulls rather than
every 7.66, and they varied the wrong axis, because they were Fribbels' HSR labels, which are
right for HSR and not here.

**The banner changes the answer, and the shipped constant cannot.** Because the character
banner's featured third is *characters* and the weapon banner's is *weapons*, a maxed account
refunds **12.2 % on the character banner and 7.2 % on the weapon banner** — the same account,
nearly double. The tiers above are the character banner's; a campaign mixing both is somewhere
between, weighted by where the wishes go. That is a fourth reason the honest answer is
computed rather than chosen from a dropdown.

**Built, and weighted in spending order rather than in proportion** (`_refund_for_campaign`).
A campaign spends *sequentially*: the ladder's own milestone walk gives each leg's expected
cost, and the budget is filled down that list, `min(remaining, cost)` per rung, with each
rung's spending credited to its own banner's rate.

The proportional split this replaced was wrong in three ways that a test asserting
`refund > 0` could not see:

- **It priced wishes on banners the plan never reaches.** A 90-wish wallet aimed at a
  character goal averaging 93.4 wishes still put 36 of those 90 on the weapon banner.
  Measured against a maxed roster: 7.02 wishes back where the truth is 8.98, **22 % low**.
- **It redistributed an unpriceable leg's spending instead of dropping it.** `total_cost`
  summed only the *slugged* legs, so a row with no banner handed its share to the named ones —
  **double** the refund, and the opposite of what the docstring promised. A leg whose banner
  is merely *unknown* was dropped correctly, so the same situation was handled two ways.
  Both now consume their budget and earn nothing.
- **It priced the whole wallet.** A 2,000-wish wallet aimed at one ~93-wish goal reported a
  refund over all 2,000. The `min(budget, …)` that claimed to guard this could never bind:
  `cost <= total_cost` by construction, so it had exactly one answer.

**The compounding is iterated to a fixed point, not done twice.** The refund buys wishes which
refund again. The earlier note that "the third pass is under a wish" is false at scale: on a
900-wish wallet against a maxed forty-character roster the passes run 96.82, 107.23, 108.42,
108.53 to a fixed point of 108.40 — the third is worth **1.19** wishes. It is monotone and
bounded, so it converges and can never *reduce* the reported refund.

**One picker cannot label two legs.** Simple mode's single banner choice applies only to the
leg whose kind it matches; the other sends no banner and earns nothing. Sending the same slug
to both priced a weapon leg's pulls with a character banner's featured 4★ *characters* — a
50 % featured rate against 75 % — and collapsed both legs onto one key, so the per-leg split
did nothing in the default mode. Pairing a character with their signature weapon's own banner
is the open item, not a second guess from the client.

### 9.4 Reading the account, and letting it be corrected

The tier is not a preference. It is *"how many of the 4★ characters I can pull are already
C6"*, and the database knows: `/api/v1/roster` records tri-state ownership per character with
its `source`, and `builds.constellation_level` records how far along each is.

- **The three featured 4★** are shown with their constellations **read from the account and
  editable**. Owner's rule for the display: **bold when sourced from the account**, *regular
  italics when the user has edited it* — so a corrected value never looks like a known one.
  `RosterEntryRead.source` already distinguishes `import` from `manual`, which is the same
  distinction one level down.
- **The non-featured pool is read from the account too, and is not editable.** Sixty-three
  rows is not a form. It contributes to the refund as a *distribution* — how many of the 45
  are at C6 — rather than as a list.
- **An existing account falls back until it re-imports.** `character_roster.constellation` is
  new and every row written before it is NULL, so a roster that has never been re-imported
  supports no exact refund.

  **It falls back to `none`, not to a tier** (owner ruling, 2026-09-22). A tier the caller did
  not choose is a number they have no reason to trust, and quietly substituting one is how the
  control came to mean nothing: the account used to *override* whichever tier was selected, so
  the dropdown sat reading "8.7% (Average)" while the roster priced the plan. `account` is now
  a value of that control and its default, a tier is honoured when asked for, and
  `refund_source` has a third verdict — `none` — which is distinct precisely because it is the
  only one the caller did not pick.

  It is visible, but **not as prose in the budget line**: that read *"(from your roster)"* and
  was removed under the page's text convention — give the data, not a commentary on it. What
  the user sees instead is the control itself showing *"Calculate with my account"*, and the
  one warning the owner did approve, for the case where they asked for it and the roster could
  not answer: *"No constellation data on account, providing refund options instead."*
- **Missing is missing.** A character with no build has no constellation, and that is not
  "C0": it is unknown. Defaulting unknown to C0 would make a large roster read as though
  nothing were maxed and understate the refund; defaulting to C6 would do the reverse. The
  count of unknowns is reported, and the page says how much of the answer rests on them.

### 9.5 Banner selection

`Category:Character Event Wishes` on the wiki holds **253 pages**, one per banner run, each
named `<Banner>/<YYYY-MM-DD>` and each carrying a `{{Wish}}` infobox with `time_start` /
`time_end` and a `{{Wish Pool}}` with the featured 5★, the three featured 4★, and both
non-featured pools. That is the whole of what a banner selector needs.

**Every banner, eight at a time** (owner, 2026-09-22). The snapshot holds all 253; the picker
shows the eight most recent and a *Show more* that reveals the next eight. Not a scroll box of
253 and not a truncated list — `CLAUDE.md` records the planner materials tab being "fixed" by
capping a 514-row list at 80, which made the page short by hiding the data. *Show more* hides
nothing; it defers.

**Banner cards**, per the owner's layout:

| | |
|---|---|
| **Character banner** | the featured 5★'s **headshot first and largest**, then the three featured 4★ headshots beside it, smaller. |
| **Weapon banner** | the **weapon first**, carrying a **mini portrait of the character it is the signature of in its corner**, then the on-banner 4★ weapons beside it, slightly smaller. |

The signature link is the one thing here the catalogue does not already answer. `app/data/kqm/`
carries weapon recommendations per character, which is a *"which weapons suit this character"*
mapping — the inverse of *"whose signature is this weapon"*, and not the same question: a
weapon can be recommended for many characters and be nobody's signature. The honest sources
are the banner data itself (a 5★ weapon banner runs alongside a character banner, and its
`alongside` field is in the `{{Wish}}` infobox already being parsed) or a curated mapping with
citations. **Deriving it from `alongside` is the better answer** — it needs no new data and it
is what "signature" actually means in practice.

**Art is already vendored.** `CatalogueIcon` and `frontend/public/icons/` hold committed
character and weapon art, 446 files, and `scripts/download_icons.py` reproduces them. A card
needs no new asset pipeline — but it does need every banner name to resolve to a catalogue
row, which is the invariant below.

- **A custom builder**, for a banner that has not been announced or for a hypothetical:
  choose the limited 5★ and the three 4★ from the catalogue, and inherit the most recent
  non-featured pools.

**It is a snapshot with a refresher, exactly like the income store** — `scripts/`, never
`app/`, a committed JSON so a fresh clone and CI need no network, and invariants that refuse a
bad refresh rather than writing it: every banner has exactly one featured 5★ and three
featured 4★, the pools are non-empty, and every name resolves against the seeded catalogue. A
name that does not resolve is the failure mode here, and it is the one `#263` already shipped
once — 205 weapon ids that matched nothing in production, silently.

### 9.6 Refund variance — how to model it for a user

Owner asked directly. Measured answer first, because the magnitude decides the design.

**The refund is independent of the cost, and HoYoverse publishes that it is**: *"each
individual Wish calculates 5★ and 4★ drop probabilities independently."* The cost is a 5★
question and the refund a 4★ one, so the honest model is not a simulation but a dot product:

```
P(success) = Σ_b  P(budget = b) · P(cost ≤ b)
```

Both halves already exist — the ladder gives the second exactly, and the first is a small PMF
off the 4★ stream.

**It barely moves.** The budget's standard deviation is **2.7 – 4.2 wishes**, because the
refund is ~8 % of the budget and the 4★ count's own relative spread over a few hundred pulls is
~20 %. Integrating it against the ladder rather than using the mean changes the reported
probability by:

| wallet, tier | budget mean ± sd | largest change to any rung |
|---|---|---|
| 160, average | 173.4 ± 2.7 | +0.18 pt |
| 200, average | 216.9 ± 3.1 | +0.34 pt |
| 260, average | 282.1 ± 3.5 | +0.05 pt |
| 200, high | 223.8 ± 4.2 | **+0.99 pt** |

Always slightly **positive** — Jensen, since the CDF is convex through the range the budget
distribution covers — so the point estimate is mildly *pessimistic*, which is the safe side.

**So: fold it in, and show the user nothing.**

1. **Integrate it** rather than using the mean. One dot product against a ≤ 20-entry PMF, exact
   given published independence, and it retires the caveat instead of printing it.
2. **Do not show a range.** The success chance is *already* a probability; putting
   "215 ± 3 wishes" next to "65 % chance" invites a reader to count the same uncertainty
   twice, and the second number is a tenth the size of the first. The budget line stays one
   number — prefixed "≈", because it is an expectation.
3. **Spend the UI on the tier instead.** Choosing `low` against `average` moves the budget by
   about **10 wishes**; the variance is ±3. The tier is three times the uncertainty and it is
   the part a user is currently *guessing*. §9.4's roster-derived constellations remove that
   guess, which is worth more than modelling the variance ever will.

That is the general shape of the answer: **the uncertainty a user should see is the one they
can act on.** They can fix a wrong constellation. They cannot do anything about the spread of
a binomial.

### 9.7 It never needs to be a simulator — and the histogram is already free

Owner, 2026-09-22: *"would it be better to switch from raw probabilities to simulations and
show a histogram? Could we generate a histogram without simulations based on the refund
variance?"* and then *"is it possible to model the refund pool mathematically without
simulation to make it 'exact' as well with a distribution?"*

**The histogram already exists and is exact.** The convolution's output *is* the distribution
of wishes-to-a-rung; the page computes it and then throws all but three numbers away. Reaching
C2 has a 409-wish-wide support peaking at 311, and the shape is visibly multi-modal — one hump
per pity cycle — which is information the mean and the median cannot carry. **Switching to
simulation would replace an exact answer with a noisy estimate of it.**

**And the refund is exactly computable too.** It looks path-dependent because a featured 4★
crosses C6 *during* a campaign and its payout changes from 2 starglitter to 5. It is not.
Prototyped 2026-09-22, four nested exact steps and no sampling anywhere:

| step | how |
|---|---|
| 4★ count in *N* pulls | the same first-passage convolution, on the 4★ curve. Came out at 13.0627 % against the official 13.000 % |
| featured vs non-featured | a **2-state Markov chain** — 50 % with the next guaranteed. Exact for any count; 66.2 % of 26 four-stars against the published 66.67 % |
| the three featured characters | counts are multinomial, so **not** independent — handled by nesting the binomials exactly rather than by sampling. O(F²), and F is under 40 for any real campaign |
| non-featured **weapons** (85 % of the non-featured third) | always 2 starglitter, so `2 × count` |
| non-featured **characters** (15 %) | the *same* nesting as the featured three, with the roster's ~45 categories instead of 3 — `O(n · draws²)`, processed one character at a time conditioning on the draws left |

Given a character's own draw count, its payout is a **deterministic** function — that is the
step that dissolves the apparent path-dependence:

    g(k) = 2 · min(k − u, 6 − c)⁺ + 5 · (k − u − (6 − c))⁺      u = 1 if unowned

**The first prototype was not exact here and the owner caught it.** It priced *every*
non-featured 4★ at 2 starglitter, which is right for the 85 % that are weapons and wrong for
the 15 % that are characters — those pay 0 unowned, 2 below C6 and **5 at C6**. On a roster of
20 at C6, 10 at C4, 8 at C2 and 7 unowned the true figure is **3.02 starglitter a draw, not
2**. It is a small slice — about 1.3 such draws per 200 pulls, so **+0.27 wishes** — but it is
a *bias* rather than noise, and it understates exactly the maxed accounts the `high` tier is
for. The fix is the same nesting at 45 categories and runs instantly.

Over 200 pulls, with that slice still simplified:

| account | starglitter | in wishes |
|---|---|---|
| three featured all at C6 | 102.7 ± 8.8 | **20.5 ± 1.8** |
| one C6, one C2, one unowned | 73.2 ± 8.6 | **14.6 ± 1.7** |

So §9 is **not a simulator** and this section is no longer named as though it were. Nothing in
this feature needs sampling: the cost is exact, the refund is exact, and their independence is
published.

### 9.8 What to draw

- **The cost distribution as a histogram**, which costs nothing because it is already computed.
  The multi-modality is the point — a reader sees the pity cycles rather than being told a mean.
- **The budget as a marker line on it.** The area to its left *is* the success chance, so the
  table's headline number becomes something you can see rather than something you take.
- **The refund's spread is a ±2-wish band on that line** (§9.7), against a distribution
  hundreds of wishes wide. Drawing it honestly means drawing it thin.

**Population, not sample.** The PMF *is* the distribution rather than an estimate of it:
no standard error, no confidence interval, identical to the last bit on every run. What
remains is **model** error — the fitted soft-pity ramp, the 15/85 split, the roster's unknown
constellations — and a simulation would carry all of that *plus* sampling noise. That is the
whole argument for not sampling.

**And the opposite caveat to the resin histograms applies.** `CLAUDE.md` records that the
planner's resin histogram falls back to a two-point distribution when only a mean is known, so
it is *narrower than reality* and every surface says so. This one is exact, and should say
that instead — the two cases look identical on screen and are not the same claim.

### 9.9 Shape, and the bar for shipping it

**§9.7 settles the shape**: this is a closed form, so it belongs in the request path beside the
ladder rather than in a job. The open question is no longer *simulate or not* but *how much of
the roster to read* — §9.4's unknown-constellation problem, OQ-W12.

`scripts/` first is still right, but for a different reason than the one this section
originally gave: to check the exact computation against a naive simulation before trusting it,
the same way `tests/unit/test_wish_planner_crossval.py` checks the ladder.

---

## 8. Open questions

| | |
|---|---|
| ~~**OQ-W8**~~ | ~~A combined ladder from one budget, with strategy ordering.~~ **Built 2026-09-22**, and generalised past Fribbels: *Custom plan* takes an ordered list of goals across several characters, which its Simple mode cannot express. |
| ~~**OQ-W4**~~ | ~~Multi Target.~~ **Built 2026-09-22** as *Custom plan*. |
| **OQ-W9** | Fribbels syncs pity, guarantee and currency **live** from the reliquary-archiver scanner. Genshin's analogue is the wish history export — same idea as OQ-W5. **Owner, 2026-09-22: low priority, not needed yet.** |
| ~~**OQ-W10**~~ | ~~Per-phase income rather than per-patch.~~ **Shelved 2026-09-22**, owner's instruction, after checking: the workbook has no phase structure in any of its 54 patch tabs or its three other tabs, and no equivalent of the Telegram source Fribbels uses for HSR publishes Genshin income per phase. It stays a known under-resolution that rounds in the player's favour. |
| ~~**OQ-W11**~~ | ~~The refund tiers are wrong in two directions.~~ **Corrected 2026-09-22** to 3.9 / 8.7 / 12.2 %, on the consolidated 4★ rate and on the axis that actually drives it. |
| ~~**OQ-W13**~~ | ~~The 15/85 split is uncited and unreproduced.~~ **Measured 2026-09-22** against the owner's 1,416 character-banner pulls: 81.5/18.5 ± 9.8, consistent with the wiki and rejecting uniform at z > 4. §9.2. |
| **OQ-W15** | The **weapon banner's 4★ rates are 6.0 % / 14.5 %**, not the character banner's 5.1 % / 13 %. The refund prices every wish at 13.057 %, so a weapon-banner campaign is under-priced by 1.115×. |
| **OQ-W14** | §9.5: derive "whose signature is this weapon" from the banner data's `alongside` field, or curate it? |
| **OQ-W12** | §9.4: the column is nullable so unknown stays unknown (OQ-W16), but **how much unknown is too much** before the refund figure should be withheld rather than estimated is still unanswered. |
| **OQ-W20** | §9.8: a histogram per rung, or one for a selected rung? Twelve goals × a 400-wide PMF is a lot of chart for one page. |
| **OQ-W5** | Genshin's wish history is exportable. Derive pity / guarantee / losses rather than asking? Would make the losses counter exact instead of remembered. |
| ~~**OQ-W7**~~ | ~~Do the two concurrent 5★ split the 50/50 further?~~ **No — resolved 2026-09-22** from HoYoverse's disclosure: `r5_up_items` holds exactly **one** character for gacha_type 301, and Character Event Wish-2 is a **separate** gacha_type (400) with its own single promotional character and its own 50%. The 50% is the whole story. (The weapon banner is the one with two, `r5_up_items` = 2, which is why its featured rate is 0.75 × ½.) |
| ~~**OQ-W16**~~ | **Built 2026-09-22** — `character_roster.constellation`, nullable, written by the importer for every owned character and editable by hand. Original text: **BLOCKER for §9.4.** A GOOD export carries `constellation` for *every* owned character, and `good_build_service` persists it **only onto builds — and only equipped characters get a build**. `character_roster` records ownership and no constellation. So for an owned-but-unequipped 4★ the constellation is parsed and then **discarded**, and those are exactly the characters the refund turns on. Fix is small (a column on the roster row, written during import) but it is a schema change and a decision. |
| ~~**OQ-W17**~~ | **Fitted 2026-09-22**, and the published numbers forced the shape: a single raised step cannot reach 14.5 % — even a certainty at pity 9 gives only 14.05 % — so the ramp must start at pity 8. 0.5778 at both 8 and 9 reproduces 14.500 % exactly. Recorded as a fit, with the same identifiability caveat as the 5★ ramps. Original text: The **weapon banner's 4★ soft-pity ramp is unpublished.** Base 6.0 % and consolidated 14.5 % are official; the shape — the character banner's is 5.1 % to pity 8, 56.1 % at 9, 100 % at 10 — is not published for it anywhere found. Fit it against the published 14.5 % the same way the 5★ ramps were fitted, and mark it a fit rather than a source. |
| ~~**OQ-W18**~~ | **Answered 2026-09-22, §9.6**: integrate it (one dot product, exact given published independence), show the user nothing, and spend the UI on the tier instead — which is 3× the uncertainty and the part they are guessing. Original text: **Refund variance.** The budget is `wallet × (1 + r)`, deterministic. Simulating the refund makes it a *random variable* correlated with the cost — more pulls, more refund — so the ladder's CDF would have to integrate over it. The mean is right either way; the **spread is understated**. §9.5 does not supply this; it is maths to be written. |
| ~~**OQ-W19**~~ | **Accepted by the owner, 2026-09-22** — *"within-pool similarity is acceptable."* Original text: **Within-pool uniformity is assumed, never verified.** The disclosure publishes no per-item probabilities, so "a specific non-featured character is as likely as any other" is an assumption. Low risk, cheap to test with a larger sample, and it changes which *constellations* fill in rather than the character/weapon split. |
