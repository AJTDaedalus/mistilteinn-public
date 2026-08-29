"""The practice mannequins, and the one place that says which rows they are.

`Manekin` and `Manekina` are the training dummies from the Serenitea Pot. They are real
catalogue rows — five-star, sword class, with a release date — and nanoka carries **seven
elemental variants of each**, so they are 14 of the 150 characters. They are never used in
combat.

Owner ruling (2026-08-28): *"Manekin(a) are out of scope. They're never used in combat. We can
hide them, no point even including them."*

## Identified by body id, not by name

`10000117` and `10000118`, the same two ids `gcsim_keys._TRAVELER_BODIES` already documents as
bodies gcsim does not implement. A name match would be the obvious thing and the wrong one:
`name` is a display string, it is localised upstream, and `ILIKE 'Manekin%'` would take any
future character whose name happens to start that way. The body id is what the source keys
them by and does not move.

## Hidden from the catalogue, not deleted

They stay seeded. `verify_seed` counts rows against the source index, and a seeder that
dropped fourteen would have to explain the gap to every count that follows — including the
prune guard, which refuses to delete an implausible share of a table precisely because a
silent shrink is indistinguishable from a truncated download. Hiding is a read-time decision
and is reversible by deleting one `where`.

`good_build_service` already excludes them from a GOOD import, but *structurally* — it builds
only characters holding a weapon or an artifact — so there is no rule there to share. This is
the first place that has to name them.
"""

from __future__ import annotations

#: nanoka body ids for the two mannequins. Their rows are spelled `10000117-2` … `10000118-8`,
#: one per element, which is why this matches on the body rather than on the whole id.
DUMMY_BODIES: frozenset[str] = frozenset({"10000117", "10000118"})


def is_practice_dummy(nanoka_id: str | None) -> bool:
    """Whether this character row is a training mannequin.

    Takes the full id (`10000117-4`) and compares the body before the dash, so a variant this
    repo has not seen — an eighth element, say — is caught by the same rule.
    """
    if not nanoka_id:
        return False
    return nanoka_id.split("-", 1)[0] in DUMMY_BODIES
