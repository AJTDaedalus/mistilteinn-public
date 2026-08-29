# RESEARCH — Fribbels Honkai: Star Rail Optimizer

A feature and navigation inventory of `fribbels/hsr-optimizer`, written so that mistilteinn
can diff its own surface against it.

## What this is and how it was gathered

**Date gathered: 2026-08-29.** Author: research subagent, no code cloned or run.

Sources, in descending order of how much I trust them:

1. **The repository's own source files**, fetched raw from
   `raw.githubusercontent.com/fribbels/hsr-optimizer/main/...` on 2026-08-29:
   - `src/lib/relics/scoring/{futureScore,potentialScore,currentScore,substatScoring,scoreFormatting,scoringConstants,scoringMetadata}.ts`
   - `src/lib/relics/scoreRelics.ts`, `src/lib/relics/estTbp/estTbp.ts`
   - `src/lib/tabs/navigation/constants.ts`, `src/lib/tabs/tabRelics/columnDefs.ts`,
     `src/lib/tabs/tabRelics/topBar/FilterPillBar.tsx`,
     `src/lib/tabs/tabRelics/bottomDock/BottomToolbar.tsx`,
     `src/lib/tabs/tabRelics/relicInsightsPanel/{BucketsPanel,Estbp}.tsx`
   - `public/locales/en_US/{sidebar,relicsTab,charactersTab,settings,importSaveTab}.yaml`
   - directory listings via `api.github.com/repos/fribbels/hsr-optimizer/contents/...`
2. **The project's own user guides**, `docs/guides/en/*.md` in the same repo —
   `relics-tab.md`, `stat-score.md`, `optimizer.md`, `benchmarks.md`,
   `score-customization.md`, `live-import.md`.
3. **DeepWiki's generated wiki** (`deepwiki.com/fribbels/hsr-optimizer`) for the
   scoring-system and optimizer-tab pages. This is a machine-generated reading of the repo,
   not author-written documentation — I use it only where it names a file or function I could
   corroborate, and I flag anywhere I could not.

### Honesty note — how these fetches worked, and what that costs

Every fetch went through a summarising reader rather than returning raw bytes. It **refused to
reproduce documents verbatim** and returned paraphrase plus selected quotes. So:

- Text in `"double quotes"` or in code blocks below was returned to me as a quotation from the
  source. I believe those are accurate transcriptions.
- Everything else is the summariser's paraphrase of a file I did not see in full.
- **I did not view a single screenshot of the running app**, and I did not load the live SPA.
  Every claim about visual appearance, density, or colour is therefore inference from code
  (component names, CSS module names, cell renderers) and is marked as such.

Where I could not determine something, it says so. Nothing below is filled in from prior
knowledge of the tool.

---

## 1. Top-level navigation

Two authoritative sources agree: the `AppPages` enum in
`src/lib/tabs/navigation/constants.ts`, and the human labels in
`public/locales/en_US/sidebar.yaml`.

`AppPages` enum order (source order, not necessarily display order):

```
HOME, OPTIMIZER, CHARACTERS, RELICS, IMPORT, CHANGELOG,
SHOWCASE, WARP, BENCHMARKS, CALCULATORS, LEADERBOARD,
WEBGPU_TEST, METADATA_TEST
```

Route hashes: `#main`, `#showcase`, `#changelog`, `#warp`, `#benchmarks`, `#aha`, `#ehr`,
`#leaderboard`, `#webgpu`, `#metadata`, `#characters`, `#relics`, `#import`. Base path
`/hsr-optimizer`, with a parallel beta path `/dreary-quibbles`.

The **sidebar groups these into three sections** (from `sidebar.yaml`, in file order):

| Section | Entries |
|---|---|
| **Tools** | Showcase, Warp Planner, Benchmarks, Calculators |
| **Optimization** | Optimizer, Relics, Characters, Import / Save, Settings, Get Started |
| **Links** | Home, Changelog, Discord, GitHub, Ko-fi, No leaks, Beta content |

What each is for (from the guides and locale strings):

- **Optimizer** — the search. Pick character + light cone, set filters and constraints, run a
  permutation search over your relics, get a ranked results grid.
- **Relics** — the whole inventory as a sortable/filterable grid, with per-relic scoring and
  potential columns.
- **Characters** — your roster as an ordered **priority list**; priority governs which
  character may take relics from which (see §2).
