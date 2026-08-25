# DESIGN: the loose ends, and icons

**Companion:** `docs/TASKS_loose_ends.md`
**Tier:** Planner (Opus). Implementation is Worker.
**Follows:** `docs/TASKS_optimizer.md` (complete). Every plan file is closed; this covers what
the `TODO(chunk-)` markers name, plus icons.

## Branch policy

Per-task branches off `dev`, merged by PR after review. **No direct commits to `dev` or
`main`.** The tasks are independent — none gates another — so they can land in any order.
Task 0 is the branch-setup gate.

---

## 1. What this covers

Five `TODO(chunk-)` markers survive, and the owner has asked for icons. Scoping them found
that **they are not five pieces of work**: one is already unblocked, one is stale, two are
ordinary, and one cannot be done without an architectural decision.

| marker | verdict |
|---|---|
| `test_talent_multipliers.py` | **doable now** — the network claim that blocked it was wrong |
| `dependencies.py` | **stale** — it plans to restore ZZZ repositories the BRIEF says to delete |
| `team.py` | ordinary work: the wipe-and-restore guarantee, re-keyed |
| `weapon_comparison.py`, `builds.py` | **needs a decision** — see §5 |

## 2. Icons (N.1)

**The basenames are already seeded.** Characters carry `UI_AvatarIcon_Ayaka`, weapons
`UI_EquipIcon_Sword_Blunt`, sets `UI_RelicIcon_10001_4`. Nothing was missing; nothing was
fetched.

fairy vendored the same way — `scripts/download_icons.py` reads basenames out of its database
and pulls from `static.nanoka.cc/assets/zzz`. The GI equivalent is `/assets/gi/{basename}.webp`,
**verified reachable** rather than assumed: `HEAD .../assets/gi/UI_AvatarIcon_Ayaka.webp` is
200.

Two decisions carry over from fairy and one does not:

- **Vendored, not hot-linked.** The same rule the YuanShen snapshot and the gcsim key snapshot
  follow: nothing in `app/` reaches the network at runtime. A page whose art depends on a
  third-party CDN being up is a page that breaks for a reason its owner cannot fix.
- **Downloaded by a script, not by the seeder.** `seed_db` must stay runnable offline — the
  crossval harness seeds from committed fixtures precisely so it needs no network.
- **Not committed to git.** fairy committed 207 files. Genshin has 150 characters, 260 weapons
  and 65 sets — 475 images. They are build assets, reproducible from a script and a seeded
  database, and a repository is not a CDN. `.gitignore`d, with the script as the reproduction.

## 3. Widening the multiplier crossval (N.2)

M.4's committed test compares **one** character, because Ayaka is the only nanoka character
payload in `tests/fixtures/`. **Neither bug M.4 found is reachable from it**: Venti's
`{param1}+{param1}` showed the sum was wrong, and Rosaria's skill and burst sharing `Skill
DMG` showed the comparison was keying on the label alone.

I recorded that as needing network, and **that was wrong**: I tested `api.hakush.in`, which is
not the host. `static.nanoka.cc` answers. `scripts/capture_nanoka_fixtures.py` is the
reproduction, and it already refuses to capture anything not named in its own list — so
widening is an edit to `DETAILS` with a reason per entry, which is the shape it was built for.

## 4. The two ordinary ones

- **N.3 — the GOOD importer's wipe-and-restore.** Teams already snapshot slot bindings before
  a wipe and restore them after, and only for builds *this owner owns*. The GOOD importer's
  `replace` mode deletes an inventory and re-inserts it, which unequips everything. Recover
  the original from `fairy@76909c4` rather than re-deriving, per the marker.
- **N.4 — the stale DI marker.** It names twelve factories to restore "with the route that
  needs it". Nine are ZZZ — agent, attack, w_engine, disc_set, disc, combo — and the BRIEF is
  explicit that ZZZ concepts are *deleted*, not deferred. One (`get_owned_build_repo`) now
  exists. The marker plans work that must not happen; it is corrected, not carried.

## 5. Weapon passives — what this design cannot decide

`weapon_comparison.unmodelled_passives` exists because a comparison seeing only base ATK and
the substat "will rank a stat-stick above a weapon whose passive is the entire reason anyone
equips it, and it will do so with a precise-looking number." **The ordering itself can be
wrong**, which is worse than an imprecise figure.

M.4's lever does not reach it. gcsim's multipliers are *generated data tables*, which is why
they could be snapshotted and compared. gcsim's weapon passives are **executable Go with
conditional and frame-dependent state** — Amos' Bow reads arrow travel time in frames:

```go
travel := float64(c.F - atk.Snapshot.SourceFrame) / 60
stacks := min(int(travel/0.1), 5)
```

There is no table to take. The stored data is free English text — *"When HP is above 90%,
increases CRIT Rate by 14%"* — with the numbers in `param_list` but the **condition** only in
prose.

So modelling them needs a **conditional modifier model**: a way to say "this bonus applies
when X". fairy had one (`app/data/modifiers/`, stripped in the fork commit as ZZZ-specific).
Rebuilding it for Genshin is a chunk in its own right, and it is the one piece of work in this
repo where the failure mode is *fabrication* — writing a condition from a reading of English
text is exactly what the citation rule exists to prevent.

**This design does not attempt it, and N.5 is an assessment rather than an implementation.**
The decision is the owner's: build the modifier model, or accept the gap permanently and keep
`unmodelled_passives` as the honest disclosure it already is.

## 6. Non-goals

- **No modifier model.** §5.
- **No icons for enemies or artifacts-as-pieces.** The three the owner named are what the
  catalogue stores basenames for.
- **No image processing.** Vendored as published; resizing is a frontend concern if it ever
  becomes one.
