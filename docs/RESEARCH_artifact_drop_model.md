# RESEARCH — How Genshin artifacts are generated and obtained (input to a resin-cost model)

Status: **complete**, 2026-10-24. This is research only, with no code and no design decisions.
Everything below was read from a source fetched on 2026-10-24. Where a figure is my own
arithmetic on sourced inputs it says **derived**. Where nothing primary backs a figure it says
**UNVERIFIED**.

## 0. Sources and how they were read

The Genshin Fandom wiki answers its HTML pages with HTTP 402 to automated clients. Its pages
were therefore read as raw wikitext through the MediaWiki API:
`https://genshin-impact.fandom.com/api.php?action=parse&page=<Page>&prop=wikitext&format=json`.
Below, *wiki:`X`* means the page `https://genshin-impact.fandom.com/wiki/X`, read this way.

| tag | source |
|---|---|
| W-DIST | wiki:`Artifact/Distribution` (marked `{{Community}}`, cites NGA thread https://nga.178.com/read.php?tid=33220261) |
| W-DROP | wiki:`Loot_System/Artifact_Drop_Distribution` (marked `{{Community}}`, cites the Genshin Data Gathering sheet) |
| GDGT | Genshin Data Gathering Team, *Drop Rates* sheet, https://docs.google.com/spreadsheets/d/10DF-Wqn-79SxTeSZPAY__RW1uGtpphAx4rG97akYskY (gid 749900704, read as a CSV export). This is the measured data behind W-DROP and it carries run counts. |
| W-ART | wiki:`Artifact`: the Definition, Extraction and Reshaping sections |
| W-ARTCH | wiki:`Artifact/Change_History` |
| W-EXP | wiki:`Artifact_EXP` |
| W-RESIN | wiki:`Original_Resin`, wiki:`Condensed_Resin`, wiki:`Condensed_Resin/Change_History`, wiki:`Domain/Change_History` |
| W-VER | wiki:`Version/5.0`, `Version/5.5`, `Version/5.7`, `Version/Luna_I` … `Luna_VII`, `Version/7.0`, `Version/7.1`. These are the wiki's transcriptions of the official notes. Each page links the HoYoverse original; for example Luna I links https://genshin.hoyoverse.com/en/news/detail/159349 and 7.0 links https://genshin.hoyoverse.com/en/news/detail/165655. |
| W-ITEM | wiki:`Sanctifying_Elixir`, `Dust_of_Enlightenment`, `Artifact_Transmuter`, `Artifact_Transmuter/Change_History`, `Artifact_Strongbox`, `Mystic_Offering`, `Domain_Reliquary`, `Spiral_Abyss`, `Spiral_Abyss/Chamber's_Bounty`, `Stygian_Onslaught`, `Imaginarium_Theater`, `Battle_Pass`, `Normal_Boss`, `Weekly_Boss`, `World_Level`, `Tutorial/Artifact_Definition_and_Extraction`, `Tutorial/Artifact_Reshaping` |
| GO | Genshin Optimizer, https://github.com/frzyc/genshin-optimizer at commit `2ce06b88a442531b49d84cbed15204a4a03d078a` (2026-10-22): `libs/gi/upopt/src/*`, `libs/gi/page-team/src/CharacterDisplay/Tabs/TabUpgradeOpt/upOpt.ts`, `libs/gi/consts/src/artifact.ts`, `libs/gi/util/src/artifact/artifact.ts`, `libs/gi/stats/src/allStat_gen.json` |
| KQM | tooflesswulf, *Artifact Sub Math* v10.1 (2022-02-06), KQM Theorycrafting Library, https://library.keqingmains.com/assets/files/ArtiSubMath-v10_1-0c25f059a10d40502b70fc546bdd2759.pdf |

**What version the game is on.** Today the game is at **7.1**, not 6.x. Version 6.0 shipped
as **"Luna I"** on 2025-09-10 (W-VER `Version/Luna_I`, `|number = 6.0`). Luna I–VII were
followed by **7.0** on 2026-08-12 and **7.1** on 2026-09-23. **7.2** is scheduled for
2026-11-04 (W-VER `Version/7.2`). Several mechanics in the brief changed during Luna; they are
called out where they apply.

**The probabilities are not published by HoYoverse.** No official source gives a probability
table. Every probability below comes either from the community-compiled wiki tables (W-DIST,
W-DROP), whose upstream is an NGA compilation, or from the GDGT measurements. GO's constants
are copied from W-DIST, and its source comment says so (`libs/gi/upopt/src/consts.ts`:
`// https://genshin-impact.fandom.com/wiki/Artifact/Distribution`). The one numeric table GO
takes from **game data** is the substat values: `ReliquaryAffixExcelConfigData`, in §4.4.

---

## 1. Domain drops (Domains of Blessing)

### 1.1 Resin per run — **this changed in 6.0 / Luna I**
- One claim costs **20 Original Resin** or **1 Condensed Resin** (wiki:`Domain_of_Blessing`).
  The resin table in W-RESIN now reads *"Domains: 20 or 40 or 1× Condensed Resin"*.
- **Condensed Resin now costs 60 Original Resin and claims 3× rewards.** It used to cost 40
  and claim 2×. Source: wiki:`Condensed_Resin/Change_History` → *Version "Luna I": "Increased
  the crafting cost from 40 Original Resin to 60 … Increased the amount of rewards received
  upon use from 2 sets to 3 sets."* The official note as transcribed in W-VER Luna I: *"The
  consumable Condensed Resin will now require Original Resin ×60 to craft. It can be used to
  claim rewards up to three times."* You can hold at most 5 (wiki:`Condensed_Resin`).
- **Also new in Luna I:** *"You can now use 40 Original Resin to claim 2× rewards"*, and
  Primogems can buy resin to claim up to 3× (W-VER Luna I; wiki:`Domain/Change_History`).
  Fragile and Transient Resin give 3× (60 resin's worth), added in 5.7.
- **For the model: every option costs the same, 20 resin per reward set.** A "condensed run
  costs 40" model is out of date.
- Each set of rewards within a multi-claim is rolled independently: *"All sets of rewards are
  random"* (wiki:`Condensed_Resin`).

### 1.2 Quality counts per reward set

Domain quality depends on **Adventure Rank, not World Level**. W-DROP's domain table has an AR
column and stops at **AR 45+**, the top bracket. W-DROP gives these as the predicted **mean**:

| AR | 2★ | 3★ | 4★ | 5★ | total |
|---|---|---|---|---|---|
| 40 | 0 | 4.97 | 1.775 | 0.355 | 7.1 |
| **45+** | 0 | **3.55** | **2.485** | **1.065** | 7.1 |

**Measured (GDGT, Domain of Blessing summary, AR 45 row): 14,088 runs → 3★ 3.55, 4★ 2.48,
5★ 1.07** per run. The AR 40 row has n = 216. The prediction and the measurement agree.

- wiki:`World_Level` describes AR 45 (WL 6) as: *"Unlocks Lv. 90 Artifact Domains, which
  guarantee at least 5★ Artifact × 1."* So the 5★ count is **1 guaranteed plus ~0.065
  expected extra**. The distribution's shape beyond its mean is **UNVERIFIED**. The model
  "1 + Bernoulli(≈0.065)" is consistent with the guarantee and the mean, but no source states
  it.
- W-ART gives a rounder summary that conflicts slightly: *"At the highest Domain level,
  Artifact Domains averages at 1 5-Star featured artifact and 1.5 4-Star featured
  artifacts."* W-DROP splits 4★ drops 1/3 across three sets (§1.3), which gives
  2.485 × 2/3 ≈ **1.66** featured 4★ (derived). So the "1.5" is rounded or stale. Use W-DROP
  and GDGT.

### 1.3 Set split
- **5★: 1/2 for each of the domain's two sets.** 3★: 1/2 each. 4★: 1/3 each across three
  sets (W-DROP *Artifact Set Distribution → Domains*). W-ART agrees: *"Featured artifacts each
  have 50% to be either of the two types."*
- **Derived:** on-set 5★ per run = 1.065 / 2 ≈ **0.53**, so about **37.6 resin per on-set
  5★**.

### 1.4 World Level 9 (5.0) did **not** touch artifact domains, as far as any source shows
- W-VER 5.0 (official note) says only: *"Adds World Level 9 … After the World Level
  increases, the levels of monsters and bosses will increase, the challenge difficulty and the
  rewards dropped will also be increased."*
- wiki:`World_Level` lists exactly one reward change for WL 9: *"Normal Bosses guarantees at
  least Character Level-Up Material × 3."* That is a boss-material change. It lists nothing
  for artifacts.
- Domain artifact quality is keyed to AR (W-DROP), and AR 45 is already the top bracket, so
  WL 9 (AR ≥ 58) has no domain bracket of its own. GDGT has **no AR ≥ 58 split** for domains.
  **Conclusion: no change is documented, and none has been measured separately.** "Unchanged
  at WL 9" is the reading, but it rests on the absence of a documented change. Treat it as
  UNVERIFIED-by-measurement.
- **Normal (40-resin) bosses: WL 9 left their artifacts unchanged too, on a tiny sample.**
  GDGT measured WL 8: 11,197 runs → 3★ 2.10, 4★ 1.47, 5★ 1.00. WL 9: **38 runs** →
  3★ 2.03, 4★ 1.42, 5★ 1.00. W-DROP: *"In World Level 8, the mean of 5-star Artifact is fixed
  to 1."*

### 1.5 "Exclusive" / one-set domains
**None found.** Every Domain of Blessing in wiki:`Domains_of_Blessing/Change_History` through
7.0 (Inverted Glacier) is a two-set domain, and the 5★ split is 1/2 (W-DROP). The newer
mechanics that let you pick a set are:
- **Stygian Onslaught "Disturbance Outbreak"**: you choose the domain, not the set; §5.6.
- **Strongbox**: §5.1.
- **Definition**: §5.2.

None of these is a guaranteed single-set domain.

---

## 2. Slot distribution
**Uniform, 20% per slot** (W-DROP *Artifact Category Distribution*). GO uses
`const pSlot = 1 / 5` in `freshArtifact` (`libs/gi/upopt/src/upOpt.ts`).

---

## 3. Main stat probabilities (all qualities; W-DIST; identical in GO `consts.ts`)

| Sands | p | Goblet | p | Circlet | p |
|---|---|---|---|---|---|
| HP% | 26.68% (80/300) | HP% | 19.25% (77/400) | HP% | 22% |
| ATK% | 26.66% (80/300) | ATK% | 19.25% (77/400) | ATK% | 22% |
| DEF% | 26.66% (80/300) | DEF% | 19.00% (76/400) | DEF% | 22% |
| ER% | 10% | each of 8 elemental/physical DMG% | 5% (20/400) | CRIT Rate% | 10% |
| EM | 10% | EM | 2.5% (10/400) | CRIT DMG% | 10% |
| | | | | Healing% | 10% |
| | | | | EM | 4% |

- Flower is always flat HP and plume is always flat ATK.
- The goblet table took its current shape in 3.0, when Dendro was added
  (W-ARTCH, *Version 3.0*: HP%/ATK% went from 21.25 to 19.25 and DEF% from 20 to 19).
- W-DIST's sands figures (26.68/26.66/26.66) sum to 100. GO's 80/300 split is equivalent to
  within rounding.

**Derived examples** (domain, AR 45+, on-set):
- CRIT circlet: 1.065 × ½ × ⅕ × 0.10 ≈ 0.0107 per run → **~1,880 resin per on-set CR circlet,
  and the same for CD**.
- A specific elemental goblet: 1.065 × ½ × ⅕ × 0.05 ≈ 0.0053 per run → **~3,760 resin**.

These buy a piece with that main stat at any substat quality.

---

## 4. Substat generation

### 4.1 Initial line count, by source (W-DROP *Initial Minor Affix Count Distribution*)

| source | 5★ with 3 lines | 5★ with 4 lines |
|---|---|---|
| **Domains** | **80%** | **20%** |
| Normal bosses | 66% | 34% |
| Weekly bosses | 66% | 34% |
| **Artifact Strongbox** | 66% | 34% |
| Domain Reliquary (Spiral Abyss) | 66% | 34% |
| Sanctifying Elixir definition | **UNVERIFIED.** GO hardcodes `prob_4line: 0.34` (`TabUpgradeOpt/upOpt.ts`) and cites nothing. No wiki page states a figure. | |

The pattern carries down to lower rarities: a 4★ from a domain is 80% 2-line / 20% 3-line,
and from a boss 66/34. The "20% vs 34%" you recalled is right: 20% for domains, 34% for
bosses, Strongbox and Abyss. W-DROP is marked `{{Community}}`, and **no sample sizes for the
line-count split appear in either W-DROP or the GDGT summary tab.**

**A Luna I change matters for modelling at +0:** *"you will be able to preview the fourth
minor affix on 5-star Artifacts with three initial minor affixes"* (W-VER Luna I; W-ARTCH). A
3-line +0 piece now shows which fourth stat it will gain at +4. GO models this as
`unactivatedSubstats`: the fourth key is known and costs one upgrade
(`levelUpArtifact`, `info.rollsLeft -= 1`).

### 4.2 Which substats appear (W-DIST)
- Each line is drawn by weight, **without replacement, excluding the main stat**. *"Minor
  affixes identical to the main affix and already-existing minor affixes are omitted from the
  pool. Flat and percent affixes are not identical."*
- Weights: **HP 6, ATK 6, DEF 6, HP% 4, ATK% 4, DEF% 4, ER 4, EM 4, CRIT Rate 3, CRIT DMG 3.**
  P(stat) = weight / Σ(weights still in the pool).
- The same rule applies to the line added at an upgrade. W-DIST's worked example: a plume that
  already has ATK%, ER and CR draws CD at 3/27 = 11.1%.
- GO implements this exactly in `libs/gi/upopt/src/substatProbs.ts` (`substatProb`, a
  recursive sequential draw without replacement).

### 4.3 Upgrades (W-DIST; GO `consts/src/artifact.ts`)
- **A 5★ upgrades at +4/+8/+12/+16/+20.** GO: `artMaxLevel[5] = 20`,
  `artSubstatRollData[5] = { low: 3, high: 4, numUpgrades: 5 }`, and
  `getRollsRemaining = ceil((20 − level)/4)`.
- **A 4-line start gets 5 upgrades into existing lines**, for 9 value-draws in total. **A 3-line
  start spends the first upgrade adding the fourth line**, which is drawn by weight as above,
  then gets 4 more, for 8 draws in total.
- **When all four lines exist, each upgrade picks a line uniformly, 25% each** (W-DIST *Minor
  Affix Slot Upgrade*).
- W-DIST also gives the distribution of how many times one chosen line is upgraded on a
  4-line piece: 0: 23.73%, 1: 39.55%, 2: 26.37%, 3: 8.79%, 4: 1.46%, 5: 0.10%. That is
  Binomial(5, ¼) (derived check: (¾)^5 = 23.73%).

### 4.4 Roll tiers
- **For 3★, 4★ and 5★: 70/80/90/100% of max, uniform at 25% each.** This holds for the
  initial value and for every upgrade (W-DIST *Minor Affix Value*). 2★ uses 70/85/100 and
  1★ uses 80/100.
- GO uses the same model: `getUniformSubstatValues` → `[0.7, 0.8, 0.9, 1]`. KQM writes it as
  `U = {7α, 8α, 9α, 10α}` and treats an n-times-upgraded line as a sum of n independent U.
- 5★ tier values, **from game data** (`ReliquaryAffixExcelConfigData`, via GO
  `libs/gi/stats/src/allStat_gen.json` → `art.sub["5"]`):

| stat | 70% | 80% | 90% | 100% |
|---|---|---|---|---|
| HP | 209.13 | 239 | 268.88 | 298.75 |
| ATK | 13.62 | 15.56 | 17.51 | 19.45 |
| DEF | 16.2 | 18.52 | 20.83 | 23.15 |
| HP% / ATK% | 4.08% | 4.66% | 5.25% | 5.83% |
| DEF% | 5.10% | 5.83% | 6.56% | 7.29% |
| EM | 16.32 | 18.65 | 20.98 | 23.31 |
| ER% | 4.53% | 5.18% | 5.83% | 6.48% |
| CRIT Rate% | 2.72% | 3.11% | 3.50% | 3.89% |
| CRIT DMG% | 5.44% | 6.22% | 6.99% | 7.77% |

---

## 5. Other acquisition routes

### 5.1 Artifact Strongbox (Mystic Offering)
- **3 × 5★ artifacts → 1 Strongbox**, which holds a random artifact from the **selected set**.
  It unlocks at AR 45, and up to 39 artifacts can go in at once (wiki:`Artifact_Strongbox`,
  `Mystic_Offering`; added in 2.0).
- The **line count is 66% 3-line / 34% 4-line**, better than a domain's 80/20 (W-DROP).
- **Which sets are offered** has grown patch by patch. For example, 7.0 added *Night of the
  Sky's Unveiling* and *Silken Moon's Serenade* (W-VER 7.0). The newest domain sets typically
  join roughly a year after release.
- **No source states that slot and main stat follow the ordinary tables.** GO's
  `freshArtifact` comment says it covers *"a Domain, Boss, or Strongbox"* with the same slot
  and main-stat distribution. **UNVERIFIED beyond GO's assumption.**
- **No acquisition limit** is stated. The binding limit is how many 5★ pieces you produce.
- **Derived resin equivalent:** the inputs are by-products, meaning off-set or junk 5★
  pieces. If every off-set domain 5★ is fed in, on-set 5★ per run rises from 0.53 to
  0.53 + 0.53/3 ≈ **0.71**, or about **28 resin per on-set 5★** instead of 37.6. That is
  before counting junk on-set pieces, which can also be fed. Weekly bosses
  (1.23 5★ per 30-resin run, §5.5) and normal bosses (1.00 per 40-resin run) supply fodder.

### 5.2 Artifact Transmuter: Definition (Sanctifying Elixir)
- **Released 5.0** (wiki:`Artifact_Transmuter/Change_History`). You choose the **set, slot,
  main stat and 2 minor affixes** (W-ART *Definition*).
- **Elixir cost per piece:** flower 1, plume 1, **sands 2, goblet 4, circlet 3** (W-ART).
- **The guarantee (since 5.5):** *"Artifacts defined through the consumption of Sanctifying
  Elixirs … are guaranteed to get at least 2 rolls for the defined Minor Affixes when fully
  leveled up."* *"Multiple defined Minor Affixes will share this pool of rolls."*
  (W-VER 5.5; wiki:`Tutorial/Artifact_Definition_and_Extraction`). Before 5.5 the only
  guarantee was that the two lines were present.
- **The limit is per artifact set per version:** 1 at 5.0, and **2 since Luna III** (6.2):
  *"Increases the Definition Count per Artifact Set per version from 1 to 2"* (W-VER Luna III).
  W-ART puts it as *"Only 2 pieces can be defined per Artifact Set per cycle."*
- **3-line or 4-line start: UNVERIFIED.** GO assumes 34% 4-line.

### 5.3 Where Elixirs come from (wiki:`Sanctifying_Elixir`)

**Recurring:**

| source | Elixirs |
|---|---|
| **Extraction** (§5.4) | 1 per version (cap) |
| **Gnostic Hymn battle pass, level 26** | 1 per BP period. wiki:`Battle_Pass` lists `Sanctifying Elixir*1` among Hymn rewards. |
| **Imaginarium Theater**, 9 and 12 Stellas | 1 each, so 2 per season. Seasons reset on the 1st of each month (wiki:`Imaginarium_Theater`). Stella rewards began in the June 2025 season. |
| Events | occasional, e.g. *To Temper Thyself and Journey Far* |

**One-time:**

| source | Elixirs |
|---|---|
| Natlan Tribal Secret Spaces | 6 |
| Tona's Flame's Restitution, levels 10/20/30/40/50 | per-level count not stated |
| Nod-Krai Meeting Points | 6 |
| Frost Moon, Ancient Moon's Remnant | 2 |
| Snezhnaya Meeting Points | 3 |

**Derived recurring supply:** about 1 + 1 + 2 × (42/30) ≈ **4.8 Elixirs per 42-day version**
for a player who buys the battle pass and takes all 12 Stellas, or ~3.8 without the pass. That
is roughly **one circlet plus one sands, or one goblet, per version**. The 42-day length is my
assumption, consistent with 7.0 → 7.1 → 7.2 being 42 days apart.

### 5.4 Extraction (turning artifacts into Elixir) (W-ART *Extraction*)
- **Input:** 5★ artifacts at **+4 or higher**, or, since Luna I, Unction and Essence.
  **100 Extraction Progress = 1 Elixir**, capped at **1 Elixir per cycle**; the Elixir page
  says *"once per Version"*.
- **Progress per artifact:**

| level | progress |
|---|---|
| +4…7 | = level |
| +8…11 | level + 2 |
| +12…15 | level + 6 |
| +16…19 | level + 14 |
| +20 | 50 |

  Unction gives 0.5 and Essence gives 2. Both work out to 5,000 EXP per point.
- **Cheapest by EXP sunk:** +4 pieces at **4,075 EXP per point**, so ~407,500 EXP per Elixir,
  or 25 junk 5★ pieces at +4 (W-ART table). The progress values were raised in Luna I
  (W-VER Luna I).

### 5.5 Weekly and normal bosses (W-DROP; GDGT)

| boss | 5★ per claim | 4★ | 3★ | measured runs | resin |
|---|---|---|---|---|---|
| Weekly (top WL) | 1.23 | 2.87 | 4.10 | GDGT AR 50: 11,953 runs | 30 for the first 3 per week, then 60 (W-RESIN) |
| Normal (WL 8+) | 1.00 | 1.47 | 2.10 | GDGT WL 8: 11,197; WL 9: 38 | 40, and Condensed Resin is not allowed |

- **Their 5★ come only from Gladiator's Finale and Wanderer's Troupe**, split ½ each
  (wiki:`Normal_Boss`, `Weekly_Boss`; W-DROP). For a modern build they are Strongbox fodder and
  EXP, not drops you would equip.
- Their line counts are 66/34 (§4.1).

### 5.6 Stygian Onslaught "Disturbance Outbreak" (added 5.7)
- Runs for the **first 10 days** of each version's Stygian Onslaught. At AR 45+, clearing a
  stage on Hard or above lets you spend resin on a Ley Line Blossom that gives **the
  highest-level drops of a Domain of Blessing you choose**, at 1× or 3× (wiki:`Stygian_Onslaught`).
- **Bonus drop:** every **120 Dire Prestige** gives an extra random 5★ from that domain's two
  sets. The page says *"There is no limit to Dire Prestige."*
- **The sources disagree on the Prestige rate.** The page body says *"20 is given for
  Original Resin and 60 for Condensed, Transient or Fragile Resin"*. The in-game
  tutorial and description text say *"Original Resin, Condensed Resin, and Fragile Resin (or
  Transient Resin) … 20/40/60"*, which reads like Condensed = 40, a pre-Luna-I value.
  **Either way, Prestige is 1 per resin**: 20 for 20, and 60 for a 3× claim (60 resin's
  worth). Treat Condensed = 60 since Luna I as **UNVERIFIED**.
- **Derived:** +1 5★ per 120 resin = +0.167 per 20 resin. During the outbreak, 5★ per
  20 resin ≈ 1.065 + 0.167 ≈ **1.23**, which is **~16% more** than an ordinary domain. This
  applies only to resin spent inside the 10-day window.
- 1,200 Dire Prestige also gives a one-time Dire Commendation, which yields 1 Dust (§5.7).

### 5.7 Reshaping (Dust of Enlightenment), added 5.7 (W-ART *Reshaping*; wiki:`Dust_of_Enlightenment`)
- **Target:** a **fully levelled (+20) 5★**. You pick **2 minor affixes**. *"All Minor
  Affixes enhancements will be reallocated, and at least 2 enhancements will be allocated to
  the selected Minor Affixes."* You then keep **either the original or the new result**.
- The Dust is consumed either way, so a reshape **can never make the piece worse**: it is a
  free option. The model should take the max.
- **Dust cost per reshape:** flower 1, plume 1, sands 2, goblet 2, circlet 2.
- **Pity system (Hallowed Exegesis):** each Dust spent gives 1 point.
  - At **6 points**, the next reshape is an **Advanced Reshape: at least 3** enhancements go to
    the chosen pair.
  - *"Upon triggering the Advanced Reshape effect for the third time in a row, the Decreed
    Reshape effect will trigger **instead**"*, which guarantees **at least 4**.
- On a **Definition-made** piece, the defined affixes are pre-selected and cannot be changed.
- **What the wiki leaves unstated:** whether initial values are re-rolled, and whether a
  3-line-origin piece keeps its 8-draw budget. GO's model (`dustReshape`) keeps each line's
  `initialValue` and redistributes `totalRolls − lines` upgrades. **Treat GO's reading as
  plausible, not verified.**
- **The guarantee's mechanism is UNVERIFIED.** Two readings differ:
  - **Floor:** allocate uniformly, and if the pair is short, push the shortfall onto the pair.
  - **Conditional resample:** redraw until the guarantee holds.

  GO implements the floor. In `markov-tree/mathUtil.ts:rollCountProb`, outcomes below `min`
  get probability 0. The outcome with exactly `min` gets the binomial mass of
  `P(Binomial(N, n/4) ≤ min)`, split uniformly within each group. The wiki text does not
  settle which reading is right.
- **Where Dust comes from, per version (wiki:`Dust_of_Enlightenment`):**

| source | Dust per version |
|---|---|
| Stygian Onslaught, Menacing and Fearless clears | 2 |
| Dire Commendation (1,200 Dire Prestige) | 1 |
| **Gnostic Hymn, level 38** | **2**, per the Dust page |
| Gnostic Chorus | 1 |
| *To Temper Thyself…* | 0.5 |

  One-time: Hidden Troves, 8 + 1 + 1 + 3 = 13.

- **The sources disagree on the battle pass.** wiki:`Battle_Pass` lists **`Dust of
  Enlightenment*1`** in the Gnostic Hymn bundle. The 5.7 note says *"Adds one Dust of
  Enlightenment to both Gnostic Hymn and Gnostic Chorus"* (W-VER 5.7). The Dust page says
  Hymn gives 2. **Treat Hymn as 1–2, unresolved.**
- **Derived recurring total:** ~3.5–6.5 Dust per version, depending on battle-pass purchases.
  That is roughly 2–3 circlet/sands/goblet reshapes per version.

### 5.8 Spiral Abyss (Domain Reliquaries)
- Floors 9–12 reset on the **16th of each month**. Before 2024-06-16 they reset twice a month
  (wiki:`Spiral_Abyss`).
- Each floor's chamber 3 gives a **Domain Reliquary: Tier I (5★)**, and chambers 1–2 give a
  **Tier II (4★)** (wiki:`Spiral_Abyss/Chamber's_Bounty`). That is **4 × 5★ per month**,
  from the two sets the reliquary currently offers (½ each), with 66/34 line counts (W-DROP).
- The sets rotate. For example, 7.0 switched to Scarlet Proof and Heart of the Furnace
  (W-VER 7.0). So these are on-set only when you happen to want the current pair.

### 5.9 Other minor sources (W-ART *How to Obtain*)
Investigation spots, chests, Hidden Troves, Tumbleweeds, elite enemies and NPC shops give
1–4★ artifacts. Elite enemies drop 3–4★ only, at 0.1 artifacts per kill (W-DROP). These matter
for **EXP** (§6), not for 5★ supply.

### 5.10 Echoing Conch / "Mystic Offerings" beyond the Strongbox
- **Echoing Conch:** nothing found. It is an exploration collectible, not an artifact source.
  **UNVERIFIED that it is irrelevant**; it was not researched further.
- "Mystic Offering" *is* the Strongbox crafting method (§5.1).

---

## 6. Artifact EXP and fodder

**EXP to reach +20 (W-EXP).** A 5★ needs **270,475 EXP**, paid in equal **Mora** (1 per EXP).
Cumulative to each tier:

| +4 | +8 | +12 | +16 | +20 |
|---|---|---|---|---|
| 16,300 | 44,725 | 87,150 | 153,300 | 270,475 |

Most of the cost is late: **43% of it is +16 → +20** (derived).

**EXP from fodder (W-EXP; W-ART *Salvage*).**
- Base EXP when fed: 1★ 420, 2★ 840, 3★ 1,260, 4★ 2,520, 5★ 3,780.
- A levelled artifact also returns 80% of the EXP sunk into it.
- **Each feed has an EXP bonus multiplier:** ×1 at 90%, ×2 at 9%, ×5 at 1%. The mean is
  **×1.13** if no overflow is wasted.
- Salvage yields 1 Unction per 2,500 EXP and 1 Essence per 10,000. Unenhanced pieces could be
  salvaged from 5.0, and levelled ones from 5.5 (W-ARTCH).

**EXP per domain run.**
- **Measured: 14,767 EXP per 20-resin run, or 738 per resin** (W-EXP citing GDGT).
- **Derived check from §1.2 means:** 3.55 × 1,260 + 2.485 × 2,520 + 1.065 × 3,780 ≈ 14,761.
- The wiki's conclusion: *"19 runs of 20 resin, or 7 runs of condensed resin"* fund one 5★ from
  +0 to +20, ignoring bonus multipliers. With ×1.13 it is ~16 runs, or **~325 resin** (derived).
- A Trounce (weekly boss) run gives a mean of 17,098 EXP (W-EXP).

**Resin-free EXP** (W-EXP):

| source | EXP |
|---|---|
| Daily investigation | ~60,000 per day (unsourced estimate on the wiki page; treat as rough) |
| NPC shops | 45 × 2★ per week = **37,800 per week** for 90,000 Mora |
| Battle pass, Artifact EXP plan | 45 Essence = 450,000 per period (wiki:`Battle_Pass`) |
| Imaginarium Theater | Unction and Essence per season |
| Realm Depot | Unction and Essence |

**Does levelling cost matter for the resin model?**
- A domain run's own fodder funds about **5% of a +20** (14.8k of 270k).
- Levelling a keeper costs about 16–19 runs' worth of fodder and Mora.
- Most pieces are abandoned at +0 or +4, at ≤16,300 EXP each.

So EXP is a real but **secondary** cost. Every 5★ that is kept and levelled to +20 costs
roughly as much fodder as ~300+ resin produces. Players who take the free sources above can
cover a large share of it.

**A modelling choice, not a sourced fact:** keep **EXP and Mora in a separate ledger** rather
than folding them into resin, the same way the planner separates mora. Report an "EXP-limited"
flag when fodder runs out.

---

## 7. How community tools estimate "resin to upgrade"

**Genshin Optimizer "Upgrade Optimization" (`libs/gi/upopt`, UI in
`page-team/…/TabUpgradeOpt/upOpt.ts`).**
- **The model** is a three-level Markov tree: *substat set → roll counts → roll values*. Its
  constants are copied from W-DIST.
- **The scoring** uses a **multivariate Gaussian approximation** of the target formula. The
  formula is linearised by its derivatives (`markov-tree/evaluation.ts`: `f_cov = df @ cov @
  df.T`, then `mvnPE_bad`). The result for each candidate is:
  - **`prob`**: the probability of beating the current build's value or threshold;
  - **`upAvg`**: the expected value given that it improves;
  - **lower/upper bounds** at ±4σ.

  Candidates are sorted by that and then refined with exact expansion.
- **Candidate types:**
  - `levelUpArtifact`: level an existing piece. A 3-line piece sums over the possible 4th
    line, or uses its known unactivated line.
  - `dustReshape`: Dust reshape with `minTotal` of 2, 3 or 4 (normal, Advanced, Decreed).
  - `elixirDefinition`: Elixir define, sweeping every set, main-stat and substat-pair choice,
    with `prob_4line = 0.34` and the ≥2-roll guarantee.
- A `freshArtifact(sets, p3sub, rarity)` function models "farm a new piece" with the slot,
  main-stat, set and 3/4-line mixture. **The current UI does not call it**: it is absent from
  `TabUpgradeOpt/upOpt.ts`'s imports.
- **GO does not convert anything to resin.** The upopt library never mentions resin. Its only
  resin code is a resin counter tool (`page-tools/ResinCounter.tsx`).

**KQM *Artifact Sub Math* (tooflesswulf, 2022): the explicit resin method.**
- It computes P(substat targets met at +20) exactly, using generating functions over
  `{7,8,9,10}α` with cached σ/µ tables.
- **For a slot:** p_tot = ⅕ Σ_slot P(new +20 piece beats current), summed over
  main-stat × 4-tuple-of-substats probabilities. Then:
  - **E[N] = 1/p_tot** artifacts to farm;
  - the expected gain E[ρ] comes from a truncated-normal mixture;
  - **damage per resin is E[ω] = −(1/c) · E[ρ] · p ln p / (1−p)**, with **c the
    artifact-to-resin ratio** and N geometric.
- **Caveat:** it assumes every artifact has 4 substats, **ignoring the 80/20 line split**,
  and predates Definition and Reshaping.
- **This is the closest published template for a "resin to beat what I have" number:**
  per-piece success probability → geometric expected count → × resin per piece.

**"Roll Value" / efficiency scorers.**
- **GO's `getArtifactEfficiency`** (`libs/gi/util/src/artifact/artifact.ts`) sums each
  filtered line's value as a fraction of one max roll (`getSubstatEfficiency` = Σrolls /
  (max × n)), which is "RV".