- **Import / Save** — scanner import, plus save-file export/load/clear.
- **Showcase** — a shareable build/profile card. `#showcase`.
- **Warp Planner** — jade/pity budgeting for banners. Not an optimizer feature at all.
- **Benchmarks** — the simulation-based DPS/Heal/Shield/Support scoring surface.
- **Calculators** — `#aha` and `#ehr` hashes suggest at least two standalone calculators
  (*inference from hash names; I did not confirm what "aha" is*).
- **Leaderboard** — `#leaderboard`. *I did not investigate its contents.*
- **Get Started** — loads a sample save file so a new user can walk the app with data in it.
  This is a real onboarding affordance and worth noting.
- **Changelog** — an in-app tab, not an external link.
- `WEBGPU_TEST` / `METADATA_TEST` — developer surfaces.

**Two "Links" entries are settings, not links**: *No leaks* (hide unreleased content) and
*Beta content*. *Inference from their placement and naming; not confirmed.*

---

## 2. The character / build page

The Characters tab is a **roster list ordered by priority**, and the Character Preview is the
build view. Strings from `charactersTab.yaml`, verbatim:

**Per-character menu actions:**
- "Add new character"
- "Edit character / light cone"
- "Switch relics with"
- "Unequip character"
- "Delete character"
- "Save current build"
- "View saved builds"
- "Move character to top"

That list is worth reading twice. It includes **named saved builds per character**, a
**"switch relics with"** direct swap between two characters, and **"move character to top"** —
which is the priority mechanic surfaced as a one-click action.

**Priority is load-bearing, not cosmetic.** From `optimizer.md`: the Character Priority filter
"defines which relics the character may steal from other characters. Characters can only take
relics from lower priority characters." So the roster order is a real constraint on the search.
`settings.yaml` confirms it is a first-class concept — `NewCharacterDefaultRank` chooses
whether a newly added character lands at "Highest priority (Rank #1)" or "Lowest priority".

**Equipping behaviour is a setting**, `RelicEquippingBehavior`:
- Replace — "Default: Replace relics without swapping"
- Swap — "Swap relics with previous owner"

That is, when you equip a piece already worn by someone else, the app can hand that character
your old piece back. *This is a real conflict the tool models explicitly.*

**What the preview shows** (per DeepWiki's character-preview page, corroborated by the
`characterPreview` source directory existing): character portrait, light cone, all equipped
relics, and statistics in **two modes — basic stats and combat stats**, where combat stats
include buffs and conditionals. There are "substat upgrade comparisons" and "relic rarity
upgrade comparisons" — i.e. *if you rolled this substat once more / if this were a 5-star,
here is the damage delta.*

**Scoring shown on the build page:**
- A **DPS Score** with a letter grade — "DPS Score rates build quality by comparing an ability
  rotation's damage to benchmark builds".
- Four benchmark flavours by role: "DPS Benchmark", "Support Benchmark", "Heal Benchmark",
  "Shield Benchmark".
- A **grade ruler** visualising baseline / benchmark / maximum on one scale.
- An **Estimated TBP** readout per equipped relic — how many days of farming to beat it (§4).

**Presets and customisation** (from `score-customization.md` and `charactersTab.yaml`):
- "Scoring algorithm" button opens the weight editor.
- Trace on/off toggles (disabled traces put asterisks on the showcase card — a nice honesty
  affordance).
- "SPD precision" — 1 or 3 decimals, 1 default.
- "SPD weight" — 0%–100%, default 1.0; explicitly "does not change the combat score, it only
  changes the relic and character scores".
- "SPD benchmark" — target a SPD value so surplus stats get reallocated into damage.
- Buff priority — main DPS vs Sub DPS; some characters ship with Sub DPS "enabled by default".
- Display: "Auto" / "Custom" / "Standard"; grid density "Default" / "Compact"; colour theme;
  screenshot export.

**Where the recommended presets come from — I could not determine this cleanly.**
`scoringMetadata.ts` resolves per-character weights via `getScoringMetadata(id)` backed by
`getGameMetadata().characters[id]?.scoringMetadata`, so **defaults are shipped in the repo's
game-metadata, per character**, carrying `stats` weights, `parts` (preferred main stats per
slot), `flatMainstatBoost`, `minWeightedRolls` and a `modified` flag. Whether those defaults are
authored by the maintainer or contributed by the community, **I could not establish** — nothing
I read names their provenance. The `modified` flag strongly implies user overrides are stored
alongside defaults (*inference*).

