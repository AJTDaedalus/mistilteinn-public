# RESEARCH — data audit for a leveling planner

**Status:** scoping only. No BRIEF, no DESIGN, no branch. Written 2026-09-07 in response to
the owner's request for a "planner" tab that plans character levels, talents and weapons.

**What this file answers:** *do we have the data?* Mostly yes, and the gaps are named below
with the source each one should come from. It does **not** decide scope — four scoping
questions are open at the bottom.

---

## 1. Verdict

| need | have it? | where |
|---|---|---|
| character ascension mats + mora, per phase | **yes** | nanoka detail `materials.ascensions` (6 entries) |
| talent mats + mora, per level 1→10 | **yes** | nanoka detail `materials.talents` (per talent, 9 entries) |
| character EXP per level | **yes** | nanoka detail `level_exp` (90 entries) |
| weapon ascension mats + mora, per phase | **yes** | nanoka detail `materials["1".."6"]` |
| weapon EXP per level | **yes** | nanoka detail `xp_requirements` (keyed 1..90) |
| material name / rarity | **yes** | inline on every mat: `{name, id, count, rank}` |
| material icon | **yes, but** | `UI_ItemIcon_{id}.webp` resolves on the CDN — 4/4 probed. Convention, not published; see §3 |
| current character level / ascension / talents | **yes** | `builds.character_level`, `.ascension_phase`, `.talent_levels` (JSONB) |
| current weapon level / ascension | **yes** | `owned_weapons.level`, `.ascension`; also `builds.weapon_level` |
| character art (full splash) | **yes, but** | `UI_Gacha_AvatarImg_<name>.webp` — **~450 KB each, ~64 MB for 150**; see §4 |
| weapon art | **yes** | `UI_EquipIcon_*` (15 KB, committed already) and `UI_EquipIcon_*_Awaken` + `UI_Gacha_EquipIcon_*` (25 KB) |
| talent icons | **yes, committed** | `talents.icon`, 261 files already in `frontend/public/icons/` |
| ascension phase → level cap (20/40/50/60/70/80/90) | **no** | needs a citation — `AvatarPromoteExcelConfigData.unlockMaxLevel`, §3 |
| EXP book / ore denominations and their mora | **no** | needs a citation — `MaterialExcelConfigData`, §3 |
| owned material stock | **no** | `good_importer` reads only `artifacts` / `characters` / `weapons`; §5 |

**Nothing in this list is imported today.** There is no materials table, no migration
mentioning one, and `level_exp` / `xp_requirements` appear in `app/` only inside a comment in
`app/models/build.py:65`. The costs are in the payloads we already pin; we have never read
them.

## 2. What the payloads look like

Character `materials.ascensions[5]` (Ayaka, 10000002):

```json
{"mats": [{"name": "Shivada Jade Gemstone", "id": 104164, "count": 6, "rank": 5},
          {"name": "Perpetual Heart",       "id": 113023, "count": 20, "rank": 4},
          {"name": "Sakura Bloom",          "id": 101202, "count": 60, "rank": 0},
          {"name": "Famed Handguard",       "id": 112046, "count": 24, "rank": 3}],
 "cost": 120000}
```

`materials.talents` is a list **per talent**, each of 9 entries (level 1→2 … 9→10), and the
9th carries `Crown of Insight`. `materials.talents` has 4 entries for Ayaka, matching her 4
`skills` — so it is keyed positionally against `skills`, which `talents.nanoka_id` already
refuses to trust. **Join on the skill id, never the index.**

Weapon `materials` is a dict keyed `"1".."6"`, same `{mats, cost}` shape.

`level_exp` is cumulative-per-level EXP (1000 → 613950 at the tail); `xp_requirements` is the
weapon equivalent keyed `"1".."90"`.

## 3. The three gaps, and where each is sourced

