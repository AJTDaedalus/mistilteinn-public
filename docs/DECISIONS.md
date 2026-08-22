# DECISIONS

Tradeoffs, rejected alternatives, and rationale — any tier. Newest first.

---

## 2026-08-22 — The optimizer and its explainability are the product; gcsim goes underneath

**Owner ruling**, answering §6 of `RESEARCH_gcsim_embed.md` ("if gcsim supplies both the
simulation and the kits, what is mistilteinn?").

**The artifact optimizer and explainability are the distinguishing features.** The simulator
is infrastructure beneath them, not the product. The shape the owner named is *"a RAG-based
artifact optimizer built on top of the simulator"*.

**And the bar is Fribbels, not GO+gcsim.** `fribbels/hsr-optimizer` — the Honkai Star Rail
optimizer the community treats as the gold standard, and what fairy was loosely built from —
is the reference for *how to be distinct*, explicitly not "GO and gcsim combined in one
site". Verified at 659 stars, TypeScript, pushed the day this was written; its `src/lib`
carries `optimization`, `simulations`, `scoring` and **`gpu`** as separate modules, plus
`relics` organisation and recommendations.

Two things that grounding settles:

1. **A simulation layer *beneath* an optimizer is the proven shape**, not a novel bet — the
   gold standard already separates `simulations` from `optimization` from `scoring`. Chunk S
   §3's two-tier recommendation matches it.
2. **The "relic organizer and recommendations" tool is G.4's ranker**, arrived at
   independently. That is corroboration that the marginal-value framing is the right one.

### What this decides

- **Chunk H's hand-curated kit corpus is superseded.** gcsim's 106 character implementations
  replace it. This retires the chunk the BRIEF named as highest-risk *for the reason it was
  risky* — it is where fabricated citations did fairy the most damage, and the answer is to
  not curate a corpus at all.
- **Chunks F and G are the product**, and are kept. §3's measurement is why they must be:
  the Chunk F chain is 430–4,700× faster than a gcsim run, and no optimizer can call a
  simulator in its inner loop.
- **gcsim is adopted as infrastructure**, sidecar-first per §7.

### What it does not decide

The concrete meaning of "RAG-based" — see the open question logged with this entry. The
readings differ materially and the wrong guess is expensive, so it is asked rather than
assumed.

**Rejected:** "GO + gcsim in one site." It is the obvious synthesis and it is not a product:
it combines two things that already exist without being better than either at anything.

---

## 2026-08-21 — Take gcsim's and GO's knowledge, not their shape

**Owner ruling.** gcsim and Genshin Optimizer are the references for *correctness* and for
*feature scope*. They are explicitly **not** the references for code structure: both are
widely described as hard to follow, and logic nobody fully understands is logic nobody can
check. Legibility here is a product goal, not a cleanup task — see DESIGN §1 A6 for the four
concrete constraints (characters as data, one mechanic one implementation, numbers that can
explain themselves, efficiency from structure rather than special cases).

**Rejected:** port-then-tidy — "match gcsim's structure first, refactor once the numbers
agree". The numbers agreeing is precisely the moment the structure stops being changeable,
because every later edit then risks a regression against a crossval suite that has become
the definition of correct. The shape has to be right before the corpus grows into it.

**Rejected:** legibility as a Chunk J/documentation concern. Explainability is a property of
the damage chain's *data flow* — what carries provenance through a calculation — and cannot
be added by a UI or a docstring after the fact.

**Cost accepted:** Chunks F and H are expected to be slower than a direct port, and the kit
schema will need concepts a special case would not. **Does not override the citation rule**:
an explainable wrong number is still wrong.

## 2026-08-21 — Rebrand target: Mitya, identifiers now / visuals later

**Owner ruling.** fairy's visual identity derives from the ZZZ NPC "Fairy" (cobalt/cyan halo
palette in `frontend/src/styles/_tokens.scss`, sampled from `references/NPC_Fairy.webp`;
`fairy-emblem.webp`; "Fairy" wordmark). mistilteinn's identity is themed on the Genshin
character **Mitya**.

Chunk A renames package/project identifiers and swaps wordmark/title/favicon to a neutral
mistilteinn placeholder. The palette, emblem, and typography wait for Chunk J.