---

## 3. Relic (artifact) management

**Display: a table, via AG Grid** (`AgGridReact`, per DeepWiki and the `RelicsGrid.tsx` /
`columnDefs.ts` file names). Not a card grid. This matters — Fribbels chose density over
prettiness for a 2000-item inventory.

**Baseline columns** (verbatim from `columnDefs.ts`, `generateBaselineColDefs`):

| Field | Header | Renderer |
|---|---|---|
| `equippedBy` | Equipped By | character icon |
| `set` | Set | set icon |
| grade | `★` | grade renderer |
| `enhance` | `+` | — |
| `part` | Part | readable part |
| `main.stat` | Main Stat | readable stat |
| `main.value` | Main Value | main value renderer |
| `augmentedStats.HP_P / ATK_P / DEF_P` | HP% / ATK% / DEF% | zeros hidden, **colour gradient** |
| `augmentedStats.HP / ATK / DEF` | HP / ATK / DEF | zeros hidden, gradient |
| `augmentedStats.SPD` | SPD | tenths, gradient |
| `augmentedStats.CR / CD / EHR / RES / BE` | CR / CD / EHR / RES / BE | gradient |
| `cv` (computed) | CV | **crit value**, gradient |

Two things to steal here: **zeros are hidden rather than printed as 0**, so the eye only lands
on substats a relic actually has; and **every stat cell carries a value-proportional colour
gradient**, so a row reads as a heat strip before you read any number.

**Plus up to 12–17 optional value columns** (§4).

**Filters** — a **filter pill bar** (`topBar/FilterPillBar.tsx`, `FilterPill.tsx`), i.e. filters
live in a horizontal bar above the grid, not in a side panel. Categories, verbatim from source:

1. Part (all slots)
2. Main Stat
3. Sub Stat
4. Enhance — `+0, +3, +6, +9, +12, +15`
5. Grade — `5★, 4★, 3★, 2★`
6. Initial Rolls — "4 substats" / "3 substats"
7. Equipped — Equipped / Unequipped
8. **Verified** — Verified / Unverified
9. Relic Sets (unreleased sets excluded)
10. Ornament Sets (unreleased sets excluded)
11. Excluded Characters (a multi-select)
12. **Value Columns** — i.e. which of the scoring columns to show is itself a filter pill

"Verified" is a scanner-provenance flag: a relic whose speed decimals came from the accurate
importer versus one whose came from OCR. **mistilteinn has an exact analogue available and
almost certainly does not model it** — a GOOD export from an OCR scanner versus a hand-entered
piece.

**Sorting:** `relics-tab.md` — sort by clicking a column header. Any column, including the
scoring columns.

**Bulk / edit actions** (`bottomDock/BottomToolbar.tsx`):
- "Add New Relic"
- "Delete relic" (with a confirm modal; operates on the selected rows)
- "Edit relic" (single selection)
- Insights-mode segmented control: **Buckets / Top10 / ESTBP**
- Bucket potential mode segmented control: **Maximum / Average**
- Character plot scope select: **All / Custom / Owned**
- "Disabled in live import mode." — actions are locked while a live scanner is attached

**Relic editor** (`RelicModal`): validated via `validateRelic()`, main-stat options change with
the chosen slot, and substat entry shows "real-time upgrade value calculations".

**Relic Locator** (`RelicLocator.tsx`) — the standout. It tells you **where in your in-game
inventory the relic physically sits**: you calibrate an inventory-width setting for your screen
size, and it can auto-apply in-game-equivalent filters after N rows so the target lands near
the top of the screen. Works only with the Reliquary Archiver importer. This is the affordance
that closes the loop between "the tool says delete this" and "I am now looking at my inventory".

**Import** (`importSaveTab.yaml`, verbatim descriptions):

| Scanner | Notes |
|---|---|
| **IceDynamix Reliquary Archiver** (recommended) | "Accurate speed decimals, instant scan"; "Imports full inventory and character roster"; "Supports live importing (new/enhanced relics are imported in real time)" |
| **Kel-Z HSR Scanner** | "Inaccurate speed decimals, 5-10 minutes OCR scan"; full inventory + roster |
| **Relic Scorer Import** | "Accurate speed decimals, instant scan"; limited to the 8 characters on your profile showcase |
| **HoyoLab Import** | "Inaccurate speed decimals, instant scan"; equipped relics only |

