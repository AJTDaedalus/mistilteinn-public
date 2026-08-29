# gcsim database configs — provenance

Real, community-submitted gcsim configs pulled from **gcsim's own public database**
(https://gcsim.app/database) for use as parser test input.

**Retrieved:** 2026-08-29

**These files are verbatim.** Do not reformat, re-indent, normalise line endings, or "fix"
anything in them — they are test input for the gcsim-config importer, and any edit invalidates
the test. In particular every file uses **CRLF (`\r\n`)** line endings, exactly as the database
stores them.

## How they were retrieved

The database page is a JS app, but it reads a plain JSON API that is reachable directly:

```
GET https://gcsim.app/api/db?q=<url-encoded JSON>
    JSON body: {"query": {...}, "limit": N, "skip": 0, "sort": {"create_date": -1}}
```

`query` is a MongoDB-style filter over the stored document; `summary.char_names` is the array
of the four character keys. Each returned document carries the raw config source in its
`config` field. The `q=` shape was read off gcsim's own frontend bundle
(`https://gcsim.app/assets/index-b012a78e.js`); nothing here was guessed.

Each config was independently re-fetched from a second endpoint,
`GET https://gcsim.app/api/share/db/<id>` (field `config_file`), and the two sources were
compared byte-for-byte. All four **match exactly**, so the saved bytes are not an artefact of
one endpoint's encoding.

## Authorship and licensing

**Licence: not stated.** gcsim's db submission rules
(https://gist.github.com/srliao/33080e3921fe834556038cbfdc70c57c, linked from the site) cover
formatting, legality of stats/actions and novelty of the rotation. They say **nothing** about
copyright, licensing, or reuse of submitted configs. gcsim's own source is licensed in the
`genshinsim/gcsim` repository, but that licence covers the simulator, **not** user-submitted
database entries.

**Author: not stated by name.** The database exposes only a numeric `submitter` field, which is
a Discord user snowflake. It is recorded below as-is. No display name, handle, or attribution
string is published by the API, so none is asserted here.

Each entry is viewable at `https://gcsim.app/db/<id>`.

## Files

### `neuvillette-furina-citlali-escoffier.txt`
- **Source URL:** https://gcsim.app/db/NP6c6P6RQtKb
- **API URL:** `https://gcsim.app/api/db?q={"query":{"_id":"NP6c6P6RQtKb"},"limit":1,"skip":0,"sort":{"create_date":-1}}`
- **Retrieved:** 2026-08-29
- **Team:** Neuvillette, Furina, Citlali, Escoffier (mono-Hydro / freeze)
- **Author:** not stated — `submitter` = `972143886153699328` (Discord id)
- **Licence:** not stated
- **db description (verbatim):** "Neuv Furina Escoffier Citlali. 4CA 24-25s rot. Single field time of E C Q 2[C] E C which makes Neuv catches all of his particles. Waveriding Whirl R5 (if you somehow have it R5)  also has similar damage, since the combo starts with E, activating its passive to have high uptime unlike usual."
- **db metadata:** created 2025-07-10T12:34:58Z, last updated 2026-08-18T04:16:59Z, share key `cWKr7CJhwhht`, sim hash `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa`, 1 target, mean DPS/target 97130.83
- **bytes:** 1894 — **sha256:** `14c40db7a310e5b9a8bb3ef3e5eff503e68d492ee5a9c9cb8b60e41f2592ab2b`

### `mavuika-escoffier-citlali-bennett.txt`
- **Source URL:** https://gcsim.app/db/FzcfMQJmQw6j
- **API URL:** `https://gcsim.app/api/db?q={"query":{"_id":"FzcfMQJmQw6j"},"limit":1,"skip":0,"sort":{"create_date":-1}}`
- **Retrieved:** 2026-08-29
- **Team:** Mavuika, Escoffier, Citlali, Bennett (Mavuika Pyro / melt)
- **Author:** not stated — `submitter` = `972143886153699328` (Discord id)
- **Licence:** not stated
- **db description (verbatim):** "⏭️🔄 Mavuika Escoffier Citlali Bennett. 18s rot. Q C1 6[D*C2] D*C2F"
- **db metadata:** created 2026-07-29T13:04:04Z, last updated 2026-08-17T23:44:41Z, share key `CWHbkhGwFWhc`, sim hash `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa`, 1 target, mean DPS/target 159244.07
- **bytes:** 4110 — **sha256:** `e1f753e8e8a5f69571762859b1e7ec4fb0fcacf34a18caa2581195b4e80f8aaf`

### `arlecchino-citlali-escoffier-bennett.txt`
- **Source URL:** https://gcsim.app/db/wdf6dMzPCHmM
- **API URL:** `https://gcsim.app/api/db?q={"query":{"_id":"wdf6dMzPCHmM"},"limit":1,"skip":0,"sort":{"create_date":-1}}`
- **Retrieved:** 2026-08-29
- **Team:** Arlecchino, Citlali, Escoffier, Bennett (Arlecchino melt)
- **Author:** not stated — `submitter` = `762585087106744330` (Discord id)
- **Licence:** not stated
- **db description (verbatim):** "Arlecchino Citlali Escoffier Bennett. ~16s Rot. Arlecchino double Cryo Melt with ungabunga easy C N15, not a cancel in sight. Escoffier & Arlecchino do not use burst."
- **db metadata:** created 2025-08-07T20:35:11Z, last updated 2026-08-23T00:42:09Z, share key `c6QHJDrcFQFj`, sim hash `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa`, 1 target, mean DPS/target 103656.85
- **bytes:** 2164 — **sha256:** `4a9dcfa61dd20b2def335769629687b98d0c8696bc35898ec2f0a33dcdc30631`

### `clorinde-chevreuse-nicole-durin.txt`
- **Source URL:** https://gcsim.app/db/LjqG7dz7DKpz
- **API URL:** `https://gcsim.app/api/db?q={"query":{"_id":"LjqG7dz7DKpz"},"limit":1,"skip":0,"sort":{"create_date":-1}}`
- **Retrieved:** 2026-08-29
- **Team:** Clorinde, Chevreuse, Nicole, Durin (Clorinde overload)
- **Author:** not stated — `submitter` = `972143886153699328` (Discord id)
- **Licence:** not stated
- **db description (verbatim):** "Clorinde Durin Chev Nicole. 18s rot. Nicole Q E > Chev Q 2[hE] > Durin 2[E] Q setup. use Durin 2[N1CD] after his Q when Clorinde doesn't use her Q. Clorinde is ~55% Team DPS share"
- **db metadata:** created 2026-07-13T16:00:34Z, last updated 2026-08-18T03:04:28Z, share key `LMCwcGQBTtnM`, sim hash `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa`, 1 target, mean DPS/target 108851.18
- **bytes:** 2200 — **sha256:** `6c8eb2993f1bc4df6929ea2e7559190e3cf9566ec4860cd0c386b3b9e0c5f773`

## Character-availability check

Every character in all four teams is on the fully-built list this account was checked against:
Neuvillette, Furina, Citlali, Escoffier, Mavuika, Bennett, Arlecchino, Clorinde, Chevreuse,
Nicole, Durin.

## Notes for the importer

Things these real configs contain that hand-written fixtures often do not — each verified
against the saved bytes, not assumed:

- **CRLF line endings throughout**, in all four files.
- **Two comment syntaxes in the same file** — `#` and `//`. `neuvillette-...` and
  `mavuika-...` use both; the other two use only `#`.
- **Whole statements commented out** rather than deleted, e.g.
  `//neuvillette add weapon="waveridingwhirl" refine=5 lvl=90/90;` and three commented-out
  `citlali add stats` lines in the Mavuika config — alternative builds left in place.
- **Trailing comments after a `;`**, in all four files, and **multiple `//` comments on one
  line** in the Mavuika rotation (`mavuika charge; // D*C2 // d*cC // No Mavuika Q buff`).
- **A trailing comment inside a `{` block header** — the Mavuika config's
  `fn mav_dc_cancel(d_travel_f) { # ... https://docs.gcsim.app/...` puts a `#` comment
  containing a URL (so, a `//`-looking substring) on the opening-brace line.
- **A user-defined function with a parameter, declared with `fn` and called from the
  rotation** (`mav_dc_cancel(6);`), plus `let` bindings — the Mavuika config only.
- **Whitespace before the terminating `;`** (`neuvillette char lvl=90/90 cons=0 talent=9,9,9 ;`)
  and inconsistent spacing generally.
- **Bracketed action params** — `charge[final=1]`.
- Control flow: `for`, `while`, `if` / `} else`, and `.char.field` condition expressions.

Note that the *db descriptions* quoted above contain emoji, but the **config text itself is
pure ASCII** in all four files. If the importer needs a non-ASCII case, these are not it.
