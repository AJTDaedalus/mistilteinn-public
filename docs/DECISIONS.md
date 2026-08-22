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

### Compute goes to the user's machine; Postgres keeps everything

**Owner ruling, 2026-08-22.** Both the simulator *and* the artifact search run in the
browser. The server keeps Postgres, the retrieval index, and corpus generation. Marginal
compute cost per user is zero.

```
browser:   gcsim WASM  +  search kernel (WASM/WebGPU, on the user's GPU)
server:    retrieval, corpus generation, the API
postgres:  catalogue, inventories, builds, and the simulated-run corpus
```

This is Fribbels' compute model with the persistence Fribbels structurally cannot have —
and it is the combination neither GO, gcsim, nor Fribbels currently occupies.

**The simulator half is nearly free.** Chunk S proved gcsim compiles to WebAssembly, and
upstream *already maintains a browser build* — `cmd/wasm`, `//go:build js && wasm`, exposing
`validateConfig` / `initializeWorker` / `simulate`. That half is adoption, not invention.

**The search half is a rewrite, and it breaks a rule this project has held all along.**

DESIGN §1 A6 says one mechanic, one implementation. A browser search kernel means **two
damage chains that must agree** — precisely the failure mode this repo spent Chunk G
avoiding, most concretely when `build_combination_log` was extracted so the optimizer and the
ranker could not drift. Naming it plainly rather than discovering it later:

- **Accepted, with a specific mitigation.** `tests/crossval` already pins the Python chain to
  gcsim at **1.3e-8 relative**. Extending it to run the same committed cases through the
  client kernel makes the oracle serve both, so "the two chains agree" becomes a gate rather
  than a hope. **The kernel does not ship until that gate exists** — a second chain without a
  test binding it to the first is the whole hazard.
- Pyodide was considered and rejected: it would run the *same* Python in the browser and keep
  one implementation, but it is single-threaded and several times slower than CPython, so a
  9,000-combination search would take **longer in the browser than it currently takes on the
  server**. Fribbels uses WebGPU because that is the only way this is a win.

### What this costs and what survives

Honest accounting, because the ruling lands on top of work finished the same week:

**Survives unchanged** — everything that is data or storage. Domain models, the nanoka
importer, the YuanShen snapshot, the GOOD importer, the catalogue and inventory APIs,
`optimization_jobs`. Client compute changes where the search runs, not where the truth lives.

**Has no production consumer, and should eventually be deleted** — the Chunk F chain and the
Chunk G optimizer.

An earlier draft of this entry claimed they would survive as the reference implementation,
the corpus generator, and the oracle. **Two of those three are wrong**, and the correction
matters because it decides whether a whole subsystem is kept alive for no reason:

- *Corpus generator* — **no.** The corpus is simulated runs, and **gcsim** generates those.
  The chain has no part in it.
- *The oracle* — **no.** gcsim is the oracle. `tests/crossval`'s fixtures are gcsim configs
  and gcsim's own JSON output, so a client kernel can be validated against them **directly**,
  with no Python in the path.
- *Reference implementation* — **no.** A reference nothing runs is dead code.

Everything the server still does — catalogue, GOOD import, builds, retrieval, corpus
generation, auth, Postgres — needs **zero damage math**.

**They do earn their keep through the port**, for one reason that is not sentiment. The
committed crossval corpus is **two cases**. The Python chain is crossval-verified and can
generate expected values for *thousands* of arbitrary inputs — random builds, DEF-scaling
hits, capped crit rate, absent substats — to **differential-test** the kernel against, with
gcsim confirming a sample. Two fixtures cannot catch a kernel that is right on
Ayaka-with-no-artifacts and wrong everywhere else. That is a far denser signal than the
crossval gate alone, and it is the standard way to port a numerical kernel safely.

Then they are deleted when the kernel passes — the rule `app/services/_ported/README.md`
already states and this project already follows: *"delete each file when its port lands."*

**Is genuinely new work** — the kernel itself, and the toolchain for it. G.3's lossless
Pareto layer, budget-K, and G.4's marginal-value ranking are *designs* that port, so the
rewrite starts from a settled algorithm rather than a blank page.

### Consequence: G.10's job runner probably goes too

Named here rather than left to be discovered. `JobRunner` and the hybrid 202 contract exist
to background **long server-side searches**. With the search client-side there is no such
thing to background. `optimization_jobs` may survive to track corpus-generation runs, which
is a genuinely long server-side job — but the optimize endpoint that motivated it would not.
Decide it in the DESIGN doc; do not let it rot as a subsystem nothing calls.

### Open: what the kernel is written in

Not decided here. The live options, with the argument for each:

- **Go** — one WASM toolchain for the whole browser payload, since gcsim is already Go and
  already shipped there. Cost: Go's WASM is large (gcsim's `wasip1` build is 40 MB) and
  carries a GC.
- **Rust** — leanest WASM, mature `wasm-bindgen`, no GC. Cost: a third language in the stack.
- **WebGPU compute shaders** — what the gold standard actually does, and the only option that
  uses the user's GPU rather than one CPU thread. Cost: a compute-shader rewrite, not a port,
  and it is the least legible of the three against DESIGN §1 A6.

Recommendation deferred until the DESIGN doc, because the answer depends on whether the
kernel evaluates candidates one at a time or in parallel batches — which is a design
question, not a language question.

### Fribbels runs entirely on the user's machine — and that is the opening

Verified, not assumed: `package.json` declares
`"homepage": "https://fribbels.github.io/hsr-optimizer"` and `"deploy": "gh-pages -d dist"`.
GitHub Pages serves **static files only**. There is no backend directory; Vite builds a
bundle. `src/lib/gpu/` is **WebGPU** (`webgpuDevice.ts`, `navigator.gpu`), so the permutation
search runs on **the user's GPU**, with `worker/` for Web Workers.

That is a sharper contrast than "GO + gcsim", and it cuts both ways:

- **Fribbels' advantage:** enormous parallelism for free. Someone else's GPU, someone else's
  electricity, zero marginal cost per user. mistilteinn searches on a shared server, which is
  exactly why G.3's Pareto and budget-K layers had to exist at all.
- **Fribbels' structural limit:** with no server it can **precompute nothing, retrieve
  nothing, and hold no state across users or sessions**. Every answer is computed from
  scratch, in a browser, from what that browser already has.

mistilteinn is backend-first with Postgres. The server is the cost; it is also the one
capability the gold standard cannot buy. **That is what makes the retrieval framing load-
bearing rather than decorative** — retrieval needs a server and a corpus, and this project
has both by construction.

### OQ-S1 answered — retrieval does both jobs

**Owner ruling, same day.** Retrieval serves the search *and* the explanation, over one
shared corpus of simulated runs:

```
offline:  gcsim over representative builds -> index by build features

search:   candidate -> retrieve nearest simulated context
                    -> score through the Chunk F chain
                    -> verify the top N by real simulation

explain:  winning build + its contribution log + retrieved runs + kit text
                    -> a grounded "why", citing real numbers
```

The two halves are one system because they share the index. And the split respects §3's
measurement: **the simulator never enters the inner loop** — it populates the corpus offline
and verifies finalists, while the 5.5e-4 s/combination chain does the searching.

The explanation half is why F.5's "a damage number must be able to explain itself" and G.1's
`contributions` log were worth their cost. They were built as a legibility constraint; they
turn out to be the retrieval corpus for the product's second differentiator.

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
