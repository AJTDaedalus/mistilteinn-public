# ER sweep — where this came from

| | |
|---|---|
| **Commit** | `caf738dc807a646e2eee7e7b572f225dd6deb510` — the pin in `docs/CROSSVAL_gcsim.md` |
| **Produced** | 2026-08-22 for D.2 · regenerated 2026-09-19 at the v2.47.2 re-pin |
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
