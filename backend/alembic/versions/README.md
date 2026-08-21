# `alembic/versions/`

**Empty on purpose.** B.10 deleted all 39 of fairy's ZZZ migrations; there was no production
database to preserve and no ZZZ table survives the port. mistilteinn's history starts fresh.

This file exists so the directory survives a clone — git does not track empty directories, and
`alembic revision` needs `version_locations` to exist.

Order of what lands here:

1. **B.13** — one initial migration for the surviving *infrastructure* tables (users, sessions,
   teams, builds/enemy_profiles skeletons, buff_presets, optimization_jobs). Chunk B's exit gate
   requires the app to boot and the auth endpoints to answer, and both need a schema.
2. **C.7** — the Genshin domain: characters, talents, talent scalings, constellations,
   ascension passives, weapons, artifact sets, artifacts, and the rewritten
   `builds`/`enemy_profiles` columns.

`alembic upgrade head` on an empty database must succeed and `alembic downgrade base` must
reverse cleanly. That second half is not a formality: fairy's history could **not** be
downgraded — `alembic downgrade base` died on `Can't emit DROP CONSTRAINT for constraint
ForeignKeyConstraint(... table=Table('combos', ...)); it has no name`, so the database had to be
reset with `DROP SCHEMA public CASCADE` instead. Name every constraint.
