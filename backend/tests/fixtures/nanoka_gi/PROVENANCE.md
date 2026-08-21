# nanoka GI index fixtures

| | |
|---|---|
| **Source** | `https://static.nanoka.cc/gi/{version}/{entity}.json` |
| **Version** | **7.0.51** — pinned from `https://static.nanoka.cc/manifest.json` → `gi.latest` (`gi.live` was `7.0`) |
| **Fetched** | 2026-08-21 |
| **Task** | C.1 |

| File | Entries | Bytes |
|---|---:|---:|
| `manifest.json` | — | 14,560 |
| `character.json` | 150 | 67,991 |
| `weapon.json` | 286 | 125,429 |
| `artifact.json` | 65 | 116,597 |

`monster.json` (585 entries, 412 KB) is **not** committed here. C.1 asks for the three entity
indexes the enums are derived from; the monster index feeds `EnemyProfile` mapping in D.6 and
is committed there if it turns out to be needed.

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
