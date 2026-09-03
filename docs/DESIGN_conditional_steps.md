# DESIGN — conditional steps in a rotation

**Status:** built 2026-09-02, the import half. `group` is a path, `group_condition` rides
beside `group_repeat`, the compiler emits nested `if` blocks and the parser reads them back.
The owner's config (`gcsim.app/db/bgHjR7MP7Fkn`) imports as **180 steps, 12 guarded**, and
the round trip is stable: import, compile, import again returns identical steps.

**OQ-C1 is still open** — nothing authors a condition in the builder yet, so a guarded
rotation can be imported and edited around but not written from scratch.

## Branch policy

`feat/conditional-steps`, off `dev`. **No direct commits to `dev` or `main`** — merged by PR
after review like every other feature. Task 0 of the TASKS file is the branch-setup gate.

## The ask

Owner, 2026-09-02, on a real community config (`gcsim.app/db/bgHjR7MP7Fkn`):

> *"We need a way to express this in our rotation"*

Four constructs were refused. **Three needed no model change** and are fixed in #233: the
`is_even(i)` branches are arithmetic and unroll into explicit cycles, and an
`if .x.burst.ready { A } else { A-minus-burst }` *is* a gated step. What is left is one block:

```
if .flins.status.manifest-flame {
  flins skill;
  if .flins.energy >= 30 {
    flins burst;
  }
}
```

A status guard with a nested energy threshold. Neither is statically resolvable and neither
reduces to readiness.

## The decision this design exists to make

The cheap model is a **condition per step**, ANDed:

| step | conditions |
|---|---|
| `flins skill` | `status.manifest-flame` |
| `flins burst` | `status.manifest-flame`, `energy >= 30` |

emitting `if A { skill; } if A && B { burst; }`.

**It is wrong, and this config is the proof.** gcsim evaluates a block's condition **once, on
entry**; the flattened form evaluates `A` again before the burst. And `A` changes in between —
`internal/characters/flins/skill.go:56` is `c.DeleteStatus(skillKey)`, so **Flins's skill
deletes the very status the block is guarded on**.

So under flattening the burst would never fire, the import would succeed, and the rotation
would carry the author's name and simulate to a different number. That is precisely the
failure `rotation_parser` refuses configs to prevent, arrived at by a different road.

**Conditions are therefore blocks, not step fields.** Evaluated once on entry, and nestable.

## Shape

The model already has `group` and `group_repeat` carried on every member of a run. Conditions
extend the same idea rather than adding a second grouping concept:

- `group` becomes a **path** — `"flame"`, `"flame/energy"` — so nesting is expressible without
  the field changing type. A step's path names every block it is inside, outermost first.
- `group_condition` is carried per member like `group_repeat` is, and the schema requires the
  members of a block to agree.
- The compiler walks the path and emits nested `if`s, one per segment, in order.
- The parser reads nested `if` blocks into paths, and **still refuses a condition it cannot
  read** — the vocabulary below is a subset, and everything outside it is named rather than
  approximated.

## The condition vocabulary

Only what gcsim publishes and this repo can round-trip:

| form | example |
|---|---|
| readiness | `.flins.burst.ready` |
| energy | `.flins.energy >= 30` |
| status | `.flins.status.manifest-flame` |

**Deliberately not included:** arithmetic on the loop index (resolved by unrolling, #233),
`is_even`, user-defined functions, and anything comparing two characters. Each is refused by
name. A grammar that accepts what it cannot faithfully re-emit is how a rotation silently
becomes a different one.

## Open questions

**OQ-C1 — does the builder author these, or only import them?** A condition is the first part
of a rotation that is not a list of moves, and the builder's whole argument is that gcsim's
syntax is the wrong authoring surface. Importing them while offering no way to write one is a
defensible first step and should be a deliberate choice rather than an omission.

**OQ-C2 — what does a conditional step do to the energy ladder?** The ladder varies ER and
reads team DPS; a block guarded on `.energy >= 30` changes shape as ER changes, so the rung
spacing and the ladder's monotonicity argument both need re-examining. Not a blocker for
importing, and a blocker for scoring.

**OQ-C3 — `else`.** #233 reduces the one `else` shape that is a gated step. A general `else`
needs a second block on the same condition, and nothing in this design covers it yet.
