# RESEARCH — element (vision) symbols on the nanoka CDN

**Question:** can the seven Genshin vision emblems (Pyro, Hydro, Dendro, Electro, Cryo, Geo,
Anemo) be vendored from `https://static.nanoka.cc/assets/gi/`, and if so under what basenames?

**Date:** 2026-08-28. **Method rule observed throughout:** the CDN answers `200 text/html` for
names it does not have, so a status code is not evidence. Every claim below rests on
`content-type: image/webp`.

---

## VERDICT — FOUND

The element emblems are on the CDN under their **plain English element names**, exactly as the
DB's `characters.element` column spells them.

| element | basename | URL | bytes |
|---|---|---|---:|
| Pyro | `Pyro` | `https://static.nanoka.cc/assets/gi/Pyro.webp` | 3596 |
| Hydro | `Hydro` | `https://static.nanoka.cc/assets/gi/Hydro.webp` | 3344 |
| Dendro | `Dendro` | `https://static.nanoka.cc/assets/gi/Dendro.webp` | 3416 |
| Electro | `Electro` | `https://static.nanoka.cc/assets/gi/Electro.webp` | 3396 |
| Cryo | `Cryo` | `https://static.nanoka.cc/assets/gi/Cryo.webp` | 3688 |
| Geo | `Geo` | `https://static.nanoka.cc/assets/gi/Geo.webp` | 3098 |
| Anemo | `Anemo` | `https://static.nanoka.cc/assets/gi/Anemo.webp` | 3618 |

All seven: `200 image/webp`. All seven `last-modified: Tue, 02 Jun 2026 05:46:51 GMT` — one
upload, one family. The WebP `VP8X` canvas header reads `3f 00 00 3f 00 00`, i.e. **64x64**.

The name is **case-sensitive**: `pyro` and `PYRO` are both `404 text/html`. `Physical` is not
in the set (`404`), so a UI that wants a physical-damage glyph needs another source.

### Bonus, same family: weapon-type icons keyed by the enum value

Found while characterising the family. These are keyed by the **nanoka/game enum string**, not
by a talent icon, and are 128x128:

| weapon type | basename | bytes |
|---|---|---:|
| Sword | `WEAPON_SWORD_ONE_HAND` | 4974 |
| Claymore | `WEAPON_CLAYMORE` | 5104 |
| Polearm | `WEAPON_POLE` | 5102 |
| Bow | `WEAPON_BOW` | 4580 |
| Catalyst | `WEAPON_CATALYST` | 4776 |

All `200 image/webp`, all `last-modified: Tue, 02 Jun 2026 05:46:53 GMT`. This is a cleaner
mapping than the previously-derived `Skill_A_01`..`Skill_A_04` / `Skill_A_Catalyst_MD`, which
are the in-game *normal-attack talent* icons rather than weapon-class glyphs, and which have to
be hand-mapped. These basenames are literally the values already stored in the DB's weapon-type
columns.

**`WEAPON_CROSSBOW` is a miss** (`404 text/html`), even though the character index uses that
spelling for one class. `ITEM_TPS_WEAPON` is a miss too. So the enum-keyed family is not
complete — do not assume a name exists because a sibling does.

Other enum-keyed names probed and **missing**: `QUALITY_ORANGE`, `QUALITY_PURPLE`,
`EQUIP_BRACER`, `EQUIP_NECKLACE`, `EQUIP_SHOES`, `EQUIP_RING`, `EQUIP_DRESS`,
`FIGHT_PROP_HP`, `FIGHT_PROP_FIRE_ADD_HURT`, `FIGHT_PROP_ELEMENT_MASTERY`, `Vision`,
`Element`, `Sword`, `Bow`, `Polearm`, `Claymore`, `Catalyst`, `Dendro_Core` — all
`404 text/html`.

---

## How this was reached — the derivation, in order

### 1. The committed data does not name an element icon (searched, came up empty)

