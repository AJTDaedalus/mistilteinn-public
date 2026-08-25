# TASKS: the loose ends, and icons

**Companion:** `docs/DESIGN_loose_ends.md` — read §1 (what scoping found) before starting.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

> **Status: all six tasks done. N.5 produced an escalation, which was its deliverable —
> `x`, not `!`: nothing here is blocked, one question was handed up.** Merged as PRs #84
> (N.0–N.1), #85 (N.2), #87 (N.3) and #88 (N.4).
>
> **What this chunk was for:** `rg "TODO\(chunk-"` counted **nine** markers, seven naming a
> closed chunk. It counts **two** now, both `TODO(chunk-H)` and both left pointing at a
> closed chunk **on purpose** — N.5 measured that gap and escalated where it should land
> rather than re-pointing them at a chunk that does not exist yet.

**Standing rules**
- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- **Run each gate standalone and check its exit code.** Not chained behind `&&`, not piped
  through `tail`. M.2 merged a lint failure because a chained commit short-circuited and the
  next line printed something that looked like success.
- Lint with **CI's own argument list**, not `ruff check app/ tests/`.
- Every new authed route joins the 401 sweep in the same commit; any API change regenerates
  `frontend/openapi.json` and leaves the contract test green.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise.**
- Tests that read a row through an API **expire the session first**, and every id needed after
  `expire_all()` is captured before it.

---

### [x] N.0 — Branch setup **(gate)**
- **Do:** per-task branches off `dev`; merge by PR.
- **Accept:** `git log --first-parent dev` is merge commits only.

### [x] N.1 — Icons — **done**
- **Do:** a script that reads icon basenames out of the seeded database and vendors the images
  from `https://static.nanoka.cc/assets/gi/{basename}.webp`, plus the frontend using them for
  characters, weapons and artifact sets.
- **Accept:**
  - **nothing in `app/` fetches at runtime** — the same rule the YuanShen and gcsim snapshots
    follow, and the reason the crossval harness needs no network;
  - `seed_db` still runs offline;
  - a missing or failed icon is **reported and the page still renders** — art is decoration
    and a broken image must not take a row with it;
  - images are `.gitignore`d, with the script as the reproduction: 475 build assets are not a
    repository's job.
- **Why the basenames are already there:** `characters.icon`, `weapons.icon` and
  `artifact_sets.icon` were seeded by Chunk D. Nothing was missing; nothing was fetched.
- **Done.** `scripts/download_icons.py` vendors **472 of 475**; a `catalogue-icon` component
  draws them on the three catalogue pages.
- **Three are genuinely not published upstream** — an unreleased weapon's placeholder and two
  artifact sets, all 404. The script separates *"upstream has no art for this"* from *"the
  fetch broke"*, because conflating them would make it exit non-zero forever, and **a check
  that can never pass is a check nobody runs.** Zero rows had a null icon basename, so the
  seeding half was already complete.
- Eight mutations, eight caught — including one that only surfaced when I stopped testing
  `Report` and started testing the branch that classifies a response.

### [x] N.2 — Widen the multiplier crossval — **done, closes `TODO(chunk-M)`**
- **Do:** capture the **Venti** and **Rosaria** payloads into `tests/fixtures/nanoka_gi/`, via
  `scripts/capture_nanoka_fixtures.py`'s own `DETAILS` list with a reason per entry.
- **Accept:** the committed crossval covers the two bugs M.4 actually found — Venti's
  `{param1}+{param1}` (summed when it is two hits) and Rosaria's skill and burst sharing the
  label `Skill DMG`; the coverage floor in `test_talent_multipliers.py` rises with it.
- **Note:** I recorded this as blocked on network and **that was wrong** — I tested
  `api.hakush.in`, which is not the host. `static.nanoka.cc` answers.
- **Done.** 1 character → **3**, 180 hits → **570**, still 0 mismatches. A test now
  reproduces M.4's summing bug against the committed fixtures and requires it to fail, so the
  regression is guarded **in CI** rather than having been caught once against a seeded
  database.
- **The capture had to be pinned explicitly.** It defaults to `gi.latest`, and nanoka has
  moved to **7.0.52** — so the first run pulled two payloads at 7.0.52 into a directory whose
  every other file is 7.0.51, and rewrote three index files. `--version 7.0.51` fixes it. A
  version bump is a deliberate separate change, not a side effect of adding two characters.

### [x] N.3 — The GOOD importer's wipe-and-restore — **done, closes `TODO(chunk-G, G.5)`**
- **Do:** snapshot team slot bindings before a `replace` import and restore them after,
  re-keyed on `Build.character_id`.
- **Accept:** a `replace` import leaves teams pointing at the same characters; **a slot
  pointing at a build another owner owns is never touched** — the subtlety the marker says to
  recover rather than re-derive, from `fairy@76909c4:backend/app/repositories/team.py`; each
  guarantee CAUGHT under mutation.
- **The marker was aimed at the wrong layer.** A `replace` deletes *artifacts*; teams point at
  *builds*, which it never touches, so team slots come through intact. What it destroys is
  every `Artifact.build_id` — each build stripped of five pieces with nothing saying why.
- **Matched on stats, not identity**, because GOOD has no stable per-artifact id — the same
  fact that makes `mode` mandatory. A piece with no match stays unequipped and is **named**,
  on the API and on the import page.
- **fairy's original could not be ported directly**: `remap_slots` relies on
  `uq_builds_owner_agent` for unambiguity, and T.1a dropped this repo's equivalent by owner
  decision. Five mutations, five caught.

### [x] N.4 — Correct the stale DI marker **(closes `TODO(chunk-F/G)`)**
- **Do:** rewrite the comment in `app/dependencies.py`.
- **Accept:** it no longer plans to restore ZZZ repositories. Nine of the twelve it names —
  agent, attack, w_engine, disc_set, disc, combo and their owned variants — are concepts the
  BRIEF says to **delete, not defer**, and `get_owned_build_repo` already exists. A marker
  that plans work which must not happen is worse than no marker.

### [x] N.5 — Weapon passives **[Planner] — assessment, not implementation** — *escalated*
- **Do:** record what modelling them requires and what it would cost. **Do not build it.**
- **Accept:** an ESCALATION block in `docs/LOG_mistilteinn.md` stating the decision the owner
  has to make: build a conditional modifier model, or accept the gap permanently.
- **Why it cannot be done blind:** M.4's lever does not reach here. gcsim's multipliers are
  generated data tables; its weapon passives are executable Go with frame-dependent state
  (Amos' Bow reads arrow travel time). The stored data has the *numbers* in `param_list` and
  the **condition** only in English prose. Writing a condition from a reading of that text is
  the fabrication the citation rule exists to prevent — and it is the failure mode fairy
  actually suffered.

---

## Open questions

- **OQ-N1 — do icons get committed?** *Answered in DESIGN §2: no.* fairy committed 207 files;
  Genshin's equivalent is 475, they are reproducible from a script and a seeded database, and
  a repository is not a CDN.
- **OQ-N2 — build the modifier model?** **Escalated, not answered** — N.5 measured it and
  handed it up. `docs/LOG_mistilteinn.md`, "ESCALATION — weapon passives have no home".
  **5 of 242 passives are reachable without new machinery**, and the option N.5 did *not*
  anticipate is the live one: weapon comparison is ≤59 candidates, which is an async-job
  shape gcsim can actually serve — unlike the artifact search §6 ruled it out of. Owner's
  call, and it needs Brain because every option reopens a settled argument.

## Not in this chunk

The modifier model, enemy and artifact-piece icons, and image processing. DESIGN §6.
