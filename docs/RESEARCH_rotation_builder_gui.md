# RESEARCH — the rotation builder as a GUI: icons, a strip, and what the model refuses

**Status:** research, 2026-08-30. No code changed. Every number below names the command that
re-derives it.

**Reads first:** `docs/DESIGN_rotation.md` §2 (what a rotation *is*, and the three things it
deliberately cannot express) and `docs/DESIGN_rotation_builder.md` §1 and §7 (what "extensive"
was allowed to mean, and what was refused). This document does not revisit either; where the
owner's request collides with one, it says so and hands the question back rather than deciding.

The request, in the owner's words:

> *"It should be a GUI interface, not a drop-down menu. It'd be nice if moves were buttons you
> could drag onto the rotation, and see the rotation as a timeline with colors and icons
> indicating the active character. I think there are rotation icons floating around somewhere
> on the internet with basic attack, skill, ult animations (with a 't' and 'h' on skill for tap
> and hold skills). Some may need variants (like Varesa and Flins ult, for example). The goal is
> a very user friendly and fun to use rotation builder that's not overly complicated and looks
> good."*

---

## 0. What the research found, in one table

| the ask | finding | where it lands |
|---|---|---|
| "rotation icons floating around the internet" | **They are in this repo's own catalogue already.** `talents.icon` holds the game's sprite basename for every character's normal attack, skill and burst. 256 distinct skill+burst sprites; **none of them vendored yet**; ~1.01 MB to add. | §1 — buildable, cheap, no decision needed |
| icons for the other actions | **Seven of the ten authorable actions have no sprite** and never did. Charged attack, aim, both plunges, dash, jump, walk. | §1.4 — draw them, do not borrow the attack icon |
| "a 't' and 'h' on skill for tap and hold" | **Hold is a gcsim *parameter*, not an action** — `skill[hold=1]`, read by 47 of gcsim's 106 characters. This model has no parameters, so a hold button is a **grammar change**, not a surface change. | §2 — **owner's call**, OQ-G1 |
| "variants (like Varesa and Flins ult)" | **Not authorable.** gcsim picks the burst form from *sim state* (`if c.StatusIsActive(apexState)`), never from the config. Two buttons would offer a choice gcsim ignores. There is also only one burst sprite per character. | §3 — refused, with the honest place it *can* be shown |
| "see the rotation as a timeline" | **Both are buildable.** An ordinal strip needs no new data. A *real* time axis costs one `sample()` call — **2.3 s for a real four-character config**, already exported by the committed wasm. §4's original refusal is corrected there. | §4, and `DESIGN_rotation_builder_gui.md` §1 |
| "colors indicating the active character" | The palette exists — seven element tokens in `_tokens.scss`. The house rule is that **colour is never the only channel** (`ElementChip`), so the strip carries art and a name too. | §4.2 |
| "drag moves onto the rotation" | **Half is built.** #184 gave the step list native HTML5 drag with `reorder(from, to)`. What is missing is a *second* drag source with *insert* semantics rather than *move*. | §5 |

---

## 1. The icons are already in the catalogue, and 256 of them are one script change away

### 1.1 The evidence

`Talent.icon` (`backend/app/models/character.py:167`) stores the nanoka basename of the game's
own sprite for each talent. Against the seeded database:

```
select talent_type, count(distinct icon) from talents where icon is not null group by 1;
  alternate_sprint   2
  elemental_burst  128
  elemental_skill  128
  normal_attack      5
```

446 talent rows across 148 characters (150 exist; two unreleased Traveler variants have no
talents seeded — the same two `weapon_symbols.py` already documents).

**The normal-attack five are already vendored and already on screen.** `Skill_A_01` … 
`Skill_A_Catalyst_MD` are in `frontend/public/icons/` because `weapon_symbols.py` derived the
weapon-class marks from exactly this column. So the pattern the builder needs is not new — it
is the one `weapon-mark` already uses, extended from five sprites to 261.

