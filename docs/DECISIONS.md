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

---

## Rotations are written by users, in our syntax rather than gcsim's (2026-08-22)

**Owner ruling:** *"Rotations should be built by users, gcsim uses a convoluted rotation
syntax, something more like fairy would be a big improvement."*

This settles what was left of Chunk I. gcsim's action list is a small scripting language —
`while 1 { if .kamisatoayaka.energy >= 80 { kamisatoayaka burst; } … }` — and this project
learned its syntax the hard way while building the ER sweep for D.2: a bare action list runs
**once** rather than looping, and an ungated `while 1` **deadlocks** because gcsim waits for an
action whose energy it can no longer generate. Both produce a plausible JSON with exactly one
burst in it. That is a bad first hour for a user who wanted to compare two artifacts.

**Decision:** users build rotations in a friendlier model of our own, and it **compiles to
gcsim's syntax**. gcsim stays the simulator; it stops being the authoring surface.

**Rejected:** shipping default rotations per archetype and no editor. It was the cheaper half
of the BRIEF's plan and it answers a different question — "what does a typical Ayaka do" rather
than "what does *mine* do" — and the whole client-optimizer design turns on team and rotation
being the user's inputs.

**Consequence:** a compiler is a place two representations can disagree, so it needs the
treatment every other translation layer here got: the emitted config is fed to real gcsim and
checked, the way `npm run gcsim:verify-config` already checks emitted configs. A rotation
editor that produces a config gcsim silently misreads is worse than gcsim's own syntax.

**Not decided here:** whether the rotation ever becomes something to *optimize*.
`DESIGN_client_optimizer.md` §3.5 warns that doing so reopens the entire client-side cost
argument, since it rests on the rotation being an input. Authoring is not optimizing.

---

## The visual identity is Mitya's, and Mitya is not in it (2026-08-22)

**Owner ruling:** *"Visual identity should be themed after the character Mitya … The character
itself shouldn't be included in the design, but his color schemes, patterns, and ornament
should be. I think the ornament, prettied up a little bit, would make a nice logo like the
fairy 'eye' does for fairy."*

**Decision:** the palette is sampled from `references/mitya.png` and
`references/mitya_ornament.png`, and the mark is his ornament drawn as geometry.

**The palette is derived, not chosen** — the same method fairy used on `NPC_Fairy.webp`:
cluster by hue family and take each band's most saturated quartile, because the rest of a band
is shading and averaging it in produces mud. Ground `#1c2334` from the coat's darkest
*chromatic* pixels, so the grey studio backdrop cannot leak in; brass `#ddae21` and amber
`#c59732` from the ornament's metal and cabochon; azure `#38a6d2` from its gems; mint `#80bec6`
from the tassels; ink `#d5d6e1` from his hair.

**Two accents, not one.** Fairy leaned monochrome and let a cyan halo carry all emphasis.
Mitya's palette has a warm family and a cool one, so warm carries identity and action and cool
carries data and state. Keeping them apart is what stops it reading as generic fantasy-purple,
and it maps onto something real: a damage number and a button are different kinds of thing.

**The mark is drawn, not traced.** A trace of a game asset carries that asset's licence and its
rendering artefacts into the app, and silts up at favicon size. The ornament *is* three
crossing ellipses with nodes at their tips, so drawing that structure reproduces it exactly and
scales to 16px. Its nodes are placed at the computed orbit tips rather than by eye — the first
draft eyeballed them and rendering it showed beads scattered near an atom rather than one
device.

**Consequence:** the mark exists twice — once in the component reading tokens, once in
`favicon.svg` with literal colours, because a favicon renders where no custom property
resolves. `tests/unit/test_emblem_matches_the_favicon.py` asserts the two agree node-for-node,
since two copies of a mark is otherwise two marks.

---

## Deploy alongside fairy on the same host (2026-08-22)

**Owner ruling:** *"Deployment should target the same server as fairy, I'd like them to co-exist
if possible on aetherus.dev as fairy.aetherus.dev and mistilteinn.aetherus.dev."*

**Decision:** one host, two stacks, two subdomains. The groundwork is already laid and was laid
for this reason: A.4/A.5 moved this stack's host ports to **8001/4201** so both run at once, and
A.6 put the `mistilteinn` databases inside fairy's existing Postgres container rather than
standing up a second one.

**The known hazard is recorded and must not be re-introduced.** Chunk A found that joining
fairy's compose network registered this backend under the alias `backend` on `fairy_default`,
where fairy's own `backend` service already lives — so fairy's tunnel would have intermittently
served mistilteinn's API. Co-existing means **reaching the shared Postgres over the host
gateway**, never joining that network. Anything in the deploy work that joins it is wrong for a
reason that is invisible until traffic is served to the wrong app.

**Spelling:** the ruling wrote *mistelteinn*; the repo, the database names and
`security/zap/` all use **mistilteinn**, and `.github/workflows/deploy-prod.yml` was deleted in
the fork commit precisely so nothing would deploy under a half-migrated identity. Using
`mistilteinn.aetherus.dev` — flagged rather than silently corrected.

---

## OQ-R1 — a rotation belongs to a team (2026-08-24)

**Decision:** `rotations.team_id`, not `build_id`.

A rotation names *several* characters acting in turn; a `Build` is one character with its
weapon and artifacts, so a rotation cannot belong to one. The team's builds supply the stats
for whoever is being simulated.

It is also what the code already assumed: `sim_context.context_key` hashes `team` and
`rotation` together, so the pairing existed at the cache layer before the schema admitted it.
fairy attached combos to a team for the same reason, and the owner named fairy as the model.

**Consequence:** `team_id` cascades. A rotation without its team is not a partial rotation, it
is an ordered list of characters nobody can place — a row that can never compile and no screen
could sensibly show.

**Also decided here:** `RotationUpdate` has **no `team_id`**. Moving a rotation between teams
would reinterpret every step against a different party, and the steps that stopped resolving
would surface later, at compile time, far from the edit that caused it.

---

## OQ-R2 — a step names a character, and a stale rotation is refused (2026-08-24)

**Decision:** a step carries the character's `nanoka_id`. Not a slot, not a build.

**Not a slot**, because slots are positional: reordering the team would silently change what
the rotation means, and a rotation that quietly becomes a *different* rotation is worse than
one that visibly breaks.

**Not a build**, because a build is a loadout. Swapping which Ayaka build sits on the team
should not invalidate a rotation that says "Ayaka bursts".

A `nanoka_id` is stable across both, and is what the compiler needs anyway to reach a gcsim
key.

**When the team loses that character, the rotation goes stale and is refused** — named steps
and all — rather than repaired. The alternatives were to drop the offending steps, which
deletes a user's authored work so an operation can succeed, or to reinterpret them against
whoever now occupies the position, which is the silent-wrong-answer this repo refuses
everywhere else. Saying no, and naming exactly which steps, leaves the user in control.

This is D.3's rule applied one layer up: an outcome the caller must act on is **stated**, not
silently substituted.

## Rotations are authored, never optimized (2026-08-25)

**Owner decision.** Searching over rotations will not be built.

`DESIGN_rotation.md` §5 had left this open on **cost** grounds — making the rotation an output
multiplies the search by the space of action lists, against a gcsim run costing ~4,700× one
damage-chain combination under WASI (Chunk S). A design pass was queued to decide whether that
was affordable.