- `maxEfficiency` adds the remaining upgrades *as if all land in filtered lines*. It is an
  optimistic bound, not an expectation.
- **"Crit Value" = CD + 2·CR** is the common shorthand. It is cited here only from low-quality
  calculator pages found by search (e.g. https://west-games.com/genshin-artifact-substat-calculator/),
  so it is not authoritative.
- These scorers measure a piece **as it stands**. None of the ones found converts to resin.

**No maintained public "resin to get a better artifact" calculator was found** beyond KQM's
formula. That is UNVERIFIED as an exhaustive claim: the search was not exhaustive.

---

## 8. Model summary (what a resin model would consume) — every input sourced above

| input | value | § |
|---|---|---|
| resin per reward set | 20 (1×, 2×/40, 3×/Condensed-60 are linear) | 1.1 |
| 5★ per set, AR 45+ | 1.065 (measured 1.07, n = 14,088) | 1.2 |
| set | ½ each, 2 sets | 1.3 |
| slot | ⅕ | 2 |
| main stat | tables | 3 |
| initial lines | domain 80/20; Strongbox, boss and Abyss 66/34; Elixir 34%? (UNVERIFIED) | 4.1 |
| substat draw | weights 6/6/6/4/4/4/4/4/3/3, without replacement, excluding main | 4.2 |
| upgrades | 5 at +4…+20, uniform over 4 lines; a 3-liner's first upgrade adds a line | 4.3 |
| roll tier | uniform over {0.7, 0.8, 0.9, 1.0} × max | 4.4 |
| Strongbox | 3 × 5★ → 1 chosen-set 5★ | 5.1 |
| Elixir costs | 1/1/2/4/3; ≥2 rolls on the 2 chosen lines; 2 per set per version | 5.2 |
| Elixir supply | ~3.8–4.8 per version | 5.3 |
| Dust costs | 1/1/2/2/2; ≥2, Advanced ≥3, Decreed ≥4; keep the better result | 5.7 |
| Dust supply | ~3.5–6.5 per version | 5.7 |
| outbreak bonus | +1 5★ per 120 resin, 10 days per version | 5.6 |
| EXP per +20 | 270,475 EXP and Mora; ~14.8k EXP per run | 6 |

**Open items, marked UNVERIFIED above:**
- the 5★ count's distribution shape;
- Elixir pieces' 4-line probability;
- whether a reshape floors or resamples, and whether it keeps initial values;
- Strongbox slot and main-stat distribution;
- Gnostic Hymn's Dust count (1 vs 2);
- WL 9 domain rates (no measurement after 5.0).
