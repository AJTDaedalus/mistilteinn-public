# nanoka GI index fixtures

| | |
|---|---|
| **Source** | `https://static.nanoka.cc/gi/{version}/{entity}.json` |
| **Version** | **7.0.51** — pinned from `https://static.nanoka.cc/manifest.json` → `gi.latest` (`gi.live` was `7.0`) |
| **Fetched** | 2026-08-21 |
| **Tasks** | C.1 (indexes + first details), D.2 (`monster.json` and the remaining details) |

| File | Entries | Bytes |
|---|---:|---:|
| `manifest.json` | — | 14,560 |
| `character.json` | 150 | 64,989 |
| `weapon.json` | 286 | 116,931 |
| `artifact.json` | 65 | 80,708 |
| `monster.json` | 585 | 398,539 |
| `detail/character_10000002.json` | — | 93,499 |
| `detail/character_10000005-2.json` | — | 350,356 |
| `detail/weapon_11501.json` | — | 10,584 |
| `detail/artifact_15025.json` | — | 3,595 |
| `detail/monster_21010101.json` | — | 10,625 |
| `detail/monster_24010101.json` | — | 15,007 |

## How to refresh

    cd backend && python -m scripts.capture_nanoka_fixtures            # rewrite
    cd backend && python -m scripts.capture_nanoka_fixtures --check    # report drift only

That script is the single definition of *what* is committed here (its `INDEXES` and
`DETAILS` constants, each detail carrying the reason it exists) and of the exact
serialisation — indexes `indent=2, ensure_ascii=False`, details `indent=1,
ensure_ascii=True`, neither with a trailing newline. Adding a fixture means editing that
list in a reviewable commit, which is what keeps this directory from accreting drive-by
downloads. `--check` exits non-zero on drift; drift is a finding, not a failure.

Why each detail payload is here — and the key map derived from them — is in
`docs/LOG_mistilteinn.md`, the D.2 entry.

## Why these are committed

`C.2`'s enums are derived from **these files**, not from a live call. A test that fetches
nanoka to check an enum is a test that goes red when a patch ships, on a machine with no
network, or when nanoka is down — and it silently stops proving anything the moment it is
allowed to skip. Committing the payload makes an upstream change show up as a reviewable diff
instead.

Refresh deliberately, as its own commit, with the version and date in this table updated.

## What was read off them

See `docs/LOG_mistilteinn.md`, the C.1 entry, for the full value sets and the two encoding
traps (the crossbow class is spelled differently in the character and weapon indexes; "no
substat" is expressed as both JSON `null` and the string `FIGHT_PROP_NONE`).
