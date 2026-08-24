# TASKS: teams and builds

**Companion:** `docs/DESIGN_teams_builds.md` — read §2 (what the survey found) before T.1.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules**
- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- `ruff check` and the relevant tests pass before each commit.
- Every new authed route joins the 401 sweep **in the same commit** —
  `test_the_sweep_covers_every_owned_route` fails otherwise, which is the point.
- Any API change regenerates `frontend/openapi.json` (`create_app().openapi()`, no server
  needed) and leaves `test_openapi_contract_is_current` green.
- Prove the negative: a new refusal gets a `python -m scripts.inject` run, and a mutation that
  **survives** means the test is wrong, not that the guard is fine.

---

### [x] T.0 — Branch setup **(gate)** — held
- **Do:** per-task branches off `dev`; merge by PR.
- **Accept:** nothing reaches `dev` outside a PR — checkable with `git log --first-parent dev`.

### [x] T.1 — The build write path refuses what cannot be simulated — **done**
- **Do:** validate `POST /builds` and `PATCH /builds/{id}`:
  - `character_id` must exist → 422 naming it (today: a 500 from the FK).
  - `weapon_id`, when given, must exist and its `weapon_type` must equal the character's →
    422 naming both types.
  - `talent_levels` keys must be `TalentType` values, checked against the enum rather than a
    list restated in the schema.
  - `talent_levels` values in 1–15, with the reason in the message.
- **Files:** `app/schemas/build.py`, `app/api/v1/builds.py`, tests.
- **Accept:** four refusals, each a 422 whose message names the problem; **both** POST and
  PATCH, because create is not the only way steps get in — R.4's review found exactly that
  hole. Each refusal CAUGHT under `scripts.inject`.
- **Why it is first:** DESIGN §2.2 — a misspelled talent key is currently read as level 1 by
  `gcsim_config._talents`, so a talent-9 burst simulates as talent 1. Building the UI first
  would mean shipping the page that makes that easy to do.
- **Done, and it found three more than the design predicted:**
  - **A second build of the same character was a 500.** `uq_builds_owner_character` was
    enforced only by the database. Now a 409 naming the limit — which is inherited from fairy
    and *under review* (`app/models/build.py`), so this makes it legible rather than
    endorsing it. **Owner decision still outstanding; see the LOG.**
  - **`BuildUpdate` silently dropped unknown fields.** A PATCH naming `character_id` returned
    200 having changed nothing. `extra="forbid"` now refuses it.
  - **The refusal message read `WEAPON_SWORD_ONE_HAND`.** That is the game's internal
    spelling, not a label; `WeaponType.display` is now the one readable name per class.
  - `MAX_TALENT_LEVEL` is **15, read off the fixtures** — every levelled talent has a 15-row
    `promote` table — not derived from constellation arithmetic, which gives 13.
  - Seven mutations, all CAUGHT.

### [x] T.1a — A user may own several builds of one character **[unplanned; owner decision]**

`uq_builds_owner_character` — inherited verbatim from fairy's `uq_builds_owner_agent` — was
dropped (owner, 2026-08-24). It forbade saving a C0 and a C6 of the same character side by
side, or a Physical Eula against a Cryo one, which are ordinary things to want to compare.
T.1 had just turned the resulting 500 into a 409, which is what made the decision blocking:
T.3 is where a user meets the limit.

**The rule moved rather than vanished.** gcsim refuses a party holding one character twice —
`pkg/simulation/setup.go:94` at pin `3647a07` returns `duplicated character %v` — so the
collection may hold two and the **team** may not. Enforced in `app/api/v1/teams.py`, which
also gained the validation `create_team` never had: a slot naming a build that does not exist
reached the foreign key and became a 500, and a slot naming a *stranger's* build was stored
and shown on every later read.

`RotationRepository._roster` now **refuses** a duplicate rather than collapsing it. Keyed by
`nanoka_id`, two Ayakas became one entry and a four-build team compiled against three
characters. The rule lives in the application, not the schema, so a row from a script or a
fixture can still arrive that way — the test writes one directly.

Four mutations, all CAUGHT. Migration `27770f8ae917`, round-tripped up and down.

### [ ] T.2 — A build carries what a row needs
- **Do:** `BuildRead` gains optional nested `character` and `weapon` summaries — name,
  element / weapon type, rarity, `nanoka_id`. Reuse the catalogue's summary shapes rather
  than defining new ones. Decide and implement server-side weapon filtering by
  `weapon_type` so the picker can offer only what T.1 accepts.
- **Files:** `app/schemas/build.py`, `app/repositories/build.py` (eager loads),
  `app/api/v1/{builds,weapons}.py`, `frontend/openapi.json`.
- **Accept:** a builds list renders names in **one** request — asserted by counting queries or
  by the response shape, not by inspection; `/api/v1/weapons?weapon_type=Sword` returns only
  swords; contract test green.
- **Why it is its own task:** it is the R.5 lesson applied — the client has no business
  mapping a UUID `character_id` to the `nanoka_id` the catalogue is keyed by.

### [ ] T.3 — The build editor
- **Do:** a page to create, edit and delete a build: pick a character, pick a weapon from the
  ones that character can hold, set levels, ascension, refinement, constellation and the three
  talent levels.
- **Files:** `frontend/src/app/pages/builds/`, `app.routes.ts`, `app.html`.
- **Accept:** reachable from the shell nav — `app.routes.spec.ts` fails otherwise; a failed
  load is surfaced rather than rendered as "no builds"; the server's refusal is shown
  verbatim; the weapon picker offers only what T.1 accepts, filtered **by the server**.

### [ ] T.4 — The team builder
- **Do:** a page to assemble up to four builds into a team, name it, and delete it.
- **Files:** `frontend/src/app/pages/teams/`, `app.routes.ts`, `app.html`.
- **Accept:** in the nav; a build already in another slot cannot be picked twice, and the
  client rule and `assert_slots_distinct` cannot disagree — the same picker-matches-validator
  guarantee as R.5, tested as one claim; refusals verbatim.

### [ ] T.5 — The loop closes
- **Do:** the rotation editor's empty state becomes a link to the team builder. One
  integration test walks the whole path.
- **Files:** `frontend/src/app/pages/rotations/rotations.html`, `backend/tests/integration/`.
- **Accept:** an integration test creates two builds, assembles a team, authors a rotation and
  compiles it, in one flow. **Not** a unit test of each step — every piece already passes its
  own tests today while the app is unusable, so what needs proving is that they are connected.

---

## Open questions

- ~~**OQ-T1**~~ **Answered in DESIGN §6: a weapon-type mismatch is a refusal.**
- ~~**OQ-T2**~~ **Answered in DESIGN §6: an unknown talent key is a refusal.**
- ~~**OQ-T3**~~ **Answered in DESIGN §6: a build may have no weapon.**

## Not in this chunk

Artifact assignment UI, build duplication or sharing, rotation optimization, and modelling
weapon/character passives. DESIGN §5 says why for each.