It is settled on different grounds, which is why the design pass is cancelled rather than
deferred: **a user writes a rotation deliberately, and one arrived at by search is not a
rotation they would recognise as theirs.** Authoring is the product; the rotation is an input
to the optimizer, not an output of it.

What this closes: the remainder of Chunk I in `TASKS_mistilteinn.md`, and the queued design
pass. Nothing in the tree changes — the boundary was already where this decision puts it.

## Weapon passives go to gcsim as a second tier (2026-08-26)

**Owner decision**, resolving the N.5 escalation in `docs/LOG_mistilteinn.md`.

`weapon_comparison` ranks candidates on base ATK and the substat alone, and reports every
candidate with a passive as `unmodelled_passives` — not as a precision caveat but because
**the ordering itself can be wrong**. N.5 measured the gap: **242 of 260 weapons carry a
passive and 5 are expressible in the Chunk F chain as it stands.** The other 237 need target
aura, enemy type, weak spots, stack counters, cooldowns, party energy or durations — none of
which the chain models, and nine of them ask questions `KernelTarget` cannot express at all.

Three options were put up. The chosen one is **route the comparison to gcsim as a second tier
above the damage chain**, rather than building a conditional modifier model or accepting the
gap permanently.

**Why this and not the modifier model.** gcsim already implements these passives — 231
directories of Go — and deriving 237 conditions from English refinement prose is precisely the
fabricated-citation failure fairy actually suffered. The BRIEF's citation rule is not
satisfied by a careful reading of a tooltip.

**Why this does not contradict `RESEARCH_gcsim_embed.md` §6.** §6 ruled gcsim out of the
**optimizer's inner loop** at ~430× a damage-chain combination, on a 9,000-combination
artifact search. Weapon comparison is not a search: it is one evaluation per candidate, at
most 59 (the sword pool). §6's conclusion — *"gcsim is a second tier above the chain, not a
replacement for it"* — is the thing being applied here, not the thing being overturned.

**What §6 does not settle, and what a measurement changed.** The escalation quoted §6's
**native** figure of 0.238 s/run and inferred ~14 s for 59 candidates. That figure is gcsim
parallelised across cores. Measured against the committed browser build at the pin, a
100-iteration 90-second rotation costs **7.84 s single-threaded** — so 59 candidates is
**~7.7 minutes**, not 14 seconds. The decision stands, because the run is already an
asynchronous, user-initiated action and the `sim_runs` corpus already exists to cache it —
but **the interaction is a job with progress, never a request that blocks**, and how far
parallelism and iteration count close that gap is `DESIGN_weapon_passives.md`'s to settle.

**What this closes:** the two surviving `TODO(chunk-H)` markers now have a destination. They
are re-pointed at this work rather than deleted, because the gap they describe is real until
it ships.

## The nanoka pin stays at 7.0.51 (2026-08-26)

**Owner decision.** Upstream is at 7.0.52; nothing here needs it, so the pin holds and is
revisited when a wanted character or weapon is actually missing.

The pin is not a stale checkout: the committed fixtures, `nanoka_transport.FIXTURE_VERSION`
and `verify_seed.FIXTURE_VERSION` all name the same version and
`tests/unit/test_capture_pinning.py` fails if they stop agreeing. The trap it guards is real —
in N.2 a capture run **without** `--version` silently followed upstream, pulling two characters
at 7.0.52 into a 7.0.51 tree and rewriting three index files, one with real content changes.

## Weapon passives are ported from gcsim's Go, not simulated (2026-08-26)

**Owner decision**, superseding the delivery half of the 2026-08-26 gcsim-tier decision above.
That one stands for the **comparison page**, which ships and works. This one is about the
**optimizer**, which the gcsim tier was never going to reach.

**The measurement that forced it** is `docs/RESEARCH_gcsim_speed.md`: **86 % of a gcsim
iteration is the frame-by-frame combat simulation**, so the stacked ceiling on making it
faster is about **4×** — a worker pool plus, optimistically, stripping the stats collectors.
A gcsim config at 100 iterations is **~8,900× `SECONDS_PER_COMBINATION`**. Four orders of
magnitude are needed and one is available, so `RESEARCH_gcsim_embed.md` §6's ruling is not
going to be overturned by tuning.

Meanwhile the optimizer has the gap the comparison page just closed, and **does not report
it**. `weapon_refinements` is read by exactly one module, only to report. `Redhorn
Stonethresher` makes DEF genuinely valuable and **the artifact search will never once consider
DEF**, returning a confident five-piece answer that is wrong with nothing suggesting doubt.

**So the passives are ported into the Chunk F chain — from gcsim's Go source.**

**Why this is not the option N.5 rejected.** N.5 rejected a conditional modifier model on
**fabrication risk**: deriving 237 conditions from English refinement prose is the failure
fairy actually suffered. **Reading gcsim's Go is a primary source.** The citation rule objects
to inventing mechanics from a tooltip, not to porting an authoritative pinned implementation —
and unlike a tooltip reading, a port can be *proved*: `tests/crossval` recomputes a committed
gcsim run, so each ported passive is checked numerically rather than trusted.

**Why the timeline objection is smaller than N.5 argued.** N.5 said durations and cooldowns
only mean something on a timeline, and this repo compiles rotations rather than simulating
them. But **the rotation is authored and known**: uptime for a duration or a cooldown can be
evaluated against a compiled action list. Monte Carlo is not required to know when a burst
happens in a rotation the user wrote.

**What is still out of reach, and stays out:** passives conditioned on **target state** —
aura, enemy type, weak spots. `KernelTarget` is level, resistance, DEF reduction and DEF
ignore, so those are unaskable questions rather than unported ones, and growing it is not in
this decision.

---

## 2026-08-28 — Three rulings on optimizer reach (owner)

Answers to the open questions in `docs/DESIGN_optimizer_reach.md`. Two of them reshape Track A
rather than settling a detail inside it, so the plan is revised, not annotated.

### 1. The conditional 2-piece sets are calibrated from the start

Nine of sixty 2-piece bonuses carry no static `add_props`; six are ability-scoped — Noblesse
burst +20 %, Marechaussee normal/charged +15 %, Golden Troupe skill +20 %, Long Night's Oath
plunging +25 %. A flat stat pool cannot say "only on burst hits".

**Ruling: calibrate them, from the first version of 2+2.** Not offered-but-flagged, and not
excluded. gcsim applies the real bonus; the cost is one extra calibration per conditional set
the user selects, at most nine.

This is the same answer the 4-piece work reached, for the same reason: the authority on a
conditional bonus is the simulator, not our reading of the tooltip. It also means the interim
state the plan proposed — selectable, flagged `unmodelled` — never exists, so no user ever
sees a 2+2 score that silently omits the bonus they picked the set for.

### 2. Only complete calculations are offered

**Ruling: no partial results, and no early stop.** A ranking is shown when it is complete for
what was asked, or it is not shown.

This **removes** the plan's streaming leaderboard and its stop-early contract. Progress
reporting stays — progress is not a result — but there is no point at which a user is handed a
top-10 that might be displaced by a state still calibrating.

**What it costs, stated plainly:** the wait can no longer be papered over with early output, so
throughput is the only lever left. Parallel calibration and probe-once stop being nice-to-haves
and become the whole of Track A.