### 1.2 The 256 that are missing

```
select distinct icon from talents
 where icon is not null and talent_type in ('elemental_skill','elemental_burst');
```

returns **256 basenames, of which 0 are present locally**. Every one of them is published:
16 sampled at random against `https://static.nanoka.cc/assets/gi/<name>.webp` returned 200 with
an average of **4,122 bytes**, so the whole set is **~1.01 MB**.

Against what is already committed: `frontend/public/icons/` is **919 tracked files, 30.4 MiB**
(`git ls-files frontend/public/icons | wc -l`, `du -sb`). Adding the talent art is **~3%
growth**, and roughly a fifteenth of what the gacha portraits alone occupy (15.1 MB, 120 files).

> **Aside, because it will mislead the next reader:** `CLAUDE.md` says the icon set is "446 files
> at 9.6 MB". That was true when written and is not now — the gacha portraits landed since.
> Re-derive with the two commands above rather than citing the line.

### 1.3 The basenames must be read, never constructed

This is the part worth writing down, because the naming looks regular and is not:

| basename | HTTP |
|---|---|
| `Skill_S_Ayaka_01` | 200 |
| `Skill_E_Ayaka` | 200 — **no `_01` suffix** |
| `Skill_E_Varesa_01` | 200 |
| `Skill_E_Varesa` | **404** |
| `Skill_E_Mavuika` | **404** |
| `Skill_E_Flins_01` | 200 |

So `Skill_E_<Character>` is right for Ayaka and wrong for Varesa, and the inverse holds too. A
downloader that builds the name from the character key would 404 on an unpredictable subset and
a UI that builds it client-side would show gaps nobody could explain. **Read the column.** This
is the same failure `weapon_symbols.py` avoided by querying rather than writing five lines from
memory, and the reason its docstring calls out `Skill_A_Catalyst_MD` by name.

### 1.4 Seven of the ten actions have no sprite, and should not borrow one

`authorable_actions()` returns ten: `attack skill burst charge aim dash jump walk high_plunge
low_plunge`. Only three are talents (`gcsim_keys._ACTION_TALENTS`), and only those three have
catalogue art.

The tempting move is to draw a charged attack with the normal-attack sprite, since it scales off
that talent. **That would say something false** — `gcsim_keys` already refuses the equivalent for
*names*, on the grounds that labelling a charged attack "Kamisato Art: Kabuki" is a wrong name
rather than a missing one. The same argument applies to a picture, and more strongly, because a
picture has no key beside it to correct the impression.

What the seven should get instead is **glyphs drawn here** — the repo already draws rather than
vendors where nothing upstream exists (`shared/emblem`, and `weapon-mark` renders a word when a
class has no mark). Seven simple marks is a small, self-contained piece of work with no upstream
dependency and no licence question.

---

## 2. "Tap and hold" is a parameter, and this model has no parameters

The owner's `t`/`h` badge is the most attractive item in the request and the only one that
cannot be built without reopening a closed decision. The evidence:

**gcsim expresses hold as a parameter on `skill`, not as a separate action.** From a real
community config committed to this repo — `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt:48`:

```
chev burst, skill[hold=1]:2;
```

**It is not rare.** Across gcsim's 106 implemented characters at the pin:

```
grep -rl '"hold"' internal/characters/ | cut -d/ -f3 | sort -u | wc -l   → 47
```

with `short_hold` (6 characters), `recast` (4), `hold_ticks` (3) and `short` (2) as further
variants of the same idea.

**And the model has nowhere to put it.** A step is `character · action · repeat · note`
(`DESIGN_rotation.md` §2). `RotationStep` has no params field, `rotation_parser` refuses
anything outside the ten actions by name, and `authorable_actions()` derives the ten by
subtraction from gcsim's own list. A hold button therefore needs a schema field, a migration, a
compiler change, a validator change, and — the part that matters — **a decision that the model
now carries per-action parameters**, which is `DESIGN_rotation.md` §2's territory, not a
builder's.

