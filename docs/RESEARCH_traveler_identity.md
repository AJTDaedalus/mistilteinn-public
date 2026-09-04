# The Traveler is sixteen characters, and nothing tells them apart

**Status:** **A, B and C are built** (see the closing section); **D is not, and needs a ruling.**
Findings first, 2026-09-04, from the owner's report
*"character ownership is really messy for traveler"*.

Everything below was re-derived against the seeded database and the owner's own account
(`screenshots@example.com`), not read off a docstring.

## 0. The count in `CLAUDE.md` is wrong

It says **28 Traveler variants** in four places (`CLAUDE.md`, `schemas/catalogue.py:136,148`,
`api/v1/catalogue.py:92`, `good_build_service.py:33,174`). At nanoka 7.0.51 the catalogue holds
**sixteen**:

```
10000005-2 … -8   seven elements   icon UI_AvatarIcon_PlayerBoy    (Aether)
10000007-2 … -8   seven elements   icon UI_AvatarIcon_PlayerGirl   (Lumine)
10000134          element NULL     icon UI_AvatarIcon_PlayerBoy    WEAPON_CROSSBOW, 0 talents
10000135          element NULL     icon UI_AvatarIcon_PlayerGirl   WEAPON_CROSSBOW, 0 talents
```

Re-derive: `select nanoka_id, name, element, icon from characters where name = 'Traveler'`.
28 is presumably 14 × 2 counted twice, or a memory of `10000117`/`10000118` (the mannequins)
being included. It matters here only because every claim about Traveler resolution in this repo
is written against a number that is not the one in the table.

## 1. All sixteen rows are *named* `Traveler`

`characters.name` is `'Traveler'` for all sixteen. There is no gender column, no title, no
disambiguating field. Upstream gives us nothing either — nanoka's index has one `en` value
(`"Traveler"`) and one `desc` for every variant. **The only signal for Aether vs Lumine
anywhere in the tree is the icon basename**, `UI_AvatarIcon_PlayerBoy` / `PlayerGirl`.

Every consequence below follows from that one fact.

## 2. The roster tab draws sixteen rows that a user cannot tell apart

`builds.html:126-155` renders each roster row as **name + element chip + a checkbox**. So:

* **Aether Pyro and Lumine Pyro are the same row twice** — same name, same chip, differing only
  in a 72px face. Seven such pairs.
* **`10000134` and `10000135` are literally identical**: name `Traveler`, `element` NULL so
  `element-chip` draws nothing, and two faces that are the only difference on the row.
* The checkbox's own accessible label is `"I have " + entry.name` — **sixteen controls all
  announcing "I have Traveler"** to a screen reader.

The tab exists precisely so a user can correct ownership by hand. They cannot correct what they
cannot identify.

## 3. Ownership is modelled per elemental variant, and the game does not work that way

`character_roster` is keyed `(owner_id, character_id)` and `character_id` is one of the sixteen.
So the schema asks sixteen questions where the game has **one and a half**:

* which Traveler you picked at the start — Aether **or** Lumine, never both, never changed;
* which elements you have unlocked, which is a property of story progress, not of ownership.

"Do you have the Anemo Traveler but not the Geo Traveler" is not a question about ownership. And
the two answers a user actually has — *my Traveler is Lumine* and *I have unlocked Dendro* —
cannot be expressed at all.

## 4. The import picks a gender by arbitrary tiebreak, and never says which

GOOD carries no gender. `good_build_service._pick` takes the **lowest `nanoka_id`**, which is
always `10000005-*` — **always Aether**. The docstring is honest about it being arbitrary, and
the *build* gets a note (`"Traveler gender is not in a GOOD export; the first was used"`).

The **roster row gets no such note.** `rebuild_builds` runs the same `_resolve` + `_pick` for
ownership (`good_build_service.py:236-251`) and writes an `import` row against the Aether
variant. A Lumine player's roster therefore says they have Aether and do not have Lumine, with
nothing on the row explaining why, and the two rows are indistinguishable anyway (§2). Their
only recourse is to tick one of two identical checkboxes and hope.

## 5. Measured on the owner's account: one Traveler row, and it is the unsimulatable one

```
character_roster: 93 rows, of which 1 is a Traveler
  10000005-5  Traveler (Cryo)  owned=true  source=import
builds:        1 Traveler build, notes "…gender is not in a GOOD export; the first was used"
```

The export (`references/genshin_export_2026-08-28_11-07.json`) lists exactly one Traveler entry,
`TravelerCryo`, so this is faithful to the file. But:

```python
character_key("10000005-5", "Traveler", "Cryo")
# GcsimKeyError: gcsim has no 'aethercryo' … there is no Cryo Traveler.
```

**gcsim implements six Traveler elements, not seven** (`gcsim_keys.py:40`). The one Traveler
this account owns and has a build for is the one element that cannot be compiled, optimized, or
simulated. That is not a new bug — `character_key` refuses loudly and correctly — but it is the
end of the chain: the roster says you have them, the builds tab offers to build them, and the
optimizer cannot run them. Nothing upstream of `character_key` warns.

