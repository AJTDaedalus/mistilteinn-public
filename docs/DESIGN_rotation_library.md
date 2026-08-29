# DESIGN: importing gcsim rotations, and a searchable library

**Status: proposed, nothing built.** Owner request (2026-08-29): *"a way to import gcsim
rotations into mistilteinn if desired, and build a rotation database similar to gcsim that
users can search or find matches for their teams if they don't want to build their own. A
'like' function to flag if a rotation was useful would also be nice."*

**Branch policy.** Work happens on `feat/rotation-library`, never on `dev` or `main`; `dev` is
updated only by PR. Sub-branches per track if the import and the library are built in
parallel. Task 0 of the TASKS file is the branch-setup gate.

---

## 1. The constraint that shapes everything

**A mistilteinn rotation is a list of `(character, action, repeat, note)`.** Ten actions are
authorable — `skill`, `burst`, `attack`, `charge`, `high_plunge`, `low_plunge`, `aim`, `dash`,
`jump`, `walk` — derived by subtraction from gcsim's own list. Three are deliberately excluded:

| excluded | why |
|---|---|
| `swap` | implicit; gcsim inserts one when the next character is not active |
| `wait`, `delay` | timing controls this model does not expose |

**gcsim's language is much larger than that.** A community config can carry conditional
expressions (`if .noelle.energy > 40`), loops other than `while 1`, `wait` for alignment,
target and energy settings, per-character `hitlag`, and more.

So **an arbitrary gcsim rotation cannot round-trip into this model**, and the interesting
design question is not "how do we parse gcsim" but *what happens to the parts we cannot
express*.

### The one thing that does round-trip

Configs **mistilteinn itself emitted** are a regular subset: `while 1 { if .c.a.ready { c a:n; } … }`,
one gate per step, no waits, no conditionals beyond `.ready`. Those parse back exactly. The
sample fixture `noelle_redhorn.txt` is this shape, and so is everything `compile_rotation`
produces.

That gives a natural two-tier import:

| tier | source | outcome |
|---|---|---|
| **1** | a config this app emitted | exact round-trip |
| **2** | anything else | parse the steps that map; **refuse the rotation if any step does not** |

**Tier 2 must refuse, not degrade.** Silently dropping an `if .energy > 40` guard or a `wait`
changes what the rotation *does* while leaving something that looks like it — the same failure
`unmodelled_passives` and `isExact` exist to prevent. A rotation whose conditionals were
discarded would simulate to a different number than the one its author published, and the
user would have no way to know.

**Open question OQ-1:** is a lossy import worth offering *at all* behind an explicit "this
dropped 4 conditional guards" report, or is refuse-and-explain the whole feature? Refusing is
the safer default and the one this document assumes.

## 2. What "a rotation database" means here

Two features wear one name, and they have different risks.

**(a) Rotations shared between users of this instance.** A `rotations.visibility` column, a
browse page, and a copy-to-my-rotations action. Contained, and the data model barely moves.

**(b) A corpus imported from gcsim's own database.** That is somebody else's content,
published under their terms, changing without notice. It needs a provenance story exactly like
`app/data/yuanshen/` has — where each rotation came from, when, and under what licence — and
this repo's standing rule is **committed snapshots, never a live fetch at runtime**.

**These should not be built together.** (a) is a product feature; (b) is a data-sourcing
decision with a licensing question attached, and it is the one that needs an owner ruling
before any code.

**Open question OQ-2:** is (b) in scope, and if so under what provenance? gcsim's rotations
are user-submitted; mirroring them is not obviously ours to do.

## 3. "Find matches for their teams"

The useful primitive, and the cheapest one: **given a team, which shared rotations name exactly
these characters?**

A rotation already stores steps by `nanoka_id`, so the character set is derivable without any
new column — but derivable is not queryable. A `rotation_characters` join table (or a sorted
array column with a GIN index) makes "rotations for this team" one query.

Ranking is the interesting part, and the honest options are:

| ranking | what it claims |
|---|---|
| exact character-set match | nothing; a filter |
| likes | that people found it useful |
| simulated DPS on *the searcher's own builds* | that it performs — and costs a gcsim run per candidate |

The third is the one users will actually want and the one that cannot be precomputed: DPS
depends on the searcher's artifacts, not the author's. `docs/RESEARCH_recipe_cost.md` measured
**7.84 s** for a 100-iteration 90-second rotation in the browser, so ranking twenty candidates
is minutes. That is a job with progress, not a search box — the same conclusion the optimizer
reached.

**Recommendation: ship the filter and the likes; leave DPS ranking as an explicit per-rotation
"try this on my team" action** rather than something a search does to twenty rotations
speculatively.

## 4. Likes

A `rotation_likes(rotation_id, user_id, created_at)` table with a unique constraint on the
pair — a count column alone cannot tell whether *this* user has already liked, and cannot be
un-liked without going negative on a race.

Deliberately **not** a rating: a five-star scale invites a judgement nobody has the evidence
to make ("is this a 3 or a 4 for my roster?"), and the question the owner actually asked is
binary — *was this useful*.

**Open question OQ-3:** are likes visible per-user (who liked it) or only as a count? A count
is less to build and less to regret.

## 5. What this does not change

**Rotations are authored, never optimized** (owner decision, 2026-08-25, `DECISIONS.md`). A
library does not touch that: a shared rotation is still one a person wrote — just not
necessarily *this* person. Nothing here searches for a rotation by generating one.

## 6. Suggested order

1. **Import tier 1** — round-trip our own configs. Small, fully testable, no new tables.
2. **Sharing + browse + character-set filter** — one column, one join table, one page.
3. **Likes** — one table.
4. **Import tier 2** — parse-or-refuse for foreign configs. Largest, and the one whose value
   depends on OQ-1.
5. **gcsim corpus** — only if OQ-2 is answered yes.

## Open questions for the owner

- **OQ-1** Refuse a gcsim config we cannot fully express, or import it with a loss report?
- **OQ-2** Is mirroring gcsim's rotation database in scope, and under what provenance?
- **OQ-3** Likes as a bare count, or attributed?
- **OQ-4** Is sharing instance-wide, or does a rotation need explicit publishing? (This
  document assumes explicit — a private rotation becoming visible by default is not a mistake
  that can be taken back.)
