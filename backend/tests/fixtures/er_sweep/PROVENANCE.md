# ER sweep — where this came from

| | |
|---|---|
| **Commit** | `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa` — the pin in `docs/CROSSVAL_gcsim.md` |
| **Produced** | 2026-08-22, for D.2 |
| **Analysed in** | `docs/RESEARCH_er_bucketing.md` |
| **Read by** | `tests/unit/test_sim_retrieval.py` |

54 gcsim runs, one per whole ER percent from 100 % to 153 %. **Only `er` varies** — every
other line of the config is identical, and the config is stored in the fixture itself with
`er=<swept>` in place of the value.

This is evidence, not a golden fixture: nothing asserts a specific DPS from it. What the
tests assert is its *shape* — that skill casts and aura uptime do not move with ER at all,
and that at least one 5 % bucket is more than 10 % wide in DPS while another is under 2 %.
Those are the two facts `sim_retrieval.py` is built on, and they are the ones that should
fail loudly if a re-pin changes them.

## Regenerating

```bash
git -C <gcsim clone> checkout 3647a07a7cc3004bc1e79d9bb5f7444de20dceaa
go build -o gcsim ./cmd/gcsim
# then one run per whole percent, substituting `er=` in the stored config
```

Two things that cost a wrong answer each and are recorded in the research doc: a bare action
list runs **once** rather than looping, and `while 1 { … }` with an ungated `burst` at the top
**deadlocks** because gcsim waits for an action it can no longer generate energy for. Both
produce a plausible-looking JSON with exactly one burst in it.

Regenerating this is a new claim about what is true and should arrive as a reviewed diff.