Import accepts an uploaded JSON file **or pasted JSON text**. Save / Load / Clear manage the
whole optimizer state as a file.

**Live import is the headline**: with the archiver running, new and enhanced relics appear in
the tool *as you roll them in game*. The setup instruction is explicit — run the archiver with
`-s` and have it open **before** logging in.

---

## 4. Relic scoring and ranking — the mechanical core

This is the part mistilteinn's owner is asking about, so I have gone to source rather than
prose wherever possible.

### 4.1 The two independent scoring systems

Fribbels runs **two unrelated scoring systems**, and conflating them is easy:

1. **Stat Score / relic potential** — a fast weighted-substat heuristic, per relic. Runs over
   the whole inventory. This is what the Relics tab columns show.
2. **Benchmark / DPS Score** — a *simulation* of an actual ability rotation, per build. Slow,
   per character. This is what the character page grades.

They share the letter-grade ladder but nothing else. §4.2–4.6 are about system 1.

### 4.2 Weights

From `stat-score.md`:

> Weights operate on a **0.0 to 1.0 scale in 0.25 increments**.

Documented defaults quoted in that guide:
- SPD: 1.0 for most characters
- A crit DPS: "0.75 ATK | 1.0 SPD | 1.0 CR | 1.0 CD"
- Defensive supports: HP/DEF at 0.25
- Offensive supports: RES at 0.25
- Defensive sustains: RES at 0.50

And a rule that solves the flat-vs-percent problem in one line:

> "Flat ATK / HP / DEF have their weight reduced to 40% of their equivalent percent stat's
> weight."

Confirmed in `scoringConstants.ts` — a `0.4` multiplier applied to HP, ATK, DEF when mapping
percent to flat. `estTbp.ts` uses the same 0.4.

**Weights are per character, shipped as defaults, and user-editable** via the "Scoring
algorithm" button. Structure per character (`scoringMetadata.ts`): `stats` (weight per
substat), `parts` (acceptable main stats per slot), `flatMainstatBoost`, `minWeightedRolls`,
`modified`. Their authorship is **undetermined** (see §2).

### 4.3 Potential scale — the normalisation that makes weights comparable

A weight of 1.0 on SPD and 1.0 on CD do not mean the same thing, because one SPD roll is worth
far more than one CD roll. Fribbels normalises with a **potential scale**, defined in
`scoringConstants.ts` as `6.48 / SubStatValues[stat][5].high` — i.e. **every substat is
expressed in units of one high Crit DMG roll (6.48%)**. The guide lists the resulting scales:

| Stat | Scale |
|---|---|
| CD, BE | 1.0 |
| DEF% | 1.2 |
| HP%, ATK%, EHR, RES | 1.5 |
| CR | 2.0 |
| **SPD** | **2.49** |

So a SPD roll counts 2.49× a CD roll before weights are applied. **This is the single cleanest
idea in the whole system and it ports to Genshin directly** — normalise every substat to one
high roll of a reference stat, then let the user's weights be plain 0–1 preferences.

### 4.4 The score formula

From `stat-score.md`:

```
WeightedPotential (per substat) = weight * value * potentialScale
RelicPotentialPct = weightedPotential / idealPotential * 100
```

`idealPotential` is the same computation run against a theoretical **perfect relic for that
slot and main stat** — so the score is *a percentage of the best relic that could exist for
this character in this slot*, not an unbounded number.

`currentScore.ts` corroborates: `rawScore / idealScore * 100`, guarded so an infinite
`idealScore` yields 0, then `truncate10ths()` / `precisionRound()`.

**Main stat is a gate, not an addend.** `substatScoring.ts` — `mainStatWeight()` returns 1 if
the relic's main stat is in the character's allowed set for that part, otherwise the metadata
weight (typically 0); `currentScore.ts` derives a `hasCorrectMain` boolean from whether that
weight is non-zero, and passes it into the rating. A wrong main stat therefore **collapses the
grade**, it does not merely dock it. *This matches Genshin's reality exactly — an ATK% sands
piece is not a slightly worse crit sands.*

There is also a `getFlatMainstatBoost()` path: when a slot's main stat is flat (Head HP, Hands
ATK), the *corresponding flat substat* is reweighted, since a flat-HP substat on a flat-HP head
is differently valuable. *I understood the mechanism but not its exact numeric effect.*