**Material icons.** nanoka publishes no material index — `gi/7.0.51/material.json` and
`item.json` both 404. But `assets/gi/UI_ItemIcon_{id}.webp` resolved 200 `image/webp` for
all four probed ids across three id families (104xxx gems/books/crown, 112xxx common drops,
101xxx local specialty). That is a **convention we would be guessing at**, and this repo's
rule against inventing a basename (`scripts/download_icons.py`, "It does not invent a
basename") applies. `MaterialExcelConfigData` publishes the real `icon` field; take it from
there and let the convention be the thing the snapshot *confirms*, not the thing we ship.

**Ascension phase → level cap.** The 20/40/50/60/70/80/90 ladder is a game constant nobody
here has cited. `AvatarPromoteExcelConfigData.unlockMaxLevel` and
`WeaponPromoteExcelConfigData` publish it. Per §"Do not write damage or reaction formulas
from memory" — the same discipline applies to a level cap that decides what a plan costs.

**EXP book / ore denominations.** Hero's Wit / Adventurer's Experience / Wanderer's Advice and
Mystic / Fine / plain Enhancement Ore, their EXP values, and the mora charged per EXP point,
are all uncited. `MaterialExcelConfigData` carries them. **This is the one place a planner
can be quietly wrong and look right**, because the raw `level_exp` total is correct and only
the conversion into books is not.

All three live in `app/data/yuanshen/schema/table_catalog.json` (confirmed present:
`MaterialExcelConfigData`, `AvatarPromoteExcelConfigData`, `WeaponPromoteExcelConfigData`,
`MaterialSourceDataExcelConfigData`, `MaterialCodexExcelConfigData`), so the route is the
existing one: extend `scripts/yuanshen/build_snapshot.py` and commit a snapshot, exactly as
E.5 did for the artifact main-stat pools. No new dependency, no runtime fetch.

`MaterialSourceDataExcelConfigData` additionally carries **domain availability by weekday**,
which is what turns a shopping list into a schedule. Out of scope unless asked for.

## 4. Art weight

Measured, six splashes: Ayaka 639 KB, Diluc 395, Yelan 440, Nahida 440, Furina 627, Klee 150
— **mean 449 KB**, so ~64 MB for 150 characters before the 28 Traveler variants.

The repo currently commits **446 files at 9.6 MB** (`docs/DECISIONS.md` §4), and the argument
that won there was that this set is *lighter* than the one fairy already ships. Splash art is
**~6.7× the entire current icon tree**. That decision does not carry over on its own reasoning
and needs re-making. Three options in §6.

Material icons themselves are cheap — comparable to the 15–22 KB `UI_ItemIcon` probes, and an
estimated 350–400 distinct materials across the whole catalogue, so roughly 5–8 MB.

## 5. The material set, derived rather than estimated

Fetched all **150 character and 286 weapon** detail payloads at 7.0.51, **0 failures**, and
took the union of every `mats` entry:

- **508 distinct materials.**
- By rarity (`rank`): `{0: 60, 1: 19, 2: 108, 3: 108, 4: 137, 5: 76}`.
- By use: **197** in character ascension, **173** in talents, **252** in weapon ascension
  (a material can appear in more than one).

An earlier draft of this file guessed "350–400". It was low by a quarter, which is the
reason the number is now derived. At the `UI_ItemIcon` sizes probed (5–21 KB) that is roughly
**5–8 MB** of new art.

**`lookup_key` is injective over all 508.** Running the existing normalisation
(`good_build_service.lookup_key`, `[^a-z0-9]` stripped, lowercased) over every material name
produced **zero collisions**. That is the same property
`test_set_key_normalisation_is_injective` asserts for the 65 artifact sets, and it is what
makes a GOOD material key safe to bind by name. A materials importer should carry the
equivalent test.

*(The index lists 286 weapons where `CLAUDE.md` says 260 are seeded — the seed filters
some. Not chased here; it changes no conclusion, since the extra payloads only add materials
and none failed to fetch.)*

## 6. The owner's own GOOD export **does** carry materials

`references/genshin_export_2026-08-28_11-07.json` — Irminsul, GOOD **v3**, 89 characters,
2,370 artifacts, 320 weapons, and a **`materials` map of 1,384 entries**. The importer reads
`artifacts` / `characters` / `weapons` and ignores it.

Joining it against the 508 by normalised key:

| | |
|---|---|
| nanoka materials present in the export | **448 / 508** |
| absent | 60 |
| entries in the export with count 0 | **0** (min 1, max 11,250) |

**Absent means zero, not unscanned.** The export contains no zero-valued entry, and the 60
absent names are exactly what a real account holds none of: every top-tier **Gemstone** (you
convert down and spend immediately), spent weekly-boss drops, the newest patch's materials,
and **all four Brilliant Diamond tiers** — the Traveler's gems, which cannot be held as items
at all. That last one is a strong signal the join is correct and not accidentally matching.

**A correction worth recording.** A first probe reported `HeroSWit` and
`AdventurerSExperience` absent and nearly became a finding that EXP books are unscanned. The
apostrophe rule was wrong: GOOD drops the apostrophe **without capitalising the next letter**
— `Hero's Wit` → `HerosWit` (**204** held), `Adventurer's Experience` → `AdventurersExperience`
(**860**). `lookup_key` normalises both sides to `heroswit` and never had the problem; only
the hand-written probe did. Weapon ore is there too — `MysticEnhancementOre` 1,541,
`FineEnhancementOre` 635, `EnhancementOre` 25.

**The one real gap is Mora.** GOOD has no currency field, and every ascension and every talent
level costs it — 120,000 mora for a single 5→6 ascension, 700,000 for one talent 9→10. The
planner can compute and total the mora cost, and **can never tell you whether you can afford
it**. That asymmetry should be visible in the UI rather than papered over: material rows can
say *still need*, the mora row can only say *costs*.

## 7. Scope, as answered by the owner 2026-09-07

1. **Art:** commit full splash art as-is (~64 MB). Reverses the weight argument in
   `DECISIONS.md` §4 deliberately; that file needs an entry saying so.
2. **Progress source:** the user picks one of their **builds** as the "from" state. No schema
   change. **A build is allowed to be hypothetical**, so the planner must show which build it
   read and what levels it took, rather than silently treating a scenario as the account.
3. **Plan shape:** one character + weapon per plan. Sections are leveling/ascension, talents,
   weapon; the cumulative summary sums those three.
4. **Owned stock:** read GOOD's `materials` section, subtract it, show *still need*. §6 says
   this works and names its one gap.

## 8. What is still open

- **Talent levels 11–15.** `builds.talent_levels` allows 1–15, but `materials.talents` covers
  only the nine steps to level 10; 11–15 come free from C3/C5. A target above 10 has no
  material cost, and the UI has to say that rather than showing an empty list.
- **Ascending without levelling** (the owner's explicit ask) is well-supported by the data —
  ascension cost and EXP cost are separate tables — but needs the level cap per phase from
  §3 to render "80/90" correctly.
- **Traveler.** 28 variants share `Brilliant Diamond`, which cannot be held. Their plans will
  always read *still need: all of it*. Probably wants special-casing.
- **Domain weekdays** (`MaterialSourceDataExcelConfigData`) — not asked for, available.

---

# Part II — the resin calculator

Asked 2026-09-07: resin cost for the full plan and per section, a **per-item** resin figure,
the drop distribution behind it, and the character crafting bonuses. Scoped below with the
same rule as Part I — derived, not recalled. Answers to the settled points first:
**Mora is a total only, never imported** (§6 already said GOOD cannot supply a balance);
**talents stop at 10**, since 11–15 are free from C3/C5 and have no material rows at all.

## 9. Resin costs are published, in full

| source | table | field | value |
|---|---|---|---|
| domains (talent / weapon / artifact) | `DungeonExcelConfigData` | `statueCostCount`, `statueCostID` | **20**, item **106** (Original Resin) — uniform across all **307** rows that charge |
| world bosses | `InvestigationMonsterConfigData` | `resinCost` | **40** (44 bosses), **60** (1) |
| ley-line blossoms | `BlossomChestExcelConfigData` | `resin`, `world_resin` | **20**, with `refreshType` separating `BLOSSOM_REFRESH_SCOIN` (mora) from `BLOSSOM_REFRESH_EXP` (EXP books) |

`DailyDungeonConfigData` gives the weekday rotation (which domain is open Mon/Thu/Sun), and
`DungeonEntryExcelConfigData.descriptionCycleRewardList` gives it as **material ids per day**
— e.g. `[[104301,104302,104303], [104304,104305,104306], [104307,104308,104309], [all nine]]`.
So "you can only farm this book on Tue/Fri/Sun" is derivable, not curated.

**This half needs no curation at all.**

## 10. Drop yields are half-published, and the shortfall is small

`RewardPreviewExcelConfigData` carries **fractional** counts — `2.2`, `5.252`, `0.35`,
`2.556` — which are per-run expected values, not item counts. Across all previews: 10,763
preview items, 4,163 with a count, **615 fractional**, of which **524 are planner materials
covering 252 distinct ones**.

**A first reading of this was wrong and is corrected here.** Seeing `2.2` on a talent domain
I took the previews to be a complete EV table. They are not: in most previews **only one item
carries a number and the rest are blank**, and the talent-domain figures do not scale sensibly
with domain level (lv38 → 2.2, lv54 → 2.5, lv71 → 1.8, lv88 → 2.2). A world boss publishes an
EV for its boss-specific drop and **nothing for the gems**, which are half of what you came
for. Had that first reading stood, the calculator would have been confidently wrong on every
gem in the game.

Classifying all 508 against resin sources and the crafting tree:

| | count |
|---|---|
| planner materials | **508** |
| reachable with resin | **247** (domain 168, boss 79) |
| craftable via `CombineExcelConfigData` | 294 |
| resin **or** craft | 388 |
| neither — overworld drops, local specialties | 120 |
| resin-reachable **with** a published expected count | **94** |
| resin-reachable **without** one | 153 |

**The 153 is not the curation bill.** `CombineExcelConfigData` publishes the whole conversion
tree — 3× lower tier → 1 higher, with its own `scoinCost` mora — so a family's EV follows from
its base tier. Collapsing the 153 by craft root: **60 roots, 48 of which already have a
published EV**, deriving 120 of the 153.

### The curation list is 12 numbers

| what | why it is missing |
|---|---|
| 7 elemental gem **Slivers** — Agnidus Agate, Nagadus Emerald, Prithiva Topaz, Shivada Jade, Vajrada Amethyst, Varunada Lazurite, Vayuda Turquoise | world bosses publish an EV for their boss drop and none for the gem branch. Each Sliver carries a family of 4 (Sliver/Fragment/Chunk/Gemstone) through the 3:1 tree |
| 5 weekly-boss drops — Ring of Boreas, Spirit Locket of Boreas, Tail of Boreas, Juvenile Jade, Evergloom Ring | family of 1 each |

Brilliant Diamond is correctly absent: it is the Traveler's gem and cannot be obtained at all,
which is the same signal §6 got from the GOOD join.

**One assumption has to be stated in the UI, not buried.** These EVs are a single figure per
source; real yields scale with **World Level** (`WorldLevelExcelConfigData` exists but was not
chased). Either the calculator declares "assumes AR55+/WL8" on its face, or the 12 numbers
become 12 × world levels. Recommend the former for a first cut — a resin estimate that quietly
assumes an account level the user does not have is the kind of wrong that looks right.

## 11. Crafting bonuses are already in our own database

`ascension_passives` holds **485 rows**, and querying their descriptions found **26** that
change crafting yield — no new import, no text scraped from anywhere. Three distinct effects:

| effect | example | usable? |
|---|---|---|
| **double the product**, stated % | Sucrose — *"crafts Character and Weapon Enhancement Materials … 10% chance to obtain double the product"*; Ayaka, Albedo, Alhaitham, Wriothesley (Weapon Ascension, 10%); Eula, Layla (Character Talent, 10%) | **yes** — exact, EV is ×(1+p) |
| **refund a portion**, stated % | Xingqiu — *"25% chance to refund a portion of the crafting materials used"*; Mona, Dori | **partly** — the *chance* is published, **"a portion" is not**. Unfixable from any table here |
| **bonus regional material** | Yae Miko 25%, Prune 10% — *"get 1 regional Character Talent Material (base material excluded)"* | yes, but needs the regional family modelled |

Cooking and furnishing bonuses (Jean, Barbara, Noelle, Xinyan, Yun Jin, Nilou, Yoimiya, Kaveh)
and the ore-refund ones (Diluc, Zhongli, Ganyu — *"15% of the ore used when crafting
Claymore-type weapons"*, which is weapon *forging*, not ascension) are in the same 26 and are
**not** planner-relevant. Filter by effect, not by "has a crafting passive".

Parsing these is text-matching against a description field, which is fragile. It is a small
fixed set, so a **curated id→effect table with a test asserting all 26 still parse** is the
honest shape — the same discipline `gcsim_keys` uses.

## 12. Verdict on punting

**Do not punt it.** The expensive half — resin costs, domain weekday rotation, the crafting
tree with its mora, and the crafting-bonus passives — is fully published or already seeded.
The gap is **12 hand-supplied numbers**, each the best-documented figure in the game, plus one
stated world-level assumption.

What genuinely is not available anywhere: the **full probability distribution**. Nothing in
`ExcelBinOutput` resolves a `drop_id` — `BlossomRefreshExcelConfigData.dropVec` references
ids like `207000400` and no table in the 1,935 defines them; the randomised tables are
server-side. So a per-item resin figure is an **expected cost**, and the honest UI says
*"≈ 320 resin"*, never a guarantee, and cannot offer a confidence interval without community
sample data this repo would have to source and cite separately.