**Why it is right anyway:** a partial ranking is the failure mode this repo keeps legislating
against. `isExact`, `uncoveredSets`, `unmodelled_passives` all exist because *a confident answer
to a question nobody asked* is worse than a slower one. A leaderboard that reorders while you
read it is that same hazard wearing a progress bar.

### 3. The set filter defaults to nothing selected

**Ruling: no sets preselected.** The user picks before a search runs.

This is what makes ruling 2 affordable. Defaulting to all 35 sets means ~3.8 min before any
output, which is intolerable once partial results are gone; a user picking three sets pays four
calibrations and gets a complete answer in well under a minute. Scope is narrowed by the person
who knows what they want, rather than the wait being hidden by streaming.

**The known cost, accepted:** a user who does not already know which set suits their character
has no default to lean on. The picker mitigates this rather than solving it — it already shows
how many distinct slots of each set the user owns, most-owned first — but this is a real
trade and is recorded as one, not smoothed over.

---

## Frontend validation (2026-08-28)

### 4. The catalogue art is committed

**Ruling: `frontend/public/icons/` goes into the repository.** This reverses OQ-N1, which
gitignored it on the reasoning that "~475 images, ~10 MB … fairy committed its 207; a
repository is not a CDN, and the script is the reproduction."

**What that decision cost.** Production served no art at all, and had done since K. Nothing
on the prod box had ever run `download_icons.py`; `Dockerfile.prod` copies a tree where the
directory did not exist; nginx's SPA fallback answered every `/icons/*.webp` with
`200 text/html`; and `CatalogueIcon` hid each failed `<img>` exactly as designed. Four layers
each behaved correctly and the compound result was a silently art-free site. It was found by
asking for the `content-type`, not the status code — `curl -I` on a basename that does not
exist returns the same `200 text/html` as one that does, so *the status code could never have
detected it.*

**Why the original comparison inverted.** It weighed 475 files against fairy's 207 and
concluded this set was the larger. Measured: **446 distinct files at 9.6 MB**, against
fairy's **207 at 27 MB**. Genshin's icons are small; ZZZ's are not.

**907 files at 33 MB as of the enemy art** — character portraits and monster icons were added
after this ruling and did not reopen it. The decision was about whether the art belongs in the
repository, not about a byte count, which is why the guard is a floor and a git query.

The set we declined to commit was about a third the weight of the one already committed one
repository over.

> **Superseded 2026-11-10 by §34:** the art is gitignored again, and prod fetches it at deploy
> time. The incident above is why that deploy step probes a content type.

**What stays.** `scripts/download_icons.py` is still the reproduction and `--check` is still
the audit — nothing about how the art is *obtained* changes. `tests/unit/test_catalogue_art_is_committed.py`
is the executable version of this ruling, and deliberately needs no database: it asks git
whether the files are tracked, which is the question CI can always answer.

**The known cost, accepted:** every future patch adds files to the repository rather than to
a build step, and a patch that retires art leaves it behind until someone prunes. That is the
trade for a deploy that cannot silently ship an empty directory.

### 5. Art belongs on the working pages, not only the catalogue

**Ruling: anywhere the app names a character, weapon or artifact set, it shows the icon.**

The art existed and reached only `/characters`, `/weapons` and `/artifact-sets` — the three
read-only pages. Builds, teams, rotations, optimize, compare and explain, which is where the
time is actually spent, rendered everything as bare text. `BuildRead.character` is a
`CharacterSummary` and has carried `icon` the whole time, so this was never a data problem;
nothing drew it.

---

## Inventory and GOOD import (2026-08-28)

### 6. Roll counts are derived, and refused where the arithmetic is ambiguous

**Ruling: show a roll indicator only where one count fits; show nothing otherwise.**

Genshin publishes no roll count — a substat is a *sum* — so it is reconstructed by
decomposing the total over the values the stat can roll. The approach is Genshin Optimizer's
(MIT, `libs/gi/util/src/artifact/artifact.ts:getSubstatRolls`), reimplemented against this
repo's committed tables: **match on the value as the export displays it, not within a float
tolerance.** Over the owner's real 2,370-artifact export, 85.0% of substats decompose exactly
one way, 10.2% more agree on the count, 4.8% match nothing.

**Where several decompositions disagree on the count, nothing is drawn.** A roll count is the
number people judge an artifact by; a confident wrong one is worse than an absent one. A bar
of *unknown* tier renders neutral rather than as tier 0, because "the worst roll" and "we do
not know which roll" are different claims.

**The known cost:** a heavily-rolled substat is exactly the one most likely to be ambiguous,
so the indicator is least available where interest is highest. `roll_value` — the line as a
multiple of one best roll — needs no decomposition and covers that gap.

### 7. GOOD import defaults to `replace`, and asks before deleting

**Ruling: `replace` is the default** (owner, 2026-08-28), reversing the earlier "chosen, never
defaulted". GOOD carries no stable per-artifact id, so `append` on a re-scan of one account
duplicates every piece — which is what an empty default was steering people into.

**With a confirmation when the inventory is non-empty.** A scanner that dies half way writes a
*valid* GOOD file holding a fraction of an inventory, so the destructive reading being right
for the common case does not make a one-click irreversible path right.

### 8. Builds are reconstituted from GOOD; teams are not

**Ruling: import builds, never teams** (owner, 2026-08-28). GOOD has no concept of a team, so
one would have to be invented; a team is assembled from builds on `/teams`.

**A build for each character actually holding a weapon or an artifact.** An export lists every
character an account owns — 89 in the reference file, including GO's practice mannequins,
which are out of scope by owner ruling. Equipping is the signal that separates the six a user
plays from the eighty they do not, and it excludes the mannequins without naming them.

**Existing builds are never overwritten.** A re-import refreshes the inventory; a build carries
decisions no scanner knows about.

### 9. OPEN — the Traveler wears one artifact set across seven elements

**Owner's model, and it is the right one:** a build per elemental Traveler, each keeping its
own level, constellation and talents, all *sharing* one set of artifacts. The game works that
way and the export agrees — talents arrive per elemental entry (`TravelerCryo` has its own
`talent` block) while artifacts carry only `location: "Traveler"`, with no element and no
gender.

**It cannot be expressed yet, and this is why.** `artifacts.build_id` is single-valued and
`uq_artifacts_build_slot` enforces one piece per slot per build, so seven builds cannot wear
the same five pieces. The options:

| | cost |
|---|---|
| duplicate the artifact rows | inflates the inventory and lets the optimizer award one physical piece to two characters — the failure `_restore_equips` already guards against |
| a nullable `artifacts_from_build_id` on `Build` | a migration, plus every reader of a build's artifacts (damage chain, optimizer, explain, the build editor) learning to follow the link |
| a build↔artifact join table | the general fix, and the largest — it changes what "equipped" means everywhere |

**Not chosen.** Until it is, the import creates the one Traveler the export actually describes,
picking the lowest `nanoka_id` for the gender the export cannot record and saying so in the
build's notes.

---

## 21. The rotation library: four rulings

**Owner, 2026-08-29**, answering `docs/DESIGN_rotation_library.md`'s open questions.

