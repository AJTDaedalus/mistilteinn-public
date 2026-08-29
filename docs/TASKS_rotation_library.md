# TASKS: the rotation library

**Status: Tracks A, B and C are built (#177, #178), and L.10 is done — which changed what
Track D is.** The measurement says two of the four configs already import (12 and 16 steps) and
the other two are blocked by a *user-defined function*, which `DESIGN_rotation_library.md` §6
already rules should stay refused. So L.11 has nothing left to rewrite and L.12 is the work:
refusing accurately, which #178 corrects. See `LOG_rotation_library.md`. Step 1 of `DESIGN_rotation_library.md` §6 was already done (#141, #155, #156).
Nothing here is blocked on a decision — `DECISIONS.md` §21 answered all four open questions on
2026-08-29.

**Two corrections this file owes its own reader.** L.1 said "a Postgres enum"; the repo's
convention is `enum_column`, a `VARCHAR` with `native_enum=False`, and `app/models/base.py`
argues for it at length. And the DPS ordering L.4 was written around is **not built** — see
*What is not in #177* below.

Read `docs/DESIGN_rotation_library.md` first. It is the authority; this file only decomposes
it. Where the two disagree, the DESIGN wins and this file is wrong.

**Branch policy.** Work happens on `feat/rotation-library`, never on `dev` or `main`; `dev` is
updated only by PR after review. Sub-branches per track if the sharing and the converter are
built in parallel: `feat/rotation-library-sharing`, `feat/rotation-library-converter`. **Task
L.0 is the branch-setup gate** — do it before any other task in this file.

---

## The one design decision this file adds

The DESIGN says ordering is *"DPS where this user has run it, then likes, then anything
else"*, and that `sim_runs` already holds the number. **It does, and it cannot be queried for
it.**

`sim_runs.context_key` is a hash and its docstring is explicit that this is deliberate:
*"storing the parts would invite querying by them and then disagreeing with the hash."* So
there is no way to ask "which runs belong to rotation X".

**The resolution: two nullable columns that are labels, never key material.**

- `sim_runs.rotation_id` — a nullable FK, `ON DELETE SET NULL`. Not part of
  `uq_sim_runs_owner_context_bucket_pin`, not read by any cache lookup, and the docstring must
  say so in those words. It exists so the library can find a user's own runs for a rotation.
- `sim_runs.rotation_signature` — the `rotation_compiler.rotation_signature` list, hashed.

**The signature is the part that stops a real bug.** A rotation is editable. Edit it and
`context_key` changes, so the next run writes a *new* row — and the old row keeps its
`rotation_id` and its DPS. Ordering the library by `rotation_id` alone would sort a rotation
by a number computed for a previous version of itself: a confident figure describing something
the user can no longer see. Matching on the signature as well means **your number appears where
you have one for the rotation as it stands, and nothing where you do not** — which is what the
DESIGN's "unsorted rather than ranked by somebody else's gear" already argues for.

A row whose `rotation_id` is null is a run from before this column existed, or one whose
rotation was deleted. Both are "no DPS to show", which is the honest answer and needs no
backfill.

---

## What is not in #177

**~~The DPS ordering.~~ Built (#179)** — `sim_runs` gains `rotation_id` and
`rotation_signature` as labels that are never key material, the library sorts by your own DPS,
and a run whose signature no longer matches is dropped rather than shown.

**And it cannot produce a number yet**, which is the finding that matters more than the
feature. Two gaps sit under it, and both were found by building this rather than by reading:

1. **Nothing in the frontend writes the run corpus at all — and the intended producer cannot.**
   Escalated as `DECISIONS.md` §25: the design says the corpus *"accumulates from real
   searches"*, and the search calls `sample()` (a per-frame log) where the corpus stores an
   aggregate with `statistics.dps.mean`. Either the search adds a run it does not need, or a
   `sim_run` becomes a different thing. **An owner decision, not an implementation detail.** `POST /api/v1/sim-runs` has zero
   callers in `frontend/src/app`. The endpoint, the repository, the ER bucketing and the
   divergence measurement are all built, tested and CI-gated; no client submits to them. So
   every `your_dps` is `None` in practice, not because the ordering is wrong but because there
   is nothing to order. This is the same shape as `createGpuKernel` having no callers
   (`BACKLOG_frontend.md` §12) and deserves its own chunk: *who submits a run, and from where*.
2. **A copy is a different row.** You cannot run a rotation on a team you do not own, so a
   stranger's published rotation reports `None` **correctly** — you have no run for it. The
   number you earn after copying lands on the copy, not on the original's card. Making it
   appear needs the copy to remember where it came from, which is a column and a decision
   nobody has made.

So §3's ordering is live for **your own** published rotations and silent for everyone else's.
`/rotations/{id}/context-key` now publishes `rotation_signature` so that whoever builds the
producer never has to compute the digest a second way.

**~~L.7's query-count harness.~~ Built, and it found an N+1 in the listing on its first honest
run.** `tests/integration/test_rotation_library_query_count.py`.

L.7 said *"'constant' asserted by reading the code is not asserted at all"*, and that turned
out to be exactly right twice over:

1. **The first version passed while counting nothing.** It listened on `app.database.engine`;
   `conftest` builds its own `test_engine`, so it compared zero with zero. `python -m
   scripts.inject` put a real N+1 into the handler and watched the test not notice — the
   mutation harness doing precisely the job it exists for, on a test written to prove
   something.
2. **Once it counted, it failed on real code.** `_your_dps` called `character_rows` in a loop
   over the page — 19 queries for 2 rotations, 41 for 8. `rosters_for` batches it, and both
   mutations are caught now.

The listing costs **14** queries, most of them per-*request* rather than per-listing: the
bearer token, the session lookup and its touch, the user row. The ceiling test allows 16 and
says why; the load-bearing test does not care what the constant is, only that it stays one.

## L.0 — the branch

Create `feat/rotation-library` off `dev`. Nothing else.

**Acceptance:** `git branch --show-current` says `feat/rotation-library`; `dev` is untouched.

---

## Track A — sharing (DESIGN §2a, §6 step 2)

### L.1 — `rotations.visibility`, private by default

One column: `visibility` as a Postgres enum `('private', 'published')`, `NOT NULL DEFAULT
'private'`.

**OQ-4's whole point is the default.** Every rotation already saved becomes `private`, which
is what an existing user expects; a migration defaulting to `published` would retroactively
publish work nobody offered. Say that in the migration's docstring, because a later reader
tidying "an obvious default" is exactly how it would be reversed.

- Files: `app/models/rotation.py`, `app/models/enums.py`, a new Alembic revision.
- **Generate the revision on the host**, not in the container (`CLAUDE.md`, §Docker).
- Tests: a rotation created through the API is private; the migration's `downgrade` drops the
  column cleanly.

**Acceptance:** `alembic upgrade head` then `downgrade -1` round-trips on a seeded database;
`pytest tests/unit/test_rotation_visibility.py` passes.

### L.2 — publish and unpublish

`PATCH /api/v1/rotations/{id}` accepts `visibility`. Not a new endpoint: it is a field of the
rotation, and a separate `/publish` would be a second way to write one column.

- **Only the owner may change it.** The existing ownership check covers this; assert it.
- Unpublishing is allowed and immediate. A user who shared something by mistake needs the
  door to open both ways.

**Acceptance:** a test proves a second user gets 404 (not 403) when patching someone else's
rotation — the existing convention, which does not confirm the row exists.

### L.3 — `rotation_characters`, so "for this team" is one query

The character set is derivable from `steps`, and derivable is not queryable (DESIGN §3).

A join table `rotation_characters(rotation_id, nanoka_id)` with a composite PK, written
whenever `steps` is written. **Rebuilt wholesale on every write**, never diffed: the steps are
already read and written whole for the same reason the DESIGN gives for JSONB, and a diff is a
second implementation of "what characters does this rotation name".

- The write path is `RotationRepository`, so nothing that saves a rotation can forget.
- Tests: editing a rotation to drop a character drops the row; a rotation whose steps name the
  same character twice yields one row.

**Acceptance:** `pytest tests/integration/test_rotation_characters.py`; a mutation via
`python -m scripts.inject` that stops the table being rebuilt on update is **caught**.

### L.4 — `GET /api/v1/rotations/library`

Published rotations only, never the caller's private ones and never another user's.

Query parameters:

| parameter | meaning |
|---|---|
| `characters` | repeated `nanoka_id`; a rotation matches when its character set **equals** this set |
| `q` | name substring |
| `sort` | `dps` (default), `likes`, `recent` |

**Exact set equality, not superset.** DESIGN §3 calls this "a filter that claims nothing", and
that is only true if it means what it says: a four-character rotation surfacing for a
three-character query would be a recommendation dressed as a filter.

The response carries, per rotation: id, name, description, the character set, the author's
display name, `like_count`, `liked_by_me`, and `your_dps` — null unless this caller has a
`sim_run` for it at the current signature (see *The one design decision*, above).

**Acceptance:** an integration test with two users proves user B sees user A's published
rotation and not their private one; `your_dps` is null for a rotation B has never run and
populated for one they have.

### L.5 — copy a shared rotation to your own

`POST /api/v1/rotations/{id}/copy` with a `team_id` body.

A shared rotation belongs to its author's team. Copying it means **re-resolving every step
against the caller's team**, and a step naming a character the caller's team does not field
must **refuse, naming the character** — the same rule the compiler already applies to a stale
rotation (`app/models/rotation.py`, OQ-R2). Never drop the step, never substitute.

The copy is private, owned by the caller, with `description` preserved and the name suffixed
so two copies are distinguishable.

**Acceptance:** copying onto a team missing one of the characters returns 422 naming them and
creates nothing.

---

## Track B — likes (DESIGN §4, §6 step 3)

### L.6 — `rotation_likes`

`rotation_likes(rotation_id, user_id, created_at)` with a unique constraint on the pair, both
FKs `ON DELETE CASCADE`.

**Not a counter column.** The DESIGN's reasoning is the acceptance criterion: a count alone
cannot say whether *this* user has liked, and cannot be un-liked without going negative under
a race.

`POST` and `DELETE /api/v1/rotations/{id}/like`. Liking your own rotation is allowed — it
costs nothing to permit and a rule against it is a rule to explain.

**Acceptance:** liking twice is idempotent (the second is a no-op, not a 500 on the unique
constraint); a concurrent double-like leaves exactly one row.

### L.7 — the count, without an N+1

`like_count` on the library listing comes from one aggregate join, not a query per row.

**Acceptance:** a test asserting the query count for a 20-rotation page is constant. This repo
has no query-count harness yet, so L.7 includes building the smallest one that works —
`sqlalchemy.event` on `before_cursor_execute` — or the task is not done, because "constant"
asserted by reading the code is not asserted at all.

---

## Track C — the frontend (BACKLOG_frontend §5)

### L.8 — the library, inside an expanded team

The owner's audit: *"It belongs as the last option inside an expanded team, opening a
card-and-filter pop-up."*

`shared/card-picker` is the pop-up, and `CardOption.icons` (#171) already draws a party. The
filter starts pre-set to the expanded team's characters, because that is the question being
asked — with a way to widen it, or the control is a list rather than a search.

Each card shows the name, the party, `like_count`, and `your_dps` where there is one.

**Acceptance:** looked at in a browser via `python -m scripts.shoot`, not merely tested. This
repo's rule stands: a green suite has never once caught a visual defect here.

### L.9 — like, and copy, from the card

A like toggle and a "Copy to my rotations" action. The copy's refusal (L.5) is shown verbatim
— it names the missing character, which is more useful than anything the page could invent.

---

## Track D — the converter (DESIGN §6 step 4)

**Largest, and last on purpose.** Four real community configs are committed under
`references/gcsim_db/`; the owner's ruling is *"whatever the four need"*.

### L.10 — measure before writing anything

Run all four through the current importer and record, per file, the exact line that refuses.
Write it into `LOG_rotation_library.md` before any converter code exists.

**This is not ceremony.** The first draft of the tier-2 importer worried about conditional
guards, and running a real config showed the blockers were the loop keyword and the sequence
syntax instead. The measurement changed the design; do it again rather than assume it still
holds.

### L.11 — the mechanical rewrites

`for … { }` → `while 1 { }`, and comma-separated action sequences into one step each.

Both are **spellings of the same rotation**, which is the whole justification: the converter
may only rewrite what provably means the same thing. Anything else is refused by L.12.

### L.12 — refuse by line, still

Whatever survives the converter and is still unexpressible is refused **naming the line**, as
now. `let` bindings, user-defined functions with bodies, `if`/`else` on state this model does
not carry, and `charge[final=1]` params are different rotations, not different spellings.

**Acceptance:** each of the four configs either imports with its step count recorded, or is
refused with the offending line quoted. No file may import *partially*.

---

## Not in this plan

- **Mirroring gcsim's database** — dropped, OQ-2. Somebody else's content under terms this
  repo has not established.
- **Ranking by the author's DPS** — the number is theirs, computed on their artifacts. The
  library shows *your* number where you have one and nothing where you do not.
- **Generating a rotation by search** — rotations are authored, never optimized (owner,
  2026-08-25). A library does not touch that: a shared rotation is still one a person wrote.