**The convergence worth noting:** KQM's own written notation is `tE` and `hE` — tap-E and
hold-E. The owner's instinct to stamp a `t` or `h` on the skill icon is literally the community
standard rendered as a badge, which is a good sign about the *design* even though the *grammar*
question stands.

**Recommendation, if the owner opens it:** the smallest honest version is a boolean `hold` valid
**only on `skill`**, offered **only for the 47 characters whose gcsim implementation reads
`p["hold"]`** — derived from gcsim's source the way `gcsim_keys` derives everything else, so the
picker offers hold exactly where gcsim will honour it and nowhere else. That keeps the property
that has held since R.4: *the picker offers exactly what the validator accepts*. It still opens
the parameter door, and `short_hold`/`recast`/`hold_ticks` are standing behind it.

---

## 3. Varesa and Flins: the variant is real, and it is not the author's to pick

`internal/characters/varesa/burst.go:41`:

```go
func (c *char) Burst(p map[string]int) (action.Info, error) {
    c.c4Burst()
    if c.StatusIsActive(apexState) {
        return c.volcanicKablam(), nil     // "Volcano Kablam", 47-frame form
    }
    ...
    if c.nightsoulState.HasBlessing() {
        ai.Abil = "Fiery Passion Flying Kick"
    }
```

Flins is the same shape — `burstFrames` against `symphonyFrames`, selected internally.

Three consequences:

1. **`p` is not consulted for the variant.** There is no `burst[form=2]`. gcsim reads its own
   state. A config *cannot* express which one fires, so a builder offering two ult buttons
   would be offering a choice that has no effect — worse than not offering it, because the
   config would come back looking like it was honoured.
2. **There is no second sprite to show.** `select count(*) from (select character_id from
   talents where talent_type='elemental_burst' group by 1 having count(*)>1)` returns **0**:
   every character has exactly one burst talent row and one burst icon. Varesa's is
   `Skill_E_Varesa_01`, and the game does not publish a "Volcano Kablam" icon.
3. **The variant is visible in the *result*, not in the *plan*.** gcsim labels the hit
   `"Volcano Kablam"` / `"Fiery Passion Flying Kick"` in its ability names, so a run's output
   can say which form fired. That belongs to whatever reads a `sim_run` back — the corpus that
   got its producer in #183 — and not to the authoring surface.

So: **refused for the builder, and the reason is worth keeping**, because "some ults need
variants" is a correct observation about the game that happens to be a wrong requirement for
this screen.

---

## 4. The timeline

> **Corrected 2026-08-30, later the same day, by measurement.** §4.1 below refused a time axis
> outright. That refusal was wrong, and `DESIGN_rotation_builder_gui.md` §1 carries the
> correction with its evidence: the committed wasm build already exports `sample(cfg, seed)`,
> and one call against the real four-character `clorinde-chevreuse-nicole-durin.txt` returns a
> frame-accurate on-field trace in **2.3 s**. Frame *counting* is the user reasoning in frames
> to hand-tune a config; being shown what the simulator did is the machine doing the counting.
> **Both timelines are wanted** — the ordinal one below while authoring, the measured one on
> demand. §4.1 stands as written for the authored view, and is superseded for the simulated one.

### 4.1 Two things are called a timeline, and only one is buildable *without a run*

`DESIGN_rotation_builder.md` §7 refuses "frame or second counts in the editor", because
`DESIGN_rotation.md` §2 removed timing on purpose and showing a duration puts the user back
into frame counting.

That refusal is about a **time axis** — tiles whose *width* is their animation length. It is not
about a **sequence strip** — tiles of equal width in order, left to right. The owner's phrasing
("see the rotation as a timeline with colors and icons indicating the active character") reads
as the strip: the thing being conveyed is *who is on field across the cycle*, which is ordering,
not duration.