**OQ-1 — importing a gcsim config we cannot fully express: refuse, and add a converter.**
Keep refusing anything still unexpressible, but first rewrite what is mechanically
translatable: `for … { }` → `while 1 { }`, and comma-separated action sequences into one step
each. The evidence for this is measured rather than assumed — putting the real community
config `skirk_team.txt` through the importer showed the blockers were the *loop keyword and
the sequence syntax*, not the conditional guards the design worried about. A converter is a
much smaller idea than "lossy import" and would have carried that file most of the way.
**Nothing is silently dropped either way**: whatever the converter cannot express is still
refused, by line.

**OQ-2 — mirroring gcsim's own rotation database: out of scope.** Those rotations are
submitted by other people under terms this repo has not established, and republishing them is
not obviously ours to do. Users import the individual configs they choose.

**OQ-3 — likes are a count.** A number, plus whether *you* liked it. No social graph and
nothing to moderate.

**OQ-4 — sharing requires explicit publishing.** Private by default. A private rotation
becoming visible by default is not a mistake that can be taken back, and instance-wide
visibility would retroactively publish everything already saved.

---

## 22. Artifact ranking runs on the rotation engine, not on a weights table

**Owner, 2026-08-29**, answering `docs/DESIGN_artifact_ranking.md`'s open questions — and
**overruling the plan's own proposal**, correctly.

**OQ-A1.** The plan proposed deriving substat weights as finite differences over the Chunk F
damage chain: better than Fribbels' curated per-character weights, because it is measured
rather than asserted. The owner's answer goes further and is the right question:

> *"Calculated via our gcsim-like optimizer. It should be the engine beneath ranking too. 'How
> much potential does this artifact have given this character in this team with this rotation?'
> With the same efficiency tweaks we did for optimize."*

A single-hit derivative cannot see a team buff or a rotation's shape, and those are most of
what decides whether Energy Recharge or CRIT DMG is worth more on a given piece. The recipe
engine already answers the real question — and **already has the performance shape this needs**:
a recipe is calibrated once per 4-piece state, after which evaluating one candidate's stats is
cheap. That cost is amortised across the whole inventory rather than paid per artifact.

So ranking is not a new engine. It is the optimizer's evaluator asked a different question:
instead of *"which five pieces score highest"*, *"what does this one piece score, and what
could it score once levelled"*.

**OQ-A2 — score against a build**, not a character at an assumed baseline. Its real weapon,
constellation and talents. A character with no build cannot be scored for, which is honest.

**OQ-A3 — numbers and grades.** Both. Grades are what make Fribbels scannable at thousands of
items; the caveat that an "A" for one character is not an "A" for another is real and belongs
in how they are labelled, not in refusing to have them.

**OQ-A4 — a distribution, following Genshin Optimizer rather than Fribbels.** Fribbels reports
a deterministic average/best/worst; GO shows a distribution per artifact, and the owner judged
that better. `docs/RESEARCH_genshin_optimizer_scoring.md` is the audit of how — a lazily
expanded tree, delta method at the coarse levels and exact enumeration at the leaves, **no
Monte Carlo anywhere**. This remains the largest new piece and the one with no crossvalidation
oracle behind it.

**A1 and A4 look incompatible and are not**, which is worth recording because the audit itself
flags it: GO's method needs a differentiable, microsecond-cheap objective, and *gcsim is
neither*. But A1 does not name gcsim. A recipe is a **transcription** of gcsim's own per-hit
decomposition, verified exact to 0.000e+00 across 245 hits and replayed as closed-form
arithmetic at **0.051 µs per hit**, with crit computed rather than rolled. It is deterministic,
cheap, and smooth but for the `effectiveCritRate` clamp — which is the same kink GO's own
objective has. **The engine A1 chose is the objective A4's method requires.** Anything that
reaches for gcsim itself inside the ranking loop has left the design.

## 23. The team reaction filter offers the base reactions only (2026-08-29)

**Owner ruling:** *"You can leave out lunar and stellar variants, just the base reactions
(minus shatter) is fine."*

`docs/RESEARCH_elemental_reactions.md` transcribed **21** reactions from the wiki's own wording.
The filter offers **fifteen** of them — every reaction a Genshin player would name — and
excludes six:

- **Shattered**, because it is not an element pair. The source says *"a Blunt or Geo attack"*
  and Blunt is Physical, so `{Cryo, Hydro}` over-counts teams and adding Geo under-counts them.
  There is no element set that is right, which is a different problem from a missing one.
- **The five Lunar/Stellar rows**, by this ruling.

**Four of those five were already excluded as uncertain, so the ruling really decides one
row: Lunar-Bloom.** That is the only Lunar/Stellar reaction whose party gate the source states
outright, so it would otherwise have been offered on certainty alone. Excluding it is a
judgement about what a *team filter* is for — narrowing a list of saved teams — and not a claim
that the reaction does not exist.

**Everything excluded stays in the committed JSON with its citation.** An exclusion that
deletes its own evidence reads as an oversight to the next person, and cannot be reversed
without redoing the research. The code matches on the `lunar_`/`stellar_` id prefix rather than
on a `category`, because the research's categories describe how a reaction *works* —
amplifying, transformative — and this is a decision about which ones a player names.

## 24. The rotation library shares by publishing, and does not yet rank (2026-08-29)

`TASKS_rotation_library.md` Tracks A and B, built in #177. Three things were decided while
building rather than before, and each is the kind that would otherwise be re-litigated by
whoever reads the code next.

**A second repository, not a mode on the first.** `RotationRepository` is owner-scoped, and
that scope is what stops one user reading another's work. Adding a "sometimes ignore the owner"
flag to it would put the check and its exception in the same object, where the exception
eventually wins an argument it should not be in. `RotationLibraryRepository` is scoped to
`visibility == published` instead, in one `_published()` method for the same reason `_for_team`
exists — two hand-written filters are two chances to forget one, and the half that forgot would
be the one reporting `total`.

**The character index is rebuilt whole on every write, never diffed.** A diff would be a second
implementation of "what characters does this rotation name", and the two would eventually
disagree — at which point the library offers a rotation for a team it cannot run on, which
reads as a bug in the search rather than in a stale index. The cost is one delete and a handful
of inserts on a rename, which buys a guarantee rather than an optimisation.

**The listing sorts newest first and says nothing about DPS**, which is *not* what
`DESIGN_rotation_library.md` §3 promises. The design says "DPS where this user has run it, then
likes"; `sim_runs.context_key` is a hash whose own docstring forbids querying by its parts, so
there is currently no way to find a user's runs for a rotation. Shipping an ordering that
claimed to be by DPS while being by date would be worse than shipping neither.

The fix is two nullable label columns — `rotation_id` **and** the rotation's signature — and
the second one is the point: a rotation is editable, so `rotation_id` alone would sort it by a
number computed for a previous version of itself. That work is named in the TASKS file rather
than done here.

## 25. ~~OPEN~~ ANSWERED — the run corpus has no producer, and the two candidates disagree (2026-08-29)

Found while building #179's DPS ordering, which needs a `sim_run` to exist before it can sort
by one. **`POST /api/v1/sim-runs` has zero callers in `frontend/src/app`.** The endpoint, the
repository, the ER bucketing, the divergence measurement and the coverage query are all built,
tested and CI-gated. Nothing writes to them.

### The design named a producer, and it cannot submit what the corpus stores

