# Furnishing suites — provenance

`suite.json` is a **committed capture**, not a live fetch, and it lives under `app/data/`
rather than `tests/fixtures/` for one concrete reason: **`tests/` is excluded from the
production image** (`backend/.dockerignore`), so seed data kept there deploys as a
`FileNotFoundError`. It did — the first deploy of the teapot tracker failed on exactly that,
and the rollback put prod back.

| | |
|---|---|
| **Source** | `https://static.nanoka.cc/gi/7.0.51/suite.json` |
| **Version** | **7.0.51**, the pin `verify_seed.FIXTURE_VERSION` names |
| **Retrieved** | 2026-09-03 |
| **Suites** | 109 |
| **With a `favorite` list** | 79 |
| **Distinct characters favouring one** | 116 |

`favorite` holds **nanoka character ids** — the same ones `characters.nanoka_id` carries, which
is what lets the tracker join to a user's owned roster with no translation. Verified against
the seeded database rather than assumed: all **232** favourite rows resolve.

Re-capture with the same URL at the pinned version and re-serialise as `indent=2,
ensure_ascii=False`, matching `tests/fixtures/nanoka_gi/`'s own convention.