- `backend/tests/fixtures/nanoka_gi/` — extracted every quoted token from all index files and
  the schema catalog (7,117 distinct). Filtering for `element|vision|elem` yields only
  Excel *table* names, ability names, and `UI_MonsterIcon_Elemental_Wind_01`. No element icon.
- The nanoka character index carries element as a **bare string** — Ayaka's record is
  `"element": "Cryo"`, alongside `"icon": "UI_AvatarIcon_Ayaka"`. There is no second icon
  field. The character *detail* payload's only `UI_`/`Skill_` strings are per-character
  (`UI_AvatarIcon_Ayaka`, `UI_Talent_S_Ayaka_01`, `UI_TraceEffectIcon_Ayaka`, ...).
- `backend/app/data/yuanshen/schema/table_catalog.json` is a name-to-sha map only, so it names
  `ElementStateExcelConfigData` and the `GCG*` tables but carries none of their columns.

### 2. The seeded database has no element-scoped icon

Every icon-bearing column was enumerated from `information_schema` —
`characters.icon`, `weapons.icon`, `artifact_sets.icon`, `talents.icon`,
`constellations.icon`, `ascension_passives.icon`, `enemy_profiles.icon`. Querying each for
`~* '(element|vision|pyro|hydro|dendro|electro|cryo|geo|anemo)'` returns exactly one row:
`enemy_profiles` → `UI_MonsterIcon_Elemental_Wind_01`, an Anemo Slime portrait, not an emblem.
The only non-per-character `talents.icon` values are `Skill_A_01`..`Skill_A_04`.

### 3. The game's own element icon names were derived from upstream — and they are NOT on this CDN

`ElementStateExcelConfigData.json`, fetched from the pinned YuanShenResources commit
(`5445617e33b29f057b9479883cc8e5e77c7d128d`, the sha in
`backend/app/data/yuanshen/schema/provenance.json`), is the authoritative element-icon table:

| elementType | elementIcon |
|---|---|
| Fire | `UI_Buff_Element_Fire` |
| Water | `UI_Buff_Element_Water` |
| Wood / Overdose / Grass | `UI_Buff_Element_Grass` |
| Electric | `UI_Buff_Element_Elect` |
| Wind | `UI_Buff_Element_Wind` |
| Frozen / Ice | `UI_Buff_Element_Frost` |
| Rock | `UI_Buff_Element_Roach` |

**Every one of those is `404 text/html` on `static.nanoka.cc/assets/gi/`**, including the two
spellings nobody would have guessed (`_Elect`, `_Roach`). So the game's real internal names are
the wrong question for this CDN — which is the finding that made the sweep worth running.

### 4. Why the game's names miss: the CDN mirrors nanoka's own data, plus nanoka's own UI set

`https://nanoka.cc`'s SvelteKit bundle builds asset URLs as
`https://static.nanoka.cc/assets/${game}/${name}`, where `name` comes straight out of the JSON
index files. Its element handling in the i18n chunk is **text**, not art:
`labels.elements = {Pyro:"Pyro", Hydro:"Hydro", ...}` (and `{Pyro:"火", ...}` in zh). Its GCG
index (`https://static.nanoka.cc/gi/7.0.51/gcg.json`, fetched and grepped) contains only
`UI_Gcg_CardFace_*` — no dice or element glyphs.

Confirmed by probe that every asset family named in nanoka's data does resolve:
`UI_AvatarIcon_Ayaka`, `UI_Gacha_AvatarIcon_Ayaka`, `UI_EquipIcon_Sword_Blunt`,
`UI_RelicIcon_10001_4`, `UI_ItemIcon_108300`, `UI_NameCardPic_Ayaka_P`,
`UI_TraceEffectIcon_Ayaka`, `UI_Talent_S_Ayaka_01`, `UI_Talent_U_Ayaka_01`,
`UI_MonsterIcon_Elemental_Wind_01`, `Skill_A_Catalyst_MD` — all `200 image/webp`.

So the CDN carries two things: the game-derived assets nanoka's data names, **and a small
hand-made set keyed by the enum strings nanoka's own UI switches on**. The element emblems are
in the second set, which is why no amount of searching game data would have found them.