`DESIGN_client_optimizer.md` §"What the server-side corpus is actually for" says it
*"accumulates from real searches"* — the context runs the rotation objective performs before
searching artifacts. That is the right shape and it does not fit:

| | |
|---|---|
| what the search calls | `mod.sample(config, SEED)` — a **per-frame log**, one seed |
| what the corpus stores | `result` with `statistics.dps.mean`, read by `dps_mean_of` |

`sample()` is what a **recipe** is built from, and the reason
`RESEARCH_gcsim_calibration.md` could prove the decomposition exact. It is not an aggregate and
carries no `statistics` block. A search therefore has nothing to submit that the schema means.

### The question, and why it is not mine to answer

**Either** the search performs an *additional* aggregate `run()` per context purely to fill the
corpus — measured at ~3.13 s per run in DESIGN's own table, six ER buckets per context, so
seconds added to every rotation search for a benefit the searcher does not receive —

**or** the corpus stores what calibration actually produces, which changes what a `sim_run`
*is*: no longer "what gcsim reported for this context" but "the sample a recipe was built
from". `dps_mean_of`, `SimRunCoverage.dps_means` and the divergence measurement all read the
aggregate, so this is a schema change and not a widening.

Both are defensible. They cost different things and they mean different things, and picking one
by implementation convenience is how a cache ends up holding numbers that do not answer the
question its column names claim.

### What is true meanwhile

`your_dps` in the rotation library is correct and returns `None` for everyone, because there is
nothing to order. That is the honest state and it is recorded in `TASKS_rotation_library.md`
rather than hidden by a placeholder.

### Answered the same day: **searches fill it** (owner)

> Make searches fill it.

So the rotation search now performs one aggregate `run()` and submits it. Three things fell
out of building it that the question above did not anticipate, each recorded because each was
invisible until something used the path:

**It is one run per *search*, not per calibration target.** A `sim_run` is keyed by context —
character, weapon, team, rotation, target — and **not** by artifacts, while calibration targets
differ only by artifact set. So the set-free baseline target is the one that answers for the
context; running one per target would store a set-specific number under a set-independent key.
Measured on the owner's real four-character 90-second rotation: `sample()` 4.13 s and a
calibration does two, against `run(100)` at 11.56 s **once**.