**Rejected:** full rebrand early — the backend-first phase order means nobody sees the frontend
for months, and a palette invented from a text description of a character (rather than sampled
from reference art, as fairy's was) would be re-done anyway.

**Consequence:** `_tokens.scss` deliberately keeps the Fairy palette until Chunk J. A half-done
rebrand is worse than an honest old one. **OQ-P1** (owner supplies Mitya reference art) blocks
Chunk J.

## 2026-08-21 — Demolition strategy: scorched earth, with an infra floor

**Owner ruling.** Chunk B deletes every ZZZ-bound module in one pass; the repo is deliberately
not a working game app across Chunks B→C.

**Rejected:** strangler / keep-green — the coexistence layer it requires *is* the ZZZ-shape
aliasing the BRIEF names as the fork's main long-term hazard, just with a deadline attached.
**Rejected:** hybrid — subsumed; the accepted plan already keeps infra green.

**Counterweight (Planner):** "scorched earth" applies to the game layer only. Auth, users,
sessions, teams, jobs, repository base, middleware, `app/formula/` core, and `app/pando/` stay
alive with green tests throughout. **Chunk B's exit gate is a green suite on a booting app** —
the point at which "the tests are expected to fail" stops being true for this repo.

**Safety net:** every deleted file remains in `/root/fairy` and at `fairy@76909c4`.

## 2026-08-21 — One Postgres server, two databases

**Owner ruling.** mistilteinn shares the fairy Postgres instance on `:5432` and owns databases
`mistilteinn` / `mistilteinn_test` alongside `fairy` / `fairy_test`.

**Rejected:** a shared database with a `genshin` Postgres schema — it would force a `search_path`
setting on every session and an `version_table_schema` on alembic, and entangle two migration
histories in one `alembic_version` namespace, to buy cross-game joins nothing has asked for.
**Rejected:** a second Postgres container on a remapped port — one more container's RAM on the
Oracle Free VM for isolation the database boundary already provides.

**Consequences:** mistilteinn's compose drops its `db` service (so the backend needs its own
connect retry — nothing sequences startup for us any more); host ports move to **8001 / 4201** to
clear fairy; one shared backup and connection-limit pool is the accepted cost. Partially resolves
**OQ-M3**.

## 2026-08-21 — nanoka.cc is the primary game-data source, not hakushin/Amber

**Planner finding, owner-informed.** The BRIEF named gi.hakush.in + Project Amber as primary
because nanoka's Genshin coverage was unverified at Brain time. Probed 2026-08-21: nanoka serves
Genshin at `gi` version 7.0.51 with the **same URL grammar** fairy's importer already speaks —
index at `{base}/gi/{ver}/{entity}.json`, detail at `{base}/gi/{ver}/en/{entity}/{id}.json` —
covering 150 characters, 286 weapons, 65 artifact sets, 585 monsters.

**Consequence:** the importer's transport layer (manifest pin, index, detail, stale-prune,
upsert) ports rather than being rewritten; only the field mapping is new. hakushin/Amber demote
to fallback adapters, **written only if a field proves missing** — not built speculatively.

## 2026-08-21 — GuraFoundation/YuanShenResources replaces Dimbreath AnimeGameData

**Owner ruling.** Raw-datamine source is `gitlab.com/GuraFoundation/YuanShenResources`. Verified
2026-08-21: root tree is `ExcelBinOutput/`, `TextMap/`, `BinOutput/`, … — structurally identical
to the layout fairy's `scripts/dimbreath/` toolkit was built against.

**Consequence:** port the toolkit (pinned-SHA fetch, byte cache, `base ⊕ overwrite` TextMap
merge, anchor assertions) rather than rewriting it; the real deltas are the GitLab API and the
Genshin table names. The BRIEF's rule is unchanged and load-bearing given GI's DMCA history:
**committed snapshots only, never a live-fetch gate.**

## 2026-08-21 — Enum vocabulary is read off live payloads, never from memory

**Planner rule.** The BRIEF's domain mapping says Genshin has 5 weapon types. The live nanoka
index says **six** — `WEAPON_CROSSBOW` exists in 7.x. It also carries a literal `"None"` element,
two different rarity encodings (`QUALITY_*` for characters, integer `rank` for weapons), and
internal element names that differ from display names (`GRASS` = Dendro).

**Consequence:** every enum in Chunk C is derived from a committed payload fixture and carries a
provenance comment naming the endpoint and version. This is the same class of rule as the
damage-constant citation rule, applied one layer down: *the agent queries the source; it never
reasons in its place.*
