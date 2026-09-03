# DESIGN — what an account remembers: ownership, saved runs, and the teapot

**Status:** design, 2026-09-03. Nothing built. **Queued behind
`TASKS_rotation_language.md`** by the owner's own sequencing — *"add to the backlog after the
rotation logic"*, and the teapot tracker after both.

## Branch policy

`feat/account-tracking`, off `dev`. **No direct commits to `dev` or `main`.** Three tracks,
each its own sub-branch merged into it by PR: `feat/build-ownership`,
`feat/saved-optimizations`, `feat/teapot-tracker`. Task 0 of `TASKS_account_tracking.md` is
the branch-setup gate.

**Track 3 depends on Track 1** — the teapot tracker is *"backed by the 'owned' flag on user's
builds"* — so it cannot start first even though it is the most visible.

## The asks, verbatim

> *"Builds should have a 'owned' boolean, users can choose it when building one manually but
> when imported they default to owned=True. They can change that in the build page if wanted.
> This way we know which units they actually have on their account and which they've just made
> to test. Right now it doesn't connect to anything, but may be useful for future features I
> have planned."*

> *"Users should also be able to save their optimization runs and see a list of previous runs
> when first going to the optimization page. These should be sharable, like the gcsim database
> sharing results. The rotations are what goes in our rotation database when people publish,
> but these sharable optimization results let others see their results. It also means we no
> longer need to cache optimizations at all, since they're stored anyways. This should have
> logical filters. Anything else you think we should be storing to make it easier to use is
> also beneficial."*

> *"a teapot set tracker, backed by the 'owned' flag on user's builds, like seelie.me's teapot
> set calculator. This one should be sortable by remaining primogems and lets users mark off
> which they've already done like Seelie does."*

---

## Track 1 — `builds.owned`

A boolean on `builds`, default **`True`**, editable on the build page.

**Why the default is `True` rather than `False`.** The owner's rule is that an *import*
defaults to owned, and an import is how almost every build arrives — a GOOD export is a record
of gear the player actually has. Defaulting the column to `True` makes the migration a no-op
for existing rows, which are all real builds. A manually created build offers the choice at
creation, and the form's default is the honest one for the commoner case.

**It connects to nothing on purpose** (owner: *"Right now it doesn't connect to anything"*),
with one exception once Track 3 lands: the teapot tracker reads it to decide which characters
a user actually has.

**The asymmetry worth naming**: weapons already record ownership — `owned_weapons` is a table
of a user's actual weapons — and artifacts are inherently owned, since they arrive from a GOOD
export. **Characters are the only entity with no ownership record**, and `builds` is where one
belongs because a build is the only per-character row a user has.

---

## Track 2 — saved, shareable optimization runs

### The correction this design has to make first

> *"It also means we no longer need to cache optimizations at all, since they're stored
> anyways."*

**These are two different things, and dropping the cache would make every search slower.**

`recipe-cache.ts` stores **calibrated recipes** — the intermediate gcsim runs a search needs
*before* it can score anything. `RESEARCH_calibration_cache.md` measured one at **~3.2 s per
4-piece set**, 30–70 KB, keyed by build, rotation, set, ER, seed and gcsim pin. A saved
optimization *result* is an outcome: the winning five artifacts and their score.

So storing results makes **re-opening a past run** free, which is exactly what the owner wants.
It does not make a **new** search cheap: a new search on the same build still has to calibrate,
and without the cache it pays 3.2 s × every set considered, every time.

### The better version of the idea, which the schema is already most of the way to

`sim_runs` **already exists and is already server-side**, keyed by `context_key`, `er_bucket`,
`gcsim_pin` and `rotation_signature` — that is a calibration cache in everything but name, and
#183 already made searches write to it. Promoting it to a *read* path gives the owner what
they asked for and more:

- **cross-device** — the same user's calibrations follow them, which the client-side cache
  cannot do;
- **cross-user** — two people with the same character, weapon, talents, rotation and gcsim pin
  produce the *same* calibration, and `context_key` already says so;
