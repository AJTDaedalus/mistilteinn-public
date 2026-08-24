# DESIGN: teams and builds — the UI, and the write path it needs

**Companion:** `docs/TASKS_teams_builds.md`
**Tier:** Planner (Opus). Implementation is Worker.
**Precedes:** nothing. This is what makes the rotation editor reachable.

## Branch policy

Work happens on per-task branches off `dev`, named `feat/<task>` or `fix/<task>`, merged to
`dev` by PR after review. **No direct commits to `dev` or `main`.** There are no parallel
tracks — the backend tasks (T.1, T.2) gate the frontend ones (T.3, T.4), so the chunk is a
line, not a fan. Task 0 of `docs/TASKS_teams_builds.md` is the branch-setup gate; nothing
starts before it.

---

## 1. Why this chunk exists

`docs/TASKS_rotation.md` completed with the rotation editor live at `/rotations`. Its empty
state says:

> You have no teams yet. A rotation's steps are checked against a team's characters, so build
> a team first.

**There is nowhere to do that.** No page creates a build, and no page assembles a team. The
editor is reachable only for rows inserted by hand. Everything downstream of it — the
compiler, the cache key, the run corpus — is exercised only by tests.

This chunk closes that, and it is also the bulk of what remains of Chunk J: the Mitya tokens
landed in #46 and have been applied to exactly one page.

## 2. What the survey found

Two gaps in the **write path**, both of which the UI would be the first thing to exercise in
anger. Neither is a frontend problem, and building the pages first would mean discovering
them through a 500.

### 2.1 `create_build` validates nothing

```python
build = await repo.create({**body.model_dump(), "owner_id": repo.owner_id})
```

That is the whole handler. Consequences, in order of severity:

- **A weapon the character cannot hold is accepted.** Nothing checks `Weapon.weapon_type`
  against `Character.weapon_type`. A Sword character holding a Bow is not a build; the game
  cannot equip it and gcsim cannot simulate it. It would be discovered at
  `/explain`, or in a gcsim run, far from the edit.
- **A `character_id` that does not exist becomes a 500.** The FK rejects it at flush time and
  the IntegrityError escapes. The user is told the server broke; what happened is that they
  named something that is not there.
- **`weapon_id` has the same shape**, plus one more: it is nullable by design (a build in
  progress), so "absent" and "wrong" have to stay distinguishable.

### 2.2 `talent_levels` is an unvalidated `dict[str, int]`

The docstring says *"Keyed by `TalentType` value. 1-15, because constellations raise the cap
past 10."* Nothing enforces either half.

The key half is the dangerous one. `gcsim_config._talents` reads:

```python
str(levels.get(name, 1))
for name in ("normal_attack", "elemental_skill", "elemental_burst")
```

**A misspelled key is silently level 1.** Not an error, not a default anyone chose — a
talent-9 burst simulated as talent 1, producing a number that is wrong and looks right. That
is the failure this repo has spent every chunk refusing, and it is currently one typo away in
a public API.

The value half matters less but is not free: a level of `999` reaches the talent-scaling
lookup, which will either raise or clamp, and neither is a sentence anyone can act on.

### 2.3 `BuildRead` carries UUIDs, not names

`character_id` and `weapon_id` are opaque ids. A builds list showing "Ayaka · Mistsplitter"
would need one catalogue fetch per build, and would have to map the UUID `character_id` to
the `nanoka_id` the catalogue is keyed by — a conversion the client has no business
performing. **This is the same shape R.5 met and solved with `/rotations/options`**, and it
gets the same answer: the server returns what the page needs to draw a row.

## 3. Approach

### 3.1 The write path refuses what cannot be simulated (T.1)

Same discipline as the rotation API: **a build that cannot be simulated is not a build**, and
refusing it at save time keeps the error next to the edit that caused it.

- Character must exist → 422 naming it, not a 500.
- Weapon, when given, must exist **and** its `weapon_type` must match the character's → 422
  naming both types.