**The strip needs no new data at all.** It is a second rendering of `steps()`, which the
component already holds.

A time axis would also be a lie in a second way: the compiler emits `.ready` gates, so a step
that is not ready is **skipped**. The drawn length of a burst tile would be the length of a
burst that fires, and the strip cannot know whether it will.

### 4.2 Colour, and the rule it has to obey

`frontend/src/styles/_tokens.scss:149` already defines `--element-anemo` … `--element-pyro` plus
`--element-none`, and `ElementChip`'s test suite states the constraint plainly: *"Colour is a
second channel, never the only one. A chip carrying the hue alone is invisible to a colourblind
reader and to find-in-page."*

So a strip tile is **element colour + the character's art + the ability's icon**, with the
character and ability names reachable as text. That is three channels, and it is also simply
more legible — seven Genshin element hues include two blues and two greens.

### 4.3 The strip earns its place by showing the swaps

gcsim's config text does not show swaps: `DESIGN_rotation.md` §3.3 established that the compiler
emits none, because naming a different character's action swaps to them implicitly. A strip
grouped into **runs of the same character** makes every implied swap visible as a boundary —
derived from the step list, free, and something neither the current list nor gcsim's text shows.

Given `swap_delay` is the exact mechanism that made every multi-character rotation in this repo
unrunnable until it was found (`CLAUDE.md`, `tests/unit/test_swap_delay_is_never_zero.py`),
a surface that draws swaps where they actually happen is worth more than it looks.

### 4.4 One decision the strip forces: what `repeat` looks like

A step with `repeat: 3` is one step and three actions. The strip can draw three tiles or one
tile with a `×3` badge.

**Recommend one tile with a badge**: it matches the model (one step), matches what compiles
(`attack:3` is one gcsim token), keeps drag semantics simple (dragging a tile moves the step,
not one of its repetitions), and keeps a 20-repeat step from swamping the strip. The rotations
list already says *"8 steps · 11 actions"*, which is the same distinction made in words.

---

## 5. Drag: what exists, and what a palette drag adds

#184 built B.4. `rotations.ts` carries `dragging` as a signal, `reorder(from, to)` as the general
move with `move(index, ±1)` as its special case, and a test pinning that the two agree. The
arrows stayed deliberately: *"a drag has no keyboard equivalent, and this list has to be
reorderable both ways."*

Dragging an ability button **onto** the strip is a different operation on the same list:

| | existing (B.4) | proposed |
|---|---|---|
| source | a step already in the list | a roster/ability button |
| semantic | **move** — remove from `from`, insert at `to` | **insert** — construct a step, splice at `to` |
| keyboard equivalent | the ↑/↓ arrows | **none today** — `quickAdd()` appends only |