### 4.5 **How a +0 relic is handled — the answer**

**Fribbels scores potential, not just current value, and it does so with an explicit
expected-value model over the rolls the relic has not yet received.** This is documented, and I
read the code.

`futureScore.ts` computes remaining upgrade rolls:

```js
const remainingRolls =
  Math.ceil((config.maxEnhance - relic.enhance) / 3) - (4 - relic.substats.length)
```

with `maxEnhance` from `scoringConstants.ts` per rarity — `5★: 15, 4★: 12, 3★: 9, 2★: 6`.
Worked through for a 5★: a **+0 with 4 substats** has `ceil(15/3) = 5` remaining rolls; a **+0
with 3 substats** has `5 − 1 = 4`, because one enhancement is spent unlocking the fourth line.

It then produces **four figures per relic**, all as a percent of the ideal:

- **current** — score of the values on the relic right now.
- **average** — expected score if fully upgraded, using **mid-roll values spread evenly over
  the four substats**:
  ```js
  rollMidFactor = remainingRolls / 4
  avgRaw += vc + rollMidFactor * mr        // current value contribution + expected upgrade
  ```
  where `mr` is `SubStatValues[stat][grade].mid * contribution(stat)`. For a relic with fewer
  than four substats it also adds the expected value of the *unknown future lines*:
  ```js
  avgRaw += (4 - allSubstats.length) * avgNewContrib * (1 + rollMidFactor)
  ```
  i.e. an as-yet-unrolled substat is charged the **average contribution across the substats
  that could still appear**.
- **best / max potential** — every remaining roll lands on the single best-weighted substat, at
  its **high** roll value:
  ```js
  bestRaw += remainingRolls * highRollPotential(bestUpgradeStat)
  const best = Math.max(0, (bestRaw + deduction) * normFactor)
  ```
  For a sub-4-line relic, missing lines are filled by sorting candidate substats by
  `highRollPotential` and taking the top ones.
- **worst** — the mirror, using `lowRollPotential`.

`normFactor = 100 / idealScore` converts each to a percent.

**Is there a probability model?** **No — and I want to be precise about this.** The reader
returned, of `futureScore.ts`: *"No probability weighting or distribution sampling occurs — only
deterministic expected values based on mid-roll averages."* The average case is a
**deterministic expected value** (mid roll, evenly spread); the max case is a **deterministic
best case**, not a percentile of a distribution. There is no Monte Carlo and no "P(this relic
ends above X%)".

Probability *does* appear, but in a different module — **`estTbp.ts`** (§4.6), which uses real
drop and roll probabilities to answer a different question.

Roll-quality granularity, from `stat-score.md`: rolls are **0.8 / 0.9 / 1.0** quality, assumed
"distributed equally (33% each)". So `.mid` ≈ the 0.9 roll.

**The upshot for mistilteinn: a +0 relic is not scored as junk.** It appears in the grid with a
low *current* score and a possibly very high *average* and *max potential* — and the user sorts
by the potential column, not the score column, when deciding what to feed resin into.

### 4.6 "Should I upgrade this?" / "is this trash?"

Four distinct affordances, which is three more than most tools have:

**(a) The potential columns themselves.** Sort by *Selected Char Max Potential* descending and
the top of the list is your upgrade queue.

**(b) Reroll columns** — `futureScore.ts` again, for 5★ relics that already have 4 substats:
```js
rerollAvg  = midRollSum * (1 + totalRolls / 4)
blockerAvg = blockedMid + (midRollSum - blockedMid) * (1 + totalRolls / 3)
```
- **Reroll average** — what this relic would be worth if its substats were re-rolled from
  scratch. *Answers: is the relic's identity (set/slot/main) worth keeping even though its
  lines are bad?*
- **Blocked reroll average** — what it would be worth if the **worst substat were prevented
  from receiving any further rolls**, so upgrades land on the other three (hence the `/3`
  denominator instead of `/4`). *I could not determine what in-game mechanic this corresponds
  to, or whether it is purely hypothetical.*
- Each has **Δ vs current** and **Δ vs your currently equipped piece** variants. That second
  one is the genuinely useful comparison — *how much better than what I am wearing?*

