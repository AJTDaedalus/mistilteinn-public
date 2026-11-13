# ER sweep — where this came from

| | |
|---|---|
| **Commit** | `b107b5dc5cb88977bed5270e5d83e64934730d4d` — the pin in `docs/CROSSVAL_gcsim.md` |
| **Produced** | 2026-08-22 for D.2 · regenerated 2026-09-19 at the v2.47.2 re-pin and 2026-11-13 at v2.50.0 |
| **Analysed in** | `docs/RESEARCH_er_bucketing.md` |
| **Read by** | `tests/unit/test_sim_retrieval.py` |

54 gcsim runs, one per whole ER percent from 100 % to 153 %, **1,000 iterations each**.
**Only `er` varies** — every other line of the config is identical, and the config is stored
in the fixture itself with `er=<swept>` in place of the value.

**`er` is the ER a character has on top of gcsim's base 100 %**, so `er_percent` 120 is
`er=0.20` and *not* `er=1.20`. gcsim gives every character `res[ER] += 1` at creation
(`basestat.go:82`, cited in `docs/CROSSVAL_gcsim.md`). Substituting the percent directly
doubles the ER and raises DPS by about a third — which looks like a re-pin having moved the
world, and was the first thing that happened when this fixture was regenerated.

**It runs 1,000 iterations because 50 was not enough to measure what the tests assert.** At
50, a bucket's width is dominated by which iterations happened to land a third burst. The
first committed sweep reported bucket 120 at **13.3 %** wide; re-running the same sweep at
**its own pin** reproduced neither the number (7.6 %) nor the bucket (125). At 1,000 the
answer is stable and the shape the research doc describes is exactly right: the widest
bucket *is* 120, at **7.3 %**, against 0.3 % at the settled top end. The coupling is real
and it is smaller than the original sample claimed.

**The widest bucket's width is not stable at 1,000 iterations either — measured
2026-11-13.** Two fresh sweeps at v2.47.2 gave **11.2 %** and **8.6 %** for bucket 120, and
two at v2.50.0 gave **7.4 %** and **9.4 %**; the committed v2.50.0 sweep reads **9.6 %**. So
the 7.3 % above was one draw, not *the* answer. What *is* stable across all five is the shape
the tests assert: the widest bucket is 120 every time, and the ends stay under 1 %. Treat the
width as a range, roughly 7-11 %.

**`cryo_aura_uptime` was 0.0 in every run until 2026-11-13**, which made its invariance
assertion one that could not fail. It is now read from gcsim's
`statistics.target_aura_uptime[0].sources.cryo.mean` — gcsim's percentage, **98.056** at
v2.50.0 against **98.074** at v2.47.2 (the hitlag change, `3f528e2c7`, moves it). The test
now also asserts it is non-zero. The other fields: `burst_casts` is the minimum and
`burst_casts_mean` the mean of `character_actions[0].sources.burst`; `skill_casts` and
`attack_casts` are their means (constant, so integers).

This is evidence, not a golden fixture: nothing asserts a specific DPS from it. What the
tests assert is its *shape* — that skill casts and aura uptime do not move with ER at all,
and that the buckets differ by an order of magnitude in width (over 5 % at the climb, under
2 % at the ends).
Those are the two facts `sim_retrieval.py` is built on, and they are the ones that should
fail loudly if a re-pin changes them.

## Regenerating

```bash
git -C <gcsim clone> checkout <the pin in docs/CROSSVAL_gcsim.md>
go build -o gcsim ./cmd/gcsim
# then one run per whole percent, substituting (percent - 100)/100 into `er=` in the stored
# config — see the note above about what `er` means.
```

Two things that cost a wrong answer each and are recorded in the research doc: a bare action
list runs **once** rather than looping, and `while 1 { … }` with an ungated `burst` at the top
**deadlocks** because gcsim waits for an action it can no longer generate energy for. Both
produce a plausible-looking JSON with exactly one burst in it.

Regenerating this is a new claim about what is true and should arrive as a reviewed diff.