**The stored number was going to be null on every row.** `dps_mean_of` read
`statistics.dps.mean`, taken from a native-CLI fixture. The browser's wasm returns `{"stats":
…}` and nothing else at the top level, so every submission would have been accepted and stored
without its headline figure — a corpus that filled up and still sorted nothing. There were no
tests for that function at all; there are now, one per shape, each with its evidence.

**The pin being submitted was not a pin.** `calibrateAll`'s third argument was called
`gcsimPin` and the optimizer passes the *artifact inventory snapshot version* through it — fine
as a cache discriminator, and rejected with a 422 by a field validated as 40 hex characters.
The submission now takes the pin from the context key it belongs to, and the parameter is
called `cacheEpoch`.

**And the stability warning was unreachable.** `stabilityFrom({})` returns `stable: true`, so
the optimize page rendered *"the rotation did not run the same way every iteration"* for a
condition nothing could produce. The aggregate that fills the corpus also measures it — and on
the owner's real rotation it **fires**: `skill`, `burst` and `swap` all vary beyond the 2 %
tolerance. One run, two answers.


## 26. A gcsim re-pin no longer empties the run corpus (2026-08-29)

Owner ruling:

> a prior version of gcsim likely doesn't mean much for a rotation. It is rare for existing
> characters to change behavior, especially in game. If a rotation did change performance,
> it'd likely be because of a bug found in gcsim.

`SimRunRepository.get` required all three of `(context_key, er_bucket, gcsim_pin)`, on the
argument that *"a lookup that omitted the pin would happily return a result from a different
simulator, which is the failure this cache is keyed to prevent."*

**That argument defeats silence, not reuse.** The objection was to serving another build's
number without saying so — and the pin is stored, returned, and visible on every row. What it
should not do is discard the whole corpus on a re-pin: for a demand-driven cache that means
every user re-simulating everything they had, to avoid a difference that is usually zero and,
when it is not, is usually a gcsim bug fix rather than a change in the game.

So the exact pin still wins, and `any_pin=True` will settle for the newest older one rather
than nothing. Ordered by `created_at`, because a pin is a commit hash and carries no order of
its own.

**What is deliberately not done:** the pin is still part of the *uniqueness* constraint, so a
re-pin writes a new row rather than overwriting. Two builds' answers for one context coexist,
which is what makes "served from an older pin" a statement anyone can check.


## 27. Rotations may repeat a chunk, because unrolling costs no grammar (2026-08-30)

**`DESIGN_rotation.md` §2 refused nesting and gave its reason: *"Nesting buys terseness and
costs a grammar."* The owner reopened it during the GUI design pass and amended it rather than
routing around it** — which is the whole point of the ruling, since the alternative on offer was
to argue that an unrolling group had never been nesting in the first place.

**What changed is the evidence, not the appetite.** The reason §2 gave is a claim about cost,
and the cost turns out not to be paid. A group carries a repeat count; the compiler emits its
steps `n` times into the flat `while 1 { … }` body it already emits. gcsim receives
character-for-character what it receives today, so the grammar §2 was protecting — **gcsim's
parser, and this repo's ability to reason about what it hands over** — is untouched.

**Two limits are part of the ruling, not implementation detail.** A group holds a count and
nothing else: no condition, no group inside a group. And unrolling happens **before**
`rotation_signature` and `compile_rotation`, so a grouped rotation and its unrolled equal
produce the same `context_key` and share one cached run. Those two functions already share
`_resolve` precisely so that a signature and a config cannot describe different things; the
unroll goes in front of both for the same reason.

**Copy/paste is not the alternative to this and never was.** §2 offered "a UI can duplicate a
selection" *in place of* nesting, and it is built alongside groups instead (owner, same day):
a group says *this chunk repeats*, copy/paste says *this fragment is reusable somewhere else*.
Separate uses, and §2's promise is kept either way — it had gone unkept for six months.

**What this does not license.** §2's other two refusals stand exactly as written. Branches are
still refused, and the argument made here is available to anyone who wants one: they would have
to show that the cost §2 names is not paid, and for a conditional it plainly is — gcsim would
have to parse it, or this repo would have to evaluate it.

## 28. The browser simulator is built into the production image (2026-08-30)

**"Optimize with rotation" had never worked in production, and nothing said so.**

`frontend/gcsim/{gcsim.wasm,wasm_exec.js}` are gitignored — 40 MB, with `PROVENANCE.md`
arguing the pin and the recipe are what belong in a repository. `angular.json` copies them
into the bundle **if they exist**, and an asset glob that matches nothing is not an error. So
the production image, built from a clean checkout, contained no simulator; nginx answered
`/gcsim/wasm_exec.js` with the SPA fallback at **`200 text/html`**; and every rotation optimize
died with *"could not load gcsim/wasm_exec.js"*.

Four layers each behaved correctly. The build was green, the deploy was green, the health check
passed, and the status code was 200. **This is `DECISIONS.md` §4 again** — the icons served as
`200 text/html` for months — and it is the same lesson: *a basename that exists and one that
does not both return 200, and only the `content-type` differs.*

**The artifact is built in the image rather than committed.** §4 reversed the icons decision on
measurement — 446 files at 9.6 MB against fairy's 207 at 27 MB — and that measurement does not
transfer: this is a single 40 MB binary that changes wholesale on every re-pin. A Go stage in
`frontend/Dockerfile.prod` clones gcsim at the pin and builds it, which costs a slower deploy
and no repository weight.

**The pin is read, not restated.** The stage copies `docs/CROSSVAL_gcsim.md` — the one document
that owns it — and greps it with the same expression `scripts/build-gcsim-wasm.sh` uses. That
is why the frontend's production build context is the repo root: a build arg or an environment
variable carrying the pin would be a second definition of what "correct" means, which
`tests/unit/test_gcsim_pin_is_single.py` exists to prevent — and which it now actually covers,
having read only the build script until this change added a second reader.

Copying only that one document keeps the layer's cache key **narrow, not exact**: the key is
the document's whole content, so a prose edit to it re-runs the clone and the 40 MB build with
the pin unchanged. That is a slow deploy rather than a wrong one, and cheaper than a second
file carrying the pin that could disagree with the one that owns it.

**Two guards, because the failure was silent at both ends.** The image refuses to build a
bundle that does not carry the simulator, since an asset glob matching nothing is exactly what
hid this. And the deploy asserts the **content type** of what production serves — not the
status code, which was 200 throughout and could never have caught it.

**Three things review caught that would have made this worse than the bug it fixes.** The
widened context pulled `./postgres-data` — the live database, uid 999 mode 0700 — into the
build, which the runner cannot even stat, so the deploy *and its rollback* would both have
failed. The CSP is `script-src 'self'` with no `'wasm-unsafe-eval'`, so shipping the artifact
would have moved the failure from the fetch to the compile and left the feature just as dead.
And `/gcsim/` had no `try_files $uri =404`, which this very nginx file's comment instructs for
"any future directory of static assets" — `.js` is a Cloudflare default-cached extension, so a
deploy window would have poisoned the edge for hours.

The pin claim above is also now true rather than aspirational: `test_gcsim_pin_is_single.py`
covered only the build script, so a hard-coded SHA in the Dockerfile would have passed green.
It reads every pin reader now, and the parametrised check was proven to fail on one.


## 29. The deploy checks what the edge serves, not only the origin (2026-08-30)

§28 added a content-type gate to the deploy, and it passed while the feature was still broken
for users. Measured minutes after that fix reached production:

    gcsim/wasm_exec.js   cf-cache-status: HIT       age: 2361   content-type: text/html
    gcsim/gcsim.wasm     cf-cache-status: DYNAMIC               content-type: application/wasm

**The gate probes the origin.** It runs `wget` inside the frontend container against
`127.0.0.1`, which is the right thing to assert about a deploy and is blind to Cloudflare — and
Cloudflare is where the failure lived. `.js` is a default-cached extension and `.wasm` is not,
so the edge held the pre-fix SPA fallback for four hours after the origin was correct.

This is the second half of the icons incident, and `nginx.prod.conf` had already written it
down: *"`content-type: text/html` at `age=4422` while the origin had the file."* §28 applied
that lesson to the origin and stopped there.

**A warning rather than a failure.** The origin is what a deploy controls; an entry cached
before a fix is real, is not that deploy's fault, and expires on its own. Failing would block
every deploy in the window over something already fixed. The actionable half is saying so and
naming the purge.

**And the origin now prevents recurrence**: `Cache-Control: no-cache` on `location /gcsim/`
means the edge revalidates rather than holding a copy for four hours. This warning exists for
the entries cached *before* that header existed, and for the next asset directory that gets
one late.

**Worth recording plainly:** the stale entry was populated by a diagnostic `curl` against the
public hostname while the origin was still broken. Probing production through the CDN caches
what production is currently serving — including its failures.

## 30. The weapon comparison page is removed; its endpoints are not (2026-08-31)

**Owner ruling.** *"Let's remove compare for now, it doesn't seem super useful since your
artifact loadout may change based on weapon stats. Unless you can argue for how we're
accounting for artifact choices, it's really not super valuable."*

No argument was available, and the module had already made the owner's case in its own
docstring:

> Artifacts are held fixed, so this answers which weapon is better in the build you have, not
> which weapon is better with its own best artifacts.
>
> …a weapon that wants a completely different artifact set loses a fixed-artifact comparison it
> would win with its own pieces.

The comparison worth having is *for each weapon, find its best artifacts, then compare the
winners* — N searches, which `DESIGN_mistilteinn.md` §3.5 deliberately keeps off the server.
The page answered the cheaper question and said so; the ruling is that the cheaper question does
not earn a tab.

**What was removed:** the route, the nav entry, the landing card, and `frontend/src/app/pages/compare/`.

**What was kept, and why:** `POST /builds/{id}/compare-weapons` and `POST
/builds/{id}/compare-weapons/gcsim`. They are tested and crossvalidated, they cost nothing to
leave, and this is a product decision that may be reversed — deleting a working, verified
service in order to remove a tab is the larger and less reversible move.

They now have **no caller**, which this repo elsewhere treats as a defect worth naming
(`createGpuKernel`, `recipe-energy.ts`). The distinction is that those were built and never
wired; this was wired and deliberately unwired. Recorded here so the next audit finds the
reason rather than the smell.

## 31. T.1a stands — several builds per character, and no uniqueness constraint (2026-09-01)

**Owner ruling.** *"Convention is to keep T1.a, because each user's account only has one of
each character."*

`BACKLOG_frontend.md` §3 asked to *"limit one build per character like Fribbels"*. That would
reinstate `uq_builds_owner_character`, which **T.1a dropped by owner decision on 2026-08-24**
(migration `27770f8ae917`). The backlog entry was written five days after the ruling and the
two were never reconciled; this reconciles them in the ruling's favour.

**Nothing is built and nothing is reverted.** The status quo already is T.1a, so the decision
is recorded rather than implemented — but it is recorded, because an audit that found the
contradiction and left it unresolved would send the next reader to re-derive it.

### What the reason changes downstream

An account holds one copy of a character, so two builds of that character are **hypotheticals
about one owned character** rather than two things that can be equipped at once. That is
consistent with everything the constraint's removal was for: a C0 beside a C6, a Physical Eula
against a Cryo one — comparisons, not inventory.

It also means the **build priority** shipped in #212 ranks what actually contends. Pieces are
contested *between characters*, not between two builds of one, so a ranking over builds
behaves as a ranking over characters in every real account. The three-way rule needs no
change: a higher-ranked build takes a contested piece, a lower-ranked one is refused, and an
unranked build takes from nobody.

**The rule that did move is still where T.1a put it.** gcsim refuses a party holding the same
character twice, so `api/v1/teams.py` enforces one-per-team — which is the place the game's
own constraint actually bites, and the reason dropping the database constraint cost nothing.

### The part of §3 that shipped

Ranking and stealing (#212). Only the uniqueness constraint was ever in question, and it is
answered here. **§3 is closed.**


## 32

**Text is allowed in the rotation builder where buttons cannot reach — and OQ-B2 is narrowed,
not repealed.**

`DESIGN_rotation_builder.md` OQ-B2 was answered by the owner on 2026-08-29: *"No — buttons
only."* The reason recorded there is good and still stands — *one way in, and no chance of a
typed vocabulary drifting from the clickable one* — and the builder exists at all because
gcsim's syntax is the wrong authoring surface.

**Owner, 2026-09-03, on the Tier 3 language plan:**

> *"We can expand beyond buttons where needed, don't consider this a hard and fast rule. The
> priority is feature parity with the user being able to build a similar rotation in the tool
> if they desire, some of these things are too complicated for that."*

and, on user-defined functions specifically:

> *"user defined functions almost need to be written, and if a user wants that level of
> complexity they'll have to author them themselves."*

**The distinction that keeps both rulings true.** OQ-B2 refused a *quick-add line for actions*
— a second, typed way to do exactly what the move buttons already do. That is still refused,
and for its original reason. What is now allowed is a surface for **what buttons cannot
express**: user-defined functions, and expressions outside a fixed dropdown vocabulary. One is
a competing vocabulary; the other is the only vocabulary there is.

Two constraints make the new surface honest rather than a loophole:

1. **It is not a second parser.** Typed text goes through the *same* parser as an import, so
   nothing authored escapes the rules an imported config obeys, and the tree stays the single
   source of truth.
2. **Its diagnostics land before it does.** A typed surface is only as friendly as its errors,
   so validation and diagnostics are their own phase and ship *first*
   (`TASKS_rotation_language.md` Phase 6, then Phase 7).

**This changed the plan's shape, not just its permissions.** Under "buttons only" the value
curve ran 13 % → 84 % → gated, and the GUI was the only way in. With text as a first-class
surface, **every rotation becomes editable as soon as parse and emit exist** (Phase 7), and the
GUI phases after it move work from typing to clicking rather than deciding whether a rotation
can be edited at all.

**Measured, so the "too complicated" judgement is not a guess.** Of the 41 configs in the
2026-09-03 gcsim-database corpus that define a function, **41 have control flow in the body and
30 take a parameter**. There is no "simple function" case a form could have covered, and
inlining them as macros — the obvious shortcut — does not exist.

---

## 33. Artifact ranking has two engines, and the second one is what #291 asked for (2026-09-05)

Issue [#291](https://github.com/AJTDaedalus/mistilteinn/issues/291), filed from Discord:

> *"Add an 'artifact ranker' alongside the optimizer, like Fribbles, that calculates and presents
> the probability an artifact, at max level, would be an upgrade for the selected
> team/rotation/build. Potential challenge: this should assume that you can move other artifacts,
> so the 'best build with this artifact leveled up' vs current for the % gain."*

`DESIGN_artifact_ranking.md` §§1–7 planned the **first** half of that and not the second. Four
rulings, and one measurement that changed a task:

| | ruling |
|---|---|
| **OQ-A5** | **Both engines.** A single-slot delta for every piece (~12 µs, 28 ms for 2,370) *and* a pinned re-search for one piece on demand (~5 s). |
| **OQ-A6** | The **distribution is in this plan**, not a later one. |
| **OQ-A7** | It lives on **`/artifacts`**, with its own build picker, reusing the warm recipe cache. |
| **OQ-A8** | A candidate from an uncalibrated set gets **its set calibrated on demand**, never a number under the wrong recipe. |

**The five-orders-of-magnitude fact is the decision.** *"Assume that you can move other
artifacts"* is not a slot swap, it is a re-optimization with the piece pinned, and the two cost
~12 µs and ~5 s per piece. A sortable whole-inventory column can only ever be the first; the
number the issue names can only ever be the second, spent deliberately on one piece. So the
column **triages** and the deep dive **settles**, and the column's number is published as a
**lower bound** — a re-search may keep the same four neighbours, so it never does worse.

**Fribbels does not offer the second half, and saying so is the point.** All five of its
per-relic columns are single-piece scores against a weights vector; its own optimizer on the
owner's 1,712-relic export quoted *"10:42:43 left"*. The pinned re-search has no reference
implementation in either tool. It is affordable here for a reason neither has: after one
calibration the evaluator is closed-form.

**gcsim stays the engine and stays outside the loop.** Owner, same day: *"We should aim, like we
did for optimize, to do what Fribbels/GO do but with gcsim as the engine."* That is OQ-A1
unchanged — the loop replays gcsim's own published per-hit decomposition closed-form, and gcsim
itself runs only to calibrate. Anything reaching for gcsim *inside* the ranking loop has left the
design.

### The measurement: the draw weights have no primary source, and the owner's export cannot supply one

Checked rather than assumed, against the pinned AnimeGameData capture `5445617e33b2`:
`ReliquaryAffixExcelConfigData` (350 rows) has **no weight field**;
`ReliquaryMainPropExcelConfigData` (66 rows) has none either; and
`ReliquaryExcelConfigData.weight` — the one field whose name matches — is an **item-drop weight**
on the artifact entry. A plan that grabbed it because the key matched would have been confidently
wrong.

So the substat appearance weights are a **named secondary source** (GO's
`libs/gi/upopt/src/consts.ts`, citing the fandom *Artifact/Distribution* page), shipped openly the
way `gcsim_config.ENERGY_DRIP` already is.

Deriving them from the owner's own 2,370-piece export was the attractive alternative and it does
not work. On flowers at +0 — the least-selected cut, 319 pieces, 1,061 lines — `eleMas` (w=4)
reads 13.29%, `critDMG_` (w=3) 12.25%, `atk` (w=6) 11.97%, `def_` (w=4) 7.82%. Inclusion
probability under a weighted draw without replacement is **monotone in weight**, so w=3 above w=6
is not a sampling wobble: either a kept inventory is still selected at +0, or the published table
is wrong. Either way that corpus is not the source, and `TASKS_artifact_ranking.md` A.3 records it
in a script and a findings doc rather than leaving the next reader to rediscover it.

**Two questions stay open and neither blocks.** **OQ-A9** — whether a pinned re-search stays
interactive over the whole inventory — is a measurement (A.10), and the DESIGN's §7 note exists
because the last time someone inferred a cost here instead of measuring it they were wrong by a
factor of thirty. **OQ-A10** — whether "% gain" is against the current build or against the best
build without the piece — is answered *current* and labelled, because the two diverge exactly when
the current build is not optimal, which for a piece someone is asking about is most of the time.

## 34. The catalogue art leaves the repository, and the repository takes AGPLv3 (2026-11-10)

**Ruling (owner):** remove the HoYoverse art and gitignore it, keeping the process that
fetches it. Adopt **AGPLv3**.

**Why the art goes.** The repository is to be published (`docs/AUDIT_open_source.md`), and a
public repository offers everything in it under its licence. The icons are HoYoverse's, so
that is not a licence anyone here can grant. A public copy also invites a takedown that the
deployed site has never drawn. Three files in `references/` went with it for the same reason:
Mitya's model render, his ornament, and a Genshin Optimizer screenshot that carries game art.
`favicon.svg` and `og-card.png` stay. They are original geometry drawn *after* the ornament,
not copies of it.

**This reverses §4, not its lesson.** §4 committed the art because the gitignored arrangement
had shipped no art to prod for weeks, silently: nothing ran the script there, and nginx's SPA
fallback answered every missing image with `200 text/html`. The replacement keeps both halves
of the fix:

- **A deploy step obtains the art.** `deploy-prod.yml` runs `scripts.download_icons` on the
  host **before** each rebuild, while the old frontend is still serving. Cloudflare caches a
  404 for hours, so a gap would be expensive. It runs again after each re-seed.
  `docker-compose.prod.yml` mounts the host directory into nginx read-only, so new art serves
  without a rebuild.
- **Content type, not status.** The deploy probes `icons/UI_AvatarIcon_Ayaka.webp` for
  `image/webp`. That also catches a mount at the wrong path, which would otherwise download
  every icon into a container deleted a second later and report success.

`tests/unit/test_catalogue_art_is_not_committed.py` replaces the old guard and pins the
steps, their order, the mount, and the container path derived from the script's own `OUT`.
`scripts.inject` confirms it catches a wrong mount path, a dropped ignore rule and a dropped
Mora icon.

**A fresh download found a gap that a committed directory had hidden.** Mora's icon,
`UI_ItemIcon_202`, which the planner draws on every bill, was committed by hand. No catalogue
row names it, so the downloader had never fetched it, and the first prod deploy after this
change would have dropped it. It is now `planner.service.MORA_ICON`, and the downloader
reads it.

**First deploy cost, measured:** 55 s to fetch 2,181 files (99 MB) into an empty directory,
using the exact command the workflow runs, as a non-root user. Later deploys fetch only what
is missing.

**`--check` is not used by the deploy.** Its hand-kept list of art nanoka does not publish has
fallen behind: the download finds 22 such basenames and reports them correctly, but `--check`
calls some of them failures. The download's own exit code and the content-type probe are the
gate.

**Why AGPLv3.** The owner chose it. It is also what would let the gcsim pin move: gcsim
relicensed to AGPLv3 on 2026-09-19, and the browser build serves it over the network. Moving
the pin is still a separate decision, and this ruling does not move it.

**Version 3 "or later", matching gcsim (owner, 2026-11-11).** gcsim's own `LICENSE` grants
"version 3 of the License, or (at your option) any later version", so this repository declares
`AGPL-3.0-or-later` in `pyproject.toml` and `package.json`. The first draft said `-only`; the
owner asked for gcsim's terms instead.

**Compatibility checked:**
- fairy, this fork's origin, has no licence but is the owner's own repository, so the owner
  can license its code.
- The pinned gcsim (v2.47.2) is MIT.
- `app/pando/` ports Genshin Optimizer, which is MIT.
- MIT code can be included in AGPLv3 work as long as its notices are kept.

Their notices are kept in `THIRD_PARTY_NOTICES.md`.


## 35. What the public copy carries (2026-11-12)

**Context.** The public copy is a separate repository built by `release/export.py` and checked
by `release/gate.py` (private design: `docs/DESIGN_open_source_release.md`). The owner ruled
on the open questions that design listed.

| question | ruling |
|---|---|
| KeqingMains guide prose (`backend/app/data/kqm/weapons.json`, `note`) | **Blanked in every commit of the public copy.** The rankings, names and links stay. The private site keeps showing the quotes. `release/rules.py:BLANK_JSON_FIELDS` does it, and the gate fails any version that still carries text. |
| Anonymous quotes from Discord bug reports | Ship. Audit B3 objected to names, and the gate refuses names. |
| Links to the private repository's issues | Leave them. They are harmless 404s for the public. |
| Operator messages pointing at the private `DEPLOY.md` | Reworded to be self-contained: the preflight error, `send_test_email`, and a comment in `gcsim-loader.ts`. |
| F1's residual case (a victim clicking a link someone else triggered) | Keep as is for now. Asking for the password on the verify page is a UX change for later. |
| Closed-beta data (the YuanShen pin is a closed-beta build; beta characters are seeded) | **Deferred, and it holds the launch.** Removing it means code changes, not a filter rule. |
| A private rehearsal repository | Approved: Actions off, no runners, push only a gated export. |

## 36. The public copy withholds unreleased materials (2026-11-12)

The closed-beta ruling deferred in §35 is settled. The beta *characters* were never in the
repository: they live in the database, which is seeded from nanoka at deploy time. What the
YuanShen snapshot does carry is a handful of unreleased material rows in
`snapshot/planner_economy.json`.

**Owner ruling:** the public copy drops those rows, from every version of the file, and the
private repo and prod keep them. Prod needs them, because it prices beta characters.
`release/rules.py:WITHHELD_JSON_KEYS` lists the rows (113094-113097 and 200130). The gate fails
an export that still carries one. It also fails on any nameless row that is still nameless at
the export's head, so a re-pin cannot add an unreviewed one. `python -m release.beta_materials`
lists named beta-only rows from the database at each re-pin.

**The list only grows.** Removing an id after launch would rewrite public history. A withheld
material that later releases therefore stays unknown in the public copy.

## 37. gcsim crosses into AGPLv3, and the site offers its source (2026-11-13)

**Ruling (owner):** re-pin gcsim from v2.47.2 (`caf738dc`, the last MIT release) to the
latest release, **v2.50.0** (`b107b5dc`), accepting gcsim's AGPLv3. This repository is already
AGPL-3.0-or-later (§34) and published at `https://github.com/AJTDaedalus/mistilteinn-public`,
which is what made the move possible.