**(c) Estimated TBP** (`estTbp/estTbp.ts`) — **the "is this trash?" answer expressed in days of
farming.** `scoreTbp()` computes the probability of obtaining a relic that beats the one in
hand, by multiplying:
- set probability `1/2` (two sets per domain),
- slot probability `1/4` for Head/Hands/Body/Feet, `1/2` for Sphere/Rope,
- main-stat probability by slot (e.g. "20% for ATK% on Body"),
- initial-substat-spread probability, drawn as a weighted sample **without replacement** with
  per-stat line weights ranging **4 (SPD) to 10 (percent stats)**,
- upgrade-path probability, "80% three-liner, 20% four-liner",

then converts:
```
days = (1 / totalProbability) * (40 / 2.1) / 240
```
— 40 energy per run, 2.1 relics per run, 240 energy per day.

**This is the mechanic mistilteinn is most conspicuously missing.** It reframes "keep or trash"
as *"a better one is 47 days away"*, which is a question a player can actually answer. And note
it **is** a genuine probability model — the thing §4.5 said the potential scorer lacks lives
here instead.

**(d) The insights panel**, three modes:
- **Buckets** — every character plotted as an avatar, bucketed by `Math.floor(potential / 10)`
  into 10 bands labelled "0%+", "10%+" … "90%+", toggleable between Average and Max potential.
  Tooltip shows the character, the potential, and — in max mode — `UpgradedStats` and
  `NewStats`, i.e. *which substats would have to hit for this to happen.* Scoped to All /
  Custom / Owned characters. **This answers "who in my roster wants this piece?" in one
  glance**, which is the question a shared inventory actually poses.
- **Top10** — presumably the ten best relics by the active metric. *Inferred from the filename
  `Top10Panel.tsx`; I did not read it.*
- **ESTBP** — the days-to-beat readout above.

### 4.7 How scores are displayed

**Letter grades**, verbatim from `scoreFormatting.ts` — 5% steps:

```ts
const RATING_TIERS = [
  { pct: 0,  rating: 'F' },   { pct: 5,  rating: 'F+' },
  { pct: 10, rating: 'D' },   { pct: 15, rating: 'D+' },
  { pct: 20, rating: 'C' },   { pct: 25, rating: 'C+' },
  { pct: 30, rating: 'B' },   { pct: 35, rating: 'B+' },
  { pct: 40, rating: 'A' },   { pct: 45, rating: 'A+' },
  { pct: 50, rating: 'S' },   { pct: 55, rating: 'S+' },
  { pct: 60, rating: 'SS' },  { pct: 65, rating: 'SS+' },
  { pct: 70, rating: 'SSS' }, { pct: 75, rating: 'SSS+' },
  { pct: 80, rating: 'WTF' }, { pct: 85, rating: 'WTF+' },
  { pct: 90, rating: 'AEON' },
]
```

`pctToRating()` takes percent **plus relic grade, part, `hasCorrectMain`, and Aeon eligibility**
— so the top tier is gated on more than the number, and a wrong main stat is reflected in the
letter. (`scoreFormatting.ts` contains **no colour logic** — I checked. Colour is applied in
the grid cells, see below.)

So the same relic carries, simultaneously: a **percent** (of the ideal relic), a **letter
grade**, a **colour gradient** in each stat cell, and a **position in a bucket plot**. Four
encodings of the same quantity, at four different reading distances.

**Full optional column list**, verbatim from `columnDefs.ts` + `relicsTab.yaml` headers:

*Selected Character (9):*

| Field | Column header |
|---|---|
| `weights.currentPct` | Selected Char Score |
| `weights.potentialSelected.averagePct` | Selected Char Avg Potential |
| `weights.potentialSelected.bestPct` | Selected Char Max Potential |
| `weights.rerollAvgSelected` | Selected Char Reroll Avg |
| `weights.rerollAvgSelectedDelta` | Selected Char Δ Reroll Avg |
| `weights.rerollAvgSelectedEquippedDelta` | Selected Char ∆ Reroll AVG VS Equipped |
| `weights.blockedRerollAvgSelected` | Selected Char Blocked Reroll Avg |
| `weights.blockedRerollAvgSelectedDelta` | Selected Char Δ Blocked Reroll Avg |
| `weights.blockedRerollAvgSelectedEquippedDelta` | Selected Char ∆ Blocked Reroll AVG VS Equipped |

*Custom Characters (4):* Avg Potential, Max Potential, Avg Reroll, Avg Blocked Reroll —
scoped to a user-chosen subset of the roster.