### 5. The sweep that found it

`Pyro` surfaced from a scripted 72-candidate sweep over 33 prefix families x
{`Fire`, `Pyro`} — `UI_Icon_Element_`, `UI_Buff_Element_`, `UI_Icon_Elem_`, `UI_ElemIcon_`,
`UI_ElementIcon_`, `UI_Icon_ElementType_`, `UI_Icon_Attribute_`, `UI_Icon_Type_`,
`UI_Gcg_Dice_`, `UI_Gcg_DiceL_`, `UI_Gcg_DiceS_`, `UI_Gcg_Buff_Element_`,
`UI_Gcg_Icon_Element_`, `UI_GcgIcon_Element_`, `UI_Icon_Vision_`, `UI_Vision_`,
`UI_VisionIcon_`, `UI_MarkPoint_Element_`, `UI_ItemIcon_Element_`, `UI_Talent_Element_`,
`UI_AbilityIcon_Element_`, `UI_EquipIcon_Element_`, `UI_Icon_Element` (unseparated),
`Eff_UI_Icon_Element_`, `UI_Icon_Skill_Element_`, `UI_ElementAtkIcon_`,
`UI_Icon_Ability_Element_`, `Element_`, `Elem_`, `UI_Icon_`, `UI_ElementalIcon_`,
`UI_Icon_ElementalType_`, and the empty prefix — plus lowercase and path-shaped variants.
**Exactly one candidate hit, and it was the empty prefix.**

Prior misses recorded before this pass, all re-confirmed as `text/html`:
`UI_Icon_Element_Fire`, `UI_Buff_Element_Fire`, `UI_Icon_Element_Pyro`, `Element_Pyro`,
`UI_ChapterIcon_Pyro`, `UI_GachaTypeIcon_Pyro`, `Skill_Pyro`, `UI_Icon_Pyro`,
`UI_ElementIcon_Pyro`, `UI_Icon_Element_Water`, `UI_ElementIcon_1`, `UI_Icon_Fire`,
`UI_Icon_Ability_Fire`, `Skill_E_Fire`, `UI_Buff_Element_Wind`, `Element_Fire_Icon`,
`UI_Icon_ElementType_Fire`, `UI_Icon_Vision_Pyro`, `UI_Vision_Pyro`, `UI_Icon_Pyro_01`,
`Eff_UI_Icon_Element_Fire`, and the path forms `/element/pyro.webp`, `/elements/pyro.webp`.

**Probe control:** `UI_AvatarIcon_Ayaka.webp` returned `200 image/webp` in the same runs, so a
miss is a real miss and not a broken request.

---

## Limits of this evidence

Two of them, and both matter.

**A probe-based negative is not a proof of absence.** Section 3's conclusion — that the game's
own `UI_Buff_Element_*` names are not on this CDN — is as strong as a 404 gets, but the sweep in
section 5 can only say *these 100-odd names are not there*. It cannot say no other name is. As
it happens the sweep found a hit, so nothing rests on its negative; but if a future reader wants
a different glyph (`Physical`, an artifact-slot icon, a stat icon) they should read this as
"not found by these probes", never as "does not exist".

**The images were not looked at.** This pass was scoped to derivation and did not download art,
so the claim that `Pyro.webp` *is* the Pyro vision emblem rests on its name, its 64x64 canvas,
its ~3.5 KB size, and its membership in a seven-file set uploaded in one second. That is strong
circumstantial evidence and not a visual confirmation. Whoever vendors them should open one and
look — this repo has already been bitten once by four layers each behaving correctly and adding
up to a site with no art (`docs/DECISIONS.md` §4).

## If they had not been found

For the record, since the question was asked: the alternatives would have been to draw the seven
emblems as inline SVG in `frontend/src/app/shared/` (they are simple, distinctive shapes, and it
would have made them theme-tintable and dependency-free), or to take them from another Genshin
asset mirror (Project Amber and gi.hakush.in both publish element icons, at the cost of a second
provenance to pin and a second CDN to vendor from). Neither is needed now.