- `talent_levels` keys must be `TalentType` values → 422 listing the three, checked against
  the enum rather than a restated list.
- `talent_levels` values bounded 1–15, with the reason (constellations raise the cap past 10)
  in the message.

Applied on **both** POST and PATCH. Create is not the only way a build changes, and R.4's
review found exactly that hole in the rotation API.

### 3.2 Builds carry what a row needs (T.2)

`BuildRead` gains a nested, optional `character` and `weapon` summary — name, element/type,
rarity, and the `nanoka_id` the catalogue is keyed by. Optional because `character_id` is
nullable in the model and a build mid-edit is a real state.

**Not a second schema.** The summaries reuse the catalogue's existing `CharacterSummary` /
`WeaponSummary` shapes where they fit, so the builds page and the catalogue page describe a
character the same way.

### 3.3 The pages (T.3, T.4)

Two pages, both following the discipline `catalogue-list.ts` established and R.5 reused:

- a failed load is **surfaced**, never rendered as "you have nothing";
- the server's refusal is shown **verbatim**, because it names what was wrong;
- the picker offers **only what the validator accepts** — so the weapon picker filters to the
  character's weapon type, and the talent inputs are the three `TalentType` values.

That last point is the one worth stating twice. In R.5 it was structural: `/rotations/options`
returned the roster the write path validates against, so the two could not disagree. Here the
same guarantee needs the weapon list filtered *by the backend's rule*, not by a rule the page
re-implements. The catalogue's `/api/v1/weapons` already supports filtering; T.2 decides
whether it filters by `weapon_type` or whether the page does. **It must be the server**, for
the same reason.

### 3.4 The loop closes (T.5)

The rotation editor's empty state becomes a link rather than an instruction, and a test walks
the whole path: create a build, create a build, assemble a team, author a rotation, compile
it. Not a unit test of each — an end-to-end one, because the thing being checked is that the
pieces are *connected*, and every piece already passes its own tests today while the app is
unusable.

## 4. Testing strategy

| task | what proves it |
|---|---|
| T.1 | a mismatched weapon, an absent character, a misspelled talent key and an out-of-range level are each a 422 with a message naming the problem; each refusal survives `scripts.inject` |
| T.2 | a builds list renders names in **one** request; the contract test is green |
| T.3 | component tests in the R.5 mould — failed load surfaced, refusal verbatim, picker matches validator |
| T.4 | the same, plus: the duplicate-slot rule the server enforces is not re-implemented client-side in a way that can disagree with it |
| T.5 | one integration test walking build → build → team → rotation → compiled config |

The standing rule applies throughout: **a skipped check blocks**, and the agent runs the
harness rather than reasoning in its place.

## 5. Non-goals

- **No artifact assignment UI.** Artifacts arrive by GOOD import and the optimizer picks
  them; a manual five-piece editor is a different chunk and probably an unwanted one.
- **No build duplication, templates, or sharing.** Nothing has asked for them.
- **No rotation optimization.** Still out of scope, still reopening the client-side cost
  argument — `DESIGN_rotation.md` §3.5.
- **Weapon and character passives remain unmodelled.** The `TODO(chunk-H)` markers stand;
  `weapon_comparison.unmodelled_passives` is how a caller finds out. This chunk does not
  change what the damage chain knows.

## 6. Open questions

- **OQ-T1 — is a weapon-type mismatch a refusal or a warning?** *Answered: refusal.* The game
  cannot equip it and gcsim cannot simulate it, so there is no reading under which the build
  is meaningful. A warning would mean storing a build the rest of the system must then
  special-case.
- **OQ-T2 — an unknown `talent_levels` key: refuse, or accept and ignore?** *Answered:
  refuse.* Accepting it means `_talents` reads the intended talent as level 1 — a wrong number
  that looks right, which is the one failure mode this repo treats as non-negotiable.
- **OQ-T3 — must a build have a weapon?** *Answered: no.* `weapon_id` stays nullable; a build
  being assembled is a real state. The damage chain already refuses to run without one, which
  is the right place for that requirement — at use, not at save.