**Why it was a decision and not a bump.** The site serves `gcsim.wasm` to every visitor, and
AGPLv3 §13 asks a program users interact with over a network to offer them its source. §34
adopted AGPL for this repository and explicitly did not move the pin; this ruling does.

**What the move obliges, and how each part is met:**

| obligation | met by |
|---|---|
| Convey the object code with its licence (§4–6) | The build copies gcsim's `LICENSE` (AGPLv3) to `gcsim/gcsim.LICENSE.txt` and its `LICENSE-MIT` to `gcsim/gcsim-mit.LICENSE.txt` beside the wasm, and Go's BSD notice for `wasm_exec.js` as before. `Dockerfile.prod` refuses an image without any of them. `test_gcsim_licence_ships_with_the_wasm.py` checks the names *and* that each comes from the right source file. |
| Keep the MIT notice for MIT-contributed code | `gcsim-mit.LICENSE.txt` ships, and `THIRD_PARTY_NOTICES.md` carries both texts. |
| Offer Corresponding Source to network users (§13) | **A footer link, "Source code (AGPL-3.0)", on every page including sign-in** (`shared/source.ts`), and a *Source code* section on `/about` linking this repository and gcsim. |
| Name the exact gcsim source | `/about` reads `gcsim/BUILT_FROM` — written by the build that produced the wasm beside it — and links `github.com/genshinsim/gcsim/tree/<that commit>`. It falls back to the repository link, never to nothing. The commit is not restated in the frontend, for the reason `test_gcsim_pin_is_single.py` exists. |

**We build gcsim unmodified**, from a clean checkout of the pin, so its Corresponding Source is
upstream's own tree at that commit. If this repository ever patches gcsim, the patched source
has to be published too, and the `/about` link would need to point at it instead.

**The About page's "currently closed source" sentence went with it.** It had been false since
the public copy was published, and leaving it beside a source link would contradict the offer.
The new wording keeps the owner's AI disclosure and the Discord invitation unchanged.

**Measured cost of the move** (`docs/RESEARCH_gcsim_repin_2026_11.md`): the damage chain is
unchanged to the last digit; one engine change (`3f528e2c7`, hitlag) moves real teams by
fractions of a percent; and the wasm is **2.4-4.2× faster** per iteration. It also changed
`flush()`'s return shape, which the app now reads through one function.