*All Characters (4):* the same four, across every character in the game.

**The "All Characters Max Potential" column is the trash detector.** If a relic's best possible
outcome is poor for *every character that exists*, it is unambiguously garbage — and no
per-character weight argument can rescue it.

### 4.8 The other system: Benchmark / DPS Score

From `benchmarks.md`. It "compares a build's performance in a single ability rotation" against
three simulated reference builds:

- **0% Baseline** — no substats at all, optimal main stats only.
- **100% Benchmark** — "a strong, realistic build achievable with reasonable farming effort".
- **200% Perfection** — perfectly optimised substats.

Scoring, per DeepWiki reading `characterScorer.ts` (`scoreCharacterSimulation()`):
```
above benchmark: 1 + (original - benchmark) / (maximum - benchmark)
below benchmark:     (original - baseline)  / (benchmark - baseline)
```

Four modes by role: DPS / Heal / Shield / Support benchmark. It accounts for eidolons,
superimpositions, team composition, rotation, stat breakpoints and set effects, and explicitly
**does not** model action advance, energy regeneration, or stacking frequency. The docs warn
scores are only comparable within identical team and equipment configurations.

**This is the design mistilteinn should recognise**: a damage number is meaningless in
isolation, so it is anchored to *two* simulated builds and reported as a position between them.
And the tool **states its own exclusions in the user-facing guide** — the same discipline as
`unmodelled_passives`.

---

## 5. The optimizer / search page

**What the user configures** (from `optimizer.md`, corroborated by DeepWiki):

- Character, light cone, eidolon, superimposition.
- **Ability and light-cone passive selectors** — "These selectors will affect the final combat
  stats and damage calculations." Conditionals are user-set, not assumed.
- A **recommended preset speed target**: "For most characters, the 133.333 speed breakpoint is
  recommended, and this will set a minimum speed for your optimization results." *A named,
  explained, one-click preset for the constraint that actually matters.*
- **Character Priority** — which characters this one may take relics from.
- **Main stat filters** — "limits optimizer to using preferred body, feet, planar sphere, and
  link rope main stats. Multiple options can be chosen for each slot."
- **Set filters** — "allows for a combination of 2-piece sets, 4-piece sets, or can be left
  empty. When multiple options are chosen, the search results will only show builds with least
  one of the selected filters active." *(sic)*
- **Stat min/max constraints** — "Left side is minimum and right side is maximum, both
  inclusive", over ATK / HP / DEF / SPD / Crit Rate / Crit Damage / Effect Hit Rate / Effect
  RES / Break Effect. Documented example: "≥ 134 speed AND ≥ 35% Crit Rate."
- Exclusions: minimum enhance, minimum rarity, include/exclude equipped relics, keep current
  equipment.
- **Advanced options**: enemy properties and combat modifiers.

**Optimization targets**: per-ability damage (Basic, Skill, Ultimate, Follow-up, DoT, Break,
Combo), any raw stat, or utility metrics (Healing Value, Shield Value, **EHP**).

**Results presentation:**
- One row per build. "The pinned top row shows the character's currently equipped build" — so
  every result is read as a delta against what you are wearing, without a second click.
- Sort by any column, including any stat or rating.
- Toggle **Basic Stats vs Combat Stats** (post-buff, post-conditional).
- Click a row to see the relics it used; **Equip** applies it.
- Rows can be **pinned** for comparison.
- A live counter of three numbers: **"Perms"** (permutations to search), **"Searched"**
  (completed), **"Results"** (rows satisfying the filters). Plus estimated completion time.

**Engine**: WebGPU with stable and experimental modes and a CPU fallback, over "millions of
possible combinations".

**The permutations counter is the interaction lesson.** The user sees the size of the space
*before* and *during* the search, so an over-broad filter is visibly the user's own doing.

---

## 6. Anything else notable

- **Warp Planner** — jade budgeting to guaranteed pity, plus a character planner projecting
  ascension and trace materials. *Wholly outside the optimizer's remit, and shipped anyway.*
- **Calculators** — at least `#aha` and `#ehr`. *Contents undetermined.*
- **Leaderboard** — `#leaderboard`. *Contents undetermined; presumably ranked showcase builds.*
- **Showcase** — a shareable build card, with a screenshot export button, and asterisks marking
  any trace the user disabled.