- and it makes the client-side cache an **optimisation rather than a correctness requirement**,
  which is the state in which it can safely be deleted later.

**Recommendation: keep `recipe-cache.ts`, add a server read path over `sim_runs`, and revisit
deleting the client cache once the server one is measured.** Deleting it first would be a
regression nobody would attribute to this change.

### What a saved run stores

**A snapshot, not a set of foreign keys.** This is the same lesson the recipe cache key
teaches: a build changes, and a shared result that silently re-read today's gear would show a
number that no longer matches what was run.

| stored | why |
|---|---|
| the objective — sets searched, weapons compared, energy model, enemy profile | without it a shared result cannot be interpreted, let alone reproduced |
| the winning artifacts, **by id and by their substats at the time** | ids alone break the moment a piece is levelled |
| the build snapshot — character, weapon, refinement, talents, constellation | the same reason |
| `rotation_id` **and** `rotation_signature` | the signature is what makes two runs comparable; the id is what makes the rotation findable |
| `gcsim_pin` | a different simulator is a different result, and this is the one that would otherwise go unnoticed for months |
| iterations and wall-clock | a shared result should say how much compute backs it |
| the score, and the runner-up margin | *"it won by 0.3 %"* and *"it won by 12 %"* are different claims |

### Sharing

Modelled on the **rotation library**, which already solves this exact problem here: a
`visibility` enum, a share key, a likes table and a list endpoint with filters. Reusing that
shape rather than inventing a second one is the point — *"The rotations are what goes in our
rotation database when people publish, but these sharable optimization results let others see
their results."*

**Filters** the list needs, taken from what a reader would actually ask: character, team,
element, artifact set, weapon, energy model, date, and "mine only". Sorting by score is
meaningless across characters, so the default order is recency.

---

## Track 3 — the teapot set tracker

**The data exists and is already in this repo's own source**, which is the finding that makes
this tractable. Probed against nanoka 7.0.51 on 2026-09-03:

| | |
|---|---|
| `https://static.nanoka.cc/gi/7.0.51/furniture.json` | **2,381 furnishings** — name in four languages, `type`, `rank`, `icon`, and a `recipe` of material ids and counts |
| `https://static.nanoka.cc/gi/7.0.51/suite.json` | **109 furnishing sets** — `units` (the constituent furnishings and their counts), `type` (indoor/outdoor), `icon`, and **`favorite`** |
| `favorite` | **79 of 109 suites** name the characters who favour them, by **nanoka character id** — the same id `characters.nanoka_id` already holds. **116 distinct characters.** |

**And the sets have art.** All **109 of 109** suites carry an `icon`, served from the same CDN
`scripts/download_icons.py` already vendors from —
`https://static.nanoka.cc/assets/gi/UI_Home_Suite_Camp_01.webp` answers **200 `image/webp`,
~58 KB**. Sampled and checked on `content-type`, not on the status code: prod once served no
art for months while every request answered `200 text/html` through nginx's SPA fallback, and
a status code could not have told the difference. At ~50–60 KB each, 109 suites is roughly
**6 MB** against the 9.6 MB of character and weapon art already committed, so `DECISIONS.md`
§4's reasoning — commit it, because a repository that is a third the weight of the one fairy
ships is not a CDN problem — applies unchanged.

So the join the tracker needs — *which sets does this user's owned roster unlock* — is
`suite.favorite` against `builds` filtered by `owned`. No new identifier scheme, no scraping.