## 6. Two unreleased bodies are ownable

`10000134` / `10000135` have **no talents seeded**, no element, and a `WEAPON_CROSSBOW` type
that `weapon_symbols` already documents as having no mark to draw. `PATCH /roster/{id}` refuses
mannequins by nanoka-id prefix and accepts these — so the roster offers a user two blank rows
they can claim to own, which then appear in `unbuilt()` as buildable placeholders.

The mannequin exclusion is the precedent: a catalogue row that is not a playable character is
excluded **by id, loudly, with a test that fails if the id stops meaning what it means**
(`test_roster_excludes_only_the_mannequins.py`). These two want the same treatment, but the
rule is different — they are not mannequins, they are *unreleased*, and `characters` already
carries `release_date`.

## 7. What the pieces agree on, and where they diverge

| surface | how it names a Traveler | picks gender |
|---|---|---|
| `characters.name` | `Traveler` ×16 | — |
| roster tab | `Traveler` + element chip | — |
| GOOD `characters[]` | `TravelerCryo` | no |
| GOOD `artifacts[].location` | `Traveler` | no |
| `good_build_service._pick` | — | lowest id → **Aether** |
| `good_weapon_service` | defers to the build importer (`:65`) | — |
| `gcsim_keys._traveler_key` | `aetherpyro` / `luminepyro` | reads `nanoka_id` |

`gcsim_keys` is the only module in the tree that models a Traveler *correctly* — body from the
id, element from the column, and a refusal by name for the element gcsim lacks. It is the shape
the rest should follow.

---

# Suggested solutions

Four, roughly independent, cheapest first. **(A) is worth doing whatever else is decided** — it
is the one that makes the bug visible instead of confusing.

## A. Give every Traveler a display name — small, no schema change

Derive a name at the read boundary rather than storing one, the way `element_symbols` and
`weapon_symbols` already derive presentation from catalogue data:

```python
# app/services/traveler.py
TRAVELER_BODIES = {"UI_AvatarIcon_PlayerBoy": "Aether", "UI_AvatarIcon_PlayerGirl": "Lumine"}

def display_name(*, name, icon, element) -> str:
    """"Traveler" → "Traveler (Lumine · Dendro)". Every other character is returned as-is."""
```

* keyed on **icon**, because that is the only signal that exists (§1), with a test asserting
  both basenames are present in the seeded catalogue so a nanoka bump that renames them fails
  loudly rather than silently collapsing sixteen names back to one;
* applied in `RosterEntryRead`, the catalogue schema, and every character picker — one helper,
  per DESIGN §1 A6's "one implementation everything reuses";
* fixes the aria-label for free.
* the two crossbow bodies become `Traveler (Aether)` / `Traveler (Lumine)` with no element,
  which is still honest and still distinguishable.

Cost: one module, one test, a handful of call sites. This alone turns §2 from "unusable" into
"odd but workable".

## B. Exclude unreleased characters from the roster — small, matches an existing precedent

Extend the mannequin rule in `services/roster.py` to a second, separately-named predicate keyed
on `release_date` (or on "zero seeded talents", which is the observable property that actually
makes them unbuildable). Refuse them in `PATCH /roster/{id}` by name, exactly as mannequins are.

Do **not** fold this into `is_mannequin` — they are excluded for a different reason, and a test
that says "these fourteen rows are the mannequins" should keep saying that.

## C. Warn where a build cannot be simulated — small, and it is the §5 gap

`character_key` already refuses correctly. Nothing above it asks before offering the build. A
`simulatable: bool` (plus reason) on the character/roster read, computed by calling
`character_key` in a try/except, would let the builds tab and the optimizer say *"gcsim has no
Cryo Traveler"* on the card instead of at the end of a seven-minute search. Six of the sixteen
Traveler rows and every post-pin character benefit.

## D. Model the Traveler as one character with an element choice — the real fix, and a chunk

The honest model matches the game: **one Traveler per account**, with a body (Aether/Lumine) and
a set of unlocked elements; a *build* names the element.

That is a schema change and it collides with an already-recorded open decision —
`good_build_service`'s module docstring says the owner's preferred model is a build per element
*sharing one artifact set*, which `artifacts.build_id` being single-valued makes impossible
today, and which is already logged in `DECISIONS.md` as its own chunk. **These are the same
chunk**, and doing (D) without it would mean touching Traveler ownership twice.

A cheap 80% of (D) that needs no schema change: make the roster tab **group the sixteen rows
into one card** — a body toggle (Aether/Lumine) and seven element checkboxes — and have it write
the sixteen underlying rows. The storage stays per-variant; the *question asked of the user*
becomes the one the game asks. Ticking Lumine would clear the Aether rows, which also gives the
import's arbitrary pick (§4) a one-click correction.