- **Enka.Network integration** — credited in the README for API support; this is what makes
  showcase-by-UID import possible.
- **Save / Load / Clear** of the entire optimizer state as a file.
- **i18n** — 18 locale files per language; internationalisation is credited in the README as a
  contributor feature.
- **In-app changelog tab** and a "Get Started" sample save.
- **"No leaks" toggle** — unreleased content is filtered out of set lists (`UnreleasedSets`
  appears in the filter code) unless opted in. *A content-policy stance encoded as a filter.*
- **Recent relics** (`RecentRelicCard.tsx`, `RecentRelics.tsx`) — a strip of just-imported
  pieces, which is what live import needs to be useful.

---

## 7. Visual / UX qualities worth copying

**Flagging clearly: I did not view the running application or any screenshot.** Everything here
is inferred from component names, CSS module names, cell renderers, and locale strings.
Treat it as a hypothesis list, not a description.

1. **A table, not a card grid, for the inventory.** AG Grid, one row per relic, ~20 baseline
   columns. Fribbels bet on density and won. For 2000 items there is no other correct answer.
2. **Colour gradients inside stat cells.** Every substat column gets a value-proportional
   gradient, so a row is legible as a heat strip before any digit is read. *Confirmed in
   `columnDefs.ts`, which names gradient styling on each stat column.*
3. **Zeros are hidden, not printed.** `hideZeroes*` formatters everywhere. A relic with three
   substats shows three numbers in a twelve-column stat block, and the shape of the row *is* the
   substat spread.
4. **Filters as pills in a top bar, not a side panel.** `FilterPillBar.tsx`. Filters stay
   visible and stay horizontal, so the grid keeps full width. Compare: a left rail costs 250px
   of table forever.
5. **Which columns exist is itself a filter pill.** The 17 scoring columns are opt-in. The
   default view is not overwhelming; the power is one pill away. *This is the answer to "we
   have too many metrics to show".*
6. **Four encodings of one number at four reading distances** — cell gradient (glance), letter
   grade (scan), percent (read), bucket plot (survey). Nothing is redundant because each is
   legible at a different zoom.
7. **The equipped build is pinned as row zero in the results.** Every candidate reads as a
   delta for free.
8. **Progress is three honest numbers** — Perms / Searched / Results — not a spinner. The user
   can see that their filter matched nothing *while it is still running*.
9. **Presets are named and explained, not just offered.** "133.333 speed breakpoint" tells the
   user why it is the default.
10. **Grid density is a user setting** ("Default" / "Compact"), as is where the info panel goes
    (above/below), as is sidebar collapse behaviour at three breakpoints. Layout is negotiated
    with the user rather than decided for them.
11. **Onboarding is a sample save file.** "Get Started" fills the app with data so the first
    session is exploration, not data entry. mistilteinn's equivalent — a demo GOOD export —
    would be a few hours of work.
12. **The Relic Locator closes the loop back to the game.** A verdict the user cannot act on is
    not a verdict. *Genshin's inventory has an equivalent physical layout and mistilteinn could
    do the same thing.*
13. **Destructive actions lock during live import.** "Disabled in live import mode."
14. **The tool states its own limits in its user guide** — the benchmark docs list what is not
    modelled, and disabled traces put asterisks on the shared card so a reader knows the number
    is qualified. Directly parallel to `unmodelled_passives`.

---

## 8. What I could not determine

Recording these rather than guessing:

- **Provenance of the default per-character weights** — shipped in repo game-metadata, but
  whether authored by the maintainer, imported from a community source, or crowd-edited, I
  found no statement.
- **What in-game mechanic "blocked reroll" models**, or whether it is purely hypothetical.
- **Contents of the Calculators tab** (`#aha`, `#ehr`) and the **Leaderboard**.
- **`Top10Panel.tsx`** — inferred from its filename only.
- **The exact numeric effect of `getFlatMainstatBoost()`** and of `minWeightedRolls`.
- **Any colour palette or visual specifics** — see the §7 caveat.
- **Whether the relic grid is virtualised.** AG Grid supports row virtualisation and would
  almost certainly be configured for it at this scale, but I did not find the configuration and
  the DeepWiki page explicitly said virtualisation was not described. *Do not cite this as
  established.*
- **The `deduction` term** in `futureScore.ts`'s best/average formulas — it appears in the
  quoted code and I do not know what it deducts.