**What is not in the data, and must be cited before it is written.** The primogem reward for
inviting a favoured character to their set is a game constant, and **this repo does not write
game values from memory** (CLAUDE.md, and fairy's hardest-won lesson). It has to come from a
citable source before any "remaining primogems" number is displayed — that sort is the
owner's stated headline feature, so a fabricated constant would be wrong in the most visible
place on the page.

**Progress is per user and per suite**, which is one small table: `(user, suite, done_at)`.
Seelie's affordance is exactly this — mark it off, and it leaves the list.

**Sorting by remaining primogems** is therefore `reward × (characters who favour it and are
owned and not yet marked done)`, descending. That is the whole product, and it is why Track 1
comes first.

### Scope note

A full teapot calculator would also track **materials** — `furniture.recipe` gives the
ingredients, and a real calculator tells you what you are short of. That is a second feature
with its own data (a user's material inventory, which this app does not have and GOOD does not
export). **Out of scope here**; the tracker answers *which sets are worth doing next*, not
*can I afford them*.

---

## What else is worth storing

The owner asked. Ranked by what they would actually save someone:

1. **Artifact `locked`.** GOOD exports carry a `lock` flag and this schema drops it. It is the
   user's own statement that a piece is not to be fed away, and an optimizer that suggests a
   build around a piece they have locked for another character is giving advice they cannot
   take. Cheap: one column, read on import.
2. **A build's own name.** `builds` has `notes` and `optimizer_priority` but no name, so two
   builds for the same character are told apart by their gear. `BACKLOG_frontend.md` §3
   already wants one build per character *and* a priority; a name is the smaller half of that.
3. **When gear was last imported.** A GOOD import replaces an inventory wholesale; knowing
   when tells a user whether a saved result predates their last farming session, which is the
   single most common reason a stored number stops being true.
4. **Team `notes`.** Teams have no free text at all, and the reason a team exists — *"Furina
   for the Skirk melt test"* — is exactly what a user forgets.

---

## OQ-A3, answered: why the local recipe cache stays

Owner: *"Test if we can safely remove the cache, but I think we can since users can go back to
old runs now."*

**Going back to old runs is real, and it is a different cost.** Re-opening a saved result is
now free. What the local cache pays for is *running a new search on the same build*, and the
corpus cannot take that over — not because it is slower, but because **its key cannot describe
the thing**:

| | keyed by | can serve |
|---|---|---|
| `recipe-cache.ts` | build, rotation, **4-piece set**, ER, seed, probe, pin | every calibration target |
| `sim_runs` | character, weapon, team, rotation, target, pin — **not artifacts** | the set-free baseline only |

A search calibrates **one target per chosen 4-piece set**, plus the set-free baseline, plus a
2+2 pair if picked (`calibrationTargets`). The corpus is written and read for the baseline
alone — `wantsAggregate = target.artifactSetIds.length === 0` — because a run keyed without
artifacts cannot describe a set-specific recipe.

So a four-set search has **five targets and the corpus can serve one**. At the measured
**~3.2 s per recipe** (`RESEARCH_calibration_cache.md`), deleting the local cache adds
**~12.8 s to every repeat four-set search**, and ~16 s with a pair.

**What would have to change first** for the answer to flip: `context_key` would have to include
the 4-piece set, which makes it a different cache with a different tenancy story — a
set-specific recipe is far less shareable across users than a set-free aggregate, so most of
the cross-user benefit that justified reading the corpus would go with it.

`frontend/src/app/sim/cache-necessity.spec.ts` pins all of this, so the decision is not
re-argued from memory.

## Open questions

| | |
|---|---|
| **OQ-A1** | Does a saved run store its **artifacts by snapshot or by reference**? Snapshot is argued above, and it costs storage — a run is ~5 pieces × ~10 substats. Reference is cheaper and silently wrong after any upgrade. |
| **OQ-A2** | Is a shared optimization result **public by default**, or private with an explicit publish like a rotation? The rotation library chose explicit; consistency argues for the same. |
| ~~**OQ-A3**~~ | **Answered 2026-09-03: the local cache cannot be removed, and the reason is structural rather than a matter of degree.** See below. |
| **OQ-A4** | Where does the **primogem reward constant** come from? It gates Track 3's headline sort and must be cited, not remembered. |
| **OQ-A5** | Should `owned` also gate the **optimizer's character picker** — offering only characters the user has? The owner said it connects to nothing for now, so this is deliberately not assumed. |