So the honest cost of "drag moves onto the rotation" is *two* pieces: the drop target, and an
insert-at-position that a keyboard can reach. The second is the one that gets forgotten, and
this repo has already been bitten once by shipping a control with no accessible name (#131).
`duplicateStep()` already inserts in place, so the splice exists; what is missing is a way to
say "add Nahida's skill *here*" without a mouse.

---

## 6. Proposals, costed

None of these changes the model. G.6 does, and is listed separately for that reason.

| # | proposal | cost | risk |
|---|---|---|---|
| **G.1** | Vendor the 256 skill/burst sprites via `scripts/download_icons.py` | ~1.01 MB, +3% on the icon tree; the script already walks tables and reports 404s honestly | none — `ABSENT_UPSTREAM` already handles a genuinely missing sprite |
| **G.2** | Publish `talents.icon` on `/rotations/options` beside `abilities` | one nullable field on `RosterCharacter`; contract regen | none — exactly the precedent `icon` set, and for the same stated reason |
| **G.3** | The sequence strip (§4): element colour, character art, ability icon, grouped by run, `×n` badge | a component over `steps()`, no new data | it must not grow a time axis (§4.1) |
| **G.4** | Drag an ability button onto the strip to insert at a position | a second drop semantic **plus** a keyboard insert (§5) | the keyboard half is the one that gets dropped |
| **G.5** | Draw glyphs for the seven actions with no sprite | seven marks, `shared/` | must not borrow the attack sprite (§1.4) |
| **G.6** | **Tap/hold** | schema + migration + compiler + validator, and a gcsim-derived table of which 47 characters read it | **reopens `DESIGN_rotation.md` §2.** Owner's decision, not this document's |

G.1–G.3 are independent of each other and of any open question. G.4 depends on G.3 having a
strip to drop onto. G.5 is independent. **G.6 is blocked on the owner.**

---

## 7. Open questions for the owner

| | question |
|---|---|
| **OQ-G1** | **Tap/hold.** §2 shows it is a grammar change, not a surface one — the model has no per-action parameters and `DESIGN_rotation.md` §2 is why. Build it (scoped to `skill`, offered only for the 47 characters gcsim reads it for), or keep the model parameterless and let the compiler's default stand? |
| **OQ-G2** | **Does the strip replace the step list, or sit above it?** The list holds four editable fields per step (character, action, repeat, note) and the strip can carry at most a tile and a badge. Two views of one list is more code and more to keep in sync; one view means losing an editing affordance. Recommend: strip above, list below, selection shared — but this is a taste call about a screen the owner will use. |
| **OQ-G3** | **Charged attack and the plunges.** They keep their keys today because naming them after the normal-attack talent would be wrong (§1.4). Is a drawn glyph plus the bare word `charge` acceptable, or do they want KQM's own shorthand (`N1C`, plunge) on the face of the button? |

---

## 8. Not proposed, and why

- ~~**A time axis with tiles sized by animation length.**~~ **Withdrawn the same day** — see
  the note at the head of §4. The gates were given as a reason against it and are the strongest
  reason for it: a step skipped because its gate was closed is invisible in the list and visible
  on a measured timeline.
- **Per-variant ult buttons for Varesa, Flins and their kin.** §3. gcsim selects the form from
  its own state; a config cannot ask for one, and there is no second sprite to draw.
- **Reusing the normal-attack sprite for charged attack, aim or the plunges.** §1.4. Wrong
  beats missing here, and `gcsim_keys` already made this exact call for names.
- **Constructing icon basenames client-side from the character key.** §1.3. `Skill_E_Ayaka` and
  `Skill_E_Varesa_01` disagree about the suffix and no rule predicts which.
- **A drag-only interface.** The arrows stayed in #184 for a reason and the same reason applies
  to insertion (§5).

---

## 9. The check none of this substitutes for

Every finding in `CLAUDE.md`'s "found by building, not by reading" paragraph was visible on
screen and invisible to a green suite — a `<select>` that always showed its first option, an
ability lookup that was live and doing nothing, a query-count test that counted zero. A strip
made of coloured tiles is exactly the kind of thing that renders plausibly while being wrong
about which character is which.

**Whatever ships here gets looked at in a browser before it is called done**, and the strip's
first check is the cheapest one available: open a rotation whose steps are not all the same
character, and read the tiles against the gcsim preview already sitting beside them.

---

## Sources

- `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt:48` — `skill[hold=1]` in a real config
- gcsim at the pin: `internal/characters/varesa/burst.go`, `internal/characters/flins/burst.go`,
  `pkg/core/action/action.go`
- The seeded database (nanoka GI 7.0.51) for every count in §1
- `https://static.nanoka.cc/assets/gi/` for the icon HTTP statuses and sizes in §1.2–1.3
- [KQM guides](https://keqingmains.com/) for the `tE`/`hE`/`N1C` notation
- [Genshin Impact Wiki — Elemental Skill](https://genshin-impact.fandom.com/wiki/Elemental_Skill)
  on tap vs hold as a game mechanic