## Not recommended

**Making the import guess a gender.** There is nothing to guess from — GOOD carries no gender in
any field, and neither does the artifact `location`. The current arbitrary-but-deterministic
pick is right; what is missing is a way for the user to *see* and *change* it, which is (A)+(D).


---

# What was built

On `feat/traveler-identity`. **A, B and C. Not D.**

## A — every Traveler has a name of its own

`app/services/traveler.py` derives one from the icon, because the icon is the only signal that
exists (§1). It is a `computed_field` on `CharacterSummary` beside `element_icon` and `stars`,
and a field on `RosterEntryRead`, so it reaches every surface at once rather than page by page.

```
Traveler + PlayerGirl + Dendro  →  "Traveler (Lumine · Dendro)"
Traveler + PlayerBoy  + None    →  "Traveler (Aether)"
Nahida                          →  "Nahida"
```

The element is **inside** the parentheses: `Traveler (Lumine) · Dendro` reads as a Lumine card
that happens to be Dendro, `Traveler (Lumine · Dendro)` reads as the character the player has.

`name` is untouched — it is what the catalogue says, and a client grouping by character rather
than by variant still needs it. The frontend renders `display_name` on the roster tab, the build
cards, the unbuilt placeholders, the shared character grid, and every `aria-label` that used to
say *"I have Traveler"* sixteen times.

**Guarded where it can break.** The naming rests on two icon basenames, so
`test_traveler.py` reads the committed nanoka capture and asserts sixteen rows named `Traveler`
carrying exactly those two icons, and that nobody else carries them. It cannot pass by being
skipped. The failure it exists to catch is quiet and one-directional: an upstream rename returns
every Traveler to the bare name and restores the exact tab this was written to fix, with nothing
on screen to say so.

The property test is the one that matters — **sixteen variants, sixteen distinct names** —
rather than four spellings checked one at a time.

## B — the two unreleased bodies are withheld, and counted

`is_unreleased(element, talent_count)` is a **conjunction, and the conjunction is the safety.**

"No talents" is the property that matters — such a character cannot be built, damaged-calculated
or compiled — but on its own it is the quiet failure this repo keeps warning about. Element is
read from the *index* row and talents from the *detail* fetch, so a seed whose detail pass failed
leaves real characters talentless, and a roster that dropped them would look exactly like
success. Four existing roster tests failed on the first draft of this rule, which is how the
narrower one got written.

It is kept separate from `is_mannequin` on purpose: both mean "cannot be owned", for different
reasons, and folding them together would make the mannequin test stop asserting what it says.

`RosterRead.withheld` publishes the count, because withholding is the one thing this endpoint
does that a user cannot see. Two at nanoka 7.0.51; anything else is a seed to look at.

`PATCH` refuses them **by name**, with their own message — *"cannot be owned"* and *"is not in
the game yet"* are different facts.

## C — a row says when gcsim cannot run it

`RosterEntryRead.simulatable` and `unsimulatable_reason`, computed by calling `character_key` in
a `try/except` and publishing **gcsim's own refusal text** rather than a sentence composed here.
The roster row draws a quiet `no gcsim` caveat with the reason on hover.

This is §5's gap closed: the owner's only Traveler is Cryo, `character_key` has always refused
it correctly, and nothing above it asked before the roster offered the row and the builds tab
offered to build it. Six of the sixteen Traveler rows benefit, and so does every character
released after the pin.

Both routes now build a row through one `_entry` helper. They did not, and that is the drift
that puts a field on one route and not the other.

## Also fixed on the way

The roster is ordered by `display_name` rather than `name`. Sixteen rows sharing one `name` have
no order among themselves, so the Travelers appeared in whatever order the database returned and
could shuffle between requests.

---

# Still open: D, and it needs a ruling

**The model is still wrong and this PR does not fix it.** The game has one Traveler per account,
of one body, with elements unlocked by story progress. This catalogue has sixteen characters and
the roster asks sixteen ownership questions, so a Lumine player still gets Aether rows written by
the import (§4) and can still say they "have" the Anemo Traveler but not the Geo one.

Naming them makes that legible. It does not make it right, and the research above is careful not
to claim otherwise.

**Why it is not in here:** (D) is a schema change entangled with an already-recorded decision —
`good_build_service`'s docstring and `DECISIONS.md` carry the owner's preferred model of a build
per element *sharing one artifact set*, which `artifacts.build_id` being single-valued makes
impossible today. They are the same chunk, and doing (D) separately means touching Traveler
ownership twice.

**The cheap 80% that needs no schema change**, from §D above and still the recommendation: group
the sixteen roster rows into **one card** — a body toggle and seven element checkboxes — writing
the sixteen rows underneath. Storage unchanged; the question asked of the user becomes the one
the game asks; and ticking Lumine clears the Aether rows, which gives the import's arbitrary pick
a one-click correction it has never had.
